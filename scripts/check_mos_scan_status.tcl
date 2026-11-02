# Status only: program mos_scan.bit / mos_scan.ltx, then run this.
#   source scripts/check_mos_scan_status.tcl
# No trigger, no storage qualifier: captures 1024 consecutive samples and prints
# the last row, so init_done / init_error / dac_ready / dac_error can be read
# without opening the waveform window.
# ASCII only: the Vivado Tcl console uses the system code page.
set project_root [file normalize [file join [file dirname [info script]] ..]]
set out_dir [file join $project_root output mos_scan]
file mkdir $out_dir
set stamp [clock format [clock seconds] -format %Y%m%d_%H%M%S]
set csv_file [file join $out_dir "status_$stamp.csv"]

set ilas [get_hw_ilas -of_objects [current_hw_device] -filter {CELL_NAME == "u_ila_scan"}]
if {[llength $ilas] != 1} {
    puts "ILA cores on this device: [get_hw_ilas -of_objects [current_hw_device]]"
    error "u_ila_scan not found. Program mos_scan.bit and mos_scan.ltx together."
}
set scan_ila [lindex $ilas 0]

foreach probe [get_hw_probes -of_objects $scan_ila] {
    set width [get_property WIDTH $probe]
    set dont_care [format {eq%d'b%s} $width [string repeat X $width]]
    set_property TRIGGER_COMPARE_VALUE $dont_care $probe
    set_property CAPTURE_COMPARE_VALUE $dont_care $probe
}
set_property CONTROL.TRIGGER_CONDITION AND $scan_ila
set_property CONTROL.CAPTURE_CONDITION AND $scan_ila
set_property CONTROL.CAPTURE_MODE ALWAYS $scan_ila
set_property CONTROL.TRIGGER_POSITION 0 $scan_ila
set_property CONTROL.DATA_DEPTH 1024 $scan_ila

run_hw_ila -trigger_now $scan_ila
wait_on_hw_ila $scan_ila -timeout 2.0
set scan_data [upload_hw_ila_data $scan_ila]
# Export directly: resetting the GUI waveform view crashes this Vivado install.
write_hw_ila_data -force -csv_file $csv_file $scan_data

set fh [open $csv_file r]
set header ""
set last ""
while {[gets $fh line] >= 0} {
    if {$header eq ""} { set header $line } else { set last $line }
}
close $fh
puts "Header: $header"
puts "Last  : $last"
puts "Expect init_done=1, init_error=0, dac_ready=1, dac_error=0."
puts "These are startup flags; inspect ADC row values as well."
puts "For INA240 OUT near 2.5 V on module AIN8, row_ch7 should be near 7D00 (hex)."
puts "All eight ADC rows at FFFF are invalid for this zero-current test."
puts "Window is about 20 us: row values are a snapshot, not a full moving scan."
puts "CSV: $csv_file"
