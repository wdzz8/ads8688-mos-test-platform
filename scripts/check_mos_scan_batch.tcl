# Read the existing FPGA image's ADC/DAC status. Never programs the FPGA.
# Usage: vivado -mode batch -source scripts/check_mos_scan_batch.tcl
set status_root [file normalize [file join [file dirname [info script]] ..]]
open_hw_manager
set status_failed [catch {
    connect_hw_server -url localhost:3121
    puts "Available JTAG targets: [get_hw_targets -quiet]"
    set status_targets [get_hw_targets -quiet *210512180081]
    if {[llength $status_targets] != 1} {
        error "Expected AX7020 JTAG target 210512180081 is not available."
    }
    open_hw_target [lindex $status_targets 0]
    set status_devices [get_hw_devices -quiet xc7z020*]
    if {[llength $status_devices] != 1} {
        error "Expected one xc7z020 device."
    }
    set status_device [lindex $status_devices 0]
    current_hw_device $status_device
    set status_ltx [file join $status_root output mos_scan mos_scan.ltx]
    set_property PROBES.FILE $status_ltx $status_device
    set_property FULL_PROBES.FILE $status_ltx $status_device
    refresh_hw_device $status_device
    source [file join $status_root scripts check_mos_scan_status.tcl]
} status_message status_options]
catch {close_hw_manager}
if {$status_failed} {
    return -options $status_options $status_message
}
