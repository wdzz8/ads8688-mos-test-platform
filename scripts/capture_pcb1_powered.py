"""Capture one PCB1 gate sweep at 1, 2 or 3 V supply, then switch DPS off.

Requires an already programmed FPGA and confirmed MCP/OPA/PCB wiring.
This performs a real, bounded hardware operation; it is not a simulation.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import serial

from dps_control import DpsController
from plot_mos_scan import average_by_point, load_rows, qualified_rows, to_volts


ROOT = Path(__file__).resolve().parent.parent


def validate_gate_tracking(rows, reference_rows=None):
    """Reject an incomplete/clipped analog staircase despite healthy I2C flags."""
    points = average_by_point(rows)
    if [point["point"] for point in points] != list(range(32)):
        raise ValueError("Gate sweep must contain all 32 points.")
    gates = [to_volts(point["row_ch0"], 0) for point in points]
    if not (-0.1 <= gates[0] <= 0.1 and 2.9 <= gates[-1] <= 3.5):
        raise ValueError("Measured gate endpoints are outside the verified 0..3.2 V staircase.")
    if any(not 0.05 <= b - a <= 0.16 for a, b in zip(gates, gates[1:])):
        raise ValueError("Measured gate staircase has a clipped or incorrect step.")
    if reference_rows is not None:
        reference = validate_gate_tracking(reference_rows)
        if any(abs(a - b) > 0.05 for a, b in zip(gates, reference)):
            raise ValueError("Measured gate voltage differs from the zero capture by more than 50 mV.")
    return gates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--zero-csv", required=True, type=Path)
    # These discrete low-voltage levels were selected for the verified 990-ohm
    # drain resistor and the existing CH1 0..5.12 V ADC range.
    parser.add_argument("--voltage", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--vivado", type=Path,
                        default=Path(r"D:\FPGAvivado\Vivado\2022.2\bin\vivado.bat"))
    args = parser.parse_args()
    # Validate prerequisites before opening the power-control link.
    zero_path = args.zero_csv.resolve()
    zero_rows = qualified_rows(load_rows(zero_path, 16))
    validate_gate_tracking(zero_rows)
    if not args.vivado.is_file():
        raise SystemExit(f"Vivado not found: {args.vivado}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = ROOT / "output" / "pcb1" / "live_capture_20261102"
    output.mkdir(parents=True, exist_ok=True)
    prefix = output / f"powered_{stamp}"
    report_path = prefix.with_suffix(".json")
    stdout_path = prefix.with_suffix(".stdout.log")
    report = {
        "source": "real_pcb1_DPS_and_ILA_capture", "success": False,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "zero_csv": str(zero_path), "voltage_set_V": float(args.voltage),
        "current_limit_A": 0.020, "capture_rows_requested": 256,
        "maximum_output_window_s": 25.0,
    }

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)
                               + "\n", encoding="utf-8")

    def check_status(status):
        if (status["output_enabled"] is not True or status["protection_raw"] != 0
                or status["raw_registers_00_09"][:2] != [args.voltage * 100, 20]
                or not args.voltage - 0.1 <= status["voltage_out_V"] <= args.voltage + 0.1):
            raise RuntimeError("DPS output, setpoints, protection or voltage changed.")

    save()
    connection = serial.Serial(port=None, baudrate=9600, timeout=1.5,
                               write_timeout=1.5)
    connection.port = args.port
    connection.dtr = connection.rts = False
    controller = None
    process = None
    try:
        with connection, stdout_path.open("w", encoding="utf-8") as stdout:
            controller = DpsController(connection)
            try:
                configured = controller.configure(f"{args.voltage:.2f}", "0.020")
                if configured["protection_raw"] != 0:
                    raise RuntimeError("DPS protection active before enabling.")
                started = time.monotonic()
                controller._write_verified(9, 1)
                time.sleep(0.25)
                report["output_on_verified"] = controller.status("scan_output_on_verified")
                check_status(report["output_on_verified"])
                print(f"DPS {args.voltage:.2f} V ON verified; acquiring 256 ILA rows...", flush=True)
                command = [
                    os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(args.vivado),
                    "-mode", "batch", "-source",
                    str(ROOT / "scripts" / "capture_mos_scan_batch.tcl"), "-notrace",
                    "-log", str(prefix.with_suffix(".vivado.log")),
                    "-journal", str(prefix.with_suffix(".jou")), "-tclargs", "256",
                ]
                process = subprocess.Popen(
                    command, cwd=ROOT, stdout=stdout, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                samples = report["samples"] = []
                while process.poll() is None:
                    if time.monotonic() - started >= 25:
                        raise TimeoutError("ILA did not finish within the output window.")
                    status = controller.status("scan_sample")
                    check_status(status)
                    samples.append({"elapsed_s": time.monotonic() - started, **status})
                    time.sleep(0.25)
                report["capture_finished_elapsed_s"] = time.monotonic() - started
                if report["capture_finished_elapsed_s"] >= 25:
                    raise TimeoutError("Capture exceeded the output window.")
                if process.returncode != 0:
                    raise RuntimeError(f"Vivado capture exit code: {process.returncode}")
                stdout.flush()
                log = stdout_path.read_text(encoding="utf-8", errors="replace")
                match = re.search(r"Exported: ([^\r\n]+\.csv)", log)
                if match is None:
                    raise RuntimeError("No qualified capture exported; raw fallback is not accepted.")
                csv_path = Path(match.group(1))
                report["capture_csv"] = str(csv_path)
                rows = qualified_rows(load_rows(csv_path, 16))
                if len(rows) != 256 or any(
                    row["point"] != index % 32 or row.get("vg_code") != row["point"] * 128
                    for index, row in enumerate(rows)
                ):
                    raise RuntimeError("Invalid point sequence or incomplete powered capture.")
                report["valid_rows"] = len(rows)
                report["capture_completed_before_shutdown"] = True
                report["measured_gate_voltages_V"] = validate_gate_tracking(rows, zero_rows)
                report["gate_tracking_accepted"] = True
                report["success"] = True
            finally:
                # Always close the power path before terminating a stalled readout.
                try:
                    if controller.identified:
                        report["after"] = controller.off()
                        print("DPS output OFF verified.", flush=True)
                finally:
                    if process is not None and process.poll() is None:
                        process.kill()
    except (Exception, KeyboardInterrupt) as error:
        report["success"] = False
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        report["events"] = controller.events if controller else []
        save()
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ("events", "samples")}, ensure_ascii=False, indent=2))
    print(f"Report: {report_path}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
