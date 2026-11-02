`timescale 1ns / 1ps
//==========================================================================
//  ADS8688 采集 —— 板载 LED 指示版（不需要 ILA 的简化验证）
//--------------------------------------------------------------------------
//  说明：本模块只是把 ads8688_top 包一层，用 4 个板载 LED 把关键状态显示出来，
//        这样你不需要搭 ILA、不需要 Set Up Debug，生成 bit 下载就能看到结果。
//
//  4 个 LED 分别代表什么（AX7020 的 LED 是低电平点亮，代码里已取反）：
//
//    LED1 (M14) : 与 LED2 每 250ms 交替点亮，确认新版已运行
//    LED2 (M15) : 与 LED1 反相，每 250ms 交替点亮
//    LED3 (K16) : 初始化回读检查    -> 初始化完成且所有寄存器回读匹配时点亮
//    LED4 (J16) : 常亮，作为本版下载确认标志
//
//  怎么判断：
//     LED3 亮表示数字寄存器通信通过，模拟采集仍需用已知输入验证。
//     LED1/LED2 交替和 LED4 常亮独立于 ADC 状态，只确认 FPGA 程序运行。
//==========================================================================
module ads8688_led_test #(
    parameter CH0_ONLY = 0
)(
    input  wire        sys_clk,     // 50MHz 板载时钟，管脚 U18
    // ---------- 接到 ADS8688 模块 P1 ----------
    (* mark_debug = "true" *) output wire        adc_cs_n,   // 一起抓进 ILA 看波形
    (* mark_debug = "true" *) output wire        adc_sclk,
    (* mark_debug = "true" *) output wire        adc_sdi,
    (* mark_debug = "true" *) input  wire        adc_sdo,    // 抓出来方便看 SPI 波形
    output wire        adc_rst_n,
    // ---------- 板载 4 个 PL LED ----------
    output wire [3:0]  led
);

    // 下面 3 个信号打了 mark_debug 标记，
    // Set Up Debug 向导会自动把它们列出来，你不用手动找
    (* mark_debug = "true" *) wire [15:0] ch_data;
    (* mark_debug = "true" *) wire [2:0]  ch_index;
    (* mark_debug = "true" *) wire        ch_valid;
    (* mark_debug = "true" *) wire        init_done;
    (* mark_debug = "true" *) wire        init_error;
    (* mark_debug = "true" *) wire [7:0]  reg_readback;

    // ---------------- 例化采集核心 ----------------
    ads8688_top #(.CH0_ONLY(CH0_ONLY)) u_adc (
        .sys_clk   (sys_clk),
        .restart   (1'b0),
        .audit_request(1'b0),
        .adc_cs_n  (adc_cs_n),
        .adc_sclk  (adc_sclk),
        .adc_sdi   (adc_sdi),
        .adc_sdo   (adc_sdo),
        .adc_rst_n (adc_rst_n),
        .ch_data   (ch_data),
        .ch_index  (ch_index),
        .ch_valid  (ch_valid),
        .init_done (init_done),
        .init_error (init_error),
        .reg_readback (reg_readback)
    );

    // 50MHz 时钟下每 250ms 换相，LED1/LED2 始终一亮一灭。
    reg [23:0] blink_cnt = 24'd0;
    reg        blink_phase = 1'b0;
    always @(posedge sys_clk) begin
        if (blink_cnt == 24'd12_499_999) begin
            blink_cnt <= 24'd0;
            blink_phase <= ~blink_phase;
        end else begin
            blink_cnt <= blink_cnt + 1'b1;
        end
    end

    wire init_ok = init_done && !init_error;

    assign led[0] = blink_phase;     // 下载确认：LED1/LED2 交替
    assign led[1] = ~blink_phase;
    assign led[2] = ~init_ok;         // 初始化回读检查
    assign led[3] = 1'b0;            // 下载确认：LED4 常亮（低电平点亮）

endmodule
