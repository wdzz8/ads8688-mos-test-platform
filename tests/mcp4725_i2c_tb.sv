`timescale 1ns / 1ps
module mcp4725_i2c_tb;
    reg clk = 0, rst = 1, start = 0;
    reg [11:0] dac_code = 0;
    tri1 scl, sda;
    reg slave_low = 0;
    assign sda = slave_low ? 1'b0 : 1'bz;
    wire busy, done, ack_error;
    integer byte_count = 0;
    reg [7:0] bytes [0:2];
    integer nack_byte = -1;
    integer stops = 0;
    time last_rise = 0;
    reg check_period = 0;
    always #10 clk = ~clk;
    mcp4725_i2c dut (
        .clk(clk), .rst(rst), .start(start), .dac_code(dac_code),
        .busy(busy), .done(done), .ack_error(ack_error), .scl(scl), .sda(sda)
    );

    // Behavioral slave follows START, eight data bits, ACK, then STOP.
    // The expected bytes implement datasheet Figure 6-1 (Fast Write).
    initial forever begin : slave
        reg [7:0] rx;
        integer b, bit_number;
        @(negedge sda);
        if (scl === 1'b1 && busy) begin
            byte_count = 0;
            last_rise = 0;
            for (b = 0; b < 3; b = b + 1) begin
                for (bit_number = 7; bit_number >= 0; bit_number = bit_number - 1) begin
                    @(posedge scl);
                    if (check_period && last_rise != 0 && $time - last_rise != 10000)
                        $fatal(1, "I2C period is %0t, expected 10us", $time - last_rise);
                    last_rise = $time;
                    rx[bit_number] = sda;
                end
                bytes[b] = rx;
                byte_count = byte_count + 1;
                @(negedge scl);
                #1 slave_low = (b != nack_byte);
                @(posedge scl);
                last_rise = $time;
                @(negedge scl);
                #1 slave_low = 0;
                if (b == nack_byte) break;
            end
            @(posedge sda);
            if (scl !== 1'b1) $fatal(1, "STOP without SCL high");
            stops = stops + 1;
        end
    end

    task automatic write_check(input [11:0] code, input integer nack);
        integer old_stops;
        begin
            old_stops = stops;
            nack_byte = nack;
            @(negedge clk);
            dac_code = code;
            start = 1;
            @(negedge clk);
            start = 0;
            // Prove the command latches its input once at START.
            dac_code = ~code;
            wait(done);
            #100;
            if (ack_error !== (nack >= 0)) $fatal(1, "ACK status mismatch");
            if (byte_count != ((nack < 0) ? 3 : nack + 1)) $fatal(1, "Byte count mismatch");
            if (bytes[0] !== 8'hC0) $fatal(1, "Address mismatch");
            if (nack < 0) begin
                if (bytes[1] !== {4'b0000, code[11:8]} || bytes[2] !== code[7:0])
                    $fatal(1, "Fast Write packing mismatch: %h %h for %h", bytes[1], bytes[2], code);
            end
            if (stops != old_stops + 1 || scl !== 1 || sda !== 1 || busy !== 0)
                $fatal(1, "STOP/idle mismatch");
        end
    endtask

    initial begin
        repeat(10) @(negedge clk);
        rst = 0;
        check_period = 1;
        write_check(12'h000, -1);
        write_check(12'hA55, -1);
        write_check(12'hFFF, -1);
        write_check(12'h800, 0);
        write_check(12'h123, 1);
        write_check(12'h456, 2);
        write_check(12'h040, -1);
        $display("PASS: MCP4725 I2C write: Fast Write packing, 100kHz, ACK/NACK, STOP, input latching, retry");
        $finish;
    end
    initial begin
        #10000000;
        $fatal(1, "I2C test timeout");
    end
endmodule
