# MCP4725 standalone test wiring on AX7020 J11.
# J11-9 = H18 (EX_IO2_4N), J11-10 = J18 (EX_IO2_4P).
set_property -dict {PACKAGE_PIN H18 IOSTANDARD LVCMOS33} [get_ports mcp_scl]
set_property -dict {PACKAGE_PIN J18 IOSTANDARD LVCMOS33} [get_ports mcp_sda]
set_property -dict {PACKAGE_PIN U18 IOSTANDARD LVCMOS33} [get_ports sys_clk]
set_property -dict {PACKAGE_PIN M14 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN M15 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN K16 IOSTANDARD LVCMOS33} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN J16 IOSTANDARD LVCMOS33} [get_ports {led[3]}]
create_clock -period 20.000 -name sys_clk [get_ports sys_clk]
