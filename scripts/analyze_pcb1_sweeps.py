"""Plot accepted real PCB1 captures; keep raw voltages and nominal calibration explicit."""

import argparse
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import re
import statistics as stats

from capture_pcb1_powered import validate_gate_tracking
from plot_mos_scan import CONFIG, load_rows, qualified_rows, to_volts


def capture_time(path):
    match = re.search(r"mos_scan_(\d{8}_\d{6})", Path(path).name)
    if match is None:
        raise ValueError(f"Capture timestamp is missing: {path}")
    return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")


def grouped(rows):
    return {point: [row for row in rows if row["point"] == point] for point in range(32)}


def volts(rows, channel):
    return [to_volts(row[f"row_ch{channel}"], CONFIG["RANGE"][channel]) for row in rows]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", nargs="+", type=Path, required=True)
    parser.add_argument("--zero-csv", nargs="+", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    zeros = []
    for path in args.zero_csv:
        rows = qualified_rows(load_rows(path, 16))
        validate_gate_tracking(rows)
        zeros.append((path, capture_time(path), grouped(rows)))
    summaries, table = [], []
    sensitivity = CONFIG["INA_GAIN"] * CONFIG["SHUNT_OHM"]
    for report_path in args.report:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if (report.get("success") is not True
                or report.get("after", {}).get("output_enabled") is not False):
            raise ValueError(f"Capture or shutdown not verified: {report_path}")
        capture = Path(report["capture_csv"])
        rows = qualified_rows(load_rows(capture, 16))
        validate_gate_tracking(rows)
        samples = grouped(rows)
        zero_path, _, baseline = min(zeros, key=lambda item: abs(item[1] - capture_time(capture)))
        validate_gate_tracking(rows, [row for point in baseline.values() for row in point])
        supply_estimate = stats.fmean(volts([row for row in rows if row["point"] <= 8], 1))
        series = []
        for point in range(32):
            rr, zz = samples[point], baseline[point]
            codes = {row.get("vg_code") for row in rr}
            if len(codes) != 1 or None in codes or codes != {row.get("vg_code") for row in zz}:
                raise ValueError(f"DAC code mismatch at point {point}")
            vg, vd, vs, ina = [stats.fmean(volts(rr, channel)) for channel in (0, 1, 2, 7)]
            offset = stats.fmean(volts(zz, 7))
            sd = stats.stdev(volts(rr, 7))
            zero_sd = stats.stdev(volts(zz, 7))
            entry = {
                "supply_set_V": report["voltage_set_V"], "point": point,
                "vg_code": next(iter(codes)), "repeats": len(rr),
                "VG_raw_V": vg, "VD_raw_V": vd, "VS_raw_V": vs,
                "VGS_raw_V": vg - vs, "VDS_raw_V": vd - vs,
                "INA_OUT_V": ina, "INA_ZERO_V": offset,
                "ID_nominal_mA": (ina - offset) / sensitivity * 1000,
                "ID_repeat_SD_mA": sd / sensitivity * 1000,
                "ID_mean_SE_mA": math.sqrt(sd**2 / len(rr) + zero_sd**2 / len(zz)) / sensitivity * 1000,
                "ID_R1_estimate_mA": (supply_estimate - vd) / 990 * 1000,
                "capture_csv": str(capture), "zero_csv": str(zero_path),
            }
            series.append(entry)
        summary = {
            "report": str(report_path), "capture_csv": str(capture),
            "zero_csv": str(zero_path), "supply_set_V": report["voltage_set_V"],
            "valid_rows": len(rows), "points": 32,
            "gate_endpoints_raw_V": [series[0]["VG_raw_V"], series[-1]["VG_raw_V"]],
            "drain_endpoints_raw_V": [series[0]["VD_raw_V"], series[-1]["VD_raw_V"]],
            "off_state_VD_used_for_R1_V": supply_estimate,
            "source_raw_mean_V": stats.fmean(row["VS_raw_V"] for row in series),
            "high_gate_current_nominal_mean_mA": stats.fmean(
                row["ID_nominal_mA"] for row in series if row["VG_raw_V"] >= 2.8),
            "median_current_repeat_SD_uA": stats.median(row["ID_repeat_SD_mA"] for row in series) * 1000,
            "R1_crosscheck_RMSE_uA": math.sqrt(stats.fmean(
                (row["ID_nominal_mA"] - row["ID_R1_estimate_mA"])**2 for row in series)) * 1000,
        }
        summaries.append(summary)
        table.extend(series)
    csv_path = args.out_dir / "accepted_sweep_points.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    metadata = {
        "source": "real_hardware_ILA_and_DPS_reports", "captures": summaries,
        "method": "nearest-in-time supplied zero CSV; INA mean matched by point and DAC code",
        "nominal_INA_gain": CONFIG["INA_GAIN"], "nominal_shunt_ohm": CONFIG["SHUNT_OHM"],
        "R1_measured_ohm_approx": 990,
        "limits": [
            "Raw voltages have no absolute gain/offset calibration; VS has about -13 mV offset.",
            "Current SD and SE measure repeatability only, excluding systematic gain/offset error.",
            "R1 current uses mean low-gate VD as supply estimate and is a crosscheck, not gain calibration.",
            "VDS changes during each gate sweep; these are load-line sweeps, not fixed-VDS transfer curves.",
            "High-gate current is limited by R1; no datasheet threshold or MOS saturation parameter is extracted.",
        ],
    }
    (args.out_dir / "accepted_sweep_analysis.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    available = {font.name for font in matplotlib.font_manager.fontManager.ttflist}
    for font in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC"):
        if font in available:
            plt.rcParams["font.sans-serif"] = [font]
            break
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8))
    for index, summary in enumerate(summaries):
        series = [row for row in table if row["capture_csv"] == summary["capture_csv"]]
        color = f"C{index % 10}"
        label = f"DPS {summary['supply_set_V']:g} V"
        vg = [row["VG_raw_V"] for row in series]
        axes[0].errorbar(vg, [row["ID_nominal_mA"] for row in series],
                         yerr=[row["ID_mean_SE_mA"] for row in series], color=color,
                         fmt="o-", ms=3, capsize=2, label=label + "：INA逐点扣零")
        axes[0].plot(vg, [row["ID_R1_estimate_mA"] for row in series],
                     "--", color=color, alpha=0.7, label=label + "：漏压差/R1估算")
        axes[1].plot(vg, [row["VD_raw_V"] for row in series], "o-", ms=3,
                     color=color, label=label)
    axes[0].set(title="2N7000 栅压扫描：电流随栅压变化", ylabel="ID / mA（INA名义增益，未精密标定）")
    axes[1].set(title="同轮漏极节点电压（相对GND）", ylabel="VD / V（原始ADC换算值）")
    for ax in axes:
        ax.set_xlabel("VG 对GND / V（原始ADC换算值）")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8)
    fig.suptitle("PCB1 实物测量 · R1≈990 Ω · VDS随栅压变化", fontsize=13)
    fig.text(0.5, 0.025,
             "误差棒为均值的1σ重复性估计，不含系统误差；VS约−13mV零偏尚未校准。来源：2026-11-02 ILA实采。",
             ha="center", fontsize=8)
    fig.tight_layout(rect=(0, 0.07, 1, 0.94))
    fig.savefig(args.out_dir / "accepted_sweeps.png", dpi=170)
    plt.close(fig)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    print(f"Saved: {csv_path}")


if __name__ == "__main__":
    main()
