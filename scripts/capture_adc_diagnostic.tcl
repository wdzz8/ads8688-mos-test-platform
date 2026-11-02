# Drain-OFF diagnostic: program, capture, or reset ADC without changing DAC.
# Args: OUTPUT_DIR program|capture|reset|observe|audit|observe_audit [OBSERVE_SECONDS]
if {[llength $argv] ni {2 3}} {error {Usage: capture_adc_diagnostic.tcl OUTPUT_DIR ACTION [OBSERVE_SECONDS]}}
set root [file normalize [file join [file dirname [info script]] ..]]
source [file join $root scripts fixed_vgs_device_status.tcl]
set out [file normalize [lindex $argv 0]]
set action [lindex $argv 1]
if {$action ni {program capture reset observe audit observe_audit}} {error "Unknown action"}
set observe_seconds 300
if {[llength $argv] == 3} {set observe_seconds [lindex $argv 2]}
if {![string is integer -strict $observe_seconds] || $observe_seconds < 1 || $observe_seconds > 1800} {
    error "OBSERVE_SECONDS must be 1..1800"
}
set image [file join $root output mos_adc_diagnostic audit_code_2560]
file mkdir $out
proc diagnostic_snapshot {ila out name words} {
    foreach probe [get_hw_probes -of_objects $ila] {
        set width [get_property WIDTH $probe]
        set value [format {eq%d'b%s} $width [string repeat X $width]]
        set_property TRIGGER_COMPARE_VALUE $value $probe
        set_property CAPTURE_COMPARE_VALUE $value $probe
    }
    set_property CONTROL.TRIGGER_CONDITION AND $ila
    set_property CONTROL.CAPTURE_CONDITION AND $ila
    set_property CONTROL.TRIGGER_POSITION 0 $ila
    if {$words} {
        set_property CONTROL.DATA_DEPTH 1024 $ila
        set_property CONTROL.CAPTURE_MODE BASIC $ila
        set valid [get_hw_probes -of_objects $ila -filter {NAME == "adc_valid"}]
        if {[llength $valid] != 1} {error "Missing adc_valid probe"}
        set_property TRIGGER_COMPARE_VALUE eq1'b1 $valid
        set_property CAPTURE_COMPARE_VALUE eq1'b1 $valid
        run_hw_ila $ila
    } else {
        set_property CONTROL.DATA_DEPTH 4096 $ila
        set_property CONTROL.CAPTURE_MODE ALWAYS $ila
        run_hw_ila -trigger_now $ila
    }
    wait_on_hw_ila $ila -timeout 5
    set data [upload_hw_ila_data $ila]
    write_hw_ila_data -force -csv_file [file join $out ${name}.csv] $data
}
proc diagnostic_csv_value {path signal} {
    set handle [open $path r]
    set lines [split [string trim [read $handle]] \n]
    close $handle
    set header [split [lindex $lines 0] ,]
    set index [lsearch -glob $header "${signal}*"]
    if {$index < 0} {error "Missing ILA CSV signal $signal"}
    return [string trim [lindex [split [lindex $lines end] ,] $index] "\r\""]
}
open_hw_manager
set failed [catch {
    connect_hw_server -url localhost:3121
    set targets [get_hw_targets -quiet *210512180081]
    if {[llength $targets] != 1} {error "Expected AX7020 JTAG 210512180081"}
    open_hw_target [lindex $targets 0]
    set devices [get_hw_devices -quiet xc7z020*]
    if {[llength $devices] != 1} {error "Expected exactly one xc7z020"}
    set device [lindex $devices 0]
    current_hw_device $device
    set_property PROBES.FILE [file join $image mos_adc_diagnostic.ltx] $device
    set_property FULL_PROBES.FILE [file join $image mos_adc_diagnostic.ltx] $device
    if {$action eq "program"} {
        set_property PROGRAM.FILE [file join $image mos_adc_diagnostic.bit] $device
        program_hw_devices $device
    }
    refresh_hw_device $device
    fixed_vgs_device_status $device [file join $out device_status.txt]
    set ilas [get_hw_ilas -of_objects $device -filter {CELL_NAME == "u_ila_adc_diagnostic"}]
    if {[llength $ilas] != 1} {error "ADC diagnostic ILA not found"}
    set ila [lindex $ilas 0]
    set dump [open [file join $out vio_properties.txt] w]
    foreach item [get_hw_probes -of_objects [get_hw_vios -of_objects $device]] {
        puts $dump "PROBE=$item"
        foreach key {NAME TYPE WIDTH INPUT_VALUE OUTPUT_VALUE OUTPUT_VALUE_RADIX} {
            if {![catch {get_property $key $item} value]} {puts $dump "$key=$value"}
        }
    }
    close $dump
    set observed_new_fault 0
    if {$action in {observe observe_audit}} {
        set vios [get_hw_vios -of_objects $device]
        if {[llength $vios] != 1} {error "Expected one ADC reset VIO"}
        set vio [lindex $vios 0]
        set monitor [open [file join $out vio_observation.csv] w]
        puts $monitor "host_epoch_ms,elapsed_ms,fault_latched,adc_reset_count,ffff_run"
        file mkdir [file join $out polls]
        set poll_index 0
        set started [clock milliseconds]
        set deadline [expr {$started + 1000 * $observe_seconds}]
        set watch_failed [catch {
            while {1} {
                set poll_name [format {poll_%04d} $poll_index]
                incr poll_index
                diagnostic_snapshot $ila [file join $out polls] $poll_name 0
                set poll_path [file join $out polls ${poll_name}.csv]
                set values {}
                foreach signal {fault_latched adc_reset_count ffff_run} {
                    lappend values [diagnostic_csv_value $poll_path $signal]
                }
                set now [clock milliseconds]
                puts $monitor "$now,[expr {$now - $started}],[join $values ,]"
                flush $monitor
                if {[scan [lindex $values 0] %x fault] != 1} {error "Invalid VIO fault value"}
                if {[scan [lindex $values 2] %x current_run] != 1} {error "Invalid VIO FFFF count"}
                if {![info exists initial_fault]} {set initial_fault $fault}
                if {$current_run >= 16 || (!$initial_fault && $fault)} {
                    set observed_new_fault 1
                    puts "ADC_DIAGNOSTIC_FAULT elapsed_ms=[expr {$now - $started}]"; break
                }
                if {$now >= $deadline} {break}
                after 1000
            }
        } watch_message watch_options]
        close $monitor
        if {$watch_failed} {return -options $watch_options $watch_message}
    }
    diagnostic_snapshot $ila $out before_spi 0
    set audit_paused 0
    scan [diagnostic_csv_value [file join $out before_spi.csv] adc_audit_done] %x audit_paused
    if {!$audit_paused} {diagnostic_snapshot $ila $out before_words 1}
    if {$action eq "audit" || ($action eq "observe_audit" && $observed_new_fault)} {
        set vio [lindex [get_hw_vios -of_objects $device] 0]
        set request [get_hw_probes -of_objects $vio -filter {NAME =~ "adc_audit_request*"}]
        set done [get_hw_probes -of_objects $vio -filter {NAME =~ "adc_audit_done*"}]
        set values [get_hw_probes -of_objects $vio -filter {NAME =~ "adc_audit_values*"}]
        if {[llength $request] != 1 || [llength $done] != 1 || [llength $values] != 1} {
            error "Register audit requires the matching audit diagnostic image"
        }
        if {$audit_paused} {error "Previous audit still paused; capture its saved values before ADC reset"}
        set_property OUTPUT_VALUE 1 $request
        commit_hw_vio $request
        set audit_failed [catch {
            after 100
            diagnostic_snapshot $ila $out audit_result_spi 0
            scan [diagnostic_csv_value [file join $out audit_result_spi.csv] adc_audit_done] %x complete
            if {$complete != 1} {error "ADC register audit did not complete in ILA"}
            set result [diagnostic_csv_value [file join $out audit_result_spi.csv] adc_audit_values]
            set handle [open [file join $out audit_values.hex] w]
            puts $handle $result
            close $handle
            puts "ADC_AUDIT_VALUES=$result ADC_PAUSED=1"
        } audit_message audit_options]
        set_property OUTPUT_VALUE 0 $request
        commit_hw_vio $request
        if {$audit_failed} {
            diagnostic_snapshot $ila $out audit_timeout_spi 0
            return -options $audit_options $audit_message
        }
    }
    if {$action eq "reset"} {
        set vios [get_hw_vios -of_objects $device]
        if {[llength $vios] != 1} {error "Expected one ADC reset VIO"}
        set vio [lindex $vios 0]
        set probe [get_hw_probes -of_objects $vio -filter {NAME =~ "adc_reset_request*"}]
        if {[llength $probe] != 1} {error "ADC reset VIO probe not found: [get_hw_probes -of_objects $vio]"}
        set_property OUTPUT_VALUE 1 $probe
        commit_hw_vio $probe
        set_property OUTPUT_VALUE 0 $probe
        commit_hw_vio $probe
        after 150
        refresh_hw_vio $vio
        diagnostic_snapshot $ila $out after_spi 0
        diagnostic_snapshot $ila $out after_words 1
    }
    puts "ADC_DIAGNOSTIC action=$action output=$out"
} message options]
catch {close_hw_manager}
if {$failed} {return -options $options $message}
