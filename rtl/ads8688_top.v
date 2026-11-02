`timescale 1ns / 1ps
//==========================================================================
//  ADS8688 8 通道 16bit ADC 采集（PL 端纯 Verilog 实现）
//--------------------------------------------------------------------------
//  硬件：AX7020 (xc7z020clg400-2)
//  时钟：板载 50MHz，管脚 U18
//  接口：SPI，MSB first
//        - 命令帧 = 32bit（16bit 命令 + 16bit 0）
//        - 寄存器写帧 = 24bit（16bit 地址/数据 + 8bit 回读时钟）
//        - 读数据帧 = 32bit（16bit 0 + 16bit 数据）
//
//  初始化流程（寄存器帧长度按 TI 手册 8.5.2.1）：
//      SOFT_RESET(0x8500) -> 等 25ms
//      -> 写寄存器 0x01 = 0xFF   (AUTO_SEQ_EN，使能 8 个通道自动扫描)
//      -> 写寄存器 0x02 = 0x00   (CH_PD，所有通道供电)
//      -> 写寄存器 0x05~0x0C = 0x00 (8 个通道量程 = ±2.5*Vref = ±10.24V)
//      -> AUTO_RST(0xA000) 进入自动扫描
//      -> 之后每帧发 0x0000(NOP) 并读回数据
//
//  ADS8688 在 SCLK 下降沿锁存 SDI 并更新 SDO。
//  SDI 在低电平中点更新，SDO 在高电平中点采样上一下降沿输出的位。
//  第 16 个下降沿输出 MSB，第 17~32 个高电平采集完整 16bit 数据。
//  完成最后一个下降沿之后再释放 CS。
//
//  芯片量程 ±10.24V（Vref = 4.096V 内部基准），0V 对应码值 32768。
//  芯片输入：V(mV) = (码值 - 32768) * 0.3125。
//  用户模块 AIN0~7 的 1K 电阻分别串在输入端和地端，与电容组成滤波器，不是 1:1 分压。
//  模块端电压可近似沿用上述换算，实际精度需考虑输入负载、基准与零点误差。
//==========================================================================
module ads8688_top #(
    parameter CLK_FREQ  = 50_000_000,   // 输入时钟频率
    parameter SCLK_FREQ = 1_000_000,    // SPI 时钟频率
    parameter CH0_ONLY  = 0,            // 1 = 手动模式，只采 CH0，排查多通道混读
    parameter EXTERNAL_RESET_ENABLE = 0, // diagnostic reset; legacy images keep POR-only behavior
    parameter DIAGNOSTIC_READ_ENABLE = 0, // read-only register audit, then hold until restart
    // Per-channel input range codes from ADS8688 Table 15:
    // 0=+/-10.24 V, 1=+/-5.12 V, 2=+/-2.56 V, 5=0..10.24 V, 6=0..5.12 V.
    // Defaults preserve the original +/-10.24 V configuration.
    parameter [3:0] RANGE0 = 4'h0,
    parameter [3:0] RANGE1 = 4'h0,
    parameter [3:0] RANGE2 = 4'h0,
    parameter [3:0] RANGE3 = 4'h0,
    parameter [3:0] RANGE4 = 4'h0,
    parameter [3:0] RANGE5 = 4'h0,
    parameter [3:0] RANGE6 = 4'h0,
    parameter [3:0] RANGE7 = 4'h0
)(
    input  wire        sys_clk,     // 50MHz 板载时钟，管脚 U18
    input  wire        restart,     // optional active-high reset, enabled by parameter
    input  wire        audit_request, // diagnostic only; accepted between conversion frames
    output reg         audit_done,
    output reg  [95:0] audit_values,  // byte 0=3F, then 01,02,03,05..0C
    // ---------- 接到 ADS8688 模块 P1 ----------
    output wire        adc_cs_n,    // 片选，低有效
    output wire        adc_sclk,    // SPI 时钟
    output wire        adc_sdi,     // FPGA -> ADC
    input  wire        adc_sdo,     // ADC -> FPGA
    output wire        adc_rst_n,   // 复位，低有效（模块 RST）
    // ---------- 给上层观察用（LED 指示 / ILA）----------
    output reg  [15:0] ch_data,     // 刚采到的通道原始码值
    output reg  [2:0]  ch_index,    // 该数据属于第几个通道 0~7
    output reg         ch_valid,    // 一个通道采完的脉冲（单周期高）
    output reg         init_done,   // 初始化帧全部完成
    output reg         init_error,  // 任意寄存器写回读不匹配，保持到重新上电
    output reg  [7:0]  reg_readback // 最近一次寄存器写回读
);

    //----------------------------------------------------------------------
    // 参数
    //----------------------------------------------------------------------
    localparam HALF_DIV     = CLK_FREQ / (SCLK_FREQ * 2);  // SCLK 半周期=多少个 clk
    localparam HALF_W       = $clog2(HALF_DIV);
    localparam MID_VAL      = (HALF_DIV / 2) - 1;          // 半周期中点
    localparam RST_LOW_CYC  = 200;                         // RST/PD 拉低 4us，硬件掉电复位
    localparam RST_WAIT_CYC = CLK_FREQ / 40;               // 25ms
    localparam GAP_1MS      = CLK_FREQ / 1000;             // 1ms
    localparam GAP_NORMAL   = 1000;                        // 20us，读帧之间的间隔

    //----------------------------------------------------------------------
    // 上电复位
    //----------------------------------------------------------------------
    reg [15:0] por_cnt = 16'd0;
    wire       sys_rst_n = por_cnt[15];
    wire       core_rst_n = sys_rst_n && !(EXTERNAL_RESET_ENABLE && restart);

    always @(posedge sys_clk) begin
        if (!por_cnt[15])
            por_cnt <= por_cnt + 1'b1;
    end

    //----------------------------------------------------------------------
    // 命令字 / 寄存器写帧
    //   seq 0     : 0x8500 软复位（32bit 命令帧）
    //   seq 1..10 : 寄存器写（24bit 帧），字节1 = 地址<<1|1
    // ---------------------------------------------------------------------
    //   0x01 = AUTO_SEQ_EN  写 0xFF  -> 帧 0x03FF (字节1=0x03 字节2=0xFF)
    //   0x02 = CH_PD        写 0x00  -> 帧 0x0500
    //   0x05 = CHIR_0       写 0x00  -> 帧 0x0B00   (±10.24V)
    //   0x06 = CHIR_1       写 0x00  -> 帧 0x0D00
    //   0x07 = CHIR_2       写 0x00  -> 帧 0x0F00
    //   0x08 = CHIR_3       写 0x00  -> 帧 0x1100
    //   0x09 = CHIR_4       写 0x00  -> 帧 0x1300
    //   0x0A = CHIR_5       写 0x00  -> 帧 0x1500
    //   0x0B = CHIR_6       写 0x00  -> 帧 0x1700
    //   0x0C = CHIR_7       写 0x00  -> 帧 0x1900
    //   seq 11    : 0xA000 进入自动扫描（32bit 命令帧）
    //   seq >= 12 : 0x0000 NOP + 读数据（32bit）
    //----------------------------------------------------------------------
    reg [3:0]  seq;
    reg [15:0] tx_word;
    reg        tx_is24;     // 1 = 寄存器帧 24bit，0 = 命令/采集帧 32bit
    reg [23:0] gap_need;    // 本帧之后要等的时钟数
    reg [3:0] audit_index;
    function [6:0] audit_address;
        input [3:0] index;
        begin
            case (index)
                0: audit_address = 7'h3f;
                1: audit_address = 7'h01;
                2: audit_address = 7'h02;
                3: audit_address = 7'h03;
                default: audit_address = index + 1'b1;
            endcase
        end
    endfunction

    always @(*) begin
        case (seq)
        4'd0 : begin tx_word = 16'h8500; tx_is24 = 1'b0; gap_need = RST_WAIT_CYC; end
        4'd1 : begin tx_word = 16'h03FF; tx_is24 = 1'b1; gap_need = GAP_1MS;      end // AUTO_SEQ_EN=0xFF
        4'd2 : begin tx_word = 16'h0500; tx_is24 = 1'b1; gap_need = GAP_1MS;      end // CH_PD=0x00
        4'd3 : begin tx_word = {8'h0B, 4'h0, RANGE0}; tx_is24 = 1'b1; gap_need = GAP_1MS; end // CH0 range
        4'd4 : begin tx_word = {8'h0D, 4'h0, RANGE1}; tx_is24 = 1'b1; gap_need = GAP_1MS; end // CH1 range
        4'd5 : begin tx_word = {8'h0F, 4'h0, RANGE2}; tx_is24 = 1'b1; gap_need = GAP_1MS; end // CH2 range
        4'd6 : begin tx_word = {8'h11, 4'h0, RANGE3}; tx_is24 = 1'b1; gap_need = GAP_1MS; end // CH3 range
        4'd7 : begin tx_word = {8'h13, 4'h0, RANGE4}; tx_is24 = 1'b1; gap_need = GAP_1MS; end // CH4 range
        4'd8 : begin tx_word = {8'h15, 4'h0, RANGE5}; tx_is24 = 1'b1; gap_need = GAP_1MS; end // CH5 range
        4'd9 : begin tx_word = {8'h17, 4'h0, RANGE6}; tx_is24 = 1'b1; gap_need = GAP_1MS; end // CH6 range
        4'd10: begin tx_word = {8'h19, 4'h0, RANGE7}; tx_is24 = 1'b1; gap_need = GAP_1MS; end // CH7 range
        4'd11: begin tx_word = CH0_ONLY ? 16'hC000 : 16'hA000;
                    tx_is24 = 1'b0; gap_need = GAP_1MS; end // MAN_CH0 / AUTO_RST
        4'd13: begin
            tx_word = DIAGNOSTIC_READ_ENABLE ? {audit_address(audit_index), 1'b0, 8'h00} : 16'h0000;
            tx_is24 = DIAGNOSTIC_READ_ENABLE; gap_need = GAP_NORMAL;
        end
        default: begin tx_word = 16'h0000; tx_is24 = 1'b0; gap_need = GAP_NORMAL; end // NOP 读
        endcase
    end

    wire [5:0] last_bit = tx_is24 ? 6'd23 : 6'd31;

    //----------------------------------------------------------------------
    // 状态机
    //----------------------------------------------------------------------
    localparam S_RSTLOW = 3'd0,  // RST 拉低
               S_OPEN   = 3'd1,  // 松开 RST 等 25ms
               S_XFER   = 3'd2,  // 发一帧
               S_GAP    = 3'd3;  // 帧间间隔

    reg  [2:0]        state;
    reg  [HALF_W-1:0] half_cnt;
    reg               sclk_r;
    wire              busy = (state == S_XFER);

    wire tick     = busy && (half_cnt == HALF_DIV - 1);   // 半周期结束
    wire mid_tick = busy && (half_cnt == MID_VAL);        // 半周期中点

    wire m_low  = mid_tick && !sclk_r;   // SCLK 低电平中点 -> 更新 SDI
    wire m_high = mid_tick &&  sclk_r;   // SCLK 高电平中点 -> 采样 SDO

    always @(posedge sys_clk or negedge core_rst_n) begin
        if (!core_rst_n) begin
            half_cnt <= {HALF_W{1'b0}};
            sclk_r   <= 1'b0;
        end else if (!busy) begin
            half_cnt <= {HALF_W{1'b0}};
            sclk_r   <= 1'b0;       // 空闲时 SCLK 拉低
        end else if (tick) begin
            half_cnt <= {HALF_W{1'b0}};
            sclk_r   <= ~sclk_r;
        end else begin
            half_cnt <= half_cnt + 1'b1;
        end
    end

    assign adc_sclk = sclk_r;

    reg [23:0] dly;
    reg [31:0] tx_sr;       // 发送移位寄存器（高 16bit 命令 + 低 16bit 0）
    reg [31:0] rx_sr;       // 接收移位寄存器（取低 16bit 为数据）
    reg [5:0]  bit_idx;     // 0 ~ last_bit
    reg [2:0]  next_channel;
    reg        tx_loaded;   // 本帧是否已装载
    reg        cs_r;
    reg        rst_r;

    assign adc_cs_n  = cs_r;
    assign adc_sdi   = tx_sr[31];
    assign adc_rst_n = rst_r;

    always @(posedge sys_clk or negedge core_rst_n) begin
        if (!core_rst_n) begin
            state     <= S_RSTLOW;
            seq       <= 4'd0;
            dly       <= 24'd0;
            tx_sr     <= 32'd0;
            rx_sr     <= 32'd0;
            bit_idx   <= 6'd0;
            next_channel <= 3'd0;
            tx_loaded <= 1'b0;
            cs_r      <= 1'b1;
            rst_r     <= 1'b1;
            ch_data   <= 16'd0;
            ch_index  <= 3'd0;
            ch_valid  <= 1'b0;
            init_done <= 1'b0;
            init_error <= 1'b0;
            reg_readback <= 8'd0;
            audit_done <= 1'b0;
            audit_values <= 96'd0;
            audit_index <= 4'd0;
        end else begin
            ch_valid <= 1'b0;                       // 默认拉低，只在完成时脉冲

            case (state)
            // ---------------- 1. RST 拉低 ----------------
            S_RSTLOW: begin
                rst_r <= 1'b0;
                cs_r  <= 1'b1;
                if (dly == RST_LOW_CYC - 1) begin
                    dly   <= 24'd0;
                    state <= S_OPEN;
                end else begin
                    dly <= dly + 1'b1;
                end
            end

            // ---------------- 2. 松开 RST，等 25ms ----------------
            S_OPEN: begin
                rst_r <= 1'b1;
                if (dly == RST_WAIT_CYC - 1) begin
                    dly   <= 24'd0;
                    state <= S_XFER;
                end else begin
                    dly <= dly + 1'b1;
                end
            end

            // ---------------- 3. 发一帧 ----------------
            S_XFER: begin
                if (!tx_loaded) begin              // 帧头：CS 拉低 + 装载
                    tx_loaded <= 1'b1;
                    cs_r      <= 1'b0;
                    tx_sr     <= {tx_word, 16'h0000};
                    rx_sr     <= 32'd0;
                end

                if (m_high) begin
                    rx_sr <= {rx_sr[14:0], adc_sdo};        // 高电平中点采样 MISO
                end

                // 先完成最后一个 SCLK 下降沿，下一 sys_clk 周期再拉高 CS。
                if (tick && sclk_r) begin
                    if (bit_idx == last_bit) begin
                        bit_idx <= 6'd0;
                        state   <= S_GAP;
                        if (tx_is24 && seq <= 4'd10) begin
                            reg_readback <= rx_sr[7:0];
                            if (rx_sr[7:0] != tx_word[7:0])
                                init_error <= 1'b1;
                        end
                        if (seq == 4'd11)
                            init_done <= 1'b1;
                        if (DIAGNOSTIC_READ_ENABLE && seq == 4'd13)
                            audit_values[audit_index * 8 +: 8] <= rx_sr[7:0];
                        if (seq == 4'd12) begin             // audit replies are never conversion data
                            ch_data  <= rx_sr[15:0];
                            ch_valid <= 1'b1;
                            ch_index <= next_channel;
                            next_channel <= CH0_ONLY ? 3'd0 : next_channel + 1'b1;
                        end
                    end else begin
                        bit_idx <= bit_idx + 1'b1;
                    end
                end

                // 低电平中点移位 SDI（跳过第一个低电平，保证首个上升沿数据有效）
                if (m_low && (bit_idx != 6'd0))
                    tx_sr <= {tx_sr[30:0], 1'b0};
            end

            // ---------------- 4. 帧间间隔 ----------------
            S_GAP: begin
                cs_r      <= 1'b1;
                tx_loaded <= 1'b0;
                if (DIAGNOSTIC_READ_ENABLE && seq == 4'd14) begin
                    // Keep CS high. A read audit never writes configuration,
                    // resets the ADC, or silently resumes with a shifted channel index.
                    audit_done <= 1'b1;
                end else if (dly >= gap_need - 1'b1) begin
                    dly <= 24'd0;
                    if (DIAGNOSTIC_READ_ENABLE && seq == 4'd12 && audit_request) begin
                        seq <= 4'd13;
                        audit_index <= 0;
                        state <= S_XFER;
                    end else if (DIAGNOSTIC_READ_ENABLE && seq == 4'd13) begin
                        if (audit_index == 11) begin
                            seq <= 4'd14;
                            audit_done <= 1'b1;
                        end else begin
                            audit_index <= audit_index + 1'b1;
                            state <= S_XFER;
                        end
                    end else begin
                        if (seq < 4'd12)
                            seq <= seq + 1'b1;
                        state <= S_XFER;
                    end
                end else begin
                    dly <= dly + 1'b1;
                end
            end

            default: state <= S_RSTLOW;
            endcase
        end
    end

endmodule
