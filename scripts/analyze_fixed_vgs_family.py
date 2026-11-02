"""Revalidate raw fixed-gate captures and plot one or more real output curves."""

import argparse
import csv
import json
from pathlib import Path
import statistics
import sys

if __package__:
    from .capture_fixed_vgs_output import summarize_capture
else:
    from capture_fixed_vgs_output import summarize_capture

INA_GAIN = 20.0
SHUNT_OHM = 0.1


def analyze_report(report_path, zero_override=None, r1_ohm=990.0):
    report_path = Path(report_path).resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("success") is not True:
        raise ValueError(f"Unsuccessful acquisition report: {report_path}")
    if report.get("final_off_error"):
        raise ValueError(f"Report has an unresolved final shutdown error: {report_path}")
    final_off = report.get("final_off")
    if final_off is not None and (final_off.get("output_enabled") is not False
                                  or final_off.get("voltage_out_V") != 0):
        raise ValueError("Final shutdown readback is invalid")
    code = int(report["dac_code"])
    zero_path = Path(zero_override or report["zero_csv"]).resolve()
    # Always reparse evidence files; cached JSON summaries are not sufficient.
    zero = summarize_capture(zero_path, code)
    zero_ina = zero["INA_OUT_V_mean"]
    source_zero = zero["VS_V_mean"]
    rows = []
    gate_min, gate_max, vgs_spans = [], [], []
    for item in report["results"]:
        if item.get("success") is not True:
            raise ValueError(f"Unsuccessful point in {report_path}")
        after = item.get("after", {})
        if after.get("output_enabled") is not False or after.get("voltage_out_V") != 0:
            raise ValueError(f"Point shutdown not verified in {report_path}")
        summary = summarize_capture(Path(item["csv"]), code, int(report["capture_depth"]), zero)
        vg, vd, vs = (summary[f"{node}_V_mean"] for node in ("VG", "VD", "VS"))
        source_delta = vs - source_zero
        ina = summary["INA_OUT_V_mean"]
        statuses = [item["output_on_verified"]] + item.get("samples", [])
        supply_readback = statistics.fmean(status["voltage_out_V"] for status in statuses)
        rows.append({
            "dac_code": code, "supply_set_V": float(item["voltage_set_V"]),
            "supply_readback_mean_V": supply_readback,
            "VG_raw_V": vg, "VD_raw_V": vd, "VS_raw_V": vs,
            "VGS_raw_V": vg - vs, "VDS_raw_V": vd - vs,
            "VS_zero_reference_V": source_zero, "VS_zero_corrected_V": source_delta,
            "VGS_source_zero_corrected_V": vg - source_delta,
            "VDS_source_zero_corrected_V": vd - source_delta,
            "INA_OUT_V": ina, "INA_ZERO_V": zero_ina,
            "ID_nominal_mA": (ina - zero_ina) / (INA_GAIN * SHUNT_OHM) * 1000,
            "ID_repeat_SD_mA": summary["INA_OUT_V_sd"] / (INA_GAIN * SHUNT_OHM) * 1000,
            "VD_repeat_SD_V": summary["VD_V_sd"],
            "ID_R1_crosscheck_mA": (supply_readback - vd) / r1_ohm * 1000,
            "rows": summary["valid_rows"], "csv": summary["csv"],
            "zero_csv": str(zero_path), "report": str(report_path),
        })
        gate_min.append(summary["VG_V_min"])
        gate_max.append(summary["VG_V_max"])
        vgs_spans.append(summary["VGS_span_V"])
    actual_levels = sorted(row["supply_set_V"] for row in rows)
    if (not rows or actual_levels != sorted(report["levels_V"])
            or len(set(actual_levels)) != len(actual_levels)):
        raise ValueError(f"Incomplete drain levels in {report_path}")
    rows.sort(key=lambda row: row["supply_set_V"])
    gate_span = max(gate_max) - min(gate_min)
    if gate_span > 0.020:
        raise ValueError("Gate varied by >20 mV across the curve")
    vgs = [row["VGS_raw_V"] for row in rows]
    crosscheck = [row["ID_nominal_mA"] - row["ID_R1_crosscheck_mA"] for row in rows]
    curve = {
        "report": str(report_path), "dac_code": code, "zero_csv": str(zero_path),
        "points": len(rows), "valid_rows": sum(row["rows"] for row in rows),
        "VG_raw_mean_V": statistics.fmean(row["VG_raw_V"] for row in rows),
        "VG_all_rows_span_V": gate_span, "VGS_max_within_point_span_V": max(vgs_spans),
        "VGS_raw_mean_V": statistics.fmean(vgs),
        "VGS_point_means_span_V": max(vgs) - min(vgs),
        "VGS_source_zero_corrected_mean_V": statistics.fmean(
            row["VGS_source_zero_corrected_V"] for row in rows),
        "VS_zero_reference_V": source_zero,
        "ID_R1_crosscheck_RMSE_mA": statistics.fmean(value ** 2 for value in crosscheck) ** 0.5,
        "ID_nominal_range_mA": [min(row["ID_nominal_mA"] for row in rows),
                                 max(row["ID_nominal_mA"] for row in rows)],
        "VDS_source_zero_corrected_range_V": [
            min(row["VDS_source_zero_corrected_V"] for row in rows),
            max(row["VDS_source_zero_corrected_V"] for row in rows)],
    }
    return rows, curve


def main(argv=None):
    parser = argparse.ArgumentParser(description="固定VGS单条或多条输出特性分析")
    parser.add_argument("report", type=Path, nargs="+")
    parser.add_argument("--zero-csv", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--r1-ohm", type=float, default=990.0)
    args = parser.parse_args(argv)
    if args.zero_csv and len(args.report) != 1:
        parser.error("--zero-csv applies to a single report only")
    if not 0 < args.r1_ohm < 100000:
        parser.error("invalid --r1-ohm")
    rows, curves = [], []
    for report_path in args.report:
        try:
            points, curve = analyze_report(report_path, args.zero_csv, args.r1_ohm)
        except (ValueError, OSError, SystemExit) as error:
            parser.error(str(error))
        rows.extend(points)
        curves.append(curve)
    curves.sort(key=lambda curve: curve["dac_code"])
    out_dir = (args.out_dir or args.report[0].parent / "analysis").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "fixed_vgs_output_points.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = {
        "source": "revalidated_real_fixed_VGS_ILA_and_DPS_reports",
        "curves": curves, "points": rows,
        "ina_gain_nominal_V_per_V": INA_GAIN, "shunt_nominal_ohm": SHUNT_OHM,
        "R1_crosscheck_approx_ohm": args.r1_ohm,
        "notes": [
            "Gate voltage is fixed; measured VDS is swept by changing the drain supply through R1.",
            "INA current uses a matched, fixed-DAC, DPS-OFF baseline and nominal gain/shunt.",
            "Source-zero correction subtracts DPS-OFF VS; it does not calibrate VG or VD gain/offset.",
            "Raw VGS/VDS retain the known approximately -13 mV source-channel offset.",
            "R1 check uses approximate resistance and coarse DPS readback; it is not an independent calibration.",
            "Error bars show within-point repeat SD, not absolute uncertainty or precision.",
        ],
    }
    json_path = out_dir / "fixed_vgs_output_analysis.json"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.2))
    colors = ["#2367ab", "#b15f20", "#207b67", "#7953a5", "#555555"]
    for index, curve in enumerate(curves):
        points = [row for row in rows if row["report"] == curve["report"]]
        vgs = curve["VGS_source_zero_corrected_mean_V"]
        label = f"DAC {curve['dac_code']}; VGS ~ {vgs:.3f} V"
        for axis in axes:
            axis.errorbar([row["VDS_source_zero_corrected_V"] for row in points],
                          [row["ID_nominal_mA"] for row in points],
                          xerr=[row["VD_repeat_SD_V"] for row in points],
                          yerr=[row["ID_repeat_SD_mA"] for row in points],
                          fmt="o-", ms=4, lw=1.5, elinewidth=0.8, capsize=2,
                          color=colors[index % len(colors)], label=label)
    axes[0].set_title("Fixed-VGS output curves: measured drain voltage")
    axes[1].set_title("Detail near the origin")
    axes[1].set_xlim(-0.015, 0.4)
    for axis in axes:
        axis.set_xlabel("VDS, source-zero corrected / V")
        axis.set_ylabel("ID, matched INA zero + nominal gain / mA")
        axis.grid(alpha=0.25)
        axis.legend(fontsize=8)
    fig.text(0.5, 0.015,
             "Real PCB1 + 2N7000 | R1 ~ 990 ohm | raw CSV/ILA retained | bars: repeat SD; absolute calibration pending",
             ha="center", fontsize=8, color="0.35")
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    png_path = out_dir / "fixed_vgs_output_curve.png"
    fig.savefig(png_path, dpi=170)
    fig.savefig(out_dir / "fixed_vgs_output_curve.svg")
    plt.close(fig)
    print(json.dumps({"curves": curves, "csv": str(csv_path), "json": str(json_path),
                      "plot": str(png_path)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
