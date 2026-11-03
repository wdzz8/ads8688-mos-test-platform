# Run in Vivado Hardware Manager after programming the matching
# mos_adc_monitor.bit and mos_adc_monitor.ltx files.
set loops [get_hw_ilas -of_objects [current_hw_device] -filter {CELL_NAME == "u_ila_mos"}]
if {[llength $loops] != 1} {error "Program mos_adc_monitor.bit/.ltx first"}
set mos_ila [lindex $loops 0]
set point_probe [get_hw_probes -of_objects $mos_ila -filter {NAME == "point_valid"}]
if {[llength $point_probe] != 1} {error "Missing point_valid probe"}
foreach probe [get_hw_probes -of_objects $mos_ila] {
    set width [get_property WIDTH $probe]
    set dont_care [format {eq%d'b%s} $width [string repeat X $width]]
    set_property TRIGGER_COMPARE_VALUE $dont_care $probe
    set_property CAPTURE_COMPARE_VALUE $dont_care $probe
}
set_property CONTROL.TRIGGER_CONDITION AND $mos_ila
set_property CONTROL.CAPTURE_CONDITION AND $mos_ila
set_property CONTROL.CAPTURE_MODE BASIC $mos_ila
set_property CONTROL.TRIGGER_POSITION 0 $mos_ila
set_property CONTROL.DATA_DEPTH 4096 $mos_ila
set_property TRIGGER_COMPARE_VALUE eq1'b1 $point_probe
set_property CAPTURE_COMPARE_VALUE eq1'b1 $point_probe
run_hw_ila $mos_ila
# The monitor qualifies one ILA sample per millisecond. 4096 qualified
# samples therefore need just over 4 seconds, so do not time out at 250 ms.
wait_on_hw_ila $mos_ila -timeout 6.0
set mos_data [upload_hw_ila_data $mos_ila]
display_hw_ila_data $mos_data
puts "Captured 4096 multi-channel snapshots, 1 ms/point. Set adc_ch0..adc_ch7 to Unsigned/Analog."
