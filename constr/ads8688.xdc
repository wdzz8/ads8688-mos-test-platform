#==========================================================================
#  ADS8688 采集 —— 引脚约束
#  开发板: AX7020 (xc7z020clg400-2)   扩展口: J11
#  说明: 端口名必须和顶层模块 ads8688_top 的端口名完全一致
#==========================================================================

#--------------------------------------------------------------------------
# 板载 50MHz 时钟
#--------------------------------------------------------------------------
set_property -dict {PACKAGE_PIN U18 IOSTANDARD LVCMOS33} [get_ports sys_clk]

#--------------------------------------------------------------------------
# ADS8688 模块 P1 -> J11 扩展口 (BANK35, 3.3V)
#   J11 编号规则: 奇数针一排(1,3,5...39), 偶数针一排(2,4,6...40),
#                板子上 Pin1/Pin2 与 Pin39/Pin40 都有丝印标出
#--------------------------------------------------------------------------
# J11 PIN3  -> F17  (IO_L6N_T0_35)   片选 CS
set_property -dict {PACKAGE_PIN F17 IOSTANDARD LVCMOS33} [get_ports adc_cs_n]

# J11 PIN4  -> F16  (IO_L6P_T0_35)   SPI 时钟 SCLK
set_property -dict {PACKAGE_PIN F16 IOSTANDARD LVCMOS33} [get_ports adc_sclk]

# J11 PIN5  -> F20  (IO_L15N_T2_35)  FPGA -> ADC 数据 SDI
set_property -dict {PACKAGE_PIN F20 IOSTANDARD LVCMOS33} [get_ports adc_sdi]

# J11 PIN6  -> F19  (IO_L15P_T2_35)  ADC -> FPGA 数据 SDO
set_property -dict {PACKAGE_PIN F19 IOSTANDARD LVCMOS33} [get_ports adc_sdo]

# J11 PIN7  -> G20  (IO_L18N_T2_35)  复位 RST
set_property -dict {PACKAGE_PIN G20 IOSTANDARD LVCMOS33} [get_ports adc_rst_n]

#--------------------------------------------------------------------------
# 时序约束
#--------------------------------------------------------------------------
create_clock -period 20.000 -name sys_clk [get_ports sys_clk]


