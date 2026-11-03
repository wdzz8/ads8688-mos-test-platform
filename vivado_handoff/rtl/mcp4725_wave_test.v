`timescale 1ns / 1ps
module mcp4725_wave_test #(
    parameter integer CLK_FREQ = 50_000_000,
    parameter integer UPDATE_HZ = 100,
    parameter [6:0] I2C_ADDR = 7'h60
)(
    input wire sys_clk,
    inout wire mcp_sda,
    output wire mcp_scl,
    output wire [3:0] led,
    output reg [11:0] dac_applied,
    output reg dac_ready,
    output reg dac_error,
    output wire dac_busy
);
    localparam integer UPDATE_DIV = CLK_FREQ / UPDATE_HZ;
    localparam integer UPDATE_W = (UPDATE_DIV <= 2) ? 1 : $clog2(UPDATE_DIV);
    reg [UPDATE_W-1:0] update_count = 0;
    reg [11:0] dac_code = 0;
    reg direction_up = 1'b1;
    reg start = 0;
    reg waiting = 0;
    wire done, ack_error;
    reg heartbeat = 0;
    reg [23:0] heartbeat_count = 0;
    reg [15:0] por_count = 0;
    wire rst = ~por_count[15];

    always @(posedge sys_clk)
        if (rst) por_count <= por_count + 1'b1;

    mcp4725_i2c #(.CLK_FREQ(CLK_FREQ), .I2C_ADDR(I2C_ADDR)) u_i2c (
        .clk(sys_clk), .rst(rst), .start(start), .dac_code(dac_code),
        .busy(dac_busy), .done(done), .ack_error(ack_error),
        .scl(mcp_scl), .sda(mcp_sda)
    );

    always @(posedge sys_clk) begin
        start <= 0;
        if (rst) begin
            update_count <= 0;
            dac_code <= 0;
            direction_up <= 1;
            waiting <= 0;
            dac_applied <= 0;
            dac_ready <= 0;
            dac_error <= 0;
            heartbeat_count <= 0;
            heartbeat <= 0;
        end else begin
            if (heartbeat_count == CLK_FREQ / 4 - 1) begin
                heartbeat_count <= 0;
                heartbeat <= ~heartbeat;
            end else heartbeat_count <= heartbeat_count + 1'b1;

            // Start-to-start timing includes the I2C transaction duration.
            if (update_count != 0) update_count <= update_count - 1'b1;
            if (done) begin
                waiting <= 0;
                if (ack_error) begin
                    dac_error <= 1;
                    dac_ready <= 0;
                end else begin
                    dac_applied <= dac_code;
                    dac_ready <= 1;
                    if (direction_up) begin
                        if (dac_code >= 4032) begin
                            dac_code <= 4095;
                            direction_up <= 0;
                        end else dac_code <= dac_code + 12'd64;
                    end else begin
                        if (dac_code <= 63) begin
                            dac_code <= 0;
                            direction_up <= 1;
                        end else dac_code <= dac_code - 12'd64;
                    end
                end
            end else if (!waiting && !dac_busy && update_count == 0) begin
                start <= 1;
                waiting <= 1;
                update_count <= UPDATE_DIV - 1;
            end
        end
    end

    assign led = {1'b0, ~dac_error, ~heartbeat, heartbeat};
endmodule
