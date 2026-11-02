"""Capture fixed-VGS output curves while stepping the DPS drain voltage.

The FPGA image must already be programmed. The script arms the ILA and controls
the bounded DPS output, recording whether shutdown was verified. Each
drain-voltage point is saved as an independent ILA CSV and a
JSON report keeps the DPS readbacks beside it.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

import serial

if __package__:
    from .dps_control import DpsController, encode_setting
    from .plot_mos_scan import load_rows, qualified_rows, to_volts
else:
    from dps_control import DpsController, encode_setting
    from plot_mos_scan import load_rows, qualified_rows, to_volts


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VIVADO = Path(r"D:\FPGAvivado\Vivado\2022.2\bin\vivado.bat")
DEFAULT_LEVELS = (0.20, 0.50, 1.00, 1.50, 2.00, 2.50, 3.00)
RANGES = (0, 6, 0, 6, 0, 0, 0, 6)


def parse_levels(text: str) -> list[float]:
    """Parse DPS voltage levels and reject values outside the safe envelope."""
    values = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            raise ValueError("levels must be comma-separated numbers")
        try:
            value = float(token)
        except ValueError as error:
            raise ValueError(f"invalid DPS voltage: {token!r}") from error
        if not math.isfinite(value) or not 0.0 < value <= 3.0:
            raise ValueError("PCB1 DPS voltage levels must be in (0, 3] V")
        values.append(encode_setting(token, 100, 3, "voltage (V)") / 100)
    if not values or len(set(values)) != len(values):
        raise ValueError("levels must contain at least one unique voltage")
    return values


def volts(rows, channel: int) -> list[float]:
    return [to_volts(row[f"row_ch{channel}"], RANGES[channel]) for row in rows]


def summarize_capture(path: Path, dac_code: int, expected_rows: int | None = None,
                      reference: dict | None = None) -> dict:
    """Validate one fixed-VGS capture and return raw-node summary statistics."""
    path = Path(path)
    rows = qualified_rows(load_rows(path, 16))
    if expected_rows is not None and len(rows) != expected_rows:
        raise ValueError(f"{path.name}: expected {expected_rows} valid rows, got {len(rows)}")
    if len(rows) < 128:
        raise ValueError(f"{path.name}: fewer than 128 valid rows")
    if any(row.get("point") != 0 for row in rows):
        raise ValueError(f"{path.name}: fixed-VGS point is not zero")
    if any(row.get("vg_code") != dac_code for row in rows):
        raise ValueError(f"{path.name}: vg_code does not match DAC code {dac_code}")
    values = {
        "VG_V": volts(rows, 0),
        "VD_V": volts(rows, 1),
        "VS_V": volts(rows, 2),
        "INA_OUT_V": volts(rows, 7),
    }
    result = {"csv": str(path), "valid_rows": len(rows), "dac_code": dac_code}
    for name, samples in values.items():
        result[f"{name}_mean"] = statistics.fmean(samples)
        result[f"{name}_min"] = min(samples)
        result[f"{name}_max"] = max(samples)
        result[f"{name}_sd"] = statistics.pstdev(samples) if len(samples) > 1 else 0.0
    result["VGS_mean_V"] = result["VG_V_mean"] - result["VS_V_mean"]
    result["VDS_mean_V"] = result["VD_V_mean"] - result["VS_V_mean"]
    expected_vg = -0.008 + 3.28 * dac_code / 4096
    if abs(result["VG_V_mean"] - expected_vg) > 0.05:
        raise ValueError("Measured gate differs from the verified DAC staircase by >50 mV")
    vgs = [gate - source for gate, source in zip(values["VG_V"], values["VS_V"])]
    result["VGS_span_V"] = max(vgs) - min(vgs)
    if result["VG_V_max"] - result["VG_V_min"] > 0.020 or result["VGS_span_V"] > 0.020:
        raise ValueError("Gate is not stable within 20 mV")
    if reference is not None and abs(result["VG_V_mean"] - reference["VG_V_mean"]) > 0.010:
        raise ValueError("Measured gate differs from its DPS-OFF reference by >10 mV")
    return result


def verified_off(controller):
    status = controller.off()
    if status["output_enabled"] is not False or status["voltage_out_V"] != 0:
        raise RuntimeError("DPS output-off / zero voltage could not be verified")
    return status


def check_cancel(args):
    path = getattr(args, "cancel_file", None)
    if path is not None and Path(path).exists():
        raise InterruptedError("Acquisition cancelled by coordinator")


def check_enabled(status: dict, voltage: float, current_limit: str) -> None:
    expected_voltage = encode_setting(f"{voltage:.2f}", 100, 5, "voltage (V)")
    expected_current = encode_setting(current_limit, 1000, 0.05, "current limit (A)")
    if (status["output_enabled"] is not True or status["protection_raw"] != 0
            or status["raw_registers_00_09"][:2] != [expected_voltage, expected_current]
            or abs(status["voltage_out_V"] - voltage) > 0.1):
        raise RuntimeError("DPS output, setpoints, protection or voltage changed")


def capture_process(args, csv_path: Path, log_path: Path):
    command = [
        os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(args.vivado),
        "-mode", "batch", "-source", str(ROOT / "scripts" / "capture_mos_fixed_vgs.tcl"),
        "-notrace", "-nolog", "-nojournal", "-tclargs", str(csv_path),
        str(args.depth), str(args.ltx),
    ]
    env = os.environ.copy()
    # The execution host used by the desktop shell does not always export this
    # Windows variable; Vivado's loader refuses to start without it.
    env["PROCESSOR_ARCHITECTURE"] = "AMD64"
    log_handle = log_path.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=log_handle, stderr=subprocess.STDOUT, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except BaseException:
        log_handle.close()
        raise
    return process, log_handle


def capture_point(args, controller, level: float, run_dir: Path, zero: dict) -> dict:
    """Stop power before CSV validation or terminating a stalled child process."""
    stamp = f"{level:.2f}".replace(".", "p")
    csv_path = run_dir / f"supply_{stamp}V.csv"
    log_path = run_dir / f"supply_{stamp}V.vivado.log"
    item = {"voltage_set_V": level, "csv": str(csv_path), "log": str(log_path),
            "success": False, "samples": []}
    process = log_handle = None
    started = None
    try:
        check_cancel(args)
        configured = controller.configure(f"{level:.2f}", args.current_limit)
        item["configured_off"] = configured
        if configured["protection_raw"] != 0:
            raise RuntimeError("DPS protection active before enabling")
        check_cancel(args)
        started = time.monotonic()
        controller._write_verified(9, 1)
        time.sleep(0.25)
        enabled = controller.status(f"fixed_vgs_{level:.2f}_on_verified")
        check_enabled(enabled, level, args.current_limit)
        item["output_on_verified"] = enabled
        process, log_handle = capture_process(args, csv_path, log_path)
        while process.poll() is None:
            check_cancel(args)
            if time.monotonic() - started >= args.timeout:
                raise TimeoutError(f"ILA capture exceeded {args.timeout:.1f} s")
            status = controller.status(f"fixed_vgs_{level:.2f}_sample")
            item["samples"].append({"elapsed_s": time.monotonic() - started, **status})
            check_enabled(status, level, args.current_limit)
            time.sleep(0.5)
        item["capture_finished_elapsed_s"] = time.monotonic() - started
        if item["capture_finished_elapsed_s"] >= args.timeout:
            raise TimeoutError("Capture finished outside the output window")
        if process.returncode != 0:
            raise RuntimeError(f"Vivado capture exit code: {process.returncode}")
        if not csv_path.is_file():
            raise RuntimeError("Vivado completed without exporting the CSV")
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        item["error"] = f"{type(error).__name__}: {error}"
    finally:
        try:
            item["after"] = verified_off(controller)
            if started is not None:
                item["output_off_verified_elapsed_s"] = time.monotonic() - started
        except (Exception, KeyboardInterrupt, SystemExit) as error:
            item["shutdown_error"] = f"{type(error).__name__}: {error}"
        # The launched cmd process has a Vivado child; kill only this tree,
        # after the power shutdown attempt, without touching the user's GUI.
        try:
            if process is not None and process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   capture_output=True, timeout=10,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                else:
                    process.kill()
                process.wait(timeout=10)
        except Exception as error:
            item["process_cleanup_error"] = str(error)
        finally:
            if log_handle is not None:
                log_handle.close()
    if not any(key in item for key in ("error", "shutdown_error", "process_cleanup_error")):
        try:
            item["summary"] = summarize_capture(csv_path, args.dac_code, args.depth, zero)
            item["success"] = True
        except (Exception, KeyboardInterrupt, SystemExit) as error:
            item["error"] = f"{type(error).__name__}: {error}"
    return item


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="固定VGS输出特性：逐级设置DPS并采集ILA")
    parser.add_argument("--port", required=True)
    parser.add_argument("--dac-code", type=int, default=2560)
    parser.add_argument("--zero-csv", required=True, type=Path)
    parser.add_argument("--levels", default=",".join(f"{v:.2f}" for v in DEFAULT_LEVELS))
    parser.add_argument("--current-limit", default="0.020")
    parser.add_argument("--depth", type=int, choices=(128, 256, 512, 1024), default=128)
    parser.add_argument("--vivado", type=Path, default=DEFAULT_VIVADO)
    parser.add_argument("--ltx", type=Path, default=None)
    parser.add_argument("--refresh-zero", action="store_true",
                        help="DPS关闭并回读后重新采零点，--zero-csv作为本次新文件路径")
    parser.add_argument("--cancel-file", type=Path,
                        help="协调程序创建此文件时停止采集并关闭DPS")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "output" / "pcb1" / "fixed_vgs_20261102")
    args = parser.parse_args(argv)

    if not 0 <= args.dac_code <= 4095:
        parser.error("--dac-code must be 0..4095")
    try:
        levels = parse_levels(args.levels)
        current_raw = encode_setting(args.current_limit, 1000, 0.020, "current limit (A)")
        if current_raw == 0:
            raise ValueError("current limit must be positive")
    except ValueError as error:
        parser.error(str(error))
    args.zero_csv = args.zero_csv.resolve()
    args.vivado = args.vivado.resolve()
    args.ltx = (args.ltx or ROOT / "output" / "mos_fixed_vgs"
                / f"code_{args.dac_code:04d}" / "mos_fixed_vgs.ltx").resolve()
    if not args.refresh_zero and not args.zero_csv.is_file():
        parser.error(f"zero CSV not found: {args.zero_csv}")
    if args.refresh_zero and args.zero_csv.exists():
        parser.error("--refresh-zero requires a new path to preserve existing evidence")
    if not args.vivado.is_file():
        parser.error(f"Vivado not found: {args.vivado}")
    if not args.ltx.is_file():
        parser.error(f"LTX file not found: {args.ltx}")
    if not math.isfinite(args.timeout) or not 10 <= args.timeout <= 45:
        parser.error("--timeout must be between 10 and 45 seconds")
    if args.depth != 128:
        parser.error("bounded PCB1 powered capture currently supports --depth 128")

    zero = None
    if not args.refresh_zero:
        try:
            zero = summarize_capture(args.zero_csv, args.dac_code)
        except (OSError, ValueError, SystemExit) as error:
            parser.error(f"invalid zero capture: {error}")
    args.output_dir = args.output_dir.resolve()
    run_dir = args.output_dir / datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
    run_dir.mkdir(parents=True, exist_ok=False)
    report_path = run_dir / "fixed_vgs_output_report.json"
    report = {
        "source": "real_pcb1_fixed_vgs_DPS_and_ILA_capture",
        "success": False,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "transport": {"port": args.port, "baud": 9600, "address": 1},
        "dac_code": args.dac_code,
        "zero_csv": str(args.zero_csv),
        "zero_summary": zero,
        "levels_V": levels,
        "current_limit_A": args.current_limit,
        "capture_depth": args.depth, "maximum_output_window_s": args.timeout,
        "vivado": str(args.vivado),
        "ltx": str(args.ltx),
        "results": [],
    }

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")

    save()
    controller = None
    connection = None
    try:
        connection = serial.Serial(port=None, baudrate=9600, bytesize=serial.EIGHTBITS,
                                   parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                                   timeout=1.5, write_timeout=1.5)
        connection.port = args.port
        connection.dtr = connection.rts = False
        with connection:
            controller = DpsController(connection, 1)
            try:
                report["initial_off"] = verified_off(controller)
                if args.refresh_zero:
                    zero_log = run_dir / "zero_capture.vivado.log"
                    process, log_handle = capture_process(args, args.zero_csv, zero_log)
                    try:
                        process.wait(timeout=45)
                        if process.returncode != 0:
                            raise RuntimeError(f"Zero capture failed; see {zero_log}")
                    finally:
                        try:
                            report["zero_after_off"] = verified_off(controller)
                        finally:
                            if process.poll() is None:
                                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                               capture_output=True, timeout=10,
                                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                                process.wait(timeout=10)
                            log_handle.close()
                    zero = summarize_capture(args.zero_csv, args.dac_code, args.depth)
                    if zero["VD_V_max"] > 0.05:
                        raise ValueError("Drain voltage is not near zero in DPS-OFF capture")
                    report["zero_summary"] = zero
                    save()
                for level in levels:
                    print(f"DAC {args.dac_code}: acquiring supply {level:.2f} V", flush=True)
                    item = capture_point(args, controller, level, run_dir, zero)
                    report["results"].append(item)
                    save()
                    if not item["success"]:
                        raise RuntimeError(item.get("error", item.get("shutdown_error", "capture failed")))
                report["success"] = True
            finally:
                if controller.identified:
                    try:
                        report["final_off"] = verified_off(controller)
                    except (Exception, KeyboardInterrupt, SystemExit) as error:
                        report["success"] = False
                        report["final_off_error"] = f"{type(error).__name__}: {error}"
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        report["success"] = False
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        report["events"] = controller.events if controller else []
        save()
    print(json.dumps({"success": report["success"], "dac_code": args.dac_code,
                      "points": len(report["results"]), "error": report.get("error"),
                      "final_off": report.get("final_off")}, ensure_ascii=False, indent=2))
    print(f"Report: {report_path}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
