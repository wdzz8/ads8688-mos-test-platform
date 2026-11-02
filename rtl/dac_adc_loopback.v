`timescale 1ns / 1ps
module dac_adc_loopback #(
    parameter integer CLK_FREQ = 50_000_000,
    parameter [6:0] I2C_ADDR = 7'h60
)(
    input wire sys_clk,
    output wire adc_cs_n,
    output wire adc_sclk,
    output wire adc_sdi,
    input wire adc_sdo,
    output wire adc_rst_n,
    inout wire mcp_sda,
    output wire mcp_scl,
    output wire [3:0] led
);
    (* mark_debug = "true" *) wire [15:0] ch_data;
    (* mark_debug = "true" *) wire ch_valid;
    (* mark_debug = "true" *) wire init_done, init_error;
    (* mark_debug = "true" *) wire [11:0] dac_applied;
    (* mark_debug = "true" *) wire dac_ready, dac_error, dac_busy;
    (* mark_debug = "true" *) reg capture_tick = 0;
    (* mark_debug = "true" *) reg [31:0] sample_ms = 0;
    reg [15:0] capture_count = 0;
    wire [3:0] dac_led;

    ads8688_top #(.CLK_FREQ(CLK_FREQ), .CH0_ONLY(1)) u_adc (
        .sys_clk(sys_clk), .restart(1'b0), .audit_request(1'b0), .adc_cs_n(adc_cs_n), .adc_sclk(adc_sclk),
        .adc_sdi(adc_sdi), .adc_sdo(adc_sdo), .adc_rst_n(adc_rst_n),
        .ch_data(ch_data), .ch_index(), .ch_valid(ch_valid),
        .init_done(init_done), .init_error(init_error), .reg_readback()
    );
    mcp4725_wave_test #(.CLK_FREQ(CLK_FREQ), .I2C_ADDR(I2C_ADDR)) u_dac (
        .sys_clk(sys_clk), .mcp_sda(mcp_sda), .mcp_scl(mcp_scl),
        .led(dac_led), .dac_applied(dac_applied), .dac_ready(dac_ready),
        .dac_error(dac_error), .dac_busy(dac_busy)
    );

    // Keep the ILA clock at 50 MHz. Storage qualification saves one row/ms
    // once both interfaces have started, covering 4.096 seconds at depth 4096.
    always @(posedge sys_clk) begin
        capture_tick <= 0;
        if (!init_done || !dac_ready) begin
            capture_count <= 0;
        end else if (capture_count == CLK_FREQ / 1000 - 1) begin
            capture_count <= 0;
            capture_tick <= 1;
            sample_ms <= sample_ms + 1'b1;
        end else capture_count <= capture_count + 1'b1;
    end

    assign led[1:0] = dac_led[1:0];
    assign led[2] = ~(init_done && !init_error && dac_ready && !dac_error);
    assign led[3] = 0;
endmodule
