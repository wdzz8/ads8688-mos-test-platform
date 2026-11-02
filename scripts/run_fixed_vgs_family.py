"""Build/program fixed-gate images and acquire their real PCB1 curves in order."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import serial

if __package__:
    from .capture_fixed_vgs_output import DEFAULT_VIVADO, ROOT, verified_off, summarize_capture
    from .dps_control import DpsController
else:
    from capture_fixed_vgs_output import DEFAULT_VIVADO, ROOT, verified_off, summarize_capture
    from dps_control import DpsController


def main():
    parser = argparse.ArgumentParser(description="PCB1多栅压真实输出曲线采集")
    parser.add_argument("--port", required=True)
    parser.add_argument("--codes", type=int, nargs="+", default=[2432, 2688, 2816])
    parser.add_argument("--build-missing", action="store_true")
    parser.add_argument("--vivado", type=Path, default=DEFAULT_VIVADO)
    args = parser.parse_args()
    if any(code < 0 or code > 4095 for code in args.codes) or len(set(args.codes)) != len(args.codes):
        parser.error("--codes must be distinct integers 0..4095")
    out_dir = ROOT / "output" / "pcb1" / "fixed_vgs_20261102" / datetime.now().strftime("family_%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=False)
    report_path = out_dir / "family_report.json"
    report = {"source": "real_PCB1_fixed_gate_family", "success": False,
              "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "requested_codes": args.codes, "curves": [], "off_checks": []}

    def save():
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def off(stage):
        connection = serial.Serial(port=None, baudrate=9600, timeout=1.5, write_timeout=1.5)
        connection.port = args.port
        connection.dtr = connection.rts = False
        with connection:
            status = verified_off(DpsController(connection))
        report["off_checks"].append({"stage": stage, "status": status})
        save()

    def vivado(script, code, log, timeout):
        env = os.environ.copy()
        env["PROCESSOR_ARCHITECTURE"] = "AMD64"
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(args.vivado),
                   "-mode", "batch", "-source", str(ROOT / "scripts" / script),
                   "-notrace", "-nolog", "-nojournal", "-tclargs"]
        command.extend(map(str, code if isinstance(code, list) else [code]))
        with log.open("w", encoding="utf-8") as handle:
            child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=handle,
                                     stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                result = child.wait(timeout=timeout)
                if result != 0:
                    raise RuntimeError(f"{script} exited {result}; see {log}")
            finally:
                if child.poll() is None:
                    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                                   capture_output=True, timeout=10,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    child.wait(timeout=10)

    save()
    try:
        off("before_family")
        for code in args.codes:
            image_dir = ROOT / "output" / "mos_fixed_vgs" / f"code_{code:04d}"
            missing = any(not (image_dir / f"mos_fixed_vgs.{ext}").is_file() for ext in ("bit", "ltx"))
            if missing:
                if not args.build_missing:
                    raise FileNotFoundError(f"Build missing image: {image_dir}")
                print(f"Building fixed DAC {code} (DPS OFF)", flush=True)
                vivado("build_mos_fixed_vgs.tcl", code, out_dir / f"build_{code}.log", 900)
            off(f"before_program_{code}")
            print(f"Programming fixed DAC {code} (DPS OFF)", flush=True)
            vivado("program_mos_fixed_vgs.tcl", code, out_dir / f"program_{code}.log", 60)
            code_out = out_dir / f"code_{code:04d}"
            code_out.mkdir()
            command = [sys.executable, str(ROOT / "scripts" / "capture_fixed_vgs_output.py"),
                       "--port", args.port, "--dac-code", str(code), "--vivado", str(args.vivado),
                       "--refresh-zero", "--zero-csv", str(code_out / "zero.csv"),
                       "--output-dir", str(code_out), "--cancel-file", str(code_out / "cancel.flag")]
            print(f"Acquiring zero and 7 drain levels at DAC {code}", flush=True)
            # Child captures have their own <=45 s output windows and shutdown.
            acquisition = subprocess.Popen(command, cwd=ROOT,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                capture_exit = acquisition.wait()
            except BaseException:
                # The child owns COM3. Ask it to perform its shutdown before
                # opening another serial connection in this coordinator.
                (code_out / "cancel.flag").write_text("cancel\n", encoding="ascii")
                acquisition.wait(timeout=60)
                raise
            off(f"after_capture_{code}")
            reports = list(code_out.glob("run_*/fixed_vgs_output_report.json"))
            if capture_exit or len(reports) != 1:
                raise RuntimeError(f"Acquisition failed at DAC {code}; see {code_out}")
            curve = json.loads(reports[0].read_text(encoding="utf-8"))
            if not curve["success"] or len(curve["results"]) != 7:
                raise RuntimeError(f"Incomplete curve at DAC {code}")
            report["curves"].append({"dac_code": code, "report": str(reports[0])})
            save()
        # Leave the gate at a previously built low/off level, with drain off.
        off("before_low_gate_restore")
        # Programming/DONE alone cannot prove the analog chain works. Recheck
        # low-gate ADC data, with one reinitialization retry while DPS is OFF.
        for attempt in range(2):
            vivado("program_mos_fixed_vgs.tcl", 256,
                   out_dir / f"restore_low_gate_{attempt}.log", 60)
            low_csv = out_dir / f"final_low_gate_{attempt}.csv"
            vivado("capture_mos_fixed_vgs.tcl",
                   [low_csv, 128, ROOT / "output/mos_fixed_vgs/code_0256/mos_fixed_vgs.ltx"],
                   out_dir / f"final_low_gate_{attempt}.log", 45)
            try:
                report["final_low_gate"] = summarize_capture(low_csv, 256, 128)
                break
            except (ValueError, SystemExit) as error:
                report.setdefault("restore_errors", []).append(str(error))
                if attempt == 1:
                    raise RuntimeError("Low gate analog check failed after reinitialization") from error
        report["final_dac_code"] = 256
        report["success"] = True
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        try:
            off("final_off")
        except (Exception, KeyboardInterrupt) as error:
            report["success"] = False
            report["shutdown_error"] = str(error)
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    print(f"Family report: {report_path}", flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
