"""Render a restrained, data-grounded product film from experiment results.

This is a motion-graphics cut. It intentionally does not present stock imagery
or a synthetic hardware render as footage of the physical test bench.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "demo/data/experiment_analysis.json"
ENGINEERING_PATH = ROOT / "demo/data/engineering_report.json"
OUTPUT_PATH = ROOT / "demo/mos_platform_release_cut.mp4"
SRT_PATH = ROOT / "demo/mos_platform_release_cut.srt"
WIDTH, HEIGHT, FPS = 1600, 900, 24
FONT_REG = Path("C:/Windows/Fonts/msyh.ttc")
FONT_BOLD = Path("C:/Windows/Fonts/msyhbd.ttc")

BG = "#101718"
BG_2 = "#182323"
PAPER = "#F0F1EC"
INK = "#17211F"
MUTED = "#81908C"
LINE = "#35433F"
ORANGE = "#F08A4B"
MINT = "#7DC9B3"
BLUE = "#6BA6CF"
RED = "#CE786A"
CURVE_COLORS = ["#6BA6CF", "#7DC9B3", "#F08A4B", "#CE786A"]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold and FONT_BOLD.exists() else FONT_REG
    return ImageFont.truetype(str(path), size)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def ease(value: float) -> float:
    value = clamp01(value)
    return value * value * (3 - 2 * value)


def rgba(hex_color: str, alpha: int) -> tuple[int, int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


class Film:
    def __init__(self, data: dict, engineering: dict):
        self.data = data
        self.engineering = engineering
        self.image = Image.new("RGB", (WIDTH, HEIGHT), BG)
        self.draw = ImageDraw.Draw(self.image)
        self.writer = cv2.VideoWriter(
            str(OUTPUT_PATH), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT)
        )
        if not self.writer.isOpened():
            raise RuntimeError("OpenCV could not open the MP4 writer")
        self.frames = 0

    def base(self, section: str, progress: float, light: bool = False) -> None:
        background = PAPER if light else BG
        self.image = Image.new("RGB", (WIDTH, HEIGHT), background)
        self.draw = ImageDraw.Draw(self.image)
        ink = INK if light else "#E9ECE7"
        muted = "#64706C" if light else MUTED
        line = "#C8D0CA" if light else LINE
        self.draw.text((110, 52), "AX7020   /   MOS CHARACTERIZATION", font=font(18, True), fill=ink)
        self.draw.text((1185, 55), section, font=font(16), fill=muted)
        self.draw.line((110, 94, 1490, 94), fill=line, width=1)
        self.draw.line((110, 94, int(110 + 1380 * clamp01(progress)), 94), fill=ORANGE, width=3)
        self.draw.text((110, 842), "真实 PCB1 数据  /  图形化回放", font=font(16), fill=muted)
        self.draw.text((1450, 842), f"{self.frames // FPS:02d}s", font=font(16), fill=muted)

    def label(self, text: str, xy: tuple[int, int], color: str = ORANGE, size: int = 19) -> None:
        self.draw.text(xy, text, font=font(size, True), fill=color)

    def title(self, text: str, xy=(110, 133), size=50, color="#F0F1EC", bold=True) -> None:
        self.draw.text(xy, text, font=font(size, bold), fill=color)

    def body(self, text: str, xy: tuple[int, int], size: int = 22, color="#AAB5B0") -> None:
        self.draw.text(xy, text, font=font(size), fill=color)

    def emit(self, count: int = 1) -> None:
        frame = cv2.cvtColor(np.asarray(self.image), cv2.COLOR_RGB2BGR)
        for _ in range(count):
            self.writer.write(frame)
            self.frames += 1

    def metric(self, x: int, y: int, number: str, caption: str, color: str = "#F0F1EC") -> None:
        self.draw.text((x, y), number, font=font(38, True), fill=color)
        self.draw.text((x, y + 50), caption, font=font(17), fill="#91A09A")

    def opener(self, seconds: int = 5) -> None:
        for i in range(seconds * FPS):
            t = i / (seconds * FPS - 1)
            self.base("01  /  INTRO", t)
            x_end = int(110 + 1380 * ease(t))
            self.draw.line((110, 390, x_end, 390), fill=ORANGE, width=2)
            self.label("FPGA  ·  MEASUREMENT  ·  EVIDENCE", (112, 332), MINT, 17)
            self.title("让每一次测量", (110, 430), 70)
            self.title("都留下证据。", (110, 515), 70, ORANGE)
            self.body("面向功率 MOS 的闭环参数测试平台", (116, 640), 25)
            self.emit()

    def architecture(self, seconds: int = 7) -> None:
        nodes = [
            (125, 340, 360, 470, "上位机", "测试编排 / 数据分析"),
            (455, 340, 700, 470, "AX7020 FPGA", "采集时序 / 质量标记"),
            (795, 340, 1040, 470, "ADS8688", "8 通道顺序采样"),
            (1135, 340, 1475, 470, "原始证据", "ILA CSV / 报告 / 曲线"),
        ]
        for i in range(seconds * FPS):
            t = i / (seconds * FPS - 1)
            self.base("02  /  SIGNAL PATH", t)
            self.label("系统架构", (110, 130))
            self.title("激励、采样与分析，各司其职。", (110, 170), 43)
            self.body("硬件负责确定性采集；上位机负责编排、闭环和可解释分析。", (113, 238), 21)
            pulse = ease(t * 1.35)
            for idx, (x0, y0, x1, y1, head, sub) in enumerate(nodes):
                self.draw.rectangle((x0, y0, x1, y1), outline="#52605B", width=2)
                self.draw.line((x0, y0, x0, y1), fill=CURVE_COLORS[idx], width=4)
                self.draw.text((x0 + 20, y0 + 32), head, font=font(24, True), fill="#F0F1EC")
                self.draw.text((x0 + 20, y0 + 82), sub, font=font(16), fill="#9AA6A0")
                if idx < len(nodes) - 1:
                    sx, ex, cy = x1 + 8, nodes[idx + 1][0] - 12, (y0 + y1) // 2
                    self.draw.line((sx, cy, ex, cy), fill="#52605B", width=2)
                    px = int(sx + (ex - sx) * max(0, min(1, pulse * 1.45 - idx * 0.24)))
                    self.draw.ellipse((px - 6, cy - 6, px + 6, cy + 6), fill=ORANGE)
            # Show the three physical paths as labels, without implying a false netlist.
            self.draw.line((125, 585, 1475, 585), fill="#35433F", width=1)
            self.draw.text((145, 620), "栅压激励", font=font(16, True), fill=ORANGE)
            self.draw.text((145, 654), "MCP4725 + OPA192", font=font(18), fill="#E5EAE5")
            self.draw.text((625, 620), "漏极供电", font=font(16, True), fill=MINT)
            self.draw.text((625, 654), "DPS / Modbus 闭环", font=font(18), fill="#E5EAE5")
            self.draw.text((1100, 620), "源极采样", font=font(16, True), fill=BLUE)
            self.draw.text((1100, 654), "INA240 → ADS8688", font=font(18), fill="#E5EAE5")
            self.metric(130, 710, "50 MHz", "FPGA 目标时钟")
            self.metric(540, 710, "416 µs", "每行 8 通道")
            self.metric(950, 710, "52 µs", "相邻通道间隔")
            self.body("通道按序扫描；时间戳保留通道间偏移。", (1130, 737), 16)
            self.emit()

    @staticmethod
    def chart_map(x: float, y: float, box, bounds) -> tuple[int, int]:
        x0, y0, x1, y1 = box
        xmin, xmax, ymin, ymax = bounds
        return (int(x0 + (x - xmin) / (xmax - xmin) * (x1 - x0)),
                int(y1 - (y - ymin) / (ymax - ymin) * (y1 - y0)))

    def chart_axes(self, box, bounds, xlabel: str, ylabel: str, light=False, xticks=5, yticks=4) -> None:
        x0, y0, x1, y1 = box
        xmin, xmax, ymin, ymax = bounds
        grid = "#D7DDD8" if light else "#2B3935"
        text = "#64706C" if light else "#899791"
        for i in range(xticks + 1):
            val = xmin + (xmax - xmin) * i / xticks
            x, _ = self.chart_map(val, ymin, box, bounds)
            self.draw.line((x, y0, x, y1), fill=grid, width=1)
            self.draw.text((x - 24, y1 + 12), f"{val:.2g}", font=font(14), fill=text)
        for i in range(yticks + 1):
            val = ymin + (ymax - ymin) * i / yticks
            _, y = self.chart_map(xmin, val, box, bounds)
            self.draw.line((x0, y, x1, y), fill=grid, width=1)
            self.draw.text((x0 - 62, y - 10), f"{val:.2g}", font=font(14), fill=text)
        self.draw.text(((x0 + x1) // 2 - 80, y1 + 38), xlabel, font=font(16), fill=text)
        self.draw.text((x0, y0 - 28), ylabel, font=font(16, True), fill=text)

    def output_curves(self, seconds: int = 11) -> None:
        curves = self.data["static"]["curves"]
        all_points = [p for c in curves for p in c["points"]]
        xmax = max(p["VDS_V"] for p in all_points) * 1.04
        ymax = max(p["ID_mA"] for p in all_points) * 1.12
        box, bounds = (240, 300, 1035, 690), (0, xmax, 0, ymax)
        duration = seconds * FPS
        for i in range(duration):
            t = i / (duration - 1)
            self.base("03  /  OUTPUT", t, light=True)
            self.label("固定栅压 · 输出特性", (110, 130), "#B95F30")
            self.title("四档栅压，逐点留下实测轨迹。", (110, 170), 42, INK)
            self.body("圆点：实测  /  虚线：经验模型拟合  /  电流为名义换算值", (114, 238), 19, "#58645F")
            self.chart_axes(box, bounds, "VDS / V", "ID / mA", light=True)
            shown = max(0.03, ease(t * 1.15))
            for cidx, curve in enumerate(curves):
                color = CURVE_COLORS[cidx]
                points = curve["points"]
                n = max(1, min(len(points), int(math.ceil(shown * len(points)))))
                observed = [self.chart_map(p["VDS_V"], p["ID_mA"], box, bounds) for p in points[:n]]
                if len(observed) > 1:
                    self.draw.line(observed, fill=color, width=3, joint="curve")
                for x, y in observed:
                    self.draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color, outline=PAPER, width=2)
                fit = [self.chart_map(p[0], p[1], box, bounds) for p in curve["fit_curve"]]
                visible = max(2, int(len(fit) * shown))
                for j, (a, b) in enumerate(zip(fit[:visible], fit[1:visible])):
                    if j % 2 == 0:
                        self.draw.line((a, b), fill=color, width=2)
                lx = 280 + cidx * 285
                self.draw.line((lx, 760, lx + 32, 760), fill=color, width=4)
                self.draw.text((lx + 42, 746), f"VGS {curve['VGS_V']:.3f} V", font=font(16), fill="#4F5C56")
            self.draw.line((1080, 300, 1080, 690), fill="#CDD4CF", width=1)
            self.metric(1120, 355, "3,584", "有效静态行", "#14566B")
            self.metric(1120, 475, "128", "每个电压点", "#14566B")
            self.body("拟合仅作曲线比较，不作为器件本征模型。", (110, 800), 16, "#6A756F")
            self.emit()

    def transfer_curve(self, seconds: int = 10) -> None:
        points = self.data["transfer"]["points"]
        min_vds = min(p["VDS_V"] for p in points)
        max_vds = max(p["VDS_V"] for p in points)
        box, bounds = (250, 310, 1000, 575), (1.80, 2.29, 0, max(p["ID_nominal_mA"] for p in points) * 1.15)
        strip, sbounds = (250, 665, 1450, 755), (1.80, 2.29, 0.48, 0.52)
        duration = seconds * FPS
        for i in range(duration):
            t = i / (duration - 1)
            self.base("04  /  TRANSFER", t)
            self.label("恒 VDS 闭环", (110, 130))
            self.title("目标不是设定值，是每一点的回读。", (110, 170), 42)
            self.body("9 个栅压点  /  接受范围 0.500 V ± 0.015 V", (114, 238), 20)
            self.chart_axes(box, bounds, "VGS / V", "ID / mA")
            self.chart_axes(strip, sbounds, "VGS / V", "VDS / V", xticks=5, yticks=2)
            # Acceptance band comes from the measured test configuration.
            ylo = self.chart_map(bounds[0], 0.485, strip, sbounds)[1]
            yhi = self.chart_map(bounds[0], 0.515, strip, sbounds)[1]
            self.draw.rectangle((strip[0], yhi, strip[2], ylo), fill="#22372F")
            zero = self.chart_map(bounds[0], 0.5, strip, sbounds)[1]
            self.draw.line((strip[0], zero, strip[2], zero), fill=MINT, width=2)
            n = max(1, min(len(points), int(math.ceil(ease(t * 1.15) * len(points)))))
            main_pts = [self.chart_map(p["VGS_V"], p["ID_nominal_mA"], box, bounds) for p in points[:n]]
            vds_pts = [self.chart_map(p["VGS_V"], p["VDS_V"], strip, sbounds) for p in points[:n]]
            if len(main_pts) > 1:
                self.draw.line(main_pts, fill=ORANGE, width=3, joint="curve")
                self.draw.line(vds_pts, fill=MINT, width=3, joint="curve")
            for x, y in main_pts:
                self.draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=ORANGE, outline=BG, width=2)
            for x, y in vds_pts:
                self.draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=MINT, outline=BG, width=2)
            self.draw.line((1060, 310, 1060, 575), fill=LINE, width=1)
            self.metric(1100, 335, "9 / 9", "转移点通过 VDS 窗口", MINT)
            self.metric(1100, 440, f"{min_vds:.3f}–{max_vds:.3f} V", "实测 VDS 范围", "#F0F1EC")
            self.body("Vth 仅作为有限范围内的趋势代理。", (110, 800), 16)
            self.emit()

    def dynamic_scene(self, result: dict, seconds: int = 4) -> None:
        metrics, trace = result["metrics"], result["trace"]
        freq = metrics["frequency_requested_Hz"]
        period_window = 3.0 / freq
        times = np.asarray(trace["time_VG_s"], dtype=float)
        t0 = times[0]
        indices = np.flatnonzero((times - t0) <= period_window)
        if len(indices) > 1800:
            indices = indices[np.linspace(0, len(indices) - 1, 1800).astype(int)]
        vgt = [(float(trace["time_VG_s"][j] - t0), float(trace["VG_V"][j])) for j in indices]
        vdt = [(float(trace["time_VD_s"][j] - t0), float(trace["VD_V"][j])) for j in indices]
        end_time = max(vgt[-1][0], vdt[-1][0])
        bounds = (0, max(period_window, end_time), 0, 3.3)
        box = (250, 345, 1450, 700)
        duration = seconds * FPS
        for i in range(duration):
            t = i / (duration - 1)
            self.base("05  /  DYNAMIC", t)
            self.label("整机动态响应", (110, 130))
            self.title(f"{freq:g} Hz  /  实测回放", (110, 170), 47)
            self.body("VG 与 VD 来自原始 ADC 通道；显示的是系统响应。", (114, 238), 20)
            self.chart_axes(box, bounds, "Time / s", "Voltage / V")
            shown = max(2, int(len(vgt) * ease(t * 1.2)))
            vgpts = [self.chart_map(a, b, box, bounds) for a, b in vgt[:shown]]
            vdpts = [self.chart_map(a, b, box, bounds) for a, b in vdt[:shown]]
            if len(vgpts) > 1:
                self.draw.line(vgpts, fill=BLUE, width=3, joint="curve")
            if len(vdpts) > 1:
                self.draw.line(vdpts, fill=ORANGE, width=3, joint="curve")
            self.draw.line((1120, 278, 1150, 278), fill=BLUE, width=4)
            self.body("VG", (1160, 266), 17)
            self.draw.line((1240, 278, 1270, 278), fill=ORANGE, width=4)
            self.body("VD", (1280, 266), 17)
            self.metric(110, 740, f"{metrics['frequency_measured_Hz']:.5f} Hz", "实测频率", MINT)
            self.metric(550, 740, f"{metrics['duty_mean'] * 100:.2f}%", "平均占空比")
            self.metric(980, 740, "416 µs", "每组 8 通道；非同时采样")
            self.emit()

    def quality(self, seconds: int = 8) -> None:
        rows = [
            ("时间戳 / 序号", "定位丢行与顺序", BLUE),
            ("通道切换标记", "识别切换瞬态", MINT),
            ("FFFF / 坏行", "拒收并保留诊断", ORANGE),
            ("VDS 窗口", "不满足则不接受该点", BLUE),
            ("DPS OFF 回读", "结束状态留证", MINT),
        ]
        for i in range(seconds * FPS):
            t = i / (seconds * FPS - 1)
            self.base("06  /  QUALITY", t)
            self.label("采样质量门控", (110, 130))
            self.title("异常先被看见，再进入结果。", (110, 170), 45)
            self.body("把原始状态、拒收依据和恢复动作一起保留下来。", (114, 238), 21)
            reveal = ease(t * 1.2)
            for idx, (head, desc, color) in enumerate(rows):
                y = 318 + idx * 91
                self.draw.line((130, y + 64, 1060, y + 64), fill=LINE, width=1)
                self.draw.text((145, y), head, font=font(25, True), fill="#F0F1EC")
                self.draw.text((470, y + 7), desc, font=font(19), fill="#98A59F")
                if reveal > idx / len(rows):
                    x = 1020 + int(130 * reveal)
                    self.draw.ellipse((x, y + 10, x + 18, y + 28), fill=color)
                    self.draw.text((x + 30, y + 5), "已纳入流程", font=font(16), fill=color)
            self.draw.rectangle((1190, 320, 1485, 707), outline="#4B5752", width=1)
            self.label("当前边界", (1220, 352), ORANGE, 17)
            self.body("精密电流标定", (1220, 405), 18)
            self.body("仍待完成", (1220, 435), 17, ORANGE)
            self.body("FFFF 唯一根因", (1220, 500), 18)
            self.body("仍在定位", (1220, 530), 17, ORANGE)
            self.body("独立硬件关断", (1220, 595), 18)
            self.body("尚待验证", (1220, 625), 17, ORANGE)
            self.body("不把未完成项写成结论。", (110, 800), 18)
            self.emit()

    def implementation(self, seconds: int = 8) -> None:
        timing, synth = self.engineering["timing"], self.engineering["synthesis"]
        values = [
            ("50", "MHz  /  目标时钟", MINT),
            (f"{timing['setup_WNS_ns']:.3f}", "ns  /  Setup WNS", BLUE),
            (f"+{timing['hold_WHS_ns']:.3f}", "ns  /  Hold WHS", ORANGE),
            (str(timing["failing_endpoints"]), "失败端点", MINT),
        ]
        for i in range(seconds * FPS):
            t = i / (seconds * FPS - 1)
            self.base("07  /  FPGA", t)
            self.label("实现结果", (110, 130))
            self.title("工程实现，也要能被复核。", (110, 170), 45)
            self.body("Vivado 2022.2  /  AX7020  /  已交付 bitstream 与匹配 LTX", (114, 238), 19)
            for idx, (number, caption, color) in enumerate(values):
                x = 120 + idx * 360
                y = 365
                self.draw.line((x, y, x + 270, y), fill=color, width=4)
                self.draw.text((x, y + 32), number, font=font(54, True), fill="#F0F1EC")
                self.draw.text((x, y + 104), caption, font=font(18), fill="#9AA6A0")
            self.draw.line((120, 550, 1480, 550), fill=LINE, width=1)
            self.metric(120, 610, str(synth["lut_total"]), "LUT")
            self.metric(465, 610, str(synth["flip_flop_total"]), "触发器")
            self.metric(810, 610, str(synth["carry4"]), "CARRY4")
            self.body("约束内 0 个失败端点；不等同于测量精度认证。", (117, 772), 18)
            self.emit()

    def outro(self, seconds: int = 5) -> None:
        for i in range(seconds * FPS):
            t = i / (seconds * FPS - 1)
            self.base("08  /  DELIVERY", t)
            self.label("可复现交付", (110, 158))
            self.title("从采集，到证据。", (110, 205), 60)
            self.draw.line((110, 315, 690, 315), fill=ORANGE, width=3)
            items = [
                ("FPGA", "mos_experiment.bit  +  .ltx"),
                ("SOURCE", "RTL  /  ILA CSV  /  分析脚本"),
                ("RESULT", "真实 PCB1 数据  /  离线工程平台"),
            ]
            for idx, (tag, content) in enumerate(items):
                y = 380 + idx * 92
                self.label(tag, (120, y), [MINT, BLUE, ORANGE][idx], 16)
                self.body(content, (290, y - 3), 22, "#E3E8E3")
            self.body("电流为名义换算值；动态频率描述整机响应。", (110, 735), 18)
            self.body("图形化数据回放 · 现场硬件镜头待补拍", (110, 775), 17, "#82908A")
            self.emit()

    def finish(self) -> None:
        self.writer.release()


def write_srt() -> None:
    entries = [
        (0, 5, "让每一次测量，都留下证据。"),
        (5, 12, "从上位机编排，到 FPGA 确定性采集，再到可复核的数据分析。"),
        (12, 23, "四档固定栅压，七个漏极电压点。每点保留 128 行，圆点来自真实采样，拟合误差单独评估。"),
        (23, 33, "恒 VDS 测试逐点检查反馈值。九个转移点均落在 0.500 伏正负 15 毫伏窗口内。"),
        (33, 45, "一、五、十赫兹动态数据来自整机采集。八个通道顺序采样，通道时间差被保留。"),
        (45, 53, "采样序号、切换标记、坏行状态和关断回读，都进入质量门控与诊断记录。"),
        (53, 61, "AX7020 实现约束内时序收敛，失败端点为零；工程报告同时给出资源和时序证据。"),
        (61, 66, "当前电流为名义换算，精密标定待补。每条结论都对应数据、实现文件与复现入口。"),
    ]

    def stamp(value: int) -> str:
        ms = value * 1000
        hours, ms = divmod(ms, 3_600_000)
        minutes, ms = divmod(ms, 60_000)
        secs, ms = divmod(ms, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"

    blocks = []
    for idx, (start, end, text) in enumerate(entries, 1):
        blocks.extend([str(idx), f"{stamp(start)} --> {stamp(end)}", text, ""])
    SRT_PATH.write_text("\n".join(blocks), encoding="utf-8-sig")


def main() -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    engineering = json.loads(ENGINEERING_PATH.read_text(encoding="utf-8"))
    film = Film(data, engineering)
    film.opener()
    film.architecture()
    film.output_curves()
    film.transfer_curve()
    for result in data["dynamic"]["results"]:
        film.dynamic_scene(result)
    film.quality()
    film.implementation()
    film.outro()
    film.finish()
    write_srt()
    print(f"{OUTPUT_PATH}  frames={film.frames} duration={film.frames / FPS:.2f}s size={OUTPUT_PATH.stat().st_size}")
    print(SRT_PATH)


if __name__ == "__main__":
    main()
