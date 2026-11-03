set project_root [file normalize [file join [file dirname [info script]] ..]]
set source_root [file normalize [file join $project_root .. ads8688_spi]]
set output_dir [file join $project_root output mos_adc_monitor]
file mkdir $output_dir
cd $output_dir

foreach source {ads8688_top.v mcp4725_i2c.v mcp4725_wave_test.v mos_adc_monitor.v} {
    read_verilog [file join $source_root rtl $source]
}
read_xdc [file join $source_root constr ads8688.xdc]
read_xdc [file join $source_root constr led.xdc]
synth_design -top mos_adc_monitor -part xc7z020clg400-2

# MCP4725 I2C pins are assigned after synthesis, matching the known-good
# non-project build flow where top-level ports are available.
set_property -dict {PACKAGE_PIN H18 IOSTANDARD LVCMOS33} [get_ports mcp_scl]
set_property -dict {PACKAGE_PIN J18 IOSTANDARD LVCMOS33} [get_ports mcp_sda]

create_debug_core u_ila_mos ila
set_property C_DATA_DEPTH 4096 [get_debug_cores u_ila_mos]
set_property C_EN_STRG_QUAL true [get_debug_cores u_ila_mos]
set_property C_INPUT_PIPE_STAGES 0 [get_debug_cores u_ila_mos]
set_property ALL_PROBE_SAME_MU true [get_debug_cores u_ila_mos]
set_property ALL_PROBE_SAME_MU_CNT 2 [get_debug_cores u_ila_mos]
connect_debug_port u_ila_mos/clk [get_nets sys_clk_IBUF_BUFG]

set probe_index 0
foreach {signal width} {
    adc_ch0 16 adc_ch1 16 adc_ch2 16 adc_ch3 16
    adc_ch4 16 adc_ch5 16 adc_ch6 16 adc_ch7 16
    adc_last_index 3 adc_sample_pulse 1
    dac_applied 12 point_valid 1 sample_ms 32
    init_done 1 init_error 1 dac_ready 1 dac_error 1 dac_busy 1
} {
    if {$probe_index > 0} {create_debug_port u_ila_mos probe}
    set port u_ila_mos/probe$probe_index
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
write_checkpoint -force mos_adc_monitor_routed.dcp
write_debug_probes -force mos_adc_monitor.ltx
write_bitstream -force mos_adc_monitor.bit
