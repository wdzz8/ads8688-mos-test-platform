`timescale 1ns / 1ps
// mos_scan 顶层仿真：ADS8688 SPI 从机模型 + MCP4725 I2C 从机模型
//
// 覆盖点：
//   1. 初始化命令序列与寄存器回读（init_error 必须为 0）
//   2. DAC 写入码按 CODE_START + point*CODE_STEP 递增
//   3. 每个扫描点只输出一行，且行的 8 个通道值与整扫边界对齐
//   4. SWEEPS 轮多点平均正确（模型让同一通道在相邻两轮相差 4，
//      平均结果应恰好是 base+2，单点采样得不到该值）
//   5. 一轮扫完 point 回绕、scan_count 递增
module mos_scan_tb;
    localparam integer POINTS = 4;
    localparam integer STEP   = 128;
    localparam integer SWEEPS  = 2;

    reg clk = 0;
    always #10 clk = ~clk;

    wire adc_cs_n, adc_sclk, adc_sdi, adc_rst_n;
    wire adc_sdo;
    wire mcp_scl, mcp_sda;
    wire [3:0] led;

    mos_scan #(
        .CLK_FREQ(50_000_000), .I2C_ADDR(7'h60),
        .POINTS(POINTS), .CODE_START(12'd0), .CODE_STEP(STEP),
        .SETTLE_MS(1), .SWEEPS(SWEEPS), .RESTART_MS(5)
    ) dut (
        .sys_clk(clk),
        .adc_cs_n(adc_cs_n), .adc_sclk(adc_sclk), .adc_sdi(adc_sdi),
        .adc_sdo(adc_sdo), .adc_rst_n(adc_rst_n),
        .mcp_sda(mcp_sda), .mcp_scl(mcp_scl), .led(led)
    );

    //======================================================================
    // ADS8688 SPI 从机模型
    //======================================================================
    reg  [15:0] sdo_value = 0;
    assign adc_sdo = adc_cs_n ? 1'bz : sdo_value;
    pullup(adc_sdo);

    integer   frame   = -1;
    integer   falling = 0;
    integer   rising  = 0;
    reg [15:0] command = 0;
    reg [15:0] frame_data;
    reg [7:0]  echo_data;
    time last_sdi_change = 0;

    // 与 mos_scan 里实例化的 RANGE0..7 一致
    function automatic [15:0] expected_command(input integer number);
        case (number)
            0:  expected_command = 16'h8500;  // SOFT_RESET
            1:  expected_command = 16'h03FF;  // AUTO_SEQ_EN
            2:  expected_command = 16'h0500;  // CH_PD
            3:  expected_command = 16'h0B00;  // CHIR_0 = ±10.24V
            4:  expected_command = 16'h0D06;  // CHIR_1 = 0..5.12V
            5:  expected_command = 16'h0F00;  // CHIR_2
            6:  expected_command = 16'h1106;  // CHIR_3
            7:  expected_command = 16'h1300;
            8:  expected_command = 16'h1500;
            9:  expected_command = 16'h1700;
            10: expected_command = 16'h1906;  // CHIR_7
            11: expected_command = 16'hA000;  // AUTO_RST
            default: expected_command = 16'h0000;
        endcase
    endfunction

    function automatic [15:0] channel_base(input integer channel);
        channel_base = 16'h1000 + channel * 16'h0100;
    endfunction

    // 相邻两轮整扫给同一通道相差 4，用于验证 SWEEPS 轮平均
    function automatic [15:0] conversion_data(input integer frame_number);
        integer channel, sweep_parity;
        begin
            channel      = (frame_number - 12) % 8;
            sweep_parity = ((frame_number - 12) / 8) % 2;
            conversion_data = channel_base(channel) + (sweep_parity ? 16'd4 : 16'd0);
        end
    endfunction

    always @(adc_sdi) last_sdi_change = $time;

    always @(negedge adc_cs_n) begin
        if (!adc_rst_n) $fatal(1, "SPI started while RST asserted");
        frame   = frame + 1;
        falling = 0;
        rising  = 0;
        command = 0;
        sdo_value = 0;
        frame_data = (frame >= 12) ? conversion_data(frame) : 16'h0000;
    end

    always @(posedge adc_sclk) begin
        if (adc_cs_n) $fatal(1, "SCLK rising while CS high");
        rising = rising + 1;
    end

    always @(negedge adc_sclk) begin
        if (frame >= 0) begin
            if (adc_cs_n) $fatal(1, "CS released before final SCLK falling edge");
            if ($time - last_sdi_change < 5) $fatal(1, "SDI setup time violated");
            falling = falling + 1;
            if (falling <= 16) command = {command[14:0], adc_sdi};
            if (falling == 16) begin
                if (command !== expected_command(frame))
                    $fatal(1, "Frame %0d command %04h, expected %04h",
                           frame, command, expected_command(frame));
                echo_data = command[7:0];
            end
            if (frame >= 1 && frame <= 10) begin
                if (falling >= 16 && falling <= 23) sdo_value <= #30 echo_data[23 - falling];
                else                                 sdo_value <= #30 1'b0;
            end else begin
                if (falling >= 16 && falling <= 31) sdo_value <= #30 frame_data[31 - falling];
                else                                 sdo_value <= #30 1'b0;
            end
        end
    end

    always @(posedge adc_cs_n) begin
        if (frame >= 0) begin
            if (rising != falling) $fatal(1, "Incomplete SCLK cycle in frame %0d", frame);
            if (falling != ((frame >= 1 && frame <= 10) ? 24 : 32))
                $fatal(1, "Wrong frame length: frame %0d, clocks %0d", frame, falling);
        end
    end

    //======================================================================
    // MCP4725 I2C 从机模型：紧跟 START、8 位数据、ACK，记录写入码
    //======================================================================
    reg  slave_low = 0;
    assign mcp_sda = slave_low ? 1'b0 : 1'bz;
    pullup(mcp_sda);
    pullup(mcp_scl);

    integer i2c_writes = 0;
    reg [11:0] written_code [0:63];
    reg [11:0] last_code = 12'hFFF;

    initial forever begin : i2c_slave
        reg [7:0] rx;
        reg [7:0] bytes [0:2];
        integer b, bit_number;
        @(negedge mcp_sda);
        if (mcp_scl === 1'b1 && dut.u_dac.busy) begin
            for (b = 0; b < 3; b = b + 1) begin
                for (bit_number = 7; bit_number >= 0; bit_number = bit_number - 1) begin
                    @(posedge mcp_scl);
                    rx[bit_number] = mcp_sda;
                end
                bytes[b] = rx;
                @(negedge mcp_scl);
                #1 slave_low = 1'b1;
                @(posedge mcp_scl);
                @(negedge mcp_scl);
                #1 slave_low = 1'b0;
            end
            @(posedge mcp_sda);
            if (mcp_scl !== 1'b1) $fatal(1, "I2C STOP without SCL high");
            if (bytes[0] !== 8'hC0) $fatal(1, "I2C address byte %02h", bytes[0]);
            last_code = {bytes[1][3:0], bytes[2]};
            if (i2c_writes < 64) written_code[i2c_writes] = last_code;
            i2c_writes = i2c_writes + 1;
        end
    end

    //======================================================================
    // 检查
    //======================================================================
    integer rows = 0;
    integer expected_point = 0;

    always @(posedge clk) begin
        if (dut.init_done && dut.init_error) $fatal(1, "ADC 初始化回读错误");
        if (dut.dac_error) $fatal(1, "DAC 报 ACK 错误");

        if (dut.row_valid) begin
            if (dut.point !== expected_point)
                $fatal(1, "行 %0d 的 point=%0d，期望 %0d", rows, dut.point, expected_point);
            if (dut.vg_code !== expected_point * STEP)
                $fatal(1, "point %0d 的 vg_code=%0d，期望 %0d",
                       expected_point, dut.vg_code, expected_point * STEP);
            if (last_code !== dut.vg_code)
                $fatal(1, "point %0d 的 DAC 实写码 %0d 与 vg_code %0d 不一致",
                       expected_point, last_code, dut.vg_code);

            // 同一通道相邻两轮相差 4，两轮平均后应恰好是 base+2
            if (dut.row_ch0 !== channel_base(0) + 2) $fatal(1, "row_ch0=%04h", dut.row_ch0);
            if (dut.row_ch1 !== channel_base(1) + 2) $fatal(1, "row_ch1=%04h", dut.row_ch1);
            if (dut.row_ch2 !== channel_base(2) + 2) $fatal(1, "row_ch2=%04h", dut.row_ch2);
            if (dut.row_ch3 !== channel_base(3) + 2) $fatal(1, "row_ch3=%04h", dut.row_ch3);
            if (dut.row_ch4 !== channel_base(4) + 2) $fatal(1, "row_ch4=%04h", dut.row_ch4);
            if (dut.row_ch5 !== channel_base(5) + 2) $fatal(1, "row_ch5=%04h", dut.row_ch5);
            if (dut.row_ch6 !== channel_base(6) + 2) $fatal(1, "row_ch6=%04h", dut.row_ch6);
            if (dut.row_ch7 !== channel_base(7) + 2) $fatal(1, "row_ch7=%04h", dut.row_ch7);
            if (led[2] !== 1'b0) $fatal(1, "LED3 应点亮（低电平点亮，0 = 正常）");

            $display("  行 %0d: point=%0d vg_code=%0d ch0..7=%04h %04h %04h %04h %04h %04h %04h %04h",
                     rows, dut.point, dut.vg_code,
                     dut.row_ch0, dut.row_ch1, dut.row_ch2, dut.row_ch3,
                     dut.row_ch4, dut.row_ch5, dut.row_ch6, dut.row_ch7);
            rows = rows + 1;
            expected_point = (expected_point + 1) % POINTS;
        end
    end

    initial begin
        wait (dut.scan_count >= 2);
        #10000;
        if (rows != 2 * POINTS) $fatal(1, "两轮扫描只输出 %0d 行", rows);
        if (i2c_writes != rows) $fatal(1, "DAC 写入 %0d 次，与 %0d 行不匹配", i2c_writes, rows);
        $display("PASS: mos_scan 扫描时序、DAC 码顺序、8 通道行数据、%0d 轮平均、point 回绕", SWEEPS);
        $finish;
    end

    initial begin
        #200000000;
        $fatal(1, "仿真超时：扫描没有启动，检查 init_done/dac_ready");
    end
endmodule
