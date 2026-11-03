set handoff_root [file normalize [file join [file dirname [info script]] ..]]
open_project [file join $handoff_root project dac_adc_loopback.xpr]
if {![llength [get_files -of_objects [get_filesets utils_1] -filter {NAME =~ *debug_setup.tcl}]]} {
    add_files -fileset utils_1 -norecurse [file join $handoff_root scripts debug_setup.tcl]
}
if {[get_property PROGRESS [get_runs synth_1]] eq "100%"} {reset_run synth_1}
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {
    error "Synthesis failed: [get_property STATUS [get_runs synth_1]]"
}
open_run synth_1
set checked_ports 0
foreach {name pin} {
    sys_clk U18 adc_cs_n F17 adc_sclk F16 adc_sdi F20 adc_sdo F19
    adc_rst_n G20 mcp_scl H18 mcp_sda J18
    led[0] M14 led[1] M15 led[2] K16 led[3] J16
} {
    set p [get_ports [list $name]]
    if {[llength $p] != 1} {error "Missing port $name"}
    if {[get_property PACKAGE_PIN $p] ne $pin} {error "Pin mismatch for $name"}
    if {[get_property IOSTANDARD $p] ne "LVCMOS33"} {error "IO standard mismatch for $name"}
    incr checked_ports
}
if {[llength [get_ports]] != $checked_ports} {error "Unexpected external port"}
if {[llength [get_debug_cores u_ila_loop]] != 1} {error "Missing ILA"}
if {[get_property C_DATA_DEPTH [get_debug_cores u_ila_loop]] != 4096} {error "ILA depth mismatch"}
if {![get_property C_EN_STRG_QUAL [get_debug_cores u_ila_loop]]} {error "Missing storage qualification"}
if {[llength [get_debug_ports u_ila_loop/probe*]] != 10} {error "ILA probe count mismatch"}
set report [open [file join $handoff_root project_check.txt] w]
puts $report "PASS: Vivado 2022.2 project synthesis completed."
puts $report "PASS: All 12 scalar external ports match the documented package pins and LVCMOS33."
puts $report "PASS: u_ila_loop is present, with 4096 samples, storage qualification, and 10 probes."
puts $report "DPS communication and external fault/trigger ports are not implemented."
puts $report "This checks synthesis and constraints; implementation/bitstream were not rerun for this project."
puts $report "program/*.bit and *.ltx are the previously built matched loopback artifacts."
close $report
puts "HANDOFF_CHECK_PASS"
close_project
