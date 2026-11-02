`timescale 1ns / 1ps
module dac_adc_capture_tb;
    reg clk = 0;
    always #125 clk = ~clk;
    tri1 sda;
    wire scl;
    integer cycles = 0;
    integer last_tick = 0;
    integer tick_count = 0;
    reg enabled = 0;

    dac_adc_loopback #(.CLK_FREQ(4_000_000)) dut (
        .sys_clk(clk), .adc_sdo(1'b0), .mcp_sda(sda), .mcp_scl(scl)
    );

    always @(posedge clk) begin
        cycles = cycles + 1;
        #1;
        if (dut.capture_tick) begin
            if (!enabled) $fatal(1, "Capture before interfaces ready");
            if (last_tick != 0 && cycles - last_tick != 4000)
                $fatal(1, "Capture cadence is not 1 ms");
            last_tick = cycles;
            tick_count = tick_count + 1;
            if (dut.sample_ms != tick_count)
                $fatal(1, "Timestamp mismatch");
        end
    end

    initial begin
        force dut.init_done = 0;
        force dut.dac_ready = 0;
        repeat (4400) @(negedge clk);
        force dut.init_done = 1;
        repeat (4400) @(negedge clk);
        enabled = 1;
        force dut.dac_ready = 1;
        repeat (12400) @(negedge clk);
        if (tick_count != 3) $fatal(1, "Expected three captures");
        enabled = 0;
        force dut.dac_ready = 0;
        repeat (4400) @(negedge clk);
        if (tick_count != 3) $fatal(1, "Capture continued after DAC not ready");
        last_tick = 0;
        enabled = 1;
        force dut.dac_ready = 1;
        repeat (8400) @(negedge clk);
        if (tick_count != 5) $fatal(1, "Capture did not resume");
        $display("PASS: ADC/DAC capture gating and 1 ms cadence");
        $finish;
    end
    initial begin
        #10_000_000;
        $fatal(1, "Capture test timeout");
    end
endmodule
