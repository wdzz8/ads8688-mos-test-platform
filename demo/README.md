# 离线演示包

直接打开 `index.html` 可以离线查看真实 PCB1 历史测试结果。

需要实时监视新采集时，在项目根目录单独开一个 PowerShell 窗口运行 `python scripts/live_demo_server.py`，浏览器打开 `http://127.0.0.1:8765/demo/index.html`。再从另一个 PowerShell 窗口按实验流程启动恒 VDS 或动态采集，并点击“实时实测”页。页面每秒读取最新报告；恒 VDS 按每次反馈迭代更新，动态测试在每档 ILA CSV 写入后显示原始 VG/VD、频率和占空比。运行编号、更新时间、原始报告路径、DPS 最近一次回读和失败状态都来自本机生成的报告。该服务只读文件，不控制仪器。按 `Ctrl+C` 可停止服务。

可直接打开 `http://127.0.0.1:8765/demo/index.html?tab=live`。这是采集批次完成后逐点更新的监视页，不是连续流式示波器。页面显示最近报告的年龄；旧报告不会标为正在测量。点击报告路径、每行“打开 ILA CSV”和失败时的 Vivado 日志链接，可检查数值来源。续测会注明继承报告。DPS 显示报告中的最近一次确认状态，不代表服务独立实时查询电源。

页面包含：

- 4 条固定 VGS 输出曲线和经验饱和拟合；
- 0.5 V 恒 VDS 转移曲线、有限差分 gm 和阈值趋势代理；
- 1、5、10 Hz 动态 VG/VD 回放；
- 数据来源、名义电流比例、复现命令和结论边界。

`mos_data_replay.mp4` 是真实采样数据回放视频，适合录屏或答辩演示；实物接线和仪器画面需按根目录分镜文档另行拍摄。

`mos_platform_release_cut_h264.mp4` 是 66 秒、16:9 的 H.264 动态图形预览片，画面由真实 PCB1 分析数据、FPGA 实现报告和工程架构生成，不包含硬件实拍或配乐。对应字幕与旁白稿在 `mos_platform_release_cut.srt`。OpenCV 源版和重新生成命令分别为 `mos_platform_release_cut.mp4` 与 `python scripts/render_release_cut.py`。提交终版前，应补入自己的台架、仪器和板卡实拍，并录制旁白。
