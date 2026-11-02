# Independent drain-OFF diagnostic image; production fixed-gate images unchanged.
set root [file normalize [file join [file dirname [info script]] ..]]
set out [file join $root output mos_adc_diagnostic audit_code_2560]
file mkdir $out
file mkdir [file join $out ip]
cd $out
create_project -in_memory -part xc7z020clg400-2
set vio_file [file join $out ip adc_reset_vio adc_reset_vio.xci]
if {[file isfile $vio_file]} {
    read_ip $vio_file
} else {
    create_ip -name vio -vendor xilinx.com -library ip -version 3.0 -module_name adc_reset_vio -dir [file join $out ip]
}
set_property -dict [list CONFIG.C_NUM_PROBE_IN 5 CONFIG.C_NUM_PROBE_OUT 2 \
    CONFIG.C_PROBE_IN0_WIDTH 1 CONFIG.C_PROBE_IN1_WIDTH 16 CONFIG.C_PROBE_IN2_WIDTH 16 \
    CONFIG.C_PROBE_IN3_WIDTH 1 CONFIG.C_PROBE_IN4_WIDTH 96 \
    CONFIG.C_PROBE_OUT0_WIDTH 1 CONFIG.C_PROBE_OUT0_INIT_VAL 0x0 \
    CONFIG.C_PROBE_OUT1_WIDTH 1 CONFIG.C_PROBE_OUT1_INIT_VAL 0x0] [get_ips adc_reset_vio]
generate_target all [get_ips adc_reset_vio]
synth_ip [get_ips adc_reset_vio]
foreach source {ads8688_top.v mcp4725_i2c.v mos_adc_diagnostic.v} {
    read_verilog [file join $root rtl $source]
}
read_xdc [file join $root constr ads8688.xdc]
read_xdc [file join $root constr led.xdc]
synth_design -top mos_adc_diagnostic -part xc7z020clg400-2
set_property -dict {PACKAGE_PIN H18 IOSTANDARD LVCMOS33} [get_ports mcp_scl]
set_property -dict {PACKAGE_PIN J18 IOSTANDARD LVCMOS33} [get_ports mcp_sda]
create_debug_core u_ila_adc_diagnostic ila
set core [get_debug_cores u_ila_adc_diagnostic]
set_property C_DATA_DEPTH 4096 $core
set_property C_EN_STRG_QUAL true $core
set_property C_INPUT_PIPE_STAGES 0 $core
set_property ALL_PROBE_SAME_MU true $core
set_property ALL_PROBE_SAME_MU_CNT 2 $core
connect_debug_port u_ila_adc_diagnostic/clk [get_nets sys_clk_IBUF_BUFG]
set index 0
foreach {signal width} {
    adc_data 16 adc_index 3 adc_valid 1 init_done 1 init_error 1 reg_readback 8
    adc_cs_n 1 adc_sclk 1 adc_sdi 1 adc_sdo 1 adc_rst_n 1
    adc_reset_request 1 dac_ready 1 dac_error 1 timestamp_cycles 32
    sample_count 32 ffff_run 16 fault_latched 1 adc_reset_count 16 adc_audit_done 1 adc_audit_values 96
} {
    if {$index > 0} {create_debug_port u_ila_adc_diagnostic probe}
    set port u_ila_adc_diagnostic/probe$index
    set_property port_width $width [get_debug_ports $port]
    set nets {}
    if {$width == 1} {
        if {$signal eq "adc_sdo"} {
            set nets [get_nets ${signal}_IBUF]
        } elseif {$signal in {adc_cs_n adc_sclk adc_sdi adc_rst_n}} {
            set nets [get_nets ${signal}_OBUF]
        } else {
            set nets [get_nets $signal]
        }
    } else {
        for {set bit 0} {$bit < $width} {incr bit} {
            lappend nets [get_nets [format {%s[%d]} $signal $bit]]
        }
    }
    if {[llength $nets] != $width} {error "Missing debug net: $signal"}
    connect_debug_port $port $nets
    incr index
}
set_property C_CLK_INPUT_FREQ_HZ 50000000 [get_debug_cores dbg_hub]
connect_debug_port dbg_hub/clk [get_nets sys_clk_IBUF_BUFG]
opt_design
place_design
route_design
report_timing_summary -file timing_summary.rpt
report_bus_skew -file bus_skew.rpt
report_drc -file drc.rpt
write_checkpoint -force mos_adc_diagnostic_routed.dcp
write_debug_probes -force mos_adc_diagnostic.ltx
write_bitstream -force mos_adc_diagnostic.bit
puts "BUILT_ADC_DIAGNOSTIC=$out"
