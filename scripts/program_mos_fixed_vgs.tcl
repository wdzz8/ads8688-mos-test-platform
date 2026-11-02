# Program only a prebuilt fixed-gate image. Caller must verify DPS output OFF.
# Usage: vivado -mode batch -source program_mos_fixed_vgs.tcl -tclargs DAC_CODE
set fixed_root [file normalize [file join [file dirname [info script]] ..]]
source [file join $fixed_root scripts fixed_vgs_device_status.tcl]
if {[llength $argv] != 1 || ![string is integer -strict [lindex $argv 0]]} {
    error "Usage: program_mos_fixed_vgs.tcl DAC_CODE"
}
set fixed_code [lindex $argv 0]
if {$fixed_code < 0 || $fixed_code > 4095} {error "DAC_CODE must be 0..4095"}
set fixed_dir [file join $fixed_root output mos_fixed_vgs [format "code_%04d" $fixed_code]]
set fixed_bit [file join $fixed_dir mos_fixed_vgs.bit]
set fixed_ltx [file join $fixed_dir mos_fixed_vgs.ltx]
foreach fixed_file [list $fixed_bit $fixed_ltx] {
    if {![file isfile $fixed_file]} {error "Missing fixed-gate image: $fixed_file"}
}
open_hw_manager
set fixed_failed [catch {
    connect_hw_server -url localhost:3121
    set targets [get_hw_targets -quiet *210512180081]
    if {[llength $targets] != 1} {error "Expected AX7020 JTAG 210512180081"}
    open_hw_target [lindex $targets 0]
    set devices [get_hw_devices -quiet xc7z020*]
    if {[llength $devices] != 1} {error "Expected exactly one xc7z020"}
    set device [lindex $devices 0]
    current_hw_device $device
    set_property PROGRAM.FILE $fixed_bit $device
    set_property PROBES.FILE $fixed_ltx $device
    set_property FULL_PROBES.FILE $fixed_ltx $device
    program_hw_devices $device
    refresh_hw_device $device
    fixed_vgs_device_status $device [file join $fixed_dir programmed_device_status.txt]
    set ilas [get_hw_ilas -of_objects $device -filter {CELL_NAME == "u_ila_scan"}]
    if {[llength $ilas] != 1} {error "Fixed-gate ILA not found after programming"}
    puts "PROGRAMMED_FIXED_DAC=$fixed_code BIT=$fixed_bit"
} fixed_message fixed_options]
catch {close_hw_manager}
if {$fixed_failed} {return -options $fixed_options $fixed_message}
