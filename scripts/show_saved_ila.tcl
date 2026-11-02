# Recover the last saved ILA capture to CSV without opening the waveform viewer.
# No programming, hardware connection, or new capture is needed.
# Run in the Vivado GUI Tcl Console:
#   source scripts/show_saved_ila.tcl
set saved_ila_root [file normalize [file join [file dirname [info script]] ..]]
set saved_ila_file [file join $saved_ila_root ads8688_1.hw backup hw_ila_data_1.ila]
if {![file isfile $saved_ila_file]} {
    error "No saved capture at $saved_ila_file. Run capture_mos_scan.tcl first."
}
set saved_ila_data [read_hw_ila_data $saved_ila_file]
set saved_ila_out [file join $saved_ila_root output mos_scan]
file mkdir $saved_ila_out
set saved_ila_stamp [clock format [clock seconds] -format %Y%m%d_%H%M%S]
set saved_ila_csv [file join $saved_ila_out recovered_$saved_ila_stamp.csv]
write_hw_ila_data -force -csv_file $saved_ila_csv $saved_ila_data
puts "Recovered saved ILA data. The waveform viewer was not opened."
puts "Saved file: $saved_ila_file"
puts "Saved at: [clock format [file mtime $saved_ila_file] -format {%Y-%m-%d %H:%M:%S}]"
puts "Exported: $saved_ila_csv"
