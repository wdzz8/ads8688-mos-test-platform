import unittest
from pathlib import Path
import tempfile
import os
import json
import time
from unittest.mock import patch

from scripts.live_demo_server import live_payload, summarize_transfer, transfer_diagnostic, transfer_diagnostic_path
from scripts.run_transfer_curve import resume_state


class LiveTransferViewTests(unittest.TestCase):
    def test_partial_failure_keeps_only_measured_points(self):
        report = {
            "success": False,
            "error": "Vivado exited 1",
            "target_VDS_V": 0.5,
            "tolerance_V": 0.015,
            "codes": [2304, 2368, 2432, 2496],
            "results": [
                {"dac_code": 2304, "success": True, "iterations": [
                    {"iteration": 0, "VGS_V": 1.84, "VDS_V": 0.46,
                     "ID_nominal_mA": 0.04, "supply_set_V": 0.5, "error_V": 0.04,
                     "power": {"csv": "output/pcb1/run/code_2304.csv"}},
                    {"iteration": 1, "VGS_V": 1.84, "VDS_V": 0.50,
                     "ID_nominal_mA": 0.04, "supply_set_V": 0.54, "error_V": 0.0},
                ]},
                {"dac_code": 2368, "success": False, "iterations": []},
            ],
        }

        live = summarize_transfer(report, "output/pcb1/transfer/run_test/transfer_report.json", None)

        self.assertEqual(live["state"], "error")
        self.assertEqual(live["accepted_points"], 1)
        self.assertEqual(live["expected_points"], 4)
        self.assertEqual(len(live["iterations"]), 3)
        self.assertTrue(live["iterations"][1]["accepted"])
        self.assertEqual(live["iterations"][-1]["dac_code"], 2368)
        self.assertTrue(live["iterations"][-1]["acquisition_failed"])
        self.assertNotIn("VDS_V", live["iterations"][-1])
        self.assertEqual(live["last"]["VDS_V"], 0.50)
        self.assertEqual(live["iterations"][0]["raw_csv"], "output/pcb1/run/code_2304.csv")
        self.assertEqual(live["error"], "Vivado exited 1")

    def test_new_point_is_pending_until_acquisition_fails(self):
        report = {"success": False, "codes": [2304], "results": [
            {"dac_code": 2304, "success": False, "iterations": []},
        ]}
        live = summarize_transfer(report, "output/run_test/transfer_report.json", time.time())
        self.assertEqual(live["state"], "recording")
        self.assertFalse(live["iterations"][0]["acquisition_failed"])
        self.assertEqual(live["points"], [])
        self.assertIsNone(live["last"])

    def test_diagnostic_uses_device_status_and_first_failed_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "output/run_test"
            first = run_dir / "code_2496/capture.log"
            cleanup = run_dir / "restore_low/capture.log"
            first.parent.mkdir(parents=True)
            cleanup.parent.mkdir(parents=True)
            first.write_text(
                'Device xc7z020 is not programmed (DONE status = 0).\n'
                '"error "FPGA configuration status rejected: [join $invalid {; }]""\n',
                encoding="utf-8",
            )
            cleanup.write_text(first.read_text(encoding="utf-8"), encoding="utf-8")
            os.utime(first, (1000, 1000))
            os.utime(cleanup, (1001, 1001))
            with patch("scripts.live_demo_server.ROOT", root):
                report = {"error": "Vivado exited 1"}
                path = "output/run_test/transfer_report.json"
                self.assertIn("DONE status = 0", transfer_diagnostic(report, path))
                self.assertEqual(transfer_diagnostic_path(report, path),
                                 "output/run_test/code_2496/capture.log")

    def test_resume_ignores_failed_point_without_iterations(self):
        previous = {"results": [
            {"dac_code": 2304, "success": True, "iterations": [
                {"supply_set_V": 0.54, "error_V": -0.005},
            ]},
            {"dac_code": 2368, "success": False, "iterations": []},
        ]}

        points, supply = resume_state(previous)

        self.assertEqual([point["dac_code"] for point in points], [2304])
        self.assertEqual(supply, 0.54)

    def test_new_run_does_not_inherit_previous_complete_curve(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "output/pcb1/transfer/run_20261102_100000/transfer_report.json"
            new = root / "output/pcb1/transfer/run_20261103_100000/transfer_report.json"
            old.parent.mkdir(parents=True)
            old.write_text(json.dumps({"success": True, "codes": [2304], "results": [
                {"dac_code": 2304, "success": True, "iterations": [
                    {"VDS_V": 0.5, "VGS_V": 1.8, "ID_nominal_mA": 0.04},
                ]},
            ]}), encoding="utf-8")
            with patch("scripts.live_demo_server.ROOT", root):
                self.assertEqual(live_payload()["transfer"]["accepted_points"], 1)
                new.parent.mkdir(parents=True)
                new.write_text(json.dumps({"success": False, "codes": [2304],
                                           "results": []}), encoding="utf-8")
                live = live_payload()["transfer"]
                self.assertEqual(live["run_id"], "run_20261103_100000")
                self.assertEqual(live["accepted_points"], 0)
                self.assertEqual(live["points"], [])
                self.assertIsNone(live["last"])


if __name__ == "__main__":
    unittest.main()
