"""Validate raw-evidence reloading and the distinction between offset and gain."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.analyze_fixed_vgs_family import analyze_report
from tests.test_fixed_vgs_capture import OFF, ON, write_rows


class FixedVgsAnalysisTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        zero, loaded = root / "zero.csv", root / "loaded.csv"
        write_rows(zero)
        write_rows(loaded)
        report = {"success": True, "dac_code": 2560, "capture_depth": 128,
                  "zero_csv": str(zero), "levels_V": [1],
                  "zero_summary": {"INA_OUT_V_mean": 0},
                  "results": [{"success": True, "voltage_set_V": 1,
                               "csv": str(loaded), "summary": {"VG_V_mean": 99},
                               "after": OFF, "output_on_verified": ON}]}
        path = root / "report.json"
        path.write_text(json.dumps(report))
        return path, report

    def test_rereads_csv_and_preserves_raw_source_offset(self):
        with TemporaryDirectory() as directory:
            path, _ = self.fixture(directory)
            points, summary = analyze_report(path)
            self.assertAlmostEqual(points[0]["ID_nominal_mA"], 0)
            self.assertAlmostEqual(points[0]["VS_zero_corrected_V"], 0)
            self.assertLess(points[0]["VS_raw_V"], -0.01)
            self.assertAlmostEqual(points[0]["VGS_source_zero_corrected_V"],
                                   points[0]["VG_raw_V"])
            self.assertNotEqual(points[0]["VGS_raw_V"], points[0]["VGS_source_zero_corrected_V"])
            self.assertEqual(summary["valid_rows"], 128)

    def test_shutdown_failure_rejects_cached_success(self):
        with TemporaryDirectory() as directory:
            path, report = self.fixture(directory)
            report["results"][0]["after"] = dict(ON)
            path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "shutdown"):
                analyze_report(path)

    def test_altered_raw_dac_code_rejects_cached_success(self):
        with TemporaryDirectory() as directory:
            path, report = self.fixture(directory)
            write_rows(Path(report["results"][0]["csv"]), code=2432)
            with self.assertRaisesRegex(ValueError, "DAC code"):
                analyze_report(path)


if __name__ == "__main__":
    unittest.main()
