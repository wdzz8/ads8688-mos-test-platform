# Check physical FPGA configuration status; PROGRAM.FILE is host metadata only.
# A passing configuration check does not establish valid ADC conversions.
proc fixed_vgs_device_status {device path} {
    file mkdir [file dirname $path]
    set handle [open $path w]
    puts $handle "TIMESTAMP=[clock format [clock seconds] -format {%Y-%m-%dT%H:%M:%S%z}]"
    set properties [list_property $device]
    set invalid {}
    foreach {property expected} {
        REGISTER.CONFIG_STATUS.BIT00_CRC_ERROR 0
        REGISTER.CONFIG_STATUS.BIT04_END_OF_STARTUP_(EOS)_STATUS 1
        REGISTER.CONFIG_STATUS.BIT11_INIT_B_INTERNAL_SIGNAL_STATUS 1
        REGISTER.CONFIG_STATUS.BIT12_INIT_B_PIN 1
        REGISTER.CONFIG_STATUS.BIT13_DONE_INTERNAL_SIGNAL_STATUS 1
        REGISTER.CONFIG_STATUS.BIT14_DONE_PIN 1
        REGISTER.CONFIG_STATUS.BIT15_IDCODE_ERROR 0
    } {
        if {[lsearch -exact $properties $property] < 0} {
            set value MISSING
        } else {
            set value [get_property $property $device]
        }
        puts $handle "$property=$value"
        puts "FPGA_STATUS $property=$value"
        if {$value ne $expected} {lappend invalid "$property=$value (expected $expected)"}
    }
    close $handle
    if {[llength $invalid]} {error "FPGA configuration status rejected: [join $invalid {; }]"}
}
