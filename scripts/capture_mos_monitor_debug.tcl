# Diagnostic capture for mos_adc_monitor.
# This deliberately removes the point_valid storage qualifier so the ILA can
# capture status bits even when init_done or dac_ready is still low.
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
# point_valid is low for almost the entire clock stream. Triggering and
# qualifying on zero gives the diagnostic capture a concrete true condition
# while still retaining all status and ADC probes.
set_property TRIGGER_COMPARE_VALUE eq1'b0 $point_probe
set_property CAPTURE_COMPARE_VALUE eq1'b0 $point_probe
run_hw_ila $mos_ila
wait_on_hw_ila $mos_ila -timeout 2.0
set mos_data [upload_hw_ila_data $mos_ila]
display_hw_ila_data $mos_data
puts "Diagnostic capture complete. Inspect init_done/init_error/dac_ready/dac_error and adc_ch0..adc_ch7."
