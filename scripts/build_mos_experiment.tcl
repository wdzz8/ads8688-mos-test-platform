set root [file normalize [file join [file dirname [info script]] ..]]
set out [file join $root output mos_experiment]
file mkdir $out
file mkdir [file join $out ip]
cd $out
create_project -in_memory -part xc7z020clg400-2
set xci [file join $out ip experiment_vio experiment_vio.xci]
if {[file isfile $xci]} {read_ip $xci} else {
    create_ip -name vio -vendor xilinx.com -library ip -version 3.0 -module_name experiment_vio -dir [file join $out ip]
}
set_property -dict [list CONFIG.C_NUM_PROBE_IN 1 CONFIG.C_NUM_PROBE_OUT 6 \
    CONFIG.C_PROBE_IN0_WIDTH 16 CONFIG.C_PROBE_OUT0_WIDTH 12 CONFIG.C_PROBE_OUT1_WIDTH 12 \
    CONFIG.C_PROBE_OUT2_WIDTH 32 CONFIG.C_PROBE_OUT3_WIDTH 1 CONFIG.C_PROBE_OUT4_WIDTH 1 CONFIG.C_PROBE_OUT5_WIDTH 1 \
    CONFIG.C_PROBE_OUT0_INIT_VAL 0x100 CONFIG.C_PROBE_OUT1_INIT_VAL 0x100 \
    CONFIG.C_PROBE_OUT2_INIT_VAL 0x17D7840 CONFIG.C_PROBE_OUT3_INIT_VAL 0 CONFIG.C_PROBE_OUT4_INIT_VAL 0 CONFIG.C_PROBE_OUT5_INIT_VAL 0] [get_ips experiment_vio]
generate_target all [get_ips experiment_vio]
synth_ip [get_ips experiment_vio]
foreach file {ads8688_top.v mcp4725_i2c.v mos_experiment.v} {read_verilog [file join $root rtl $file]}
read_xdc [file join $root constr ads8688.xdc]
read_xdc [file join $root constr led.xdc]
synth_design -top mos_experiment -part xc7z020clg400-2
set_property -dict {PACKAGE_PIN H18 IOSTANDARD LVCMOS33} [get_ports mcp_scl]
set_property -dict {PACKAGE_PIN J18 IOSTANDARD LVCMOS33} [get_ports mcp_sda]
create_debug_core u_ila_experiment ila
set core [get_debug_cores u_ila_experiment]
set_property C_DATA_DEPTH 8192 $core
set_property C_EN_STRG_QUAL true $core
set_property C_INPUT_PIPE_STAGES 0 $core
set_property ALL_PROBE_SAME_MU true $core
set_property ALL_PROBE_SAME_MU_CNT 2 $core
connect_debug_port u_ila_experiment/clk [get_nets sys_clk_IBUF_BUFG]
set i 0
foreach {signal width} {
    row_ch0 16 row_ch1 16 row_ch2 16 row_ch3 16 row_ch4 16 row_ch5 16 row_ch6 16 row_ch7 16
    row_valid 1 row_bad 1 row_transition 1 row_sequence 32 timestamp_cycles 32 row_start_cycles 32
    vg_code 12 row_start_code 12 transition_count 32 configuration_id 16
    init_done 1 init_error 1 dac_ready 1 dac_error 1 dac_busy 1 ffff_run 16 fault_latched 1
    safe_gate_requested 1 safe_gate_zeroed 1 fault_event_reason 4 fault_event_sequence 32
    fault_event_timestamp 32 fault_event_config 16 feature_code 12 feature_samples 16 feature_event_samples 16
    feature_sum_ch7 32 feature_sumsq_ch7 64 feature_mean_ch7 16 feature_var_ch7 32 feature_valid 1
} {
    if {$i>0} {create_debug_port u_ila_experiment probe}
    set port u_ila_experiment/probe$i
    set_property port_width $width [get_debug_ports $port]
    set nets {}
    if {$width==1} {set nets [get_nets $signal]} else {
        for {set b 0} {$b<$width} {incr b} {lappend nets [get_nets [format {%s[%d]} $signal $b]]}
    }
    if {[llength $nets]!=$width} {error "Missing probe $signal"}
    connect_debug_port $port $nets
    incr i
}
set_property C_CLK_INPUT_FREQ_HZ 50000000 [get_debug_cores dbg_hub]
connect_debug_port dbg_hub/clk [get_nets sys_clk_IBUF_BUFG]
opt_design
place_design
route_design
report_timing_summary -file timing_summary.rpt
report_bus_skew -file bus_skew.rpt
report_drc -file drc.rpt
write_checkpoint -force mos_experiment_routed.dcp
write_debug_probes -force mos_experiment.ltx
write_bitstream -force mos_experiment.bit
puts "BUILT_MOS_EXPERIMENT=$out"
