"""Inspect raw diagnostic ILA CSVs; never accepts FFFF as calibrated voltages."""
import argparse
import csv
import json
from pathlib import Path
import statistics

if __package__:
    from .plot_mos_scan import normalize, parse_value, to_volts
else:
    from plot_mos_scan import normalize, parse_value, to_volts


def inspect(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        table = list(csv.reader(handle))
    header_index = next(i for i, row in enumerate(table)
                        if "sample in buffer" in ",".join(row).lower())
    header = [normalize(name).removesuffix("_OBUF").removesuffix("_IBUF")
              for name in table[header_index]]
    rows = [{name: parse_value(cell, 16) for name, cell in zip(header, row)}
            for row in table[header_index + 1:] if len(row) == len(header)]
    rows = [r for r in rows if r.get("adc_valid") in (0, 1)]
    if not rows:
        raise ValueError("No diagnostic rows")
    result = {"csv": str(path), "rows": len(rows)}
    for name in ("init_done", "init_error", "dac_ready", "dac_error",
                 "fault_latched", "adc_reset_count", "ffff_run", "reg_readback"):
        result[name + "_first_last"] = [rows[0][name], rows[-1][name]]
    words = [r for r in rows if r["adc_valid"] == 1]
    result["valid_pulses"] = len(words)
    result["FFFF_words"] = sum(r["adc_data"] == 65535 for r in words)
    ticks = [(b["timestamp_cycles"] - a["timestamp_cycles"]) % (1 << 32)
             for a, b in zip(rows, rows[1:])]
    result["contiguous_50MHz_samples"] = bool(ticks) and all(step == 1 for step in ticks)
    result["captured_span_s"] = sum(ticks) / 50_000_000
    word_ticks = [(b["timestamp_cycles"] - a["timestamp_cycles"]) % (1 << 32)
                  for a, b in zip(words, words[1:])]
    if word_ticks:
        result["word_interval_us_min_max"] = [min(word_ticks) / 50, max(word_ticks) / 50]
    result["channel_order_errors"] = sum(b["adc_index"] != (a["adc_index"] + 1) % 8
                                         for a, b in zip(words, words[1:]))
    result["channels"] = {}
    for channel in range(8):
        data = [r["adc_data"] for r in words if r["adc_index"] == channel]
        if not data:
            continue
        summary = {"samples": len(data), "raw_min": min(data), "raw_max": max(data),
                   "raw_mean": statistics.fmean(data)}
        if all(value != 65535 for value in data):
            range_code = (0, 6, 0, 6, 0, 0, 0, 6)[channel]
            summary["nominal_mean_V"] = statistics.fmean(to_volts(value, range_code) for value in data)
        result["channels"][str(channel)] = summary
    result["SPI_levels"] = {name: sorted(set(r[name] for r in rows))
                            for name in ("adc_cs_n", "adc_sclk", "adc_sdi", "adc_sdo", "adc_rst_n")}
    result["SCLK_rising_edges_in_window"] = sum(a["adc_sclk"] == 0 and b["adc_sclk"] == 1
                                               for a, b in zip(rows, rows[1:]))
    result["SDO_levels_while_CS_low"] = sorted(set(r["adc_sdo"] for r in rows if not r["adc_cs_n"]))
    if result["contiguous_50MHz_samples"]:
        frames = []
        start = None
        for index, row in enumerate(rows[1:], 1):
            previous = rows[index - 1]
            if previous["adc_cs_n"] and not row["adc_cs_n"]:
                start = index
            if not previous["adc_cs_n"] and row["adc_cs_n"] and start is not None:
                edges = [i for i in range(start + 1, index)
                         if not rows[i - 1]["adc_sclk"] and rows[i]["adc_sclk"]]
                # Sample at the middle of each high half-period, matching the RTL.
                samples = [rows[i + 11] for i in edges if i + 11 < index]
                def pack(name):
                    value = 0
                    for sample in samples:
                        value = (value << 1) | sample[name]
                    return f"{value:0{(len(samples) + 3) // 4}X}"
                frames.append({"bits": len(samples), "SDI_hex": pack("adc_sdi"),
                               "SDO_hex": pack("adc_sdo"),
                               "start_sample": start, "end_sample": index})
                start = None
        result["complete_SPI_frames"] = frames
    result["raw_capture_valid"] = bool(words) and not result["FFFF_words"] and all(
        r["init_done"] == r["dac_ready"] == 1 and r["init_error"] == r["dac_error"] == 0
        for r in words)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    results = [inspect(path) for path in sorted(args.directory.glob("*_words.csv"))]
    results += [inspect(path) for path in sorted(args.directory.glob("*_spi.csv"))]
    if not results:
        parser.error("No diagnostic CSVs found")
    path = args.directory / "inspection.json"
    path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
