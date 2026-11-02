"""Pair manually entered DMM voltages with raw ADC captures, with DPS OFF.

prepare programs an existing fixed-gate image and captures a baseline. record
captures again without programming, validates that the gate stayed at the same
level, and appends the explicitly supplied meter reading. No coefficients are
applied from a single point and no operation enables the drain supply.
"""

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import subprocess
import sys

import serial

if __package__:
    from .capture_fixed_vgs_output import DEFAULT_VIVADO, ROOT, summarize_capture, verified_off
    from .dps_control import DpsController
    from .plot_mos_scan import load_rows, qualified_rows
else:
    from capture_fixed_vgs_output import DEFAULT_VIVADO, ROOT, summarize_capture, verified_off
    from dps_control import DpsController
    from plot_mos_scan import load_rows, qualified_rows


QUANTITIES = {"VG": (0, "Q1-2 / VG"), "VS": (2, "Q1-1 / VS"),
              "VD": (1, "Q1-3 / VD")}


def reading_volts(text, unit):
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise ValueError("Reading must be a number; specify its unit separately") from error
    if not value.is_finite():
        raise ValueError("Reading must be finite")
    if unit not in ("V", "mV", "uV"):
        raise ValueError("Reading unit must be V, mV or uV")
    value *= {"V": Decimal(1), "mV": Decimal("0.001"), "uV": Decimal("0.000001")}[unit]
    if abs(value) > 5.12:
        raise ValueError("Reading exceeds this low-voltage calibration range")
    return float(value)


def save(path, report):
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def off(port):
    connection = serial.Serial(port=None, baudrate=9600, timeout=1.5, write_timeout=1.5)
    connection.port = port
    connection.dtr = connection.rts = False
    with connection:
        return verified_off(DpsController(connection))


def vivado(executable, script, arguments, log, timeout=60):
    env = os.environ.copy()
    env["PROCESSOR_ARCHITECTURE"] = "AMD64"
    command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(executable),
               "-mode", "batch", "-source", str(ROOT / "scripts" / script),
               "-notrace", "-nolog", "-nojournal", "-tclargs", *map(str, arguments)]
    with log.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=handle,
                                   stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            if process.wait(timeout=timeout) != 0:
                raise RuntimeError(f"Vivado operation failed; see {log}")
        finally:
            if process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                process.wait(timeout=10)


def snapshot(report, directory, name):
    csv = directory / f"{name}.csv"
    ltx = ROOT / "output/mos_fixed_vgs" / f"code_{report['dac_code']:04d}" / "mos_fixed_vgs.ltx"
    vivado(report["vivado"], "capture_mos_fixed_vgs.tcl", [csv, 128, ltx],
           directory / f"{name}.log")
    summary = summarize_capture(csv, report["dac_code"], 128)
    rows = qualified_rows(load_rows(csv, 16))
    summary["adc_raw_mean_codes"] = {
        f"CH{channel}": sum(row[f"row_ch{channel}"] for row in rows) / len(rows)
        for channel in range(8)
    }
    summary["captured_at_utc"] = datetime.now(timezone.utc).isoformat()
    return summary


def make_pair(report, after, text, unit, meter_range, notes):
    reference = reading_volts(text, unit)
    before = report["before"]
    if (before["dac_code"] != after["dac_code"]
            or abs(before["VG_V_mean"] - after["VG_V_mean"]) > 0.002):
        raise ValueError("Gate changed between the reference snapshots; repeat the meter reading")
    quantity = report["quantity"]
    if abs(before[f"{quantity}_V_mean"] - after[f"{quantity}_V_mean"]) > 0.002:
        raise ValueError("Measured node changed by >2 mV; repeat the reference reading")
    nominal = (before[f"{quantity}_V_mean"] + after[f"{quantity}_V_mean"]) / 2
    return {
        "quantity": quantity, "meter": report["meter"],
        "reference_source": "user_entered_DMM_display",
        "display_text": text, "display_unit": unit, "meter_range": meter_range,
        "reference_V": reference, "ADC_nominal_bracket_mean_V": nominal,
        "ADC_minus_DMM_V": nominal - reference,
        "before_csv": before["csv"], "after_csv": after["csv"],
        "notes": notes, "absolute_calibration_completed": False,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="DPS OFF条件下人工万用表电压参考记录")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--port", required=True)
    prepare.add_argument("--quantity", choices=tuple(QUANTITIES), default="VG")
    prepare.add_argument("--dac-code", type=int, default=256)
    prepare.add_argument("--meter", default="ALIENTEK DM40A")
    prepare.add_argument("--vivado", type=Path, default=DEFAULT_VIVADO)
    prepare.add_argument("--output-dir", type=Path, default=ROOT / "output/pcb1/manual_calibration")
    record = sub.add_parser("record")
    record.add_argument("--report", type=Path, required=True)
    record.add_argument("--reading", required=True)
    record.add_argument("--unit", required=True, choices=("V", "mV", "uV"))
    record.add_argument("--meter-range", default="not_reported")
    record.add_argument("--notes", default="")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        image = ROOT / "output/mos_fixed_vgs" / f"code_{args.dac_code:04d}"
        if not args.vivado.is_file() or not all((image / f"mos_fixed_vgs.{x}").is_file()
                                               for x in ("bit", "ltx")):
            parser.error("Vivado or matching fixed-gate image is missing")
        directory = args.output_dir.resolve() / datetime.now().strftime("reference_%Y%m%d_%H%M%S_%f")
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "reference.json"
        report = {"source": "manual_DMM_reference_with_real_ADC", "stage": "preparing",
                  "quantity": args.quantity, "dac_code": args.dac_code,
                  "meter": args.meter, "port": args.port, "vivado": str(args.vivado.resolve()),
                  "created_at_utc": datetime.now(timezone.utc).isoformat()}
    else:
        try:
            reading_volts(args.reading, args.unit)
        except ValueError as error:
            parser.error(str(error))
        path = args.report.resolve()
        report = json.loads(path.read_text(encoding="utf-8"))
        if report["stage"] != "awaiting_meter_reading":
            parser.error("Reference must be awaiting a reading; prepare a new point")
        directory = path.parent
        # Keep the actual display reading even if ADC acquisition fails. A
        # submission is only a reference pair after both snapshots validate.
        report["meter_submission"] = {
            "quantity": report["quantity"], "meter": report["meter"],
            "display_text": args.reading, "display_unit": args.unit,
            "reference_V": reading_volts(args.reading, args.unit),
            "meter_range": args.meter_range, "notes": args.notes,
            "submitted_at_utc": datetime.now(timezone.utc).isoformat(),
            "pairing_status": "pending_ADC_validation",
        }
    save(path, report)
    try:
        report["off_before"] = off(report["port"])
        if args.command == "prepare":
            # A second attempt is only performed with the drain OFF, retaining
            # any failed CSV and the failure reason as evidence.
            for attempt in range(2):
                vivado(report["vivado"], "program_mos_fixed_vgs.tcl", [report["dac_code"]],
                       directory / f"program_{attempt}.log")
                try:
                    report["before"] = snapshot(report, directory, f"before_{attempt}")
                    break
                except (ValueError, SystemExit) as error:
                    report.setdefault("invalid_captures", []).append(str(error))
                    if attempt == 1:
                        raise RuntimeError("ADC did not recover; reference point not ready") from error
            report["stage"] = "awaiting_meter_reading"
        else:
            after = snapshot(report, directory, "after")
            report["after"] = after
            pair = make_pair(report, after, args.reading, args.unit, args.meter_range, args.notes)
            report["pair"] = pair
            report["stage"] = "recorded"
            report["meter_submission"]["pairing_status"] = "accepted"
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        report["stage"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        if args.command == "record":
            report["meter_submission"]["pairing_status"] = "rejected"
            report["meter_submission"]["rejection_reason"] = report["error"]
    finally:
        try:
            report["off_after"] = off(report["port"])
        except (Exception, KeyboardInterrupt) as error:
            report["stage"] = "failed"
            report["shutdown_error"] = str(error)
        save(path, report)
    print(f"Reference: {path}")
    print(f"Stage: {report['stage']}")
    if report["stage"] == "awaiting_meter_reading":
        name = report["quantity"]
        print(f"DMM DCV: RED {QUANTITIES[name][1]}, BLACK PCB GND.")
        print(f"ADC nominal {name}: {report['before'][f'{name}_V_mean']:.9f} V")
    if report.get("pair"):
        print(json.dumps(report["pair"], ensure_ascii=False, indent=2))
    if report.get("error"):
        print(report["error"])
    return 0 if report["stage"] in ("recorded", "awaiting_meter_reading") else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
