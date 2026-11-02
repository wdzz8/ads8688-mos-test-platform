# Program the existing matched mos_scan image, then read ADC/DAC status.
# Prerequisites: AX7020 and analog module supplies ON; DPS output OFF.
# This starts the existing DAC staircase. Connect its gate path only as instructed.
set program_root [file normalize [file join [file dirname [info script]] ..]]
set program_bit [file join $program_root output mos_scan mos_scan.bit]
set program_ltx [file join $program_root output mos_scan mos_scan.ltx]
foreach program_file [list $program_bit $program_ltx] {
    if {![file isfile $program_file]} { error "File not found: $program_file" }
}
open_hw_manager
set program_failed [catch {
    connect_hw_server -url localhost:3121
    puts "Available JTAG targets: [get_hw_targets -quiet]"
    set program_targets [get_hw_targets -quiet *210512180081]
    if {[llength $program_targets] != 1} {
        error "Expected AX7020 JTAG target 210512180081 is not available."
    }
    open_hw_target [lindex $program_targets 0]
    set program_devices [get_hw_devices -quiet xc7z020*]
    if {[llength $program_devices] != 1} { error "Expected one xc7z020 device." }
    set program_device [lindex $program_devices 0]
    current_hw_device $program_device
    set_property PROGRAM.FILE $program_bit $program_device
    set_property PROBES.FILE $program_ltx $program_device
    set_property FULL_PROBES.FILE $program_ltx $program_device
    program_hw_devices $program_device
    refresh_hw_device $program_device
    after 500
    set program_ilas [get_hw_ilas -of_objects $program_device]
    foreach program_ila $program_ilas {
        if {![catch {list_property_value CONTROL.DATA_DEPTH $program_ila} program_depths]} {
            puts "ILA capture-depth options: $program_depths"
        }
    }
    source [file join $program_root scripts check_mos_scan_status.tcl]
} program_message program_options]
catch {close_hw_manager}
if {$program_failed} {
    return -options $program_options $program_message
}
