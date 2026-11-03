# Synthesis post-hook: recreate the loopback ILA from the tested build.
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
# The project flow writes its synthesis checkpoint before the post-hook.
# Persist the inserted cores so open_run and implementation can load them.
write_checkpoint -force dac_adc_loopback.dcp
