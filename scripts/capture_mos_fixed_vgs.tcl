# Capture a fixed-VGS image. The image must already be programmed manually.
# Usage: ... -source capture_mos_fixed_vgs.tcl -tclargs OUTPUT_CSV DEPTH LTX_FILE
set fixed_capture_root [file normalize [file join [file dirname [info script]] ..]]
source [file join $fixed_capture_root scripts fixed_vgs_device_status.tcl]
if {[llength $argv] < 1 || [llength $argv] > 3} {
    error "Usage: capture_mos_fixed_vgs.tcl OUTPUT_CSV ?DEPTH? ?LTX_FILE?"
}
set fixed_csv [file normalize [lindex $argv 0]]
set fixed_depth 256
if {[llength $argv] >= 2} {set fixed_depth [expr {int([lindex $argv 1])}]}
set fixed_ltx ""
if {[llength $argv] == 3} {
    set fixed_ltx [file normalize [lindex $argv 2]]
    if {![file isfile $fixed_ltx]} {error "LTX file not found: $fixed_ltx"}
}
if {$fixed_depth < 128 || $fixed_depth > 1024 || ($fixed_depth & ($fixed_depth - 1)) != 0} {
    error "DEPTH must be a power of two from 128 to 1024"
}
open_hw_manager
set fixed_failed [catch {
    connect_hw_server -url localhost:3121
    set targets [get_hw_targets -quiet *210512180081]
    if {[llength $targets] != 1} {error "Expected AX7020 JTAG target 210512180081"}
    open_hw_target [lindex $targets 0]
    set devices [get_hw_devices -quiet xc7z020*]
    if {[llength $devices] != 1} {error "Expected one xc7z020 device"}
    set device [lindex $devices 0]
    current_hw_device $device
    if {$fixed_ltx ne ""} {
        # Bind probes to an already programmed design; this does not program
        # or reset the FPGA and fixes the common bit-without-ltx case.
        set_property PROBES.FILE $fixed_ltx $device
        set_property FULL_PROBES.FILE $fixed_ltx $device
    }
    refresh_hw_device $device
    fixed_vgs_device_status $device [file rootname $fixed_csv].device_status.txt
    set ilas [get_hw_ilas -of_objects $device -filter {CELL_NAME == "u_ila_scan"}]
    if {[llength $ilas] != 1} {error "Program a matching fixed-VGS image first"}
    set ila [lindex $ilas 0]
    set row_probe [get_hw_probes -of_objects $ila -filter {NAME == "row_valid"}]
    if {[llength $row_probe] != 1} {error "Missing row_valid probe"}
    foreach probe [get_hw_probes -of_objects $ila] {
        set width [get_property WIDTH $probe]
        set dont_care [format {eq%d'b%s} $width [string repeat X $width]]
        set_property TRIGGER_COMPARE_VALUE $dont_care $probe
        set_property CAPTURE_COMPARE_VALUE $dont_care $probe
    }
    set_property CONTROL.TRIGGER_CONDITION AND $ila
    set_property CONTROL.CAPTURE_CONDITION AND $ila
    set_property CONTROL.CAPTURE_MODE BASIC $ila
    set_property CONTROL.TRIGGER_POSITION 0 $ila
    set_property CONTROL.DATA_DEPTH $fixed_depth $ila
    set_property TRIGGER_COMPARE_VALUE eq1'b1 $row_probe
    set_property CAPTURE_COMPARE_VALUE eq1'b1 $row_probe
    run_hw_ila $ila
    wait_on_hw_ila $ila -timeout 60
    set data [upload_hw_ila_data $ila]
    file mkdir [file dirname $fixed_csv]
    write_hw_ila_data -force -csv_file $fixed_csv $data
    write_hw_ila_data -force [file rootname $fixed_csv].ila $data
    puts "Exported fixed-VGS capture: $fixed_csv"
} fixed_message fixed_options]
catch {close_hw_manager}
if {$fixed_failed} {return -options $fixed_options $fixed_message}
