`timescale 1ns / 1ps
module mcp4725_wave_tb;
    reg clk = 0;
    always #500 clk = ~clk;
    tri1 scl, sda;
    reg slave_low = 0;
    assign sda = slave_low ? 0 : 1'bz;
    wire [11:0] applied;
    wire ready, error_flag, busy;
    wire [3:0] led;
    integer writes = 0, expected = 0;
    reg up = 1;
    time last_start = 0;
    reg inject_nack = 0;
    mcp4725_wave_test #(.CLK_FREQ(1_000_000), .UPDATE_HZ(100)) dut (
        .sys_clk(clk), .mcp_sda(sda), .mcp_scl(scl), .led(led),
        .dac_applied(applied), .dac_ready(ready), .dac_error(error_flag), .dac_busy(busy)
    );
    initial forever begin : model
        reg [7:0] bytes [0:2];
        integer b, k;
        @(negedge sda);
        if (scl === 1 && busy) begin
            if (last_start != 0 && $time - last_start != 10000000)
                $fatal(1, "Update interval is not 10ms");
            last_start = $time;
            for (b = 0; b < 3; b = b + 1) begin
                for (k = 7; k >= 0; k = k - 1) begin
                    @(posedge scl); bytes[b][k] = sda;
                end
                @(negedge scl); #1 slave_low = !inject_nack;
                @(posedge scl);
                @(negedge scl); #1 slave_low = 0;
                if (inject_nack) break;
            end
            @(posedge sda);
            if (!inject_nack) begin
                if (bytes[0] !== 8'hC0 || bytes[1][7:4] !== 0 || {bytes[1][3:0],bytes[2]} !== expected[11:0])
                    $fatal(1, "Triangle wire data differs from expected %0d", expected);
                wait(!busy);
                repeat(3) @(negedge clk);
                if (!ready || applied !== expected[11:0] || error_flag)
                    $fatal(1, "Applied code/status mismatch");
                writes = writes + 1;
                if (writes == 129) begin
                    if (expected != 0) $fatal(1, "Triangle did not return to zero");
                    inject_nack = 1;
                end
                if (up) begin
                    if (expected >= 4032) begin expected = 4095; up = 0; end
                    else expected = expected + 64;
                end else begin
                    if (expected <= 63) begin expected = 0; up = 1; end
                    else expected = expected - 64;
                end
            end else begin
                wait(!busy);
                repeat(3) @(negedge clk);
                if (ready || !error_flag || applied !== 0)
                    $fatal(1, "NACK published an unapplied code");
                $display("PASS: MCP4725 triangle: full up/down cycle, 10ms updates, ACK-qualified codes, NACK status");
                $finish;
            end
        end
    end
    initial begin #1400000000; $fatal(1, "Wave test timeout"); end
endmodule
