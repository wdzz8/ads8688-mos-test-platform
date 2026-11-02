set project_root [file normalize [file join [file dirname [info script]] ..]]
set source_root $project_root
set output_dir [file join $project_root output ads8688_debug]
set build_mode [lindex $argv 0]
switch -- $build_mode {
    "" { set ch0_only 0; set output_name ads8688_led_confirm }
    "ch0" { set ch0_only 1; set output_name ads8688_ch0_test }
    default { error "Unknown build mode: $build_mode (expected ch0 or no argument)" }
}
file mkdir $output_dir
cd $output_dir

read_verilog [file join $source_root rtl ads8688_top.v]
read_verilog [file join $source_root rtl ads8688_led_test.v]
read_xdc [file join $source_root constr ads8688.xdc]
read_xdc [file join $source_root constr led.xdc]
synth_design -top ads8688_led_test -part xc7z020clg400-2 -generic CH0_ONLY=$ch0_only
read_xdc [file join $project_root ads8688_1.srcs constrs_1 new debug.xdc]
opt_design
place_design
route_design
report_timing_summary -file timing_summary.rpt
report_drc -file drc.rpt
write_checkpoint -force ${output_name}_routed.dcp
write_debug_probes -force ${output_name}.ltx
write_bitstream -force ${output_name}.bit
