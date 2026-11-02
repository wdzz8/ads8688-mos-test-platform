# Build a fixed-gate, continuous ADC image from the verified mos_scan RTL.
# Usage: vivado -mode batch -source scripts/build_mos_fixed_vgs.tcl -tclargs DAC_CODE
# DAC_CODE is the MCP4725 code (0..4095); no hardware is programmed here.
set fixed_root [file normalize [file join [file dirname [info script]] ..]]
if {[llength $argv] != 1} { error "Usage: build_mos_fixed_vgs.tcl DAC_CODE" }
set fixed_code [expr {int([lindex $argv 0])}]
if {$fixed_code < 0 || $fixed_code > 4095} { error "DAC_CODE must be 0..4095" }
set fixed_out [file join $fixed_root output mos_fixed_vgs [format "code_%04d" $fixed_code]]
file mkdir $fixed_out
cd $fixed_out
set fixed_src [file join $fixed_root rtl]
foreach source {ads8688_top.v mcp4725_i2c.v mos_scan.v} {
    read_verilog [file join $fixed_src $source]
}
read_xdc [file join $fixed_root constr ads8688.xdc]
read_xdc [file join $fixed_root constr led.xdc]

# POINTS=1 and CODE_STEP=0 turn the verified scan controller into a fixed-VGS
# monitor while retaining its ADC initialization, averaging, flags and ILA.
synth_design -top mos_scan -part xc7z020clg400-2 \
    -generic POINTS=1 -generic CODE_START=$fixed_code -generic CODE_STEP=0 \
    -generic SETTLE_MS=100 -generic SWEEPS=8 -generic RESTART_MS=2
set_property -dict {PACKAGE_PIN H18 IOSTANDARD LVCMOS33} [get_ports mcp_scl]
set_property -dict {PACKAGE_PIN J18 IOSTANDARD LVCMOS33} [get_ports mcp_sda]

create_debug_core u_ila_scan ila
set_property C_DATA_DEPTH 1024 [get_debug_cores u_ila_scan]
set_property C_EN_STRG_QUAL true [get_debug_cores u_ila_scan]
set_property C_INPUT_PIPE_STAGES 0 [get_debug_cores u_ila_scan]
set_property ALL_PROBE_SAME_MU true [get_debug_cores u_ila_scan]
set_property ALL_PROBE_SAME_MU_CNT 2 [get_debug_cores u_ila_scan]
connect_debug_port u_ila_scan/clk [get_nets sys_clk_IBUF_BUFG]
set probe_index 0
foreach {signal width} {
    point 1 vg_code 12
    row_ch0 16 row_ch1 16 row_ch2 16 row_ch3 16
    row_ch4 16 row_ch5 16 row_ch6 16 row_ch7 16
    row_valid 1 scan_count 8 adc_index 3 adc_valid 1
    init_done 1 init_error 1 dac_ready 1 dac_error 1
} {
    if {$probe_index > 0} {create_debug_port u_ila_scan probe}
    set port u_ila_scan/probe$probe_index
    set_property port_width $width [get_debug_ports $port]
    set_property PROBE_TYPE DATA_AND_TRIGGER [get_debug_ports $port]
    set signal_nets {}
    if {$width == 1} {
        set signal_nets [get_nets $signal]
    } else {
        for {set bit 0} {$bit < $width} {incr bit} {
            lappend signal_nets [get_nets [format {%s[%d]} $signal $bit]]
        }
    }
    if {[llength $signal_nets] != $width} {error "Missing debug net: $signal"}
    connect_debug_port $port $signal_nets
    incr probe_index
}
set_property C_CLK_INPUT_FREQ_HZ 50000000 [get_debug_cores dbg_hub]
connect_debug_port dbg_hub/clk [get_nets sys_clk_IBUF_BUFG]
opt_design
place_design
route_design
report_timing_summary -file timing_summary.rpt
report_drc -file drc.rpt
write_checkpoint -force mos_fixed_vgs_routed.dcp
write_debug_probes -force mos_fixed_vgs.ltx
write_bitstream -force mos_fixed_vgs.bit
puts "Built fixed-VGS image: DAC_CODE=$fixed_code output=$fixed_out"
