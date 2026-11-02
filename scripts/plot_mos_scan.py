"""解析 Vivado ILA 导出的 mos_scan CSV，换算电压并画转移特性曲线。

用法：
    python scripts/plot_mos_scan.py output/mos_scan/mos_scan_20261029_153000.csv

只依赖标准库 + matplotlib。所有换算系数都在下面的 CONFIG 里，实测后改这里即可。
"""

import argparse
import csv
import math
import re
import statistics
import sys
from pathlib import Path

CONFIG = {
    # 实测通道确认后改这里：ADS8688 芯片通道号 0~7 对应 VG/VD/VS/ID
    # 没有确认的通道先填 None，脚本会跳过对应曲线
    "CH_MAP": {"VG": 1, "VD": 2, "VS": 3, "ID": 7},
    # 与 mos_scan.v 里 RANGE0..RANGE7 保持一致
    "RANGE": [0, 6, 0, 6, 0, 0, 0, 6],
    # INA240A1 模块：20V/V，板载 2512 0.1Ω，REF1 接 GND、REF2 接 VCC，
    # 所以零电流输出在 VCC/2。用 5V 供电时零点为 2.5V。
    # ID_OFFSET_V 使用同一 INA + ADC 链路的零电流均值，不代替绝对电压校准。
    # 临时零点来源：mos_scan_20261030_192736.csv，CH7量程6，1024个有效扫描行，VCC约4.999V。
    # 5/50mA基本响应已核对后保留名义系数；固定零点仅适用于相近供电，VCC/2变化尚未自动补偿。
    "INA_GAIN": 20.0,        # A1名义值；基本响应核对后保留，精确增益/整机精度未验收
    "SHUNT_OHM": 0.1,        # 模块板载 2512 0.1Ω
    "ID_OFFSET_V": 2.49906608581543,   # 最新临时零点；测试电阻取下，IN-接地
}

# Profiles change wiring interpretation only; ranges must match the programmed
# mos_scan image. In that image CH1 remains 0..5.12 V, including with PCB1.
PROFILES = {
    "bench": {"VG": 1, "VD": 2, "VS": 3, "ID": 7},
    "pcb1": {"VG": 0, "VD": 1, "VS": 2, "ID": 7},
}


def qualified_rows(rows):
    selected = [row for row in rows if row.get("row_valid") == 1]
    if not selected:
        raise SystemExit("没有 row_valid=1 的扫描数据，不能生成测量结果")
    expected = {"init_done": 1, "init_error": 0, "dac_ready": 1, "dac_error": 0}
    for index, row in enumerate(selected):
        if any(row.get(name) != value for name, value in expected.items()):
            raise SystemExit(f"第{index + 1}个有效行通信状态异常或缺失，停止换算")
        if any(f"row_ch{i}" not in row for i in range(8)):
            raise SystemExit(f"第{index + 1}个有效行缺少ADC数据，停止换算")
        if all(row[f"row_ch{i}"] == 65535 for i in range(8)):
            raise SystemExit("全部ADC通道均为FFFF，停止换算")
    return selected

# ADS8688 量程码 -> (满量程电压, 是否双极性)，见 TI SBAS582 表 15
RANGES = {
    0: (10.24, True),
    1: (5.12, True),
    2: (2.56, True),
    5: (10.24, False),
    6: (5.12, False),
}


def to_volts(raw, code):
    full_scale, bipolar = RANGES[code]
    if bipolar:
        return (raw - 32768) * (2 * full_scale / 65536)
    return raw * (full_scale / 65536)


def normalize(name):
    name = re.sub(r"\[\d+:\d+\]", "", name.strip())
    name = re.sub(r"^(u_ila_scan_)", "", name)
    return name.strip()


def parse_value(text, radix):
    text = text.strip()
    if not text or "x" in text.lower():
        return None
    text = text.lower().removeprefix("0x")
    try:
        return int(text, radix)
    except ValueError:
        return None


def load_rows(path, radix):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        table = list(csv.reader(handle))

    header_index = next(
        (i for i, row in enumerate(table) if "sample in buffer" in ",".join(row).lower()),
        None,
    )
    if header_index is None:
        raise SystemExit("没有找到 ILA CSV 表头，请确认导出的是 write_hw_ila_data -csv_file 文件")

    columns = [normalize(name) for name in table[header_index]]
    required = {"point", "row_valid"} | {f"row_ch{i}" for i in range(8)}
    missing = required - set(columns)
    if missing:
        raise SystemExit(f"CSV 缺少列 {sorted(missing)}；实际列为 {columns}")

    rows = []
    for row in table[header_index + 1:]:
        if len(row) < len(columns):
            continue
        values = {}
        for name, cell in zip(columns, row):
            value = parse_value(cell, radix)
            if value is not None:
                values[name] = value
        if "point" in values and "row_valid" in values:
            rows.append(values)
    return rows


def average_by_point(rows):
    grouped = {}
    for row in rows:
        if not row.get("row_valid"):
            continue
        grouped.setdefault(row["point"], []).append(row)
    averaged = []
    for point in sorted(grouped):
        samples = grouped[point]
        entry = {"point": point, "repeats": len(samples)}
        for key in samples[0]:
            if key in ("point", "row_valid"):
                continue
            entry[key] = statistics.fmean(s[key] for s in samples)
        averaged.append(entry)
    return averaged


def resolve_csv(argument):
    """没给文件名时自动取 output/mos_scan 下最新的抓取文件。"""
    capture_dir = Path(__file__).resolve().parent.parent / "output" / "mos_scan"
    candidates = sorted(
        (p for p in capture_dir.glob("mos_scan_*.csv") if not p.stem.endswith("_points")),
        key=lambda p: p.stat().st_mtime,
    )
    if argument:
        path = Path(argument)
        if path.is_file():
            return path
        raise SystemExit(
            f"找不到文件：{argument}\n"
            f"目录 {capture_dir} 下现有的抓取文件：\n  "
            + "\n  ".join(p.name for p in candidates[-5:])
        )
    if not candidates:
        raise SystemExit(f"{capture_dir} 里没有 mos_scan_*.csv，先跑 capture_mos_scan.tcl")
    newest = candidates[-1]
    print(f"使用最新抓取文件：{newest.name}")
    return newest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file", nargs="?", default=None,
                        help="不填则自动使用 output/mos_scan 下最新的 mos_scan_*.csv")
    parser.add_argument("--radix", type=int, default=16, choices=(10, 16))
    parser.add_argument("--loopback", action="store_true",
                        help="DAC 回环检查：把 AIN0 当作 VG，画 ADC 读数 vs DAC 码")
    parser.add_argument("--all", action="store_true",
                        help="打印全部 8 个通道的电压，用于确认通道映射")
    parser.add_argument("--out", default=None)
    parser.add_argument("--profile", choices=tuple(PROFILES), default="bench",
                        help="bench=历史台架；pcb1=最终PCB（VG/VD/VS/ID为CH0/1/2/7）")
    zero = parser.add_mutually_exclusive_group()
    zero.add_argument("--zero-csv", type=Path,
                      help="同一供电条件下、DPS输出关闭时的零电流采集CSV")
    zero.add_argument("--id-offset-v", type=float,
                      help="显式指定INA+ADC链路的实测零电流电压（V）")
    parser.add_argument("--zero-by-point", action="store_true",
                        help="使用--zero-csv中相同point和DAC码的INA均值扣零，保留原始节点电压")
    args = parser.parse_args()
    if args.zero_by_point and (not args.zero_csv or args.loopback):
        parser.error("--zero-by-point需要--zero-csv，且不能用于--loopback")

    args.csv_file = str(resolve_csv(args.csv_file))
    rows = load_rows(args.csv_file, args.radix)
    if not rows:
        raise SystemExit("CSV 里没有有效行，检查 ILA 是否真的抓到了数据")
    rows = qualified_rows(rows)
    points = average_by_point(rows)

    ch_map = {"VG": 0, "VD": None, "VS": None, "ID": None} if args.loopback else PROFILES[args.profile]
    ranges = CONFIG["RANGE"]
    gain, shunt, offset = CONFIG["INA_GAIN"], CONFIG["SHUNT_OHM"], CONFIG["ID_OFFSET_V"]
    offsets_by_point = {}
    if not args.loopback:
        if args.zero_csv:
            zero_rows = qualified_rows(load_rows(args.zero_csv, args.radix))
            zero_channel = ch_map["ID"]
            offset = statistics.fmean(
                to_volts(row[f"row_ch{zero_channel}"], ranges[zero_channel])
                for row in zero_rows
            )
            if args.zero_by_point:
                zero_points = {entry["point"]: entry for entry in average_by_point(zero_rows)}
                # Matching just the point number is insufficient after a DAC step change.
                for entry in points:
                    point = entry["point"]
                    baseline = zero_points.get(point)
                    codes = {row.get("vg_code") for row in rows if row["point"] == point}
                    zero_codes = {row.get("vg_code") for row in zero_rows if row["point"] == point}
                    if baseline is None or len(codes) != 1 or None in codes or codes != zero_codes:
                        raise SystemExit(f"零点与带电数据的point={point}或DAC码不匹配，停止扣零")
                    offsets_by_point[point] = to_volts(
                        baseline[f"row_ch{zero_channel}"], ranges[zero_channel])
            print(f"零点来源：{args.zero_csv}，{len(zero_rows)}个有效行")
            if args.zero_by_point:
                print("INA逐点扣零；VG/VD/VS仍为未经绝对校准的原始ADC换算值。")
        elif args.id_offset_v is not None:
            if not math.isfinite(args.id_offset_v) or not 0 <= args.id_offset_v <= 5.12:
                raise SystemExit("零电流电压必须是0～5.12 V内的有限数值")
            offset = args.id_offset_v
        elif args.profile == "pcb1":
            raise SystemExit("PCB1供电已改变，请先采零点并传入 --zero-csv，或指定 --id-offset-v")
        print(f"配置：{args.profile}；通道：{ch_map}；INA零点：{offset:.9f} V")
        print("电流使用名义INA增益和分流电阻；尚未完成整机精度校准。")
        if args.profile == "pcb1":
            print("当前固件CH1漏压量程为0～5.12 V；本配置只用于该范围内的低压验证。")

    def channel_volts(entry, key):
        channel = ch_map.get(key)
        if channel is None:
            return None
        return to_volts(entry.get(f"row_ch{channel}", 0), ranges[channel])

    table = []
    for entry in points:
        vg, vd, vs = (channel_volts(entry, k) for k in ("VG", "VD", "VS"))
        v_id = channel_volts(entry, "ID")
        point_offset = offsets_by_point.get(entry["point"], offset)
        current_ma = None
        if v_id is not None:
            current_ma = (v_id - point_offset) / (gain * shunt) * 1000.0
        table.append({
            "point": entry["point"],
            "repeats": entry["repeats"],
            "vg_code": entry.get("vg_code", 0),
            "VG": vg, "VD": vd, "VS": vs,
            "VGS": None if vg is None or vs is None else vg - vs,
            "VDS": None if vd is None or vs is None else vd - vs,
            "ID_mA": current_ma,
            "INA_OUT_V": v_id,
            "INA_ZERO_V": point_offset if v_id is not None else None,
            "ID_ZERO_METHOD": "point_and_DAC_matched" if args.zero_by_point else "global_mean",
        })

    if args.all:
        print("通道映射检查：每行是 8 个 ADS8688 通道换算后的电压（V）")
        print(f"{'pt':>3} {'code':>5} " + " ".join(f"{'ch'+str(i):>8}" for i in range(8)))
        for entry in points:
            volts = [to_volts(entry[f"row_ch{i}"], ranges[i]) for i in range(8)]
            print(f"{entry['point']:>3} {entry.get('vg_code', 0):>5} "
                  + " ".join(f"{v:>8.3f}" for v in volts))
        print()

    print(f"{'pt':>3} {'n':>3} {'code':>5} {'VG':>8} {'VD':>8} {'VS':>8} {'VGS':>8} {'VDS':>8} {'ID/mA':>9}")
    for row in table:
        def fmt(value, width, digits=3):
            return f"{'--':>{width}}" if value is None else f"{value:>{width}.{digits}f}"
        print(f"{row['point']:>3} {row['repeats']:>3} {row['vg_code']:>5} "
              f"{fmt(row['VG'], 8)} {fmt(row['VD'], 8)} {fmt(row['VS'], 8)} "
              f"{fmt(row['VGS'], 8)} {fmt(row['VDS'], 8)} {fmt(row['ID_mA'], 9, 4)}")

    out_dir = Path(args.csv_file).parent
    stem = Path(args.csv_file).stem
    summary = (Path(args.out) if args.out else out_dir / f"{stem}_points.csv")
    with open(summary, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    print(f"\n逐点平均结果：{summary}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("未安装 matplotlib，跳过绘图：python -m pip install matplotlib")
        return

    # 中文字体，找不到就退回英文刻度（避免出现方块）
    available = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
    for font in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC"):
        if font in available:
            plt.rcParams["font.sans-serif"] = [font]
            break
    plt.rcParams["axes.unicode_minus"] = False

    usable = [r for r in table if r["VGS"] is not None and r["ID_mA"] is not None]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))

    if args.loopback:
        series = [(r["vg_code"], r["VG"]) for r in table if r["VG"] is not None]
        if series:
            axes[0].plot(*zip(*series), "o-", ms=3, label="ADC 实测")
            codes = [c for c, _ in series]
            axes[0].plot(codes, [3.3 * c / 4096 for c in codes], "--", lw=1,
                         label="理论 3.3V*code/4096")
            axes[0].legend()
            axes[0].set_xlabel("DAC code")
            axes[0].set_ylabel("AIN0 / V")
            axes[0].set_title("DAC 回环：ADC 读数 vs DAC 码")
            axes[0].grid(alpha=0.3)
    elif usable:
        axes[0].plot([r["VGS"] for r in usable], [r["ID_mA"] for r in usable], "o-", ms=3)
        axes[0].set_xlabel("VGS / V")
        axes[0].set_ylabel("ID / mA")
        axes[0].set_title("栅压扫描 ID-VGS（VDS随负载变化）")
        axes[0].grid(alpha=0.3)
    else:
        axes[0].text(0.5, 0.5, "CH_MAP 未配置 VG/VS/ID，无法画曲线",
                     ha="center", va="center", transform=axes[0].transAxes)

    for key, style in (("VG", "C0.-"), ("VD", "C1.-"), ("VS", "C2.-")):
        series = [(r["point"], r[key]) for r in table if r[key] is not None]
        if series:
            axes[1].plot(*zip(*series), style, ms=2, label=key)
    axes[1].set_xlabel("扫描点序号")
    axes[1].set_ylabel("电压 / V")
    axes[1].set_title("各节点电压 vs 扫描点")
    axes[1].grid(alpha=0.3)
    axes[1].legend()

    fig.tight_layout()
    png = out_dir / f"{stem}_curve.png"
    fig.savefig(png, dpi=150)
    print(f"曲线图：{png}")

    # Gate voltage also changes during this capture, so this is a sweep path,
    # not an output characteristic measured at a fixed VGS.
    vds_values = [r["VDS"] for r in usable]
    if vds_values and max(vds_values) - min(vds_values) > 0.2:
        fig2, ax2 = plt.subplots(figsize=(5.5, 4))
        ax2.plot(vds_values, [r["ID_mA"] for r in usable], ".-")
        ax2.set_xlabel("VDS / V")
        ax2.set_ylabel("ID / mA")
        ax2.set_title("栅压扫描路径（非固定VGS输出特性）")
        ax2.grid(alpha=0.3)
        fig2.tight_layout()
        png2 = out_dir / f"{stem}_output.png"
        fig2.savefig(png2, dpi=150)
        print(f"栅压扫描路径图：{png2}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
