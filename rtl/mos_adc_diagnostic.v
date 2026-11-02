`timescale 1ns / 1ps
// Drain OFF diagnostic only. ADC can be reset independently of the fixed DAC.
// Fault evidence is sticky across ADC resets and clears only on FPGA programming.
module mos_adc_diagnostic #(
    parameter [11:0] DAC_CODE = 12'd2560
)(
    input wire sys_clk,
    output wire adc_cs_n, adc_sclk, adc_sdi, adc_rst_n,
    input wire adc_sdo,
    inout wire mcp_sda,
    output wire mcp_scl,
    output wire [3:0] led
);
    reg [15:0] por_count = 0;
    wire por = !por_count[15];
    always @(posedge sys_clk)
        if (!por_count[15]) por_count <= por_count + 1'b1;

    (* mark_debug = "true" *) wire adc_reset_request;
    (* mark_debug = "true" *) wire adc_audit_request;
    (* mark_debug = "true" *) wire adc_audit_done;
    (* mark_debug = "true" *) wire [95:0] adc_audit_values;
    (* mark_debug = "true" *) wire [15:0] adc_data;
    (* mark_debug = "true" *) wire [2:0] adc_index;
    (* mark_debug = "true" *) wire adc_valid, init_done, init_error;
    (* mark_debug = "true" *) wire [7:0] reg_readback;
    ads8688_top #(
        .EXTERNAL_RESET_ENABLE(1), .DIAGNOSTIC_READ_ENABLE(1), .CH0_ONLY(0),
        .RANGE0(0), .RANGE1(6), .RANGE2(0), .RANGE3(6),
        .RANGE4(0), .RANGE5(0), .RANGE6(0), .RANGE7(6)
    ) u_adc (
        .sys_clk(sys_clk), .restart(adc_reset_request),
        .audit_request(adc_audit_request), .audit_done(adc_audit_done),
        .audit_values(adc_audit_values),
        .adc_cs_n(adc_cs_n), .adc_sclk(adc_sclk), .adc_sdi(adc_sdi),
        .adc_sdo(adc_sdo), .adc_rst_n(adc_rst_n),
        .ch_data(adc_data), .ch_index(adc_index), .ch_valid(adc_valid),
        .init_done(init_done), .init_error(init_error), .reg_readback(reg_readback)
    );

    wire dac_busy, dac_done, dac_ack_error;
    reg dac_start = 0;
    reg dac_sent = 0;
    (* mark_debug = "true" *) reg dac_ready = 0;
    (* mark_debug = "true" *) reg dac_error = 0;
    mcp4725_i2c u_dac (
        .clk(sys_clk), .rst(por), .start(dac_start), .dac_code(DAC_CODE),
        .busy(dac_busy), .done(dac_done), .ack_error(dac_ack_error),
        .scl(mcp_scl), .sda(mcp_sda)
    );
    always @(posedge sys_clk) begin
        dac_start <= 0;
        if (por) begin
            dac_sent <= 0;
            dac_ready <= 0;
            dac_error <= 0;
        end else begin
            if (!dac_sent && !dac_busy) begin
                dac_start <= 1;
                dac_sent <= 1;
            end
            if (dac_done) begin
                dac_ready <= !dac_ack_error;
                dac_error <= dac_ack_error;
            end
        end
    end

    (* mark_debug = "true" *) reg [31:0] timestamp_cycles = 0;
    (* mark_debug = "true" *) reg [31:0] sample_count = 0;
    (* mark_debug = "true" *) reg [15:0] ffff_run = 0;
    (* mark_debug = "true" *) reg fault_latched = 0;
    (* mark_debug = "true" *) reg [15:0] adc_reset_count = 0;
    reg reset_previous = 0;
    always @(posedge sys_clk) begin
        if (por) begin
            timestamp_cycles <= 0;
            sample_count <= 0;
            ffff_run <= 0;
            fault_latched <= 0;
            adc_reset_count <= 0;
            reset_previous <= 0;
        end else begin
            timestamp_cycles <= timestamp_cycles + 1'b1;
            reset_previous <= adc_reset_request;
            if (adc_reset_request && !reset_previous)
                adc_reset_count <= adc_reset_count + 1'b1;
            if (adc_valid) begin
                sample_count <= sample_count + 1'b1;
                if (adc_data == 16'hffff) begin
                    if (ffff_run != 16'hffff) ffff_run <= ffff_run + 1'b1;
                    if (ffff_run >= 15) fault_latched <= 1;
                end else ffff_run <= 0;
            end
        end
    end

    adc_reset_vio u_adc_reset_vio (
        .clk(sys_clk), .probe_in0(fault_latched),
        .probe_in1(adc_reset_count), .probe_in2(ffff_run),
        .probe_in3(adc_audit_done), .probe_in4(adc_audit_values),
        .probe_out0(adc_reset_request), .probe_out1(adc_audit_request)
    );
    assign led = {1'b1, !fault_latched,
                  !(init_done && !init_error && dac_ready && !dac_error), timestamp_cycles[24]};
endmodule
