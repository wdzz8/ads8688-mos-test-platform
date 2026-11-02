`timescale 1ns / 1ps
// PCB1 host-controlled fixed gate / low-frequency square-wave experiment.
// Each row is one unaveraged, sequential 8-channel sweep. No drain control.
module mos_experiment #(parameter integer CLK_FREQ=50_000_000)(
    input wire sys_clk, input wire adc_sdo,
    output wire adc_cs_n, adc_sclk, adc_sdi, adc_rst_n,
    inout wire mcp_sda, output wire mcp_scl, output wire [3:0] led
);
    reg [15:0] por_count=0;
    wire por=!por_count[15];
    always @(posedge sys_clk) if (por) por_count<=por_count+1'b1;
    wire [11:0] request_low, request_high;
    wire [31:0] request_half_cycles;
    wire request_wave, request_apply, request_adc_reset;
    (* mark_debug="true" *) wire [15:0] adc_data;
    (* mark_debug="true" *) wire [2:0] adc_index;
    (* mark_debug="true" *) wire adc_valid, init_done, init_error;
    ads8688_top #(.EXTERNAL_RESET_ENABLE(1), .RANGE0(0), .RANGE1(6),
        .RANGE2(0), .RANGE3(6), .RANGE4(0), .RANGE5(0), .RANGE6(0), .RANGE7(6)) u_adc(
        .sys_clk(sys_clk), .restart(request_adc_reset), .audit_request(1'b0),
        .adc_cs_n(adc_cs_n), .adc_sclk(adc_sclk), .adc_sdi(adc_sdi),
        .adc_sdo(adc_sdo), .adc_rst_n(adc_rst_n), .ch_data(adc_data),
        .ch_index(adc_index), .ch_valid(adc_valid), .init_done(init_done),
        .init_error(init_error), .reg_readback()
    );
    reg [11:0] low_code=256, high_code=256;
    reg [31:0] half_cycles=25_000_000, phase_cycles=0;
    reg wave=0, phase=0, previous_apply=0;
    (* mark_debug="true" *) reg [15:0] configuration_id=0;
    wire apply=request_apply && !previous_apply;
    wire [11:0] desired_code=phase ? high_code : low_code;
    always @(posedge sys_clk) begin
        previous_apply<=request_apply;
        if (por) begin
            low_code<=256; high_code<=256; half_cycles<=25_000_000;
            phase_cycles<=0; wave<=0; phase<=0; configuration_id<=0;
        end else if (apply) begin
            low_code<=request_low; high_code<=request_high;
            half_cycles <= request_half_cycles < CLK_FREQ/1000 ? CLK_FREQ/1000 : request_half_cycles;
            phase_cycles<=0; phase<=0; wave<=request_wave;
            configuration_id<=configuration_id+1'b1;
        end else if (wave && init_done && !init_error) begin
            if (phase_cycles>=half_cycles-1) begin
                phase_cycles<=0; phase<=!phase;
            end else phase_cycles<=phase_cycles+1'b1;
        end else begin phase_cycles<=0; phase<=0; end
    end
    reg dac_start=0, have_code=0;
    reg [11:0] dac_set=256;
    wire dac_done, dac_ack_error;
    (* mark_debug="true" *) wire dac_busy;
    (* mark_debug="true" *) reg dac_ready=0, dac_error=0;
    (* mark_debug="true" *) reg [11:0] vg_code=256;
    (* mark_debug="true" *) reg [31:0] transition_count=0;
    mcp4725_i2c #(.CLK_FREQ(CLK_FREQ)) u_dac(
        .clk(sys_clk), .rst(por), .start(dac_start), .dac_code(dac_set),
        .busy(dac_busy), .done(dac_done), .ack_error(dac_ack_error),
        .scl(mcp_scl), .sda(mcp_sda)
    );
    always @(posedge sys_clk) begin
        dac_start<=0;
        if (por) begin
            dac_ready<=0; dac_error<=0; have_code<=0; vg_code<=256; transition_count<=0;
        end else begin
            if (apply) dac_error<=0;
            if (init_done && !init_error && !dac_busy && !dac_start && !dac_done &&
                !dac_error && (!have_code || vg_code!=desired_code)) begin
                dac_set<=desired_code; dac_start<=1;
            end
            if (dac_done) begin
                if (dac_ack_error) begin dac_error<=1; dac_ready<=0; end
                else begin
                    have_code<=1; dac_ready<=1; vg_code<=dac_set;
                    transition_count<=transition_count+1'b1;
                end
            end
        end
    end
    (* mark_debug="true" *) reg [15:0] row_ch0=0,row_ch1=0,row_ch2=0,row_ch3=0;
    (* mark_debug="true" *) reg [15:0] row_ch4=0,row_ch5=0,row_ch6=0,row_ch7=0;
    (* mark_debug="true" *) reg row_valid=0,row_bad=0,row_transition=0;
    (* mark_debug="true" *) reg [31:0] row_sequence=0;
    (* mark_debug="true" *) reg [31:0] timestamp_cycles=0;
    (* mark_debug="true" *) reg [31:0] row_start_cycles=0;
    reg [31:0] cycles=0, sweep_start=0, sweep_transition=0;
    reg [11:0] sweep_code=0;
    reg [15:0] sweep_config=0;
    reg [2:0] expected_channel=0;
    reg aligned=0, sweep_bad=0, sweep_busy=0;
    (* mark_debug="true" *) reg [15:0] ffff_run=0;
    (* mark_debug="true" *) reg fault_latched=0;
    (* mark_debug="true" *) reg [11:0] row_start_code=0;
    always @(posedge sys_clk) begin
        cycles<=cycles+1'b1; row_valid<=0;
        if (por) begin
            cycles<=0; aligned<=0; row_sequence<=0; ffff_run<=0; fault_latched<=0;
        end else begin
            if (!init_done || request_adc_reset) aligned<=0;
            if (adc_valid && init_done && !request_adc_reset) begin
                if (adc_data==16'hffff) begin
                    if (ffff_run!=65535) ffff_run<=ffff_run+1'b1;
                    if (ffff_run>=15) fault_latched<=1;
                end else ffff_run<=0;
                if (adc_index==0) begin
                    aligned<=1; expected_channel<=1; row_ch0<=adc_data;
                    sweep_start<=cycles; sweep_code<=vg_code; sweep_config<=configuration_id;
                    sweep_transition<=transition_count; sweep_busy<=dac_busy;
                    sweep_bad<=adc_data==16'hffff;
                end else if (aligned && adc_index==expected_channel) begin
                    expected_channel<=expected_channel+1'b1;
                    sweep_bad<=sweep_bad || adc_data==16'hffff;
                    sweep_busy<=sweep_busy || dac_busy;
                    case (adc_index)
                        1: row_ch1<=adc_data; 2: row_ch2<=adc_data; 3: row_ch3<=adc_data;
                        4: row_ch4<=adc_data; 5: row_ch5<=adc_data; 6: row_ch6<=adc_data;
                        7: begin
                            row_ch7<=adc_data; row_valid<=1; row_sequence<=row_sequence+1'b1;
                            timestamp_cycles<=cycles; row_start_cycles<=sweep_start; row_start_code<=sweep_code;
                            row_bad<=sweep_bad || adc_data==16'hffff || init_error || !dac_ready || dac_error;
                            row_transition<=sweep_busy || dac_busy || sweep_transition!=transition_count ||
                                sweep_config!=configuration_id;
                        end
                    endcase
                end else aligned<=0;
            end
        end
    end
    experiment_vio u_control(
        .clk(sys_clk), .probe_in0(configuration_id),
        .probe_out0(request_low), .probe_out1(request_high), .probe_out2(request_half_cycles),
        .probe_out3(request_wave), .probe_out4(request_adc_reset), .probe_out5(request_apply)
    );
    assign led={1'b1,!fault_latched,!(init_done && !init_error && dac_ready && !dac_error),cycles[24]};
endmodule
