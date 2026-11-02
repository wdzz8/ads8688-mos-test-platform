# Capture 32 scans and export data without opening the waveform viewer.
# Prerequisite: mos_scan.bit and mos_scan.ltx from output/mos_scan are programmed.
# Usage (Vivado Hardware Manager Tcl console):
#   source scripts/capture_mos_scan.tcl
# Plot the CSV separately in PowerShell with plot_mos_scan.py --loopback.
# Note: this file is ASCII only on purpose. The Vivado Tcl console reads scripts
# with the system code page, so non-ASCII text would be garbled.
set project_root [file normalize [file join [file dirname [info script]] ..]]
set out_dir [file join $project_root output mos_scan]
file mkdir $out_dir
set stamp [clock format [clock seconds] -format %Y%m%d_%H%M%S]
set csv_file [file join $out_dir "mos_scan_$stamp.csv"]
set capture_depth 1024
if {[info exists ::mos_capture_depth]} { set capture_depth $::mos_capture_depth }
if {![string is integer -strict $capture_depth] || $capture_depth < 128 ||
    $capture_depth > 1024 || ($capture_depth & ($capture_depth - 1)) != 0} {
    error "Capture depth must be a power of two between 128 and 1024."
}

# Bus probes may be reported as "point[4:0]"; match by name prefix.
proc find_probe {ila base} {
    foreach p [get_hw_probes -of_objects $ila] {
        set n [get_property NAME $p]
        if {[string equal -nocase $n $base] || [string first "${base}\[" $n] == 0} {
            return $p
        }
    }
    return ""
}

proc list_probes {ila} {
    set names {}
    foreach p [get_hw_probes -of_objects $ila] {
        lappend names "[get_property NAME $p]([get_property WIDTH $p])"
    }
    return $names
}

set ilas [get_hw_ilas -of_objects [current_hw_device] -filter {CELL_NAME == "u_ila_scan"}]
if {[llength $ilas] != 1} {
    puts "ILA cores on this device: [get_hw_ilas -of_objects [current_hw_device]]"
    error "u_ila_scan not found. Program mos_scan.bit and mos_scan.ltx together."
}
set scan_ila [lindex $ilas 0]
puts "ILA [get_property NAME $scan_ila] probes: [list_probes $scan_ila]"

set row_probe   [find_probe $scan_ila row_valid]
set point_probe [find_probe $scan_ila point]
if {$row_probe eq "" || $point_probe eq ""} {
    error "row_valid or point probe missing. Existing probes: [list_probes $scan_ila]"
}

# Reset every probe to don't-care, then set the qualifier and trigger only.
foreach probe [get_hw_probes -of_objects $scan_ila] {
    set width [get_property WIDTH $probe]
    set dont_care [format {eq%d'b%s} $width [string repeat X $width]]
    set_property TRIGGER_COMPARE_VALUE $dont_care $probe
    set_property CAPTURE_COMPARE_VALUE $dont_care $probe
}

set_property CONTROL.TRIGGER_CONDITION AND $scan_ila
set_property CONTROL.CAPTURE_CONDITION AND $scan_ila
set_property CONTROL.CAPTURE_MODE BASIC $scan_ila
set_property CONTROL.TRIGGER_POSITION 0 $scan_ila
if {![catch {list_property_value CONTROL.DATA_DEPTH $scan_ila} depth_options]} {
    puts "Available ILA capture depths: $depth_options"
}
set_property CONTROL.DATA_DEPTH $capture_depth $scan_ila

# Store one sample per scan point, starting at point 0 of a scan.
set_property CAPTURE_COMPARE_VALUE eq1'b1 $row_probe
set_property TRIGGER_COMPARE_VALUE  eq1'b1 $row_probe
set_property TRIGGER_COMPARE_VALUE  eq5'b00000 $point_probe

puts "Arming qualified capture: $capture_depth rows ..."
run_hw_ila $scan_ila
if {[catch {wait_on_hw_ila $scan_ila -timeout 60} err]} {
    puts "Qualified capture timed out: $err"
    catch {stop_hw_ila $scan_ila}
    puts "Retrying with a plain capture to check the data path ..."
    foreach probe [get_hw_probes -of_objects $scan_ila] {
        set width [get_property WIDTH $probe]
        set dont_care [format {eq%d'b%s} $width [string repeat X $width]]
        set_property TRIGGER_COMPARE_VALUE $dont_care $probe
        set_property CAPTURE_COMPARE_VALUE $dont_care $probe
    }
    set_property CONTROL.CAPTURE_MODE ALWAYS $scan_ila
    run_hw_ila -trigger_now $scan_ila
    wait_on_hw_ila $scan_ila -timeout 3
    set raw_data [upload_hw_ila_data $scan_ila]
    set raw_csv [file join $out_dir "raw_$stamp.csv"]
    write_hw_ila_data -force -csv_file $raw_csv $raw_data
    write_hw_ila_data -force [file rootname $raw_csv].ila $raw_data
    puts "Plain capture exported: $raw_csv ($capture_depth samples, 20 ns apart)"
    puts "Read init_done / init_error / dac_ready / dac_error / adc_valid from it."
    puts "Use check_mos_scan_status.tcl for a quick status read."
    return
}

set scan_data [upload_hw_ila_data $scan_ila]
# Vivado 2022.2 on this PC crashes in display_hw_ila_data -reset.
# Export first and keep capture completely independent of the GUI viewer.
write_hw_ila_data -force -csv_file $csv_file $scan_data
puts "Exported: $csv_file"
write_hw_ila_data -force [file rootname $csv_file].ila $scan_data
puts "Saved ILA: [file rootname $csv_file].ila"
puts "Capture complete. The waveform viewer was not opened."
