`timescale 1ns / 1ps
// MCP4725 single-write I2C master.
// Fast Write: address, {00, PD=00, D11..D8}, D7..D0. No EEPROM write.
// SDA and SCL are open-drain signals; external pull-ups are required.
module mcp4725_i2c #(
    parameter integer CLK_FREQ = 50_000_000,
    parameter integer I2C_FREQ = 100_000,
    parameter [6:0]   I2C_ADDR = 7'h60
)(
    input  wire       clk,
    input  wire       rst,
    input  wire       start,
    input  wire [11:0] dac_code,
    output reg        busy,
    output reg        done,
    output reg        ack_error,
    output wire       scl,
    inout  wire       sda
);

    localparam integer TICK_DIV = CLK_FREQ / (I2C_FREQ * 2);
    localparam integer TICK_W = (TICK_DIV <= 2) ? 1 : $clog2(TICK_DIV);

    localparam [3:0] ST_IDLE      = 4'd0,
                     ST_START_LOW = 4'd1,
                     ST_BIT_LOW   = 4'd2,
                     ST_BIT_HIGH  = 4'd3,
                     ST_ACK_LOW   = 4'd4,
                     ST_ACK_HIGH  = 4'd5,
                     ST_STOP_LOW  = 4'd6,
                     ST_STOP_HIGH = 4'd7,
                     ST_STOP_REL  = 4'd8;

    reg [3:0] state;
    reg [TICK_W-1:0] tick_count;
    reg scl_low;
    reg sda_low;
    reg [1:0] byte_index;
    reg [2:0] bit_index;
    reg [23:0] tx_bytes;

    assign scl = scl_low ? 1'b0 : 1'bz;
    assign sda = sda_low ? 1'b0 : 1'bz;

    wire tick = (tick_count == TICK_DIV - 1);
    wire sda_in = sda;

    always @(posedge clk) begin
        if (rst) begin
            state      <= ST_IDLE;
            tick_count <= {TICK_W{1'b0}};
            scl_low    <= 1'b0;
            sda_low    <= 1'b0;
            byte_index <= 2'd0;
            bit_index  <= 3'd7;
            tx_bytes   <= 24'd0;
            busy       <= 1'b0;
            done       <= 1'b0;
            ack_error  <= 1'b0;
        end else begin
            done <= 1'b0;
            if (busy && !tick) begin
                tick_count <= tick_count + 1'b1;
            end else if (busy) begin
                tick_count <= {TICK_W{1'b0}};
            end

            case (state)
            ST_IDLE: begin
                scl_low <= 1'b0;
                sda_low <= 1'b0;
                if (start && !busy) begin
                    tx_bytes <= {I2C_ADDR, 1'b0, 4'b0000, dac_code};
                    tick_count <= {TICK_W{1'b0}};
                    byte_index <= 2'd0;
                    bit_index <= 3'd7;
                    ack_error <= 1'b0;
                    busy <= 1'b1;
                    // START: SDA falls while SCL is released high.
                    sda_low <= 1'b1;
                    state <= ST_START_LOW;
                end
            end

            ST_START_LOW: begin
                if (tick) begin
                    scl_low <= 1'b1;
                    state <= ST_BIT_LOW;
                end
            end

            ST_BIT_LOW: begin
                // Data is stable while SCL is low; release SDA for a one.
                sda_low <= ~tx_bytes[23 - byte_index*8 - (7 - bit_index)];
                if (tick) begin
                    scl_low <= 1'b0;
                    state <= ST_BIT_HIGH;
                end
            end

            ST_BIT_HIGH: begin
                if (tick) begin
                    scl_low <= 1'b1;
                    if (bit_index == 3'd0) begin
                        sda_low <= 1'b0;
                        state <= ST_ACK_LOW;
                    end else begin
                        bit_index <= bit_index - 1'b1;
                        state <= ST_BIT_LOW;
                    end
                end
            end

            ST_ACK_LOW: begin
                // SDA is released for the slave ACK. Sample while SCL high.
                if (tick) begin
                    scl_low <= 1'b0;
                    state <= ST_ACK_HIGH;
                end
            end

            ST_ACK_HIGH: begin
                if (tick) begin
                    if (sda_in)
                        ack_error <= 1'b1;
                    scl_low <= 1'b1;
                    if (sda_in || byte_index == 2'd2) begin
                        sda_low <= 1'b1;
                        state <= ST_STOP_LOW;
                    end else begin
                        byte_index <= byte_index + 1'b1;
                        bit_index <= 3'd7;
                        state <= ST_BIT_LOW;
                    end
                end
            end

            ST_STOP_LOW: begin
                if (tick) begin
                    // STOP: raise SCL first while SDA remains low.
                    scl_low <= 1'b0;
                    state <= ST_STOP_HIGH;
                end
            end

            ST_STOP_HIGH: begin
                if (tick) begin
                    sda_low <= 1'b0;
                    state <= ST_STOP_REL;
                end
            end

            ST_STOP_REL: begin
                if (tick) begin
                    busy <= 1'b0;
                    done <= 1'b1;
                    state <= ST_IDLE;
                end
            end

            default: begin
                state <= ST_IDLE;
                busy <= 1'b0;
                scl_low <= 1'b0;
                sda_low <= 1'b0;
            end
            endcase
        end
    end
endmodule
