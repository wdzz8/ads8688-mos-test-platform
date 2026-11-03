"""Serve the demo dashboard and read-only views of real acquisition reports."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.experiment_data import load_capture


def iso_time(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")


def relative_path(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def latest_report(folder: str, filename: str) -> Path | None:
    candidates = list((ROOT / folder).glob(f"run_*/{filename}"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.parent.name)


def read_report(path: Path | None) -> tuple[dict | None, str | None, float | None]:
    if path is None:
        return None, None, None
    try:
        modified = path.stat().st_mtime
        report = json.loads(path.read_text(encoding="utf-8"))
        return report, relative_path(str(path)), modified
    except (OSError, json.JSONDecodeError):
        return None, relative_path(str(path)), None


def report_state(report: dict, modified: float | None) -> str:
    if report.get("success") is True:
        return "complete"
    if report.get("error") or report.get("cleanup_error") or report.get("shutdown_error"):
        return "error"
    if modified is not None and time.time() - modified <= 90:
        return "recording"
    return "incomplete"


def transfer_diagnostic(report: dict, report_name: str | None) -> str | None:
    if not report_name or not report.get("error"):
        return None
    run_dir = (ROOT / report_name).parent
    logs = sorted(run_dir.rglob("capture.log"), key=lambda item: item.stat().st_mtime)
    for log in logs:
        try:
            content = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        not_programmed = re.findall(r"Device xc7z020[^\r\n]*not programmed[^\r\n]*", content)
        if not_programmed:
            return "Vivado 检测到 FPGA 未配置（DONE status = 0）"
        status = dict(re.findall(
            r"FPGA_STATUS REGISTER\.CONFIG_STATUS\.(BIT(?:04|11|12|13|14)_[A-Z_]+)=(\d+)",
            content,
        ))
        failed = [name for name, value in status.items() if value != "1"]
        if failed:
            return "FPGA 配置状态未通过：" + ", ".join(failed)
    return None


def transfer_diagnostic_path(report: dict, report_name: str | None) -> str | None:
    if not report_name or not report.get("error"):
        return None
    run_dir = (ROOT / report_name).parent
    logs = sorted(run_dir.rglob("capture.log"), key=lambda item: item.stat().st_mtime)
    for log in logs:
        try:
            content = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "not programmed" in content or re.search(
            r"FPGA_STATUS REGISTER\.CONFIG_STATUS\.BIT(?:04|11|12|13|14)_[A-Z_]+=0",
            content,
        ):
            return relative_path(str(log))
    return None


def summarize_transfer(report: dict | None, path: str | None, modified: float | None) -> dict:
    if report is None:
        return {"available": False, "state": "waiting", "points": [], "iterations": []}
    state = report_state(report, modified)
    points = []
    iterations = []
    for item in report.get("results", []):
        item_iterations = item.get("iterations", [])
        for capture in item_iterations:
            power = capture.get("power") or {}
            row = {
                "dac_code": item.get("dac_code"),
                "iteration": capture.get("iteration"),
                "VGS_V": capture.get("VGS_V"),
                "VDS_V": capture.get("VDS_V"),
                "ID_nominal_mA": capture.get("ID_nominal_mA"),
                "supply_set_V": capture.get("supply_set_V"),
                "error_V": capture.get("error_V"),
                "accepted": bool(item.get("success")) and
                            capture is item_iterations[-1],
                "raw_csv": relative_path(power.get("csv")),
            }
            iterations.append(row)
        if not item_iterations and not item.get("success"):
            iterations.append({
                "dac_code": item.get("dac_code"),
                "iteration": None,
                "accepted": False,
                "acquisition_failed": state in {"error", "incomplete"},
            })
        if item.get("success") and item_iterations:
            capture = item_iterations[-1]
            points.append({
                "dac_code": item.get("dac_code"),
                "VGS_V": capture.get("VGS_V"),
                "VDS_V": capture.get("VDS_V"),
                "ID_nominal_mA": capture.get("ID_nominal_mA"),
                "iteration": capture.get("iteration"),
            })

    last_capture = next((row for row in reversed(iterations)
                         if row.get("VDS_V") is not None), None)
    last_power = None
    for item in reversed(report.get("results", [])):
        captures = item.get("iterations", [])
        if captures:
            last_power = captures[-1].get("power")
            break
    off_status = report.get("final_off")
    if off_status is None and last_power:
        off_status = last_power.get("off_after")
    active_item = next((item for item in reversed(report.get("results", []))
                        if not item.get("success")), None)
    return {
        "available": True,
        "state": state,
        "run_id": Path(path).parent.name if path else None,
        "path": path,
        "started_at_utc": report.get("started_at_utc"),
        "updated_at_utc": iso_time(modified) if modified else None,
        "age_s": max(0, time.time() - modified) if modified else None,
        "target_VDS_V": report.get("target_VDS_V"),
        "tolerance_V": report.get("tolerance_V"),
        "expected_points": len(report.get("codes", [])),
        "accepted_points": len(points),
        "current_dac_code": active_item.get("dac_code") if active_item else None,
        "current_iteration": (len(active_item.get("iterations", []))
                              if active_item else None),
        "last": last_capture,
        "points": points,
        "iterations": iterations,
        "dps_output_enabled": (off_status.get("output_enabled")
                               if off_status else None),
        "dps_voltage_out_V": off_status.get("voltage_out_V") if off_status else None,
        "error": report.get("error") or report.get("cleanup_error") or
                 report.get("shutdown_error"),
        "diagnostic": transfer_diagnostic(report, path),
        "diagnostic_path": transfer_diagnostic_path(report, path),
        "resumed_from": relative_path(report.get("resumed_from")),
    }


@lru_cache(maxsize=12)
def dynamic_trace(csv_path: str, modified_ns: int, expected_rows: int,
                  low_code: int, high_code: int, frequency: float) -> dict:
    del modified_ns
    rows = load_capture(csv_path, expected_rows, {low_code, high_code})
    times = [row["time_CH0_s"] for row in rows]
    vg = [row["CH0_V"] for row in rows]
    vd = [row["CH1_V"] for row in rows]
    ordered = sorted(vg)
    threshold = (ordered[int(0.1 * (len(ordered) - 1))] +
                 ordered[int(0.9 * (len(ordered) - 1))]) / 2
    state = [value >= threshold for value in vg]
    rising = [times[i] for i in range(1, len(state)) if state[i] and not state[i - 1]]
    periods = [b - a for a, b in zip(rising, rising[1:]) if b > a]
    measured = 1 / (sum(periods) / len(periods)) if periods else None
    duties = []
    for start, end in zip(rising, rising[1:]):
        indices = [i for i, stamp in enumerate(times) if start <= stamp < end]
        if indices:
            duties.append(sum(state[i] for i in indices) / len(indices))
    stride = max(1, len(rows) // 1200)
    sample = list(range(0, len(rows), stride))
    if sample[-1] != len(rows) - 1:
        sample.append(len(rows) - 1)
    return {
        "requested_frequency_Hz": frequency,
        "measured_frequency_Hz": measured,
        "duty_mean": sum(duties) / len(duties) if duties else None,
        "valid_rows": len(rows),
        "trace": [{"t": times[i], "t_vd": rows[i]["time_CH1_s"],
                   "vg": vg[i], "vd": vd[i]} for i in sample],
    }


def summarize_dynamic(report: dict | None, path: str | None, modified: float | None) -> dict:
    if report is None:
        return {"available": False, "state": "waiting", "results": []}
    results = []
    for item in report.get("results", []):
        powered = item.get("powered") or {}
        csv_value = powered.get("csv")
        trace = None
        trace_error = None
        if item.get("success") and csv_value:
            capture_path = Path(csv_value)
            if not capture_path.is_absolute():
                capture_path = ROOT / capture_path
            try:
                stat = capture_path.stat()
                trace = dynamic_trace(
                    str(capture_path), stat.st_mtime_ns, 8192,
                    int(report.get("low_code", 256)),
                    int(report.get("high_code", 2816)),
                    float(item.get("frequency_Hz", 0)),
                )
            except (OSError, ValueError, StopIteration) as error:
                trace_error = str(error)
        results.append({
            "frequency_Hz": item.get("frequency_Hz"),
            "success": bool(item.get("success")),
            "valid_rows": (powered.get("summary") or {}).get("valid_rows"),
            "trace": trace,
            "trace_error": trace_error,
            "csv": relative_path(csv_value),
            "dps_off": (powered.get("off_after") or {}).get("output_enabled") is False,
        })
    return {
        "available": True,
        "state": report_state(report, modified),
        "run_id": Path(path).parent.name if path else None,
        "path": path,
        "started_at_utc": report.get("started_at_utc"),
        "updated_at_utc": iso_time(modified) if modified else None,
        "age_s": max(0, time.time() - modified) if modified else None,
        "results": results,
        "expected_frequencies": len(report.get("requested_frequencies_Hz", [1, 5, 10])),
        "completed_frequencies": sum(result["success"] for result in results),
        "dps_output_enabled": ((report.get("final_off") or {}).get("output_enabled")),
        "error": report.get("error") or report.get("cleanup_error"),
    }


def live_payload() -> dict:
    transfer_path = latest_report("output/pcb1/transfer", "transfer_report.json")
    dynamic_path = latest_report("output/pcb1/dynamic", "dynamic_report.json")
    transfer, transfer_name, transfer_modified = read_report(transfer_path)
    dynamic, dynamic_name, dynamic_modified = read_report(dynamic_path)
    return {
        "server_time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "poll_interval_ms": 1000,
        "transfer": summarize_transfer(transfer, transfer_name, transfer_modified),
        "dynamic": summarize_dynamic(dynamic, dynamic_name, dynamic_modified),
    }


class DemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if urlparse(self.path).path == "/api/live":
            body = json.dumps(live_payload(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if urlparse(self.path).path == "/":
            self.path = "/demo/index.html"
        return super().do_GET()

    def log_message(self, format, *args):
        if args and str(args[1]) != "200":
            super().log_message(format, *args)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), DemoHandler)
    print(f"Live MOS dashboard: http://127.0.0.1:{port}/demo/index.html", flush=True)
    print("Read-only local report monitor; start acquisition from PowerShell.", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
