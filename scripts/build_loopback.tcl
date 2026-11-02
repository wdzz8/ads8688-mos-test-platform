set project_root [file normalize [file join [file dirname [info script]] ..]]
set source_root $project_root
set output_dir [file join $project_root output dac_adc_loopback]
file mkdir $output_dir
cd $output_dir
foreach source {ads8688_top.v mcp4725_i2c.v mcp4725_wave_test.v dac_adc_loopback.v} {
    read_verilog [file join $source_root rtl $source]
}
read_xdc [file join $source_root constr ads8688.xdc]
read_xdc [file join $source_root constr led.xdc]
synth_design -top dac_adc_loopback -part xc7z020clg400-2
set_property -dict {PACKAGE_PIN H18 IOSTANDARD LVCMOS33} [get_ports mcp_scl]
set_property -dict {PACKAGE_PIN J18 IOSTANDARD LVCMOS33} [get_ports mcp_sda]

create_debug_core u_ila_loop ila
set_property C_DATA_DEPTH 4096 [get_debug_cores u_ila_loop]
set_property C_EN_STRG_QUAL true [get_debug_cores u_ila_loop]
set_property C_INPUT_PIPE_STAGES 0 [get_debug_cores u_ila_loop]
set_property ALL_PROBE_SAME_MU true [get_debug_cores u_ila_loop]
set_property ALL_PROBE_SAME_MU_CNT 2 [get_debug_cores u_ila_loop]
connect_debug_port u_ila_loop/clk [get_nets sys_clk_IBUF_BUFG]
set probe_index 0
foreach {signal width} {
    ch_data 16 dac_applied 12 capture_tick 1 sample_ms 32
    init_done 1 init_error 1 dac_ready 1 dac_error 1 dac_busy 1 ch_valid 1
} {
    if {$probe_index > 0} {create_debug_port u_ila_loop probe}
    set port u_ila_loop/probe$probe_index
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
write_checkpoint -force dac_adc_loopback_routed.dcp
write_debug_probes -force dac_adc_loopback.ltx
write_bitstream -force dac_adc_loopback.bit
