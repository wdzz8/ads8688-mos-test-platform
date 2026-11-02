`timescale 1ns / 1ps
// Bench monitor for the MOS test platform.
//
// This stage deliberately does not control the DPS or a MOS power path. It
// verifies the complete low-energy measurement chain first:
//   MCP4725 -> optional OPA192 buffer -> ADS8688 -> FPGA channel registers.
// All eight ADS8688 channel values are retained so the J16/ADS channel
// mapping can be checked with a meter before the final scan controller is
// enabled.
module mos_adc_monitor #(
    parameter integer CLK_FREQ = 50_000_000,
    parameter [6:0] I2C_ADDR = 7'h60
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
    // The present ADS configuration uses +/-10.24 V for the high-voltage
    // nodes and 0..5.12 V for low-voltage positive signals. RANGE0 remains
    // bipolar so a grounded test input still reads near mid-scale.
    (* mark_debug = "true" *) wire [15:0] adc_data;
    (* mark_debug = "true" *) wire [2:0]  adc_index;
    (* mark_debug = "true" *) wire        adc_valid;
    (* mark_debug = "true" *) wire        init_done;
    (* mark_debug = "true" *) wire        init_error;
    wire [7:0]  reg_readback;

    (* mark_debug = "true" *) reg [15:0] adc_ch0 = 0;
    (* mark_debug = "true" *) reg [15:0] adc_ch1 = 0;
    (* mark_debug = "true" *) reg [15:0] adc_ch2 = 0;
    (* mark_debug = "true" *) reg [15:0] adc_ch3 = 0;
    (* mark_debug = "true" *) reg [15:0] adc_ch4 = 0;
    (* mark_debug = "true" *) reg [15:0] adc_ch5 = 0;
    (* mark_debug = "true" *) reg [15:0] adc_ch6 = 0;
    (* mark_debug = "true" *) reg [15:0] adc_ch7 = 0;
    (* mark_debug = "true" *) reg [2:0]  adc_last_index = 0;
    (* mark_debug = "true" *) reg        adc_sample_pulse = 0;
    (* mark_debug = "true" *) wire [11:0] dac_applied;
    (* mark_debug = "true" *) wire        dac_ready;
    (* mark_debug = "true" *) wire        dac_error;
    (* mark_debug = "true" *) wire        dac_busy;
    (* mark_debug = "true" *) reg         point_valid = 0;
    (* mark_debug = "true" *) reg [31:0]  sample_ms = 0;

    reg [15:0] capture_count = 0;
    wire [3:0] dac_led;

    ads8688_top #(
        .CLK_FREQ(CLK_FREQ), .CH0_ONLY(0),
        .RANGE0(4'h0), // AIN0: bipolar for grounded/DAC loopback checks
        .RANGE1(4'h6), // AIN1: 0..5.12 V, expected gate voltage
        .RANGE2(4'h0), // AIN2: bipolar high-voltage node
        .RANGE3(4'h6), // AIN3: 0..5.12 V, expected source voltage
        .RANGE4(4'h0), .RANGE5(4'h0), .RANGE6(4'h0), .RANGE7(4'h6)
    ) u_adc (
        .sys_clk(sys_clk), .restart(1'b0), .audit_request(1'b0), .adc_cs_n(adc_cs_n), .adc_sclk(adc_sclk),
        .adc_sdi(adc_sdi), .adc_sdo(adc_sdo), .adc_rst_n(adc_rst_n),
        .ch_data(adc_data), .ch_index(adc_index), .ch_valid(adc_valid),
        .init_done(init_done), .init_error(init_error),
        .reg_readback(reg_readback)
    );

    // The existing triangular DAC source is useful as a safe low-voltage
    // stimulus. It is intentionally kept separate from the final VGS scan.
    mcp4725_wave_test #(.CLK_FREQ(CLK_FREQ), .I2C_ADDR(I2C_ADDR)) u_dac (
        .sys_clk(sys_clk), .mcp_sda(mcp_sda), .mcp_scl(mcp_scl),
        .led(dac_led), .dac_applied(dac_applied), .dac_ready(dac_ready),
        .dac_error(dac_error), .dac_busy(dac_busy)
    );

    // Keep the most recent conversion for every channel. The values are
    // updated only on adc_valid, so ILA rows never contain half-written data.
    always @(posedge sys_clk) begin
        adc_sample_pulse <= adc_valid;
        if (adc_valid) begin
            adc_last_index <= adc_index;
            case (adc_index)
                3'd0: adc_ch0 <= adc_data;
                3'd1: adc_ch1 <= adc_data;
                3'd2: adc_ch2 <= adc_data;
                3'd3: adc_ch3 <= adc_data;
                3'd4: adc_ch4 <= adc_data;
                3'd5: adc_ch5 <= adc_data;
                3'd6: adc_ch6 <= adc_data;
                3'd7: adc_ch7 <= adc_data;
            endcase
        end
    end

    // ILA storage qualification: one complete multi-channel snapshot each
    // millisecond. At depth 4096 this spans about 4.1 s.
    always @(posedge sys_clk) begin
        point_valid <= 1'b0;
        if (!init_done || !dac_ready) begin
            capture_count <= 0;
            sample_ms <= 0;
        end else if (capture_count == CLK_FREQ / 1000 - 1) begin
            capture_count <= 0;
            point_valid <= 1'b1;
            sample_ms <= sample_ms + 1'b1;
        end else begin
            capture_count <= capture_count + 1'b1;
        end
    end

    assign led[1:0] = dac_led[1:0];
    assign led[2] = ~(init_done && !init_error && dac_ready && !dac_error);
    assign led[3] = 1'b0;
endmodule
