# AX7020 MOS 测试平台

## 2026-11-02 交付状态

真实 PCB1 实测和离线演示已经完成：

- `output/pcb1/fixed_vgs_20261102/family_20261102_173244/analysis/`：4 条固定 VGS 输出曲线，3,584 个有效行。
- `output/pcb1/transfer/run_20261102_222410_092311/`：9 点恒 VDS 转移曲线，VDS 保持在 0.5 V ± 15 mV。
- `output/pcb1/dynamic/run_20261102_215847_036499/`：1、5、10 Hz 动态采集，每档 8,192 组，共 24,576 组有效行；每轮 DPS 输出均有 OFF 回读。
- `demo/index.html`：无需网络即可打开的交互式演示页面；`demo/mos_data_replay.mp4` 是由真实采样生成的数据回放素材。
- `demo/data/experiment_analysis.json`：重新读取原始 CSV 后生成的分析结果，包含经验模型、留一验证、动态周期/占空比和转移曲线 gm 趋势。
- `demo/data/intelligent_analysis.json`：基于真实分析结果生成的 TinyMLP 探索性回归、器件画像和残差驱动的下一采样点建议；不参与硬件数据验收。
- `demo/data/engineering_report.json`：从已交付 bit/LTX、综合日志和 timing report 提取的 FPGA 工程指标，用于说明平台适用度和实现证据。
- [初赛创新点与视频策略_20261103.md](初赛创新点与视频策略_20261103.md)：按竞赛通知的创新性、科学性、工程可行性、设计难度和 FPGA 适用度整理的初赛主线、加分项与三分钟视频结构。

快速打开演示：在文件管理器中双击 `demo/index.html`。更新数据后运行：

```powershell
python scripts/analyze_experiments.py
python scripts/intelligent_analysis.py
python scripts/build_engineering_report.py
python scripts/build_demo_bundle.py
```

演示中的电流使用 INA240 20 V/V 和 0.1 Ω 分流器的名义系数，并用 DPS OFF 基线扣除零点；精密电压/电流标定尚未完成。Vth 仅是有限 VDS、有限栅压范围下的趋势代理，动态频率是整机采样系统响应，不代表 MOS 本征开关速度。实物视频请按[视频拍摄分镜_20261102.md](视频拍摄分镜_20261102.md)拍摄，软件回放不能替代实拍。

使用 AX7020、ADS8688、MCP4725、OPA192、INA240 和可控漏极电源采集 MOS 管的 VGS、VDS、ID。
交付形式为演示视频和 GitHub 源代码。验收未限定控制必须运行在 FPGA 内，当前按电脑程序统一调度 FPGA 与电源推进。
厂家 Riden 上位机软件不是项目运行依赖；USB 通信板的驱动和实际设备连接仍然需要工作。

## 当前状态

- 20:48已实机完成只读寄存器对照，通道使能/掉电/输出格式/8路量程均匹配。该诊断文件和约301秒 ILA 观察作为历史排查证据保留；当前交付采集使用统一实验镜像 `output/mos_experiment/mos_experiment.bit/.ltx`。详细流程见[ADC故障排查_20261102.md](ADC故障排查_20261102.md)。
- 2026-11-02 20:13 已抓到诊断镜像运行中全FFFF，并实证仅复位 ADC、重新初始化即可恢复；该证据和根因未隔离的限制保留在[ADC故障排查_20261102.md](ADC故障排查_20261102.md)。后续实测对坏行直接拒收，必要时在 DPS OFF 下重新初始化。
- 2026-11-02 DM40A首个人工VG参考已配对保存：用户读数204.65 mV，前后ADC名义均值194.579 mV，ADC−DMM≈−10.071 mV；量程未提供。第二个DAC2560点三次复采全FFFF，包含用户要求完整重新编译下载后的第三次；2.0533 V读数均保留但未配对。`reference_20261102_190857_329719` 已失败，当前暂停标定。故障现场DONE/INIT_B/EOS=1、CRC_ERROR=0且ILA计数变化，说明FPGA程序在运行；重新下载后约97秒的384行有效不能证明根治。用户确认模块采用5 V供电，未提供精确实测数值。现加入独立ADC复位、SPI波形和连续FFFF锁存诊断，DPS保持关闭。每次采集独立检查物理配置及ADC原码。证据见`output/pcb1/manual_calibration/`和`output/pcb1/adc_fault_diagnostic/`；未应用校准系数。
- 2026-11-02 已扩展为4条真实固定栅压输出曲线：源压扣零后VGS约1.941/2.044/2.146/2.248 V，各7点×128行，共3584个有效行；最大名义电流约0.112/0.359/0.934/2.156 mA。新增档位完成电脑自动下载、DPS OFF零点、逐点带电采集及关断回读。合并图、CSV、报告见[多栅压输出特性实测_20261102.md](output/pcb1/fixed_vgs_20261102/family_20261102_173244/多栅压输出特性实测_20261102.md)。结束恢复低栅压时曾出现ADC全FFFF，DPS保持关闭并重新初始化后复核128行有效、VG≈0.19466 V。DM40A 的 USB 仅用于拷贝文件与固件升级，人工输入参考流程见[标定与动态下一步_20261102.md](标定与动态下一步_20261102.md)；后续恒 VDS、动态和演示结果见 README 顶部交付状态。
- 2026-11-02 已完成真实PCB的1/2/3 V自动栅压扫描，各32点、每点8次重复，采集后DPS输出均回读关闭。随后用 DAC 码2560（实测固定 VGS≈2.057 V）完成0.20～3.00 V七个漏极电压点的固定栅压输出曲线，每点128行、DPS逐点回读关闭；结果见`output/pcb1/fixed_vgs_20261102/`及[固定栅压输出特性实测结果_20261102.md](output/pcb1/fixed_vgs_20261102/固定栅压输出特性实测结果_20261102.md)。途中用户发现OPA负电源掉线；异常栅压数据已排除，ADC出现全FFFF后重新初始化并复测通过。最新接线见[当前PCB自动扫描接线_20261102.md](当前PCB自动扫描接线_20261102.md)。当前数据仍使用名义增益/分流电阻，精密标定限制见 README 顶部交付状态。
- 新Q1基本复测：截止VDS=1.003 V，接回漏极采样后用户确认正常；固定栅压VGS=3.248 V时VDS=3.25 mV、DPS显示约1 mA。旧Q1异常的根因没有单独确认。以下2026-11-01条目保留为历史记录。

- 已验证 ADC/DAC 回环、OPA192 单路逐次采集，以及 INA240 约 5 mA/50 mA 的基本正向响应。
- 历史 `mos_scan` 是固定自运行阶梯扫描；当前统一 `mos_experiment` 镜像支持主机设定 DAC 低/高码、频率和 ILA 采集，真实动态数据见本 README 顶部交付状态。
- DPS 由第二台 IT6302 提供 12 V，面板显示输入约 11.97 V；用户确认已设置 0.00 V、0.020 A、开机默认输出关闭。
- 2026-11-01 已识别 DPS USB 通信板为 CH340（COM3），并按 9600 波特率、地址 1 成功只读回型号 3005、输入 11.98 V、输出关闭；记录见 `output/dps/status_20261101_com3.json`。
- 用户确认初始限流确为 0.000 A；已由自有程序改为 0.020 A，并在输出关闭时回读验证。随后完成 1.00 V 空载定时输出，期间设备回报 1.00 V/0.000 A、无保护，结束后回报关闭和 0.00 V。20秒测试的用户万用表读数为开启1.0034 V、关闭后−0.08 mV，空载基本响应通过，非精度校准；见 `output/dps/meter_observations_20261101.json`。
- 已完成100.50Ω负载的CV/CC基本响应：1V设定时电阻两端0.9790V（推算9.74mA）；3V/20mA设定时进入CC，电阻两端2.23V（推算22.19mA）。20mA设定不能视为精确保护阈值。
- 实机软件中断后关闭已验证；USB断连、电脑断电、强制终止及独立保护仍待验证。
- 已接入实物`2N7000 JCAZW`，串联100.50Ω漏极电阻、G/S短接，完成1.00V/20mA的基本截止检查：万用表VDS=1.003V，DPS回报1.00V/0.000A，结束回读输出关闭。此结果不代表漏电流精度；沟道导通及真实曲线仍待验证。记录见`output/mos_scan/mos_bench_setup_20261101.json`。
- 用户确认PCB已到货，最终工程及实物图待核对。当前固定栅压台架完整接线见[当前台架完整接线_20261101.md](当前台架完整接线_20261101.md)；旧`当前接线说明.txt`保留的是历史回环配置。
- 用户已提供最终工程`ProDoc_mos管特性测试曲线平台_2026-11-01.epro2`和`ProDoc_PCB1_2026-11-01.epro2`。已解析确认Q1网络为1=VS、2=VG、3=VD，板上R1/R2/R3分别为1k漏极、1k栅极、100k栅极下拉；J10为漏极电源，J14为INA240 IN+/IN−，J16为ADC_ID/VG/VD/VS。详见`output/pcb1/ProDoc_PCB1工程核对_20261101.md`。
- MOS 静态特性、动态波形及完整自动流程尚未完成，不能将模块回环结果视为整机验收结果。

## 自有 Python 工具

在项目根目录安装依赖：

```powershell
python -m pip install -r requirements.txt
```

列出串口，不打开任何设备：

```powershell
python scripts/dps_status.py ports
```

确认实际 DPS 端口后，读取型号、设置值、输入/输出电压和输出状态。2026-11-01 实测端口为 `COM3`；重新插接后应先枚举确认：

```powershell
python scripts/dps_status.py status --port COM3 --baud 9600 --address 1 --output output/dps/status.json
```

该工具仅实现 Modbus `0x03` 读取，不开启输出、不修改设定，不自动探测其他串口。返回报文须通过地址、功能码、长度及 CRC 检查；型号寄存器必须为 3005 才换算数值。
寄存器地址和名义比例参考 [libsigrok 的公开 DPS 驱动](https://github.com/sigrokproject/libsigrok/tree/master/src/hardware/rdtech-dps)，仍须与这台实物的面板和配套协议核对。
单元测试中的数据均为合成报文，不能作为硬件通信已通过的证据。

```powershell
python -m unittest discover -s tests -p test_dps_status.py -v
```

## 电源台架控制

`scripts/dps_control.py` 提供参数设定、关闭和有限时长输出，当前限制为 0~5 V、0~50 mA。配置时先关闭输出再设置参数；写响应和寄存器回读均需通过校验。只有 `pulse` 会开启输出，持续时间为软件目标时长，实际结束还包含串口事务延迟，不能用于精确定时激励。

保持输出关闭，设定 0.00 V、20 mA：

```powershell
python scripts/dps_control.py configure --port COM3 --voltage 0.00 --current-limit 0.020 --output output/dps/configure.json
```

确认输出端空载或连接了本轮测试负载后，进行约 5 秒的 1 V 输出，并在结束后关闭：

```powershell
python scripts/dps_control.py pulse --port COM3 --voltage 1.00 --current-limit 0.020 --seconds 5 --output output/dps/pulse.json
```

立即发送关闭命令并回读：

```powershell
python scripts/dps_control.py off --port COM3 --output output/dps/off.json
```

每次操作保存开始、过程和结束状态，失败记录包含错误及关闭尝试。通信异常或 Ctrl+C 时程序尝试关闭；电脑断电、进程被强制终止或 USB 断开时，软件不能保证关断，实际保护仍需独立验证。证据文件应使用不同文件名以保留各轮测试。

已保存的实机记录：`output/dps/configure_20261101_000V_020mA.json`、`output/dps/pulse_20261101_100V_020mA_5s.json`。协议和故障路径的合成报文测试：

```powershell
python -m unittest discover -s tests -p "test_dps*.py" -v
```

## FPGA 采集与现有绘图

匹配的 `output/mos_scan/mos_scan.bit` 和 `.ltx` 下载后，在 Vivado Tcl Console 执行：

```tcl
source scripts/capture_mos_scan.tcl
```

生成真实 CSV/ILA 后，回环检查可运行：

```powershell
python scripts/plot_mos_scan.py --loopback --all
```

该命令展示模块回环。脚本默认 `--profile bench` 保留历史台架映射。最终 PCB 必须显式选 `--profile pcb1`，对应 VG/VD/VS/ID=CH0/CH1/CH2/CH7；电压换算仍匹配现有 `mos_scan` 固件，因此 CH1 的漏压量程是 0～5.12 V。本阶段仅用于1 V等低压验证。

同一供电下，先在DPS输出关闭时抓取零电流CSV，再采带电数据；使用实际文件名运行：

```powershell
python scripts/plot_mos_scan.py <loaded.csv> --profile pcb1 --zero-csv <zero.csv> --zero-by-point --all
```

`--zero-csv` 所指文件必须确实来自用户确认的零电流状态；文件内容本身不能证明DPS关闭。PCB配置要求显式传入新零点，不能继续套用更换供电前的固定零点。换算使用名义INA增益/分流电阻，尚不代表整机精度。由于板上R1串联限流，扫描VGS时VDS也变化，图标为栅压扫描路径，不称为固定VDS转移特性或固定VGS输出特性。
`--zero-by-point` 按相同point及DAC码扣除INA均值，拒绝缺失/不匹配的零点；不加该选项仍使用单一全局均值。逐点CSV保留INA原始输出、使用的零点及扣零方法，VG/VD/VS未作绝对电压校准。
Vivado 仍用于配置和读取 FPGA，厂家电源软件可以省去。

确认使用上述自动扫描接线、模拟电源稳定、DPS端口正确、FPGA已Program后，可运行真实硬件单轮采集：

```powershell
python scripts/capture_pcb1_powered.py --port COM3 --zero-csv <zero.csv> --voltage 1
```

仅提供1/2/3 V三档，20 mA限流，每轮256行，25秒软件目标窗口，结束尝试关闭并回读。程序检查零点和带电数据的实际栅压端点、阶梯步长及相互偏差；初始化/I2C标志通过不等于模拟信号有效。电脑/USB故障时的独立关断保护仍待验证。

多轮合并图及重复性统计使用：

```powershell
python -X utf8 scripts/analyze_pcb1_sweeps.py --report <report1.json> <report2.json> --zero-csv <zero_before.csv> <zero_after.csv> --out-dir <analysis_dir>
```

每轮选择时间最近的所提供零点，按栅压点扣零；漏压差/R1仅作交叉估算。图中误差棒是重复采样均值的标准误差，不含系统误差，不能当作整机精度指标。

固定栅压输出特性模式：`scripts/build_mos_fixed_vgs.tcl` 通过 Vivado generic 设置 `POINTS=1`、`CODE_STEP=0`，保留 ADS8688 初始化、8 次平均和 ILA 行格式，只把 MCP4725 固定在指定 DAC 码。已生成 `output/mos_fixed_vgs/code_0256/` 和 `code_2560/`；其中 code 2560 前一轮实测约对应 VG=2.04 V。构建不会自动下载到 AX7020；手动 Program 对应目录内的 `.bit` 与 `.ltx` 后，使用 `scripts/capture_mos_fixed_vgs.tcl` 抓取连续 ADC 行，再由 DPS 控制程序逐级改变 VDS。

固定栅压模式的操作和验收要求见[固定栅压输出特性下一步_20261102.md](固定栅压输出特性下一步_20261102.md)。

已补充固定栅压输出特性自动采集器 `scripts/capture_fixed_vgs_output.py`。它要求先用 DPS 输出关闭状态抓取零电流 CSV，然后按 0.20、0.50、1.00、1.50、2.00、2.50、3.00 V 逐点设置 DPS；每点验证输出、保护状态和设定值，启动固定 VGS ILA 采集，采集完成后立即关闭并回读 DPS。示例：

```powershell
python scripts/capture_fixed_vgs_output.py --port COM3 --dac-code 2560 `
  --zero-csv output/pcb1/fixed_vgs_20261102/zero_code2560.csv
python scripts/analyze_fixed_vgs.py `
  output/pcb1/fixed_vgs_20261102/run_<timestamp>/fixed_vgs_output_report.json
```

脚本默认每个电压点保存 128 行；`capture_mos_fixed_vgs.tcl` 同时传入深度和 LTX 时会正确使用指定深度。分析结果中的 ID 仍使用名义 INA 增益/分流电阻和匹配的 DPS OFF 零点，不能当作精密标定结果。

## 后续交付工作

实测、分析和离线演示已完成；实物镜头按[视频拍摄分镜_20261102.md](视频拍摄分镜_20261102.md)拍摄即可。精密电压/电流标定和独立硬件关断保护仍属于后续增强项。
构建所需10份RTL/XDC已从实际使用的相邻历史目录原样归入本项目`rtl/`和`constr/`，SHA256记录在`output/source_collection_20261102.json`。构建与仿真脚本改为读取项目内源文件；ADS8688 SPI、MCP4725 I2C/波形/回环及mos_scan仿真均通过，41项Python测试通过。批处理环境缺少`PROCESSOR_ARCHITECTURE`时需设为`AMD64`；新的自动采集器已处理该变量。
公开仓库：[wdzz8/ads8688-mos-test-platform](https://github.com/wdzz8/ads8688-mos-test-platform)。

后续实测顺序见[标定与动态下一步_20261102.md](标定与动态下一步_20261102.md)。多栅压自动采集命令为`python scripts/run_fixed_vgs_family.py --port COM3 --codes 2432 2688 2816 --build-missing`，会操作真实硬件；浏览已有结果无需重新采集。合并分析使用`python scripts/analyze_fixed_vgs_family.py <report1.json> <report2.json> ... --out-dir <analysis_dir>`。`scripts/intelligent_analysis.py` 会对已完成的真实 CSV 分析结果运行一个固定种子的 2-8-1 TinyMLP，并用留一误差和局部残差给出下一轮 VDS 加密建议；建议点必须重新实测，不能直接写成测量结果。当前采集器限制为漏极电源不超过3 V、限流不超过20 mA、每点128行；报告保留实际关闭回读，不能用软件目标窗口代替独立硬件关断保护。
