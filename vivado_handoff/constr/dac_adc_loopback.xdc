# AX7020 / xc7z020clg400-2 / dac_adc_loopback
# Electrical pin mapping only. External interface delays are not yet specified.
set_property -dict {PACKAGE_PIN U18 IOSTANDARD LVCMOS33} [get_ports sys_clk]
create_clock -period 20.000 -name sys_clk [get_ports sys_clk]

# ADS8688: J11-3,4,5,6,7 respectively; DAISY is tied to module GND.
set_property -dict {PACKAGE_PIN F17 IOSTANDARD LVCMOS33} [get_ports adc_cs_n]
set_property -dict {PACKAGE_PIN F16 IOSTANDARD LVCMOS33} [get_ports adc_sclk]
set_property -dict {PACKAGE_PIN F20 IOSTANDARD LVCMOS33} [get_ports adc_sdi]
set_property -dict {PACKAGE_PIN F19 IOSTANDARD LVCMOS33} [get_ports adc_sdo]
set_property -dict {PACKAGE_PIN G20 IOSTANDARD LVCMOS33} [get_ports adc_rst_n]

# MCP4725: J11-9=SCL, J11-10=SDA. External pullups to 3.3 V required.
set_property -dict {PACKAGE_PIN H18 IOSTANDARD LVCMOS33} [get_ports mcp_scl]
set_property -dict {PACKAGE_PIN J18 IOSTANDARD LVCMOS33} [get_ports mcp_sda]

# Board LEDs, active low.
set_property -dict {PACKAGE_PIN M14 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN M15 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN K16 IOSTANDARD LVCMOS33} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN J16 IOSTANDARD LVCMOS33} [get_ports {led[3]}]

# DPS USB/UART, external trigger, interlock and fault pins: not assigned.
# These are not ports in the current RTL; do not create placeholder constraints.
