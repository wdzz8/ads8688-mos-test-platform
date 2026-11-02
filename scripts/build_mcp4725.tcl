set project_root [file normalize [file join [file dirname [info script]] ..]]
set source_root $project_root
set output_dir [file join $project_root output mcp4725_debug]
file mkdir $output_dir
cd $output_dir

read_verilog [file join $source_root rtl mcp4725_i2c.v]
read_verilog [file join $source_root rtl mcp4725_wave_test.v]
read_xdc [file join $source_root constr mcp4725.xdc]
synth_design -top mcp4725_wave_test -part xc7z020clg400-2
opt_design
place_design
route_design
report_timing_summary -file timing_summary.rpt
report_drc -file drc.rpt
write_checkpoint -force mcp4725_wave_test_routed.dcp
write_bitstream -force mcp4725_wave_test.bit
