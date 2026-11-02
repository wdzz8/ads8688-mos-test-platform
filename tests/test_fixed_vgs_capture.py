"""Synthetic fault tests for powered fixed-gate acquisition; no hardware I/O."""

import csv
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import capture_fixed_vgs_output as capture


OFF = {"output_enabled": False, "voltage_out_V": 0, "protection_raw": 0}
ON = {"output_enabled": True, "protection_raw": 0, "voltage_out_V": 1,
      "raw_registers_00_09": [100, 20]}


def write_rows(path, *, gate=2.044, code=2560, last_gate=None):
    fields = ["Sample in Buffer", "point", "vg_code", "row_valid", "init_done",
              "init_error", "dac_ready", "dac_error"] + [f"row_ch{i}" for i in range(8)]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        for index in range(128):
            voltage = last_gate if index == 127 and last_gate is not None else gate
            data = [round(32768 + voltage / 0.0003125), 1000, 32727,
                    32768, 32768, 32768, 32768, 32000]
            writer.writerow([format(v, "x") for v in
                             [index, 0, code, 1, 1, 0, 1, 0] + data])


class FixedVgsTests(unittest.TestCase):
    def test_levels_reject_rounding_nonfinite_and_unverified_supply_range(self):
        for value in ("1.001", "1.005", "3.01", "0", "nan", "inf", "1,1", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                capture.parse_levels(value)
        self.assertEqual(capture.parse_levels("0.2,0.50,3"), [0.2, 0.5, 3])

    def test_gate_flags_alone_do_not_accept_clipping_or_instability(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.csv"
            write_rows(path)
            self.assertEqual(capture.summarize_capture(path, 2560, 128)["valid_rows"], 128)
            write_rows(path, gate=1.6)
            with self.assertRaisesRegex(ValueError, "50 mV"):
                capture.summarize_capture(path, 2560, 128)
            write_rows(path, last_gate=2.08)
            with self.assertRaisesRegex(ValueError, "20 mV"):
                capture.summarize_capture(path, 2560, 128)
            write_rows(path, code=2432)
            with self.assertRaisesRegex(ValueError, "DAC code"):
                capture.summarize_capture(path, 2560, 128)

    def test_powered_gate_is_checked_against_matched_zero(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.csv"
            write_rows(path, gate=2.060)
            with self.assertRaisesRegex(ValueError, "10 mV"):
                capture.summarize_capture(path, 2560, 128, {"VG_V_mean": 2.044})

    def run_point(self, directory, controller, **mocks):
        args = SimpleNamespace(dac_code=2560, depth=128, current_limit="0.020", timeout=45)
        with patch.object(capture.time, "sleep"), \
             patch.object(capture, "capture_process", **mocks):
            return capture.capture_point(args, controller, 1.0, Path(directory), {})

    def controller(self):
        controller = Mock()
        controller.events = []
        controller.configure.return_value = dict(OFF)
        controller.status.return_value = dict(ON)
        controller.off.return_value = dict(OFF)
        return controller

    def test_protection_prevents_enable(self):
        controller = self.controller()
        controller.configure.return_value["protection_raw"] = 2
        with TemporaryDirectory() as directory:
            result = self.run_point(directory, controller)
        self.assertFalse(result["success"])
        controller._write_verified.assert_not_called()
        controller.off.assert_called_once()

    def test_cancellation_prevents_starting_new_output(self):
        controller = self.controller()
        with TemporaryDirectory() as directory:
            args = SimpleNamespace(dac_code=2560, depth=128, current_limit="0.020",
                                   timeout=45, cancel_file=Path(directory) / "cancel.flag")
            args.cancel_file.write_text("cancel")
            item = capture.capture_point(args, controller, 1.0, Path(directory), {})
        self.assertFalse(item["success"])
        controller.configure.assert_not_called()
        controller._write_verified.assert_not_called()
        controller.off.assert_called_once()

    def test_enable_exception_and_interrupt_both_attempt_off(self):
        for error in (TimeoutError("serial"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), TemporaryDirectory() as directory:
                controller = self.controller()
                controller._write_verified.side_effect = error
                result = self.run_point(directory, controller)
                self.assertFalse(result["success"])
                controller.off.assert_called_once()

    def test_csv_parser_systemexit_is_reported_after_power_off(self):
        controller = self.controller()
        process = Mock(returncode=0)
        process.poll.return_value = 0
        with TemporaryDirectory() as directory:
            (Path(directory) / "supply_1p00V.csv").write_text("synthetic")
            with patch.object(capture, "summarize_capture", side_effect=SystemExit("FFFF")):
                result = self.run_point(directory, controller,
                                        return_value=(process, io.StringIO()))
        self.assertFalse(result["success"])
        self.assertIn("SystemExit", result["error"])
        self.assertFalse(result["after"]["output_enabled"])

    def test_output_off_failure_cannot_be_success(self):
        controller = self.controller()
        controller.off.side_effect = TimeoutError("shutdown")
        process = Mock(returncode=0)
        process.poll.return_value = 0
        with TemporaryDirectory() as directory:
            (Path(directory) / "supply_1p00V.csv").write_text("synthetic")
            result = self.run_point(directory, controller,
                                    return_value=(process, io.StringIO()))
        self.assertFalse(result["success"])
        self.assertIn("shutdown_error", result)

    def test_timeout_stops_power_before_process_cleanup(self):
        events = []
        controller = self.controller()
        controller.off.side_effect = lambda: (events.append("off") or dict(OFF))
        process = Mock()
        process.poll.return_value = None
        process.kill.side_effect = lambda: events.append("kill")
        with TemporaryDirectory() as directory, \
             patch.object(capture.time, "monotonic", side_effect=[0, 100, 101]), \
             patch.object(capture.subprocess, "run", side_effect=lambda *a, **k: events.append("kill")):
            result = self.run_point(directory, controller,
                                    return_value=(process, io.StringIO()))
        self.assertFalse(result["success"])
        self.assertEqual(events[:2], ["off", "kill"])

    def test_final_off_is_inside_open_serial_context_and_failure_sets_exit_code(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            zero = root / "zero.csv"
            zero.write_text("synthetic")
            connection = Mock()
            connection.__enter__ = Mock(return_value=connection)
            connection.__exit__ = Mock()
            controller = self.controller()
            with patch.object(capture.serial, "Serial", return_value=connection), \
                 patch.object(capture, "DpsController", return_value=controller), \
                 patch.object(capture, "summarize_capture", return_value={}), \
                 patch.object(capture, "capture_point", return_value={"success": True}), \
                 patch.object(capture, "verified_off", side_effect=[dict(OFF), TimeoutError("off")]), \
                 patch("sys.stdout", new=io.StringIO()):
                code = capture.main(["--port", "FAKE", "--zero-csv", str(zero),
                                     "--levels", "1", "--output-dir", str(root)])
            report = json.loads(next(root.glob("run_*/fixed_vgs_output_report.json")).read_text())
            self.assertEqual(code, 1)
            self.assertFalse(report["success"])
            self.assertIn("final_off_error", report)


if __name__ == "__main__":
    unittest.main()
