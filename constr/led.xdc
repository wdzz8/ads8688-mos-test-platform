#==========================================================================
#  板载 4 个 PL LED 的引脚约束（配合 ads8688_led_test 顶层）
#  AX7020：4 个 PL LED 接在 BANK35，3.3V，低电平点亮
#  注意：sys_clk / adc_* 的约束已经在 ads8688.xdc 里，这里不要重复写
#==========================================================================

# LED1 -> M14
set_property -dict {PACKAGE_PIN M14 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
# LED2 -> M15
set_property -dict {PACKAGE_PIN M15 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
# LED3 -> K16
set_property -dict {PACKAGE_PIN K16 IOSTANDARD LVCMOS33} [get_ports {led[2]}]
# LED4 -> J16
set_property -dict {PACKAGE_PIN J16 IOSTANDARD LVCMOS33} [get_ports {led[3]}]


