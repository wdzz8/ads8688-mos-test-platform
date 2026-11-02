# Caller owns the drain-off / bounded-power policy. VIO is output-only control;
# all accepted state and measurements come from ILA, never VIO INPUT_VALUE.
if {[llength $argv]!=8} {error "Usage: OUT program|capture LOW HIGH HALF_CYCLES WAVE DEPTH ADC_RESET"}
lassign $argv out action low high half wave depth restart
set root [file normalize [file join [file dirname [info script]] ..]]
source [file join $root scripts fixed_vgs_device_status.tcl]
set out [file normalize $out]
file mkdir $out
foreach item [list $low $high $half $wave $depth $restart] {
    if {![string is integer -strict $item]} {error "Integer arguments required"}
}
if {$action ni {program capture} || $low<0 || $high>4095 || $high<$low || $half<50000 ||
    $half>50000000 || $wave ni {0 1} || $restart ni {0 1} || $depth<128 || $depth>8192 ||
    ($depth & ($depth-1))!=0} {error "Invalid experiment arguments"}
proc output_probe {vio pattern value} {
    set p [get_hw_probes -of_objects $vio -filter "NAME =~ $pattern"]
    if {[llength $p]!=1} {error "Missing experiment output $pattern"}
    set_property OUTPUT_VALUE_RADIX HEX $p
    set digits [expr {([get_property WIDTH $p]+3)/4}]
    set_property OUTPUT_VALUE [format %0*x $digits $value] $p
}
open_hw_manager
set failed [catch {
    connect_hw_server -url localhost:3121
    set targets [get_hw_targets -quiet *210512180081]
    if {[llength $targets]!=1} {error "Expected AX7020 JTAG 210512180081"}
    open_hw_target [lindex $targets 0]
    set device [lindex [get_hw_devices xc7z020*] 0]
    current_hw_device $device
    set image [file join $root output mos_experiment]
    set_property PROBES.FILE [file join $image mos_experiment.ltx] $device
    set_property FULL_PROBES.FILE [file join $image mos_experiment.ltx] $device
    if {$action eq "program"} {
        set_property PROGRAM.FILE [file join $image mos_experiment.bit] $device
        program_hw_devices $device
    }
    refresh_hw_device $device
    fixed_vgs_device_status $device [file join $out device_status.txt]
    set vio [get_hw_vios -of_objects $device -filter {CELL_NAME == "u_control"}]
    if {[llength $vio]!=1} {error "Experiment control core missing"}
    output_probe $vio request_apply* 0
    output_probe $vio request_low* $low
    output_probe $vio request_high* $high
    output_probe $vio request_half_cycles* $half
    output_probe $vio request_wave* $wave
    output_probe $vio request_adc_reset* $restart
    commit_hw_vio $vio
    if {$restart} {
        output_probe $vio request_adc_reset* 0
        commit_hw_vio $vio
        after 150
    }
    output_probe $vio request_apply* 1
    commit_hw_vio $vio
    output_probe $vio request_apply* 0
    commit_hw_vio $vio
    after 200
    set ila [get_hw_ilas -of_objects $device -filter {CELL_NAME == "u_ila_experiment"}]
    if {[llength $ila]!=1} {error "Experiment ILA missing"}
    foreach p [get_hw_probes -of_objects $ila] {
        set w [get_property WIDTH $p]
        set any [format {eq%d'b%s} $w [string repeat X $w]]
        set_property TRIGGER_COMPARE_VALUE $any $p
        set_property CAPTURE_COMPARE_VALUE $any $p
    }
    set row [get_hw_probes -of_objects $ila -filter {NAME == "row_valid"}]
    set_property CONTROL.DATA_DEPTH $depth $ila
    set_property CONTROL.CAPTURE_MODE BASIC $ila
    set_property CONTROL.TRIGGER_POSITION 0 $ila
    set_property CONTROL.TRIGGER_CONDITION AND $ila
    set_property CONTROL.CAPTURE_CONDITION AND $ila
    set_property TRIGGER_COMPARE_VALUE eq1'b1 $row
    set_property CAPTURE_COMPARE_VALUE eq1'b1 $row
    run_hw_ila $ila
    wait_on_hw_ila $ila -timeout 15
    set data [upload_hw_ila_data $ila]
    write_hw_ila_data -force -csv_file [file join $out rows.csv] $data
    puts "EXPERIMENT_CAPTURED=$out LOW=$low HIGH=$high WAVE=$wave HALF=$half"
} message options]
catch {close_hw_manager}
if {$failed} {return -options $options $message}
