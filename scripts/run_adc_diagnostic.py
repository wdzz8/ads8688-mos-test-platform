"""Run a drain-OFF ADC diagnostic and preserve raw captures and supply status."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

if __package__:
    from .capture_fixed_vgs_output import DEFAULT_VIVADO, ROOT
    from .manual_voltage_calibration import off, vivado
    from .inspect_adc_diagnostic import inspect
else:
    from capture_fixed_vgs_output import DEFAULT_VIVADO, ROOT
    from manual_voltage_calibration import off, vivado
    from inspect_adc_diagnostic import inspect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("program", "capture", "reset", "observe", "audit", "observe_audit"))
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 1800:
        parser.error("--seconds must be 1..1800")
    directory = args.output or ROOT / "output/pcb1/adc_fault_diagnostic" / (
        args.action + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    report_path = directory / "diagnostic.json"
    bit = ROOT / "output/mos_adc_diagnostic/audit_code_2560/mos_adc_diagnostic.bit"
    report = {"action": args.action, "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "bit": str(bit), "bit_sha256": hashlib.sha256(bit.read_bytes()).hexdigest(),
              "measurement_accepted_for_calibration": False, "stage": "started"}
    try:
        report["off_before"] = off(args.port)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        arguments = [directory, args.action]
        if args.action in ("observe", "observe_audit"):
            arguments.append(args.seconds)
        vivado(DEFAULT_VIVADO, "capture_adc_diagnostic.tcl", arguments,
               directory / "capture.log", timeout=args.seconds + 60 if args.action in ("observe", "observe_audit") else 60)
        report["stage"] = "captured"
        inspections = [inspect(path) for path in sorted(directory.glob("*_words.csv"))]
        inspections += [inspect(path) for path in sorted(directory.glob("*_spi.csv"))]
        if not inspections:
            raise RuntimeError("No diagnostic CSVs were produced")
        (directory / "inspection.json").write_text(
            json.dumps(inspections, indent=2) + "\n", encoding="utf-8")
        report["inspections"] = inspections
        audit = directory / "audit_values.hex"
        if audit.exists():
            value = int(audit.read_text().strip(), 16)
            addresses = [0x3f, 1, 2, 3, *range(5, 13)]
            expected = [0x00, 0xff, 0, 0, 0, 6, 0, 6, 0, 0, 0, 6]
            report["register_audit"] = {
                "read_only": True, "ADC_paused_until_reset": True,
                "command_readback_note": "3F reflects the last NOP word (00); it does not independently prove the conversion mode.",
                "registers": [{"address_hex": f"{address:02X}", "raw": (value >> (8 * index)) & 255,
                               "expected": expected[index],
                               "matches_expected": ((value >> (8 * index)) & 255) == expected[index]}
                              for index, address in enumerate(addresses)]}
            (directory / "audit_registers.json").write_text(
                json.dumps(report["register_audit"], indent=2) + "\n", encoding="utf-8")
        observation = directory / "vio_observation.csv"
        if observation.exists():
            with observation.open(newline="", encoding="utf-8") as handle:
                polls = list(csv.DictReader(handle))
            report["observation"] = {
                "requested_seconds": args.seconds,
                "source": "ILA snapshots, not VIO INPUT_VALUE",
                "polls": len(polls),
                "elapsed_seconds": int(polls[-1]["elapsed_ms"]) / 1000,
                "fault_latched_observed": any(int(row["fault_latched"], 16) for row in polls),
                "initial_fault_latched": int(polls[0]["fault_latched"], 16),
                "maximum_ffff_run_at_poll": max(int(row["ffff_run"], 16) for row in polls),
                "new_fault_observed": any(int(row["ffff_run"], 16) >= 16 for row in polls)
                    or (not int(polls[0]["fault_latched"], 16)
                        and any(int(row["fault_latched"], 16) for row in polls)),
                "note": "Sticky flag detects runs of at least 16 FFFF words; this is not a continuous archive of every ADC word."}
        report["stage"] = "inspected"
    except BaseException as error:
        report["stage"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        try:
            report["off_after"] = off(args.port)
        except BaseException as error:
            report["off_after_error"] = f"{type(error).__name__}: {error}"
            report["stage"] = "failed"
            raise
        finally:
            report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(report_path)
    for item in report["inspections"]:
        print(Path(item["csv"]).name, "rows", item["rows"],
              "FFFF", item["FFFF_words"], "fault", item["fault_latched_first_last"],
              "reset", item["adc_reset_count_first_last"],
              "raw_valid", item["raw_capture_valid"])


if __name__ == "__main__":
    main()
