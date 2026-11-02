# Read FPGA configuration and fixed-gate rows without programming or resetting.
# Caller must verify the drain supply OFF. Args: OUTPUT_DIR DAC_CODE
if {[llength $argv] != 2} {error "Usage: diagnose_fixed_vgs.tcl OUTPUT_DIR DAC_CODE"}
set diagnostic_root [file normalize [file join [file dirname [info script]] ..]]
set diagnostic_out [file normalize [lindex $argv 0]]
set diagnostic_code [lindex $argv 1]
if {![string is integer -strict $diagnostic_code] || $diagnostic_code < 0 || $diagnostic_code > 4095} {
    error "DAC_CODE must be 0..4095"
}
set diagnostic_ltx [file join $diagnostic_root output mos_fixed_vgs [format "code_%04d" $diagnostic_code] mos_fixed_vgs.ltx]
if {![file isfile $diagnostic_ltx]} {error "Matching LTX not found"}
file mkdir $diagnostic_out
open_hw_manager
set diagnostic_failed [catch {
    connect_hw_server -url localhost:3121
    set targets [get_hw_targets -quiet *210512180081]
    if {[llength $targets] != 1} {error "Expected AX7020 JTAG 210512180081"}
    set target [lindex $targets 0]
    open_hw_target $target
    set devices [get_hw_devices -quiet xc7z020*]
    if {[llength $devices] != 1} {error "Expected exactly one xc7z020"}
    set device [lindex $devices 0]
    current_hw_device $device
    set_property PROBES.FILE $diagnostic_ltx $device
    set_property FULL_PROBES.FILE $diagnostic_ltx $device
    refresh_hw_device $device
    set handle [open [file join $diagnostic_out device_properties.txt] w]
    puts $handle "TIMESTAMP=[clock format [clock seconds] -format {%Y-%m-%dT%H:%M:%S%z}]"
    puts $handle "ACTION=read_only_no_program_no_reset"
    foreach property [lsort [list_property $device]] {
        if {![catch {get_property $property $device} value]} {
            puts $handle "$property=$value"
        }
    }
    close $handle
    foreach property {NAME IS_PROGRAMMED REGISTER.CONFIG_STATUS REGISTER.BOOT_STATUS REGISTER.COR0 REGISTER.COR1} {
        if {[lsearch -exact [list_property $device] $property] >= 0} {
            puts "DIAGNOSTIC $property=[get_property $property $device]"
        }
    }
    set ilas [get_hw_ilas -of_objects $device -filter {CELL_NAME == "u_ila_scan"}]
    if {[llength $ilas] != 1} {error "Expected fixed-gate ILA"}
    set ila [lindex $ilas 0]
    set row_probe [get_hw_probes -of_objects $ila -filter {NAME == "row_valid"}]
    if {[llength $row_probe] != 1} {error "Missing row_valid probe"}
    foreach probe [get_hw_probes -of_objects $ila] {
        set width [get_property WIDTH $probe]
        set value [format {eq%d'b%s} $width [string repeat X $width]]
        set_property TRIGGER_COMPARE_VALUE $value $probe
        set_property CAPTURE_COMPARE_VALUE $value $probe
    }
    set_property CONTROL.TRIGGER_CONDITION AND $ila
    set_property CONTROL.CAPTURE_CONDITION AND $ila
    set_property CONTROL.CAPTURE_MODE BASIC $ila
    set_property CONTROL.TRIGGER_POSITION 0 $ila
    set_property CONTROL.DATA_DEPTH 128 $ila
    set_property TRIGGER_COMPARE_VALUE eq1'b1 $row_probe
    set_property CAPTURE_COMPARE_VALUE eq1'b1 $row_probe
    run_hw_ila $ila
    wait_on_hw_ila $ila -timeout 45
    set data [upload_hw_ila_data $ila]
    write_hw_ila_data -force -csv_file [file join $diagnostic_out rows.csv] $data
    puts "DIAGNOSTIC output=$diagnostic_out"
} diagnostic_message diagnostic_options]
catch {close_hw_manager}
if {$diagnostic_failed} {return -options $diagnostic_options $diagnostic_message}
