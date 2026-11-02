# ADS8688 调试

## 供电与接线

以下针脚按用户提供的康威 ADS8688 V0.2 原理图和 AX7020 手册核对。
模块 P1-10 为 AVDD，应供 5V；模块上的 RT9193-3.3V 将其转换为 DVDD=3.3V，SPI 可以连接 AX7020 的 LVCMOS33 接口。
3.3V 直接给 AVDD 供电不满足 ADS8688 的 4.75~5.25V 工作范围，读数不能用于判断正常采集。

- 模块 P1-10（AVDD）接 AX7020 J11-2（5V）。
- 模块 P1-4/6/8（GND）任一脚接 AX7020 J11-1（GND）。
- 模块 P1-2（CS）接 AX7020 J11-3（F17）。
- 模块 P1-5（CLK）接 AX7020 J11-4（F16）。
- 模块 P1-3（SDI）接 AX7020 J11-5（F20）。
- 模块 P1-7（SDO）接 AX7020 J11-6（F19）。
- 模块 P1-1（RST）接 AX7020 J11-7（G20）。
- 模块 P1-9（DAISY）单片使用时保持低电平，原理图已有 10k 下拉。

请按针脚编号核对，模块 P1 与开发板 J11 不能直接按相同编号一对一连接。
可用万用表确认模块 U1 输出或 ADS8688 的 DVDD 对地约为 3.3V，REFCAP 约为 4.096V。

## 已修正的逻辑

Vivado 工程引用的是相邻 `ads8688_spi/rtl` 目录中的 RTL。

- 寄存器写帧从 16 个时钟改为 24 个时钟，最后 8 个时钟接收写回读；依据 TI SBAS582C 第 46 页 8.5.2.1。
- 在最后一个 SCLK 下降沿完成后，等待一个 50MHz 系统时钟周期（20ns）再拉高 CS，满足最小 10ns 保持时间。
- 接收数据的高电平中点采样保留。芯片在第 16 个下降沿输出 MSB，主机在第 17~32 个高电平采集 16 位数据。
- 修正首帧 CH0 被标记为 CH1 的通道编号偏移。
- 增加 `init_done`、`init_error`、`reg_readback`；`init_error` 对寄存器回读不匹配保持置位。
- LED3 改为初始化完成且全部寄存器回读匹配时点亮。
- ILA 深度改为 4096，采样时钟 50MHz，可以覆盖完整的 32us SPI 帧。
- ILA probe6 直接连接 SDO 输入缓冲器输出，不依赖综合生成的临时网络名称；最终 LTX 中名称可能显示为 `p_3_in`。

`init_done=1` 只表示初始化帧已发送完成；必须同时检查 `init_error=0`。
初始化检查通过也不能代替已知输入电压的模拟采集验证。

## 下载与观察

已生成文件位于 `output/ads8688_debug`：

- `ads8688_led_confirm.bit`：增加灯光下载确认状态的 bitstream。
- `ads8688_led_confirm.ltx`：对应的 ILA 探针文件，必须与上述 bitstream 配套。

在 Vivado Hardware Manager 中将 Program File 和 Debug Probes File 分别选为上述文件，再下载。
工程原来 `ads8688_1.runs/impl_1` 中的 bitstream 未替换。

本次灯光下载确认状态：LED1 和 LED2 每 0.25 秒交替点亮，LED4 常亮；即使 ADS8688 未接，这组灯光也会运行。
LED3 仍表示初始化寄存器回读通过。确认灯光仅证明 FPGA 运行了此版程序，不代表 ADC 通信或采集成功。
此前的 `ads8688_led_test.bit/.ltx` 仍是旧灯光版本，下载时请选择带 `led_confirm` 的文件。

1. 使用 5V 给模块供电，确认共地与上述信号接线。
2. 将模块 AIN0（P2-4）接地；使用 `ch_valid=1` 且 `ch_index=0` 的样本观察该通道。
3. 检查 `init_done=1`、`init_error=0`，此时 LED3 应亮。
4. 波形检查用 `adc_cs_n_OBUF` 的下降沿作为触发，采样窗口设为 4096，触发位置约 128；probe6 是 SDO。
5. 采样值检查用 `ch_valid=1` 作为触发，并按 `ch_index` 区分通道，避免混入其他悬空输入。

模块 AIN0~7 的两个 1k 电阻分别串在 AIN_xP 和 AIN_xGND，电容跨接在这两个输入之间，属于输入滤波电路，不是 1:1 分压。
按内部 4.096V 基准和当前芯片 ±10.24V 量程，忽略较小的输入负载及测量误差：

- 模块输入 0V：约 `0x8000`。
- 模块输入 3.3V：约 `0xA940`，实际会有电阻、基准和测量误差。
- 模块端电压约为 `(raw - 32768) * 0.3125mV`，计算时先将 raw 扩展为有符号整数，避免无符号下溢。
- AX7020 J11-39 和 J11-40 均为 3.3V 电源，可用作已知输入测试；模块 AVDD 仍需保持 5V。

此前说明中的 `0x94A0` 和 `0.625mV` 来自把滤波电阻误判为分压电阻，已修正；采集逻辑无需因此重新下载。

若仍是 `FFFF`，先看 `init_error` 和 CS 低时的 SDO：

- `init_error=1`：寄存器通信未通过，检查模块 DVDD、RST 是否保持高、实际 CS/CLK/SDI/SDO 接线及波形。
- SDO 在 CS 低的整个帧内持续高：优先检查 SDO 连通性、CS 是否到达模块、排针方向和模块数字电源。正常帧开头 SDO 应为低。
- `init_error=0` 且 SDO 有实际串行数据：再检查所选通道、输入接线、REFCAP 电压和模拟输入电路。

## 验证与重建

### CH0 单通道测试版

`output/ads8688_debug/ads8688_ch0_test.bit` 和同名 `.ltx` 是单独生成的诊断版。
这一版使用 `MAN_CH0=0xC000` 固定采样 CH0，`ch_index` 始终为 0，SPI 时钟仍为 1MHz。
LED1/LED2 交替、LED4 常亮、LED3 初始化检查的状态与确认版相同。

下载这一对文件后，将模块 AIN0（P2-4）接模块 GND，ILA 用 `ch_valid=1` 触发，读取触发点的 `ch_data`。
在相同通道和输入条件下比较多次捕获，接地应接近 `8000`；接模块端 3.3V 应接近 `A940`。
几个计数的变化可属于噪声，数千计数的变化需要继续检查供电、基准和 SPI 波形。
若用此版仍大幅变化，记录 `init_error` 和接地时读数的最小/最大值，再测模块 DVDD、REFCAP 对地电压。

已检查用户保存的 CH0 单通道 ILA 捕获：接地时有效值为 `7FD9`（名义换算约 -12.19mV）；接 J11-39 时有效值为 `A92B`（约 3.29344V），相邻读数 `A92C` 仅差 1 个计数。
两次捕获均为 `ch_index=0`、`init_done=1`、`init_error=0`。这说明 CH0 能响应已知输入变化；精度、长期稳定性以及其余通道仍需单独验证，不能仅凭这两个输入点确认。

Vivado 的 Set Up Debug 向导可能把采样深度重新设成 1024；50MHz 采样下 1024 点只有 20.48us，覆盖不了 32us 完整帧。
当前约束已设为 4096，调试时应配套使用本次生成的 `.ltx`，信号按名称识别。

```powershell
& 'D:\FPGAvivado\Vivado\2022.2\bin\vivado.bat' -mode batch -nojournal -nolog -source scripts\build_debug.tcl -tclargs ch0
```

### 自动扫描版

仿真覆盖正常回传、SDO 恒高、SDO 恒低和单次错误回读，并检查初始化命令、完整时钟数、CS 保持时间、16 次采样及通道回绕。
还覆盖固定 CH0 的手动命令、连续 CH0 样本和手动模式回读错误检测。
仿真成功不代表已在实物上验证。

```powershell
& .\scripts\run_spi_sim.ps1
& 'D:\FPGAvivado\Vivado\2022.2\bin\vivado.bat' -mode batch -nojournal -nolog -source scripts\build_debug.tcl
```

本次布局布线的已定义时序约束通过；SPI 外部输入/输出延时约束仍需在实际板级时序设计中完善。
DRC 无错误，包含 Xilinx 调试核和纯 PL 设计未实例化 PS7 的警告。

## MCP4725 I2C 波形测试版

已增加独立的 `mcp4725_wave_test` 顶层。修正后的驱动使用 100kHz I2C Fast Write 向 MCP4725 的易失 DAC 寄存器写入三角波码值：0、64、128 ... 4032、4095，再反向返回，更新频率为 100Hz，完整三角波周期约 1.28s。

测试版文件：

- `output/mcp4725_debug/mcp4725_wave_test.bit` 为旧版，命令格式有误，不能用于本次测试。请下载下文的 ADC/DAC 合并版。

AX7020 接线（与 ADS8688 的 J11-3~7 不冲突）：

- MCP4725 VDD 接 3.3V，VSS 接 GND；MCP4725 A0 接 GND，默认 I2C 地址为 `0x60`。
- MCP4725 SCL 接 AX7020 J11-9（H18），SDA 接 J11-10（J18）。
- SDA、SCL 各接一个外部上拉电阻到 3.3V，推荐 2.2k~4.7k；FPGA 端是开漏输出，不能把 SDA 直接推高。
- MCP4725 VOUT 可先接万用表或示波器；若同时验证 ADS8688，将 VOUT 接 ADS8688 AIN0（P2-4），两块板共地，ADS8688 模块 AVDD 仍接 5V。

下载与验收：

1. 先断开 MCP4725 VOUT 与 MOS 偏置电路，只连接 DAC、I2C、3.3V 和 GND。
2. 用 `mcp4725_wave_test.bit` 对 FPGA 编程；LED1/LED2 应交替闪烁，LED4 常亮；LED3 正常时熄灭，亮起表示 I2C 未检测到 ACK。
3. 修正后的驱动中，示波器观察 SCL 应为约 100kHz；一次写入依次发送地址字节 `0xC0`、`0000+D11..D8` 和 `D7..D0`，每字节后检查 ACK。
4. 测量 VOUT，应在 0V 到接近 VDD 之间缓慢上升再下降。理论值为 `VOUT = VDD * DAC_code / 4096`。
5. 如果 LED3 熄灭且 VOUT 不变化，优先检查 MCP4725 的 A0 地址、SDA/SCL 上拉、J11 针脚方向和共地。

当前 I2C 驱动只写易失 DAC 寄存器，不写 EEPROM，避免频繁扫描损耗 EEPROM；后续接入 MOS 测试平台时可复用该驱动，分别控制 VGS 和 VDS 的两颗 MCP4725。

## MCP4725 输出与 ADS8688 采集联合测试

合并顶层 `dac_adc_loopback` 使用修正后的 DAC 驱动，同时沿用已验证的 ADS8688 CH0 单通道采集逻辑。原 ADC 工程与其调试约束未替换。

1. ADS8688 保持 5V 供电，MCP4725 保持 3.3V 供电，全部共地；ADC SPI 与 DAC I2C 接线保持上述配置。
2. 断开 AIN0 原来的 GND 或 3.3V 测试线，将 MCP4725 VOUT 接 ADS8688 AIN0（P2-4），暂不连接 MOS 偏置电路。
3. 在 Hardware Manager 的 Program Device 对话框中，Program File 选择 `output/dac_adc_loopback/dac_adc_loopback.bit`，Debug Probes File 选择同目录的 `dac_adc_loopback.ltx`，两者必须配套。
4. 下载后 LED1/LED2 交替、LED4 常亮；这一合并版 LED3 常亮表示 ADC 初始化通过且 DAC 收到 ACK，并且没有检测到通信错误。
5. 在 Vivado 的 Tcl Console 执行以下命令。它设置触发和存储条件，然后捕获 4096 点，正常情况下约需 4.1 秒。若未收到 DAC ACK，捕获不会开始，脚本最多等待 15 秒。

```tcl
source scripts/capture_loopback.tcl
```

6. 将 `ch_data` 的 Radix 设为 Unsigned、Waveform Style 设为 Analog，并缩放到整个捕获窗口。应看到约三个完整三角波，理论码值从 `0x8000` 上升至接近 `0xA940`，再下降，周期约 1.28 秒。实际端点受 VDD、偏移和增益误差影响。
7. `dac_applied` 是 DAC 已确认接收的设定值；`ch_data` 才是 ADC 实测值。检查 `init_done=1`、`init_error=0`、`dac_ready=1`、`dac_error=0`。若实测仍平直，先检查 VOUT 到 AIN0 的连线并用万用表确认 VOUT 是否变化。

ILA 仍运行于 50MHz，但仅在 `capture_tick=1` 时存储，每个保存点相隔 1ms。以 `sample_ms` 的差值计算实际时间，不要将界面按 50MHz 时钟标出的横轴时间当成信号周期。每个保存点记录最近一次完成的 ADC 数据；DAC 切换附近可能有不到一次 ADC 采集周期的延迟。

仿真已覆盖正确的 Fast Write 数据格式、100kHz SCL、各字节 NACK 后终止、ACK 恢复、完整三角波顺序与 10ms 更新间隔。合并版已生成 bit/ltx，已定义的时序约束通过；外部接口延时约束仍未完善，实物波形需按上述步骤验证。

```powershell
& .\scripts\run_mcp4725_sim.ps1
& 'D:\FPGAvivado\Vivado\2022.2\bin\vivado.bat' -mode batch -nojournal -nolog -source scripts\build_loopback.tcl
```
