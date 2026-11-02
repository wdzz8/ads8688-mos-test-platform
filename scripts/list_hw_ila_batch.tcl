# Read-only JTAG diagnostic. Never programs the FPGA or changes DPS.
set diag_root [file normalize [file join [file dirname [info script]] ..]]
open_hw_manager
set diag_failed [catch {
    connect_hw_server -url localhost:3121
    puts "TARGETS=[get_hw_targets -quiet]"
    set targets [get_hw_targets -quiet *210512180081]
    if {[llength $targets] != 1} {error "Expected AX7020 JTAG target 210512180081"}
    open_hw_target [lindex $targets 0]
    set devices [get_hw_devices -quiet xc7z020*]
    if {[llength $devices] != 1} {error "Expected one xc7z020 device"}
    set device [lindex $devices 0]
    current_hw_device $device
    refresh_hw_device $device
    puts "DEVICE=[get_property NAME $device]"
    puts "PROGRAM_FILE=[get_property PROGRAM.FILE $device]"
    puts "PROBES_FILE=[get_property PROBES.FILE $device]"
    puts "ILAS=[get_hw_ilas -of_objects $device]"
    foreach ila [get_hw_ilas -of_objects $device] {
        puts "ILA=[get_property CELL_NAME $ila] NAME=[get_property NAME $ila]"
        puts "PROBES=[get_hw_probes -of_objects $ila]"
    }
} diag_message diag_options]
catch {close_hw_manager}
if {$diag_failed} {return -options $diag_options $diag_message}
