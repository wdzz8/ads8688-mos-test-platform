# Run with Vivado 2022.2; all source references stay inside this folder.
set handoff_root [file normalize [file dirname [info script]]]
create_project dac_adc_loopback [file join $handoff_root project] -part xc7z020clg400-2
set_property target_language Verilog [current_project]
foreach name {ads8688_top.v mcp4725_i2c.v mcp4725_wave_test.v dac_adc_loopback.v} {
    add_files -norecurse [file join $handoff_root rtl $name]
}
add_files -fileset constrs_1 -norecurse [file join $handoff_root constr dac_adc_loopback.xdc]
set_property top dac_adc_loopback [get_filesets sources_1]
add_files -fileset utils_1 -norecurse [file join $handoff_root scripts debug_setup.tcl]
set_property STEPS.SYNTH_DESIGN.TCL.POST [file join $handoff_root scripts debug_setup.tcl] [get_runs synth_1]
update_compile_order -fileset sources_1
puts "HANDOFF_PROJECT_READY: [get_property DIRECTORY [current_project]]"
close_project
