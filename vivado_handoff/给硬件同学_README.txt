AX7020 + ADS8688 + MCP4725 硬件交接包
============================================================

先看这份文件，再看：
1. 工程资料说明.txt       总体说明、信号解释、DPS 状态
2. 信号引脚表.csv         可直接导入表格的信号—引脚清单
3. EDA硬件核对清单.txt    原理图/PCB 设计和上电检查项目
4. constr/dac_adc_loopback.xdc
5. project/dac_adc_loopback.xpr

当前已验证的功能是：MCP4725 通过 I2C 输出慢速三角波，ADS8688 通过 SPI
采集 CH0/AIN0，FPGA 通过 ILA 观察 ADC 数据。该回环已经在实物上观察到
随 DAC 输出下降和上升的 ADC 波形。

当前工程的真实边界：
- ADS8688 DAISY 没有接 FPGA，而是模块端直接接 GND。
- DPS 电源模块的 USB/串口型号、协议、电平和接口针脚尚未提供，因此没有
  虚构 FPGA 封装引脚；预留信号和待确认项见“接口预留与风险说明.txt”。
- OPA192、两颗 INA240、MOS 管偏置及电流采样模拟前端尚未并入本次已验证的
  Vivado 顶层；它们的模拟网络需要硬件同学按最终原理图另行确认。

工程打开方式：
直接打开 project/dac_adc_loopback.xpr（Vivado 2022.2，器件 xc7z020clg400-2）。
若只需下载，使用 program/dac_adc_loopback.bit 和同目录 .ltx。
若需重新生成，回到本文件夹的上一级目录，在 Vivado Tcl Console 执行：
source vivado_handoff/create_project.tcl

请不要把 program 中的 bit 和 ltx 与其他版本混用。DPS 接口确定后，应先更新
RTL 顶层端口、信号引脚表、XDC 和本说明，再重新综合布局布线和生成 bit/ltx。

PCB 到货前的台架联调文件：
阶段C_无PCB台架联调步骤.txt       逐步接线、上电和判定顺序
通道映射记录.csv                  记录 J16/模拟输入到 ADS8688 AIN0~AIN7 的实测结果
program/mos_adc_monitor.bit/.ltx  多通道监视版本，保留 adc_ch0~adc_ch7

多通道版本仍然只驱动 MCP4725 低压三角波，不控制 DPS，不连接 MOS 功率回路。
先完成 OPA192 电源、DAC 到 OPA192、ADS8688 通道映射和 INA240 小信号测试，
再把实测通道和量程写回最终 MOS 扫描工程。
