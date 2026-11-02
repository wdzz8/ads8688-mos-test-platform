# Source in the Hardware Manager Tcl Console after programming the matched
# dac_adc_loopback.bit/.ltx pair. This script only captures data.
set loops [get_hw_ilas -of_objects [current_hw_device] -filter {CELL_NAME == "u_ila_loop"}]
if {[llength $loops] != 1} {error "Program dac_adc_loopback.bit/.ltx first"}
set loop_ila [lindex $loops 0]
set capture_probe [get_hw_probes -of_objects $loop_ila -filter {NAME == "capture_tick"}]
if {[llength $capture_probe] != 1} {error "Missing capture_tick probe"}
foreach probe [get_hw_probes -of_objects $loop_ila] {
    set width [get_property WIDTH $probe]
    set dont_care [format {eq%d'b%s} $width [string repeat X $width]]
    set_property TRIGGER_COMPARE_VALUE $dont_care $probe
    set_property CAPTURE_COMPARE_VALUE $dont_care $probe
}
set_property CONTROL.TRIGGER_CONDITION AND $loop_ila
set_property CONTROL.CAPTURE_CONDITION AND $loop_ila
set_property CONTROL.CAPTURE_MODE BASIC $loop_ila
set_property CONTROL.TRIGGER_POSITION 0 $loop_ila
set_property CONTROL.DATA_DEPTH 4096 $loop_ila
set_property TRIGGER_COMPARE_VALUE eq1'b1 $capture_probe
set_property CAPTURE_COMPARE_VALUE eq1'b1 $capture_probe
run_hw_ila $loop_ila
# The loopback capture is qualified at one sample per millisecond. 4096
# samples need just over 4 seconds, so allow the hardware run to finish.
wait_on_hw_ila $loop_ila -timeout 6.0
set loop_data [upload_hw_ila_data $loop_ila]
display_hw_ila_data $loop_data
puts "Captured 4096 points, 1 ms/point. Set ch_data radix=Unsigned, waveform style=Analog."
