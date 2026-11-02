# 构建 MOS 扫描版：VG 阶梯 + 每点一行数据 + ILA 导出
# 用法：vivado -mode batch -source scripts/build_mos_scan.tcl
set project_root [file normalize [file join [file dirname [info script]] ..]]
set source_root  $project_root
set output_dir   [file join $project_root output mos_scan]
file mkdir $output_dir
cd $output_dir

foreach source {ads8688_top.v mcp4725_i2c.v mos_scan.v} {
    read_verilog [file join $source_root rtl $source]
}
read_xdc [file join $source_root constr ads8688.xdc]
read_xdc [file join $source_root constr led.xdc]
synth_design -top mos_scan -part xc7z020clg400-2

# MCP4725 I2C 引脚与已验证版本一致，综合后再约束
set_property -dict {PACKAGE_PIN H18 IOSTANDARD LVCMOS33} [get_ports mcp_scl]
set_property -dict {PACKAGE_PIN J18 IOSTANDARD LVCMOS33} [get_ports mcp_sda]

# ILA：每次只存一行（row_valid），深度 1024 覆盖约 32 轮完整扫描
create_debug_core u_ila_scan ila
set_property C_DATA_DEPTH 1024 [get_debug_cores u_ila_scan]
set_property C_EN_STRG_QUAL true [get_debug_cores u_ila_scan]
set_property C_INPUT_PIPE_STAGES 0 [get_debug_cores u_ila_scan]
set_property ALL_PROBE_SAME_MU true [get_debug_cores u_ila_scan]
set_property ALL_PROBE_SAME_MU_CNT 2 [get_debug_cores u_ila_scan]
connect_debug_port u_ila_scan/clk [get_nets sys_clk_IBUF_BUFG]

# 探针顺序即 CSV 列顺序，plot_mos_scan.py 按列名识别，不依赖顺序
set probe_index 0
foreach {signal width} {
    point 5
    vg_code 12
    row_ch0 16 row_ch1 16 row_ch2 16 row_ch3 16
    row_ch4 16 row_ch5 16 row_ch6 16 row_ch7 16
    row_valid 1
    scan_count 8
    adc_index 3
    adc_valid 1
    init_done 1 init_error 1 dac_ready 1 dac_error 1
} {
    if {$probe_index > 0} {create_debug_port u_ila_scan probe}
    set port u_ila_scan/probe$probe_index
    set_property port_width $width [get_debug_ports $port]
    set_property PROBE_TYPE DATA_AND_TRIGGER [get_debug_ports $port]
    set signal_nets {}
    if {$width == 1} {
        set signal_nets [get_nets $signal]
    } else {
        for {set bit 0} {$bit < $width} {incr bit} {
            lappend signal_nets [get_nets [format {%s[%d]} $signal $bit]]
        }
    }
    if {[llength $signal_nets] != $width} {error "Missing debug net: $signal"}
    connect_debug_port $port $signal_nets
    incr probe_index
}
set_property C_CLK_INPUT_FREQ_HZ 50000000 [get_debug_cores dbg_hub]
connect_debug_port dbg_hub/clk [get_nets sys_clk_IBUF_BUFG]

opt_design
place_design
route_design
report_timing_summary -file timing_summary.rpt
report_drc -file drc.rpt
write_checkpoint -force mos_scan_routed.dcp
write_debug_probes -force mos_scan.ltx
write_bitstream -force mos_scan.bit
