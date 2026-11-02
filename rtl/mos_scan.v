`timescale 1ns / 1ps
//==========================================================================
//  MOS 扫描控制器（台架版，不控制 DPS）
//--------------------------------------------------------------------------
//  工作方式：
//    1. 通过 MCP4725 输出 VG 阶梯：DAC 码 = CODE_START + point * CODE_STEP
//    2. 每个扫描点先等 SETTLE_MS 稳定，再累加 SWEEPS 轮 ADS8688 八通道整扫
//    3. 每点输出一行：point + vg_code + row_ch0..row_ch7（已除以 SWEEPS）
//    4. row_valid 既是一行的结束脉冲，也是 ILA 的存储限定条件
//    5. 一轮扫完等待 RESTART_MS 后自动重新开始，方便随时抓取
//
//  说明：
//    - 不控制 DPS，漏极电压由外部电源手动给定，本版只负责扫 VGS 和采数
//    - 一行内的 8 个通道值来自同一轮整扫，已按芯片通道 0..7 分开
//    - 8 个通道的量程沿用 mos_adc_monitor：CH0/CH2 双极性 ±10.24V，
//      CH1/CH3/CH7 单极性 0..5.12V，其余双极性 ±10.24V
//==========================================================================
module mos_scan #(
    parameter integer CLK_FREQ   = 50_000_000,
    parameter [6:0]   I2C_ADDR   = 7'h60,
    parameter integer POINTS     = 32,          // 扫描点数
    parameter [11:0]  CODE_START = 12'd0,       // 起始 DAC 码
    parameter [11:0]  CODE_STEP  = 12'd128,     // 每点 DAC 码步进
    parameter integer SETTLE_MS  = 20,          // 每点稳定时间
    parameter integer SWEEPS     = 8,           // 每点平均的整扫轮数，必须是 2 的幂
    parameter integer RESTART_MS = 200          // 一轮扫完后的间隔
)(
    input  wire        sys_clk,
    output wire        adc_cs_n,
    output wire        adc_sclk,
    output wire        adc_sdi,
    input  wire        adc_sdo,
    output wire        adc_rst_n,
    inout  wire        mcp_sda,
    output wire        mcp_scl,
    output wire [3:0]  led
);

    //----------------------------------------------------------------------
    // 参数
    //----------------------------------------------------------------------
    localparam integer IDX_W       = (POINTS <= 1) ? 1 : $clog2(POINTS);
    localparam integer SETTLE_CYC  = (CLK_FREQ / 1000) * SETTLE_MS;
    localparam integer SETTLE_W    = $clog2(SETTLE_CYC + 1);
    localparam integer GAP_CYC     = (CLK_FREQ / 1000) * 2;          // 点间 2ms
    localparam integer RESTART_CYC = (CLK_FREQ / 1000) * RESTART_MS;
    localparam integer GAP_W       = $clog2(RESTART_CYC + 1);
    localparam integer RETRY_CYC   = (CLK_FREQ / 1000) * 50;         // I2C 失败后 50ms 重试
    localparam integer ACC_SHIFT   = $clog2(SWEEPS);

    localparam [2:0] S_WAIT   = 3'd0,
                     S_DAC    = 3'd1,
                     S_SETTLE = 3'd2,
                     S_ALIGN  = 3'd3,
                     S_ACC    = 3'd4,
                     S_NEXT   = 3'd5,
                     S_GAP    = 3'd6,
                     S_RETRY  = 3'd7;

    //----------------------------------------------------------------------
    // 上电复位
    //----------------------------------------------------------------------
    reg [15:0] por_cnt = 16'd0;
    wire       sys_rst = ~por_cnt[15];

    always @(posedge sys_clk) begin
        if (!por_cnt[15])
            por_cnt <= por_cnt + 1'b1;
    end

    //----------------------------------------------------------------------
    // ADC 采集
    //----------------------------------------------------------------------
    (* mark_debug = "true" *) wire [15:0] adc_data;
    (* mark_debug = "true" *) wire [2:0]  adc_index;
    (* mark_debug = "true" *) wire        adc_valid;
    (* mark_debug = "true" *) wire        init_done;
    (* mark_debug = "true" *) wire        init_error;
    wire [7:0] reg_readback;

    ads8688_top #(
        .CLK_FREQ(CLK_FREQ), .CH0_ONLY(0),
        .RANGE0(4'h0), // AIN0: 双极性，用于 DAC 回环和双极性节点
        .RANGE1(4'h6), // AIN1: 0..5.12 V，预计栅极电压
        .RANGE2(4'h0), // AIN2: 双极性，预计漏极电压
        .RANGE3(4'h6), // AIN3: 0..5.12 V，预计源极电压
        .RANGE4(4'h0), .RANGE5(4'h0), .RANGE6(4'h0),
        .RANGE7(4'h6)  // AIN7: 0..5.12 V，预计 INA240 电流输出
    ) u_adc (
        .sys_clk(sys_clk), .restart(1'b0), .audit_request(1'b0), .adc_cs_n(adc_cs_n), .adc_sclk(adc_sclk),
        .adc_sdi(adc_sdi), .adc_sdo(adc_sdo), .adc_rst_n(adc_rst_n),
        .ch_data(adc_data), .ch_index(adc_index), .ch_valid(adc_valid),
        .init_done(init_done), .init_error(init_error),
        .reg_readback(reg_readback)
    );

    //----------------------------------------------------------------------
    // MCP4725 I2C 输出
    //----------------------------------------------------------------------
    reg  [11:0] dac_set   = 12'd0;
    reg         dac_start = 1'b0;
    wire        dac_busy;
    wire        dac_done;
    wire        dac_ack_err;

    mcp4725_i2c #(.CLK_FREQ(CLK_FREQ), .I2C_ADDR(I2C_ADDR)) u_dac (
        .clk(sys_clk), .rst(sys_rst), .start(dac_start), .dac_code(dac_set),
        .busy(dac_busy), .done(dac_done), .ack_error(dac_ack_err),
        .scl(mcp_scl), .sda(mcp_sda)
    );

    //----------------------------------------------------------------------
    // 扫描状态机
    //----------------------------------------------------------------------
    reg  [2:0]         state;
    (* mark_debug = "true" *) reg [IDX_W-1:0] point;
    reg  [2:0]         sweep_cnt;
    reg  [SETTLE_W-1:0] settle_cnt;
    reg  [GAP_W-1:0]   gap_cnt;
    reg                dac_fired;
    // mark_debug 必须加：否则综合会把这两个寄存器改名，ILA 会接到同名的
    // 不相干网络上，采到的 dac_ready / dac_error 恒为 0
    (* mark_debug = "true" *) reg dac_ready;
    (* mark_debug = "true" *) reg dac_error;

    (* mark_debug = "true" *) reg [20:0] sum0, sum1, sum2, sum3;
    (* mark_debug = "true" *) reg [20:0] sum4, sum5, sum6, sum7;

    (* mark_debug = "true" *) reg [15:0] row_ch0, row_ch1, row_ch2, row_ch3;
    (* mark_debug = "true" *) reg [15:0] row_ch4, row_ch5, row_ch6, row_ch7;
    (* mark_debug = "true" *) reg [11:0] vg_code;
    (* mark_debug = "true" *) reg        row_valid;
    (* mark_debug = "true" *) reg [7:0]  scan_count;
    (* mark_debug = "true" *) reg        scan_done;

    // 心跳计数：CLK_FREQ/2 需要 ceil(log2()) 位，之前用 24 位装不下 25,000,000
    localparam integer HB_CYC = CLK_FREQ / 2;
    localparam integer HB_W   = $clog2(HB_CYC + 1);
    reg heartbeat;
    reg [HB_W-1:0] heartbeat_cnt;

    always @(posedge sys_clk) begin
        dac_start <= 1'b0;
        row_valid <= 1'b0;

        if (sys_rst) begin
            state       <= S_WAIT;
            point       <= {IDX_W{1'b0}};
            sweep_cnt   <= 3'd0;
            settle_cnt  <= {SETTLE_W{1'b0}};
            gap_cnt     <= {GAP_W{1'b0}};
            dac_fired   <= 1'b0;
            dac_ready   <= 1'b0;
            dac_error   <= 1'b0;
            sum0 <= 21'd0; sum1 <= 21'd0; sum2 <= 21'd0; sum3 <= 21'd0;
            sum4 <= 21'd0; sum5 <= 21'd0; sum6 <= 21'd0; sum7 <= 21'd0;
            row_ch0 <= 16'd0; row_ch1 <= 16'd0; row_ch2 <= 16'd0; row_ch3 <= 16'd0;
            row_ch4 <= 16'd0; row_ch5 <= 16'd0; row_ch6 <= 16'd0; row_ch7 <= 16'd0;
            vg_code   <= 12'd0;
            scan_count<= 8'd0;
            scan_done <= 1'b0;
            heartbeat <= 1'b0;
            heartbeat_cnt <= {HB_W{1'b0}};
        end else begin
            // 1Hz 心跳
            if (heartbeat_cnt == HB_CYC - 1) begin
                heartbeat_cnt <= {HB_W{1'b0}};
                heartbeat     <= ~heartbeat;
            end else begin
                heartbeat_cnt <= heartbeat_cnt + 1'b1;
            end

            case (state)
            // 等 ADC 初始化完成，给本点装载 DAC 码
            S_WAIT: begin
                if (init_done && !init_error) begin
                    dac_set   <= CODE_START + (point * CODE_STEP);
                    dac_fired <= 1'b0;
                    state     <= S_DAC;
                end
            end

            // 发起一次 MCP4725 Fast Write
            S_DAC: begin
                if (!dac_busy && !dac_fired) begin
                    dac_start <= 1'b1;
                    dac_fired <= 1'b1;
                end
                if (dac_done) begin
                    dac_fired <= 1'b0;
                    if (dac_ack_err) begin
                        dac_error <= 1'b1;
                        gap_cnt   <= RETRY_CYC;
                        state     <= S_RETRY;
                    end else begin
                        dac_error  <= 1'b0;
                        dac_ready  <= 1'b1;
                        vg_code    <= dac_set;
                        settle_cnt <= SETTLE_CYC;
                        state      <= S_SETTLE;
                    end
                end
            end

            // 等模拟通路稳定
            S_SETTLE: begin
                if (settle_cnt == {SETTLE_W{1'b0}}) begin
                    sum0 <= 21'd0; sum1 <= 21'd0; sum2 <= 21'd0; sum3 <= 21'd0;
                    sum4 <= 21'd0; sum5 <= 21'd0; sum6 <= 21'd0; sum7 <= 21'd0;
                    state <= S_ALIGN;
                end else begin
                    settle_cnt <= settle_cnt - 1'b1;
                end
            end

            // 对齐到整扫边界，保证每轮 8 个通道各采一次
            S_ALIGN: begin
                if (adc_valid && (adc_index == 3'd7)) begin
                    sweep_cnt <= 3'd0;
                    state     <= S_ACC;
                end
            end

            // 累加 SWEEPS 轮整扫
            S_ACC: begin
                if (adc_valid) begin
                    case (adc_index)
                    3'd0: sum0 <= sum0 + adc_data;
                    3'd1: sum1 <= sum1 + adc_data;
                    3'd2: sum2 <= sum2 + adc_data;
                    3'd3: sum3 <= sum3 + adc_data;
                    3'd4: sum4 <= sum4 + adc_data;
                    3'd5: sum5 <= sum5 + adc_data;
                    3'd6: sum6 <= sum6 + adc_data;
                    3'd7: sum7 <= sum7 + adc_data;
                    endcase

                    if (adc_index == 3'd7) begin
                        if (sweep_cnt == SWEEPS - 1) begin
                            // 本轮的 CH7 还在 adc_data 里，需要单独补进来
                            row_ch0 <= sum0 >> ACC_SHIFT;
                            row_ch1 <= sum1 >> ACC_SHIFT;
                            row_ch2 <= sum2 >> ACC_SHIFT;
                            row_ch3 <= sum3 >> ACC_SHIFT;
                            row_ch4 <= sum4 >> ACC_SHIFT;
                            row_ch5 <= sum5 >> ACC_SHIFT;
                            row_ch6 <= sum6 >> ACC_SHIFT;
                            row_ch7 <= (sum7 + adc_data) >> ACC_SHIFT;
                            row_valid <= 1'b1;
                            state     <= S_NEXT;
                        end else begin
                            sweep_cnt <= sweep_cnt + 1'b1;
                        end
                    end
                end
            end

            // 本点结束，准备下一个点
            S_NEXT: begin
                if (point == POINTS - 1) begin
                    point      <= {IDX_W{1'b0}};
                    scan_count <= scan_count + 1'b1;
                    scan_done  <= 1'b1;
                    gap_cnt    <= RESTART_CYC;
                end else begin
                    point   <= point + 1'b1;
                    gap_cnt <= GAP_CYC;
                end
                state <= S_GAP;
            end

            S_GAP: begin
                if (gap_cnt == {GAP_W{1'b0}}) begin
                    state <= S_WAIT;
                end else begin
                    gap_cnt <= gap_cnt - 1'b1;
                end
            end

            S_RETRY: begin
                if (gap_cnt == {GAP_W{1'b0}}) begin
                    state <= S_WAIT;
                end else begin
                    gap_cnt <= gap_cnt - 1'b1;
                end
            end

            default: state <= S_WAIT;
            endcase
        end
    end

    // LED 低电平点亮，所以 1'b1 = 灭、1'b0 = 亮：
    //   LED1 1Hz 心跳
    //   LED2 每完成一轮扫描翻转一次（不翻转说明扫描没跑起来）
    //   LED3 亮 = init_done、dac_ready 都正常且无错误；灭 = 有问题
    assign led[0] = heartbeat;
    assign led[1] = ~scan_count[0];
    assign led[2] = ~(init_done && !init_error && dac_ready && !dac_error);
    assign led[3] = 1'b1;

endmodule
