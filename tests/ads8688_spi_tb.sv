`timescale 1ns / 1ps

module ads8688_spi_case #(
    parameter integer SDO_MODE = 0,
    parameter integer CH0_ONLY = 0,
    parameter integer RESTART_TEST = 0,
    parameter integer AUDIT_TEST = 0
)(
    input wire sys_clk,
    output reg complete
);
    initial complete = 0;
    wire cs_n, sclk, sdi, rst_n, sdo;
    wire [15:0] ch_data;
    wire [2:0] ch_index;
    wire ch_valid, init_done, init_error;
    wire [7:0] reg_readback;
    reg sdo_value = 0;
    integer frame = -1;
    integer falling_edges = 0;
    integer rising_edges = 0;
    integer samples = 0;
    reg [15:0] command = 0;
    reg [15:0] frame_data;
    reg [7:0] echo_data;
    time last_falling = 0;
    time last_sdi_change = 0;
    reg previous_valid = 0;
    reg restart = 0;
    integer restart_count = 0;
    reg audit_request = 0;
    wire audit_done;
    wire [95:0] audit_values;
    integer audit_byte;
    function automatic [6:0] read_address(input integer index);
        case(index)
            0: read_address = 7'h3f;
            1: read_address = 7'h01;
            2: read_address = 7'h02;
            3: read_address = 7'h03;
            default: read_address = index + 1;
        endcase
    endfunction

    // Model the chip's tri-state output and an external pull-up while idle.
    pullup(sdo);
    assign sdo = SDO_MODE == 1 ? 1'b1 :
                 SDO_MODE == 2 ? 1'b0 : cs_n ? 1'bz : sdo_value;

    ads8688_top #(.CH0_ONLY(CH0_ONLY), .EXTERNAL_RESET_ENABLE(RESTART_TEST || AUDIT_TEST),
                 .DIAGNOSTIC_READ_ENABLE(AUDIT_TEST)) dut (
        .sys_clk(sys_clk), .restart(restart), .audit_request(audit_request),
        .audit_done(audit_done), .audit_values(audit_values), .adc_cs_n(cs_n), .adc_sclk(sclk),
        .adc_sdi(sdi), .adc_sdo(sdo), .adc_rst_n(rst_n),
        .ch_data(ch_data), .ch_index(ch_index), .ch_valid(ch_valid),
        .init_done(init_done), .init_error(init_error),
        .reg_readback(reg_readback)
    );

    always @(negedge rst_n) begin
        if (audit_request && restart_count == 0) $fatal(1, "Read audit reset the ADC");
        frame = -1;
        samples = 0;
        previous_valid = 0;
    end
    initial if (RESTART_TEST) begin
        wait (samples == 8);
        @(negedge sys_clk);
        restart = 1;
        restart_count = restart_count + 1;
        repeat (4) @(negedge sys_clk);
        restart = 0;
    end
    initial if (AUDIT_TEST) begin
        wait (samples == 8);
        @(negedge sys_clk);
        audit_request = 1;
        wait (audit_done);
        @(negedge sys_clk);
        for (audit_byte = 0; audit_byte < 12; audit_byte = audit_byte + 1)
            if (audit_values[audit_byte * 8 +: 8] !== (8'ha0 ^ audit_byte[7:0]))
                $fatal(1, "Wrong audit byte %0d", audit_byte);
        repeat (2000) begin
            @(negedge sys_clk);
            if (!cs_n || sclk || !rst_n || ch_valid || samples != 8)
                $fatal(1, "Read audit did not hold SPI and conversions idle");
        end
        audit_request = 0;
        restart = 1;
        restart_count = 1;
        repeat (4) @(negedge sys_clk);
        restart = 0;
        wait (samples == 16);
        if (audit_done) $fatal(1, "ADC restart did not clear audit hold");
        $display("PASS: read-only audit 12 registers, no reset/write, hold, restart recovery");
    end

    function automatic [15:0] expected_command(input integer number);
        if (AUDIT_TEST && !restart_count && number >= 20)
            expected_command = {read_address(number - 20), 1'b0, 8'h00};
        else
        case (number)
            0: expected_command = 16'h8500;
            1: expected_command = 16'h03ff;
            2: expected_command = 16'h0500;
            3: expected_command = 16'h0b00;
            4: expected_command = 16'h0d00;
            5: expected_command = 16'h0f00;
            6: expected_command = 16'h1100;
            7: expected_command = 16'h1300;
            8: expected_command = 16'h1500;
            9: expected_command = 16'h1700;
            10: expected_command = 16'h1900;
            11: expected_command = CH0_ONLY ? 16'hc000 : 16'ha000;
            default: expected_command = 16'h0000;
        endcase
    endfunction

    function automatic [15:0] conversion_data(input integer channel);
        case (channel)
            0: conversion_data = 16'h8000;
            1: conversion_data = 16'h94a0;
            2: conversion_data = 16'h0000;
            3: conversion_data = 16'hffff;
            4: conversion_data = 16'h5555;
            5: conversion_data = 16'haaaa;
            6: conversion_data = 16'h8001;
            7: conversion_data = 16'h7fff;
        endcase
    endfunction

    always @(sdi) last_sdi_change = $time;

    always @(negedge cs_n) begin
        if (!rst_n) $fatal(1, "SPI started while RST/PD was asserted");
        frame = frame + 1;
        falling_edges = 0;
        rising_edges = 0;
        command = 0;
        sdo_value = 0;
        frame_data = frame >= 12 ? conversion_data(CH0_ONLY ? 0 : (frame - 12) % 8) : 0;
    end

    always @(posedge sclk) begin
        if (cs_n) $fatal(1, "SCLK rising with CS high");
        rising_edges = rising_edges + 1;
    end

    // TI SBAS582C: latch SDI on falling edges and launch MSB on edge 16.
    always @(negedge sclk) begin
        if (frame >= 0 && !restart) begin
            if (cs_n) $fatal(1, "CS released before final SCLK falling edge");
            if ($time - last_sdi_change < 5)
                $fatal(1, "SDI setup time violated");
            falling_edges = falling_edges + 1;
            last_falling = $time;
            if (falling_edges <= 16)
                command = {command[14:0], sdi};
            if (falling_edges == 16) begin
                if (command !== expected_command(frame))
                    $fatal(1, "Frame %0d command got %04h expected %04h",
                           frame, command, expected_command(frame));
                echo_data = command[7:0];
                if (AUDIT_TEST && !restart_count && frame >= 20)
                    echo_data = 8'ha0 ^ (frame - 20);
                if (SDO_MODE == 3 && frame == 5)
                    echo_data = echo_data ^ 8'h80;
            end
            if ((frame >= 1 && frame <= 10) || (AUDIT_TEST && !restart_count && frame >= 20)) begin
                if (falling_edges >= 16 && falling_edges <= 23)
                    sdo_value <= #30 echo_data[23 - falling_edges];
                else
                    sdo_value <= #30 0;
            end else begin
                if (falling_edges >= 16 && falling_edges <= 31)
                    sdo_value <= #30 frame_data[31 - falling_edges];
                else
                    sdo_value <= #30 0;
            end
        end
    end

    always @(posedge cs_n) begin
        if (frame >= 0 && !restart) begin
            if (sclk !== 0 || $time - last_falling < 10)
                $fatal(1, "Final SCLK edge / CS hold time violated");
            if (rising_edges != falling_edges)
                $fatal(1, "Incomplete SCLK cycle in frame %0d", frame);
            if (falling_edges != (((frame >= 1 && frame <= 10) ||
                (AUDIT_TEST && !restart_count && frame >= 20)) ? 24 : 32))
                $fatal(1, "Wrong frame length: frame %0d, clocks %0d",
                       frame, falling_edges);
            if (samples == 16 && (!(RESTART_TEST || AUDIT_TEST) || restart_count == 1)) begin
                $display("PASS SDO_MODE=%0d CH0_ONLY=%0d: initialization, frame timing, 16 samples",
                         SDO_MODE, CH0_ONLY);
                complete = 1;
            end
        end
    end

    always @(negedge sys_clk) begin
        if (ch_valid) begin
            if (previous_valid) $fatal(1, "ch_valid longer than one clock");
            if (!init_done || init_error !== (SDO_MODE != 0))
                $fatal(1, "Initialization status wrong for SDO_MODE=%0d", SDO_MODE);
            if (ch_index !== (CH0_ONLY ? 0 : samples % 8))
                $fatal(1, "Wrong channel: got %0d expected %0d", ch_index, samples % 8);
            if (ch_data !== (SDO_MODE == 1 ? 16'hffff :
                             SDO_MODE == 2 ? 16'h0000 : conversion_data(CH0_ONLY ? 0 : samples % 8)))
                $fatal(1, "Wrong conversion: got %04h, sample %0d", ch_data, samples);
            samples = samples + 1;
        end
        previous_valid = ch_valid;
    end
endmodule

module ads8688_spi_tb;
    reg sys_clk = 0;
    always #10 sys_clk = ~sys_clk;
    wire [7:0] complete;
    ads8688_spi_case #(.SDO_MODE(0)) normal(sys_clk, complete[0]);
    ads8688_spi_case #(.SDO_MODE(1)) stuck_high(sys_clk, complete[1]);
    ads8688_spi_case #(.SDO_MODE(2)) stuck_low(sys_clk, complete[2]);
    ads8688_spi_case #(.SDO_MODE(3)) corrupt_echo(sys_clk, complete[3]);
    ads8688_spi_case #(.CH0_ONLY(1)) manual_ch0(sys_clk, complete[4]);
    ads8688_spi_case #(.SDO_MODE(3), .CH0_ONLY(1)) manual_bad_echo(sys_clk, complete[5]);
    ads8688_spi_case #(.RESTART_TEST(1)) external_restart(sys_clk, complete[6]);
    ads8688_spi_case #(.AUDIT_TEST(1)) register_audit(sys_clk, complete[7]);

    initial begin
        wait (&complete);
        $display("PASS: all ADS8688 SPI regression checks");
        $finish;
    end
    initial begin
        #160000000; // restart case performs the full initialization twice
        $fatal(1, "Timed out waiting for conversion data");
    end
endmodule
