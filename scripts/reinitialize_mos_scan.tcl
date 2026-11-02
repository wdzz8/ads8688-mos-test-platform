# Repeat the ADS8688 startup sequence by programming the existing mos_scan image.
# Keep the ADS8688 and INA240 supplies on before running this script.
# Run in an already-connected Vivado Hardware Manager Tcl console:
#   source scripts/reinitialize_mos_scan.tcl
# No build and no waveform display/reset are performed.
set mos_reinit_root [file normalize [file join [file dirname [info script]] ..]]
set mos_reinit_bit [file join $mos_reinit_root output mos_scan mos_scan.bit]
set mos_reinit_ltx [file join $mos_reinit_root output mos_scan mos_scan.ltx]
foreach mos_reinit_file [list $mos_reinit_bit $mos_reinit_ltx] {
    if {![file isfile $mos_reinit_file]} {
        error "Required file not found: $mos_reinit_file"
    }
}
set mos_reinit_device [current_hw_device]
if {[llength $mos_reinit_device] != 1} {
    error "Select the connected AX7020 xc7z020 device first."
}
if {![string match -nocase xc7z020* [get_property NAME $mos_reinit_device]]} {
    error "The selected device is not the expected AX7020 xc7z020."
}
set_property PROGRAM.FILE $mos_reinit_bit $mos_reinit_device
set_property PROBES.FILE $mos_reinit_ltx $mos_reinit_device
set_property FULL_PROBES.FILE $mos_reinit_ltx $mos_reinit_device
puts "Reprogramming the existing mos_scan image to restart ADS8688 initialization ..."
program_hw_devices $mos_reinit_device
refresh_hw_device $mos_reinit_device
# Allow power-on reset, register initialization, and averaged rows to complete.
after 500
puts "Reading a status snapshot after reinitialization ..."
source [file join $mos_reinit_root scripts check_mos_scan_status.tcl]
