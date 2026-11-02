"""Verify physical channel decoding and zero subtraction using synthetic CSVs."""

import csv
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "plot_mos_scan.py"
HEADER = ["Sample in Buffer", "point[4:0]", "vg_code[11:0]"] + [
    f"row_ch{i}[15:0]" for i in range(8)
] + ["row_valid", "init_done", "init_error", "dac_ready", "dac_error"]


def write_capture(path, current_codes, *, init_error=0):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerow(["Radix - UNSIGNED"] + ["HEX"] * (len(HEADER) - 1))
        for index, code in enumerate(current_codes):
            # PCB1: CH0=2.5 V, CH1=1 V, CH2=0 V. CH3 deliberately differs
            # from CH2 to expose reuse of the old bench channel mapping.
            channels = [40768, 12800, 32768, 25600, 32768, 32768, 32768, code]
            values = [index, index % 2, (index % 2) * 128] + channels + [
                1, 1, init_error, 1, 0
            ]
            writer.writerow([format(value, "x") for value in values])


class PlotMosScanTests(unittest.TestCase):
    def run_plot(self, capture, *args):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(capture), *map(str, args)],
            capture_output=True, text=True, encoding="utf-8", env=env,
            timeout=30,
        )

    def test_pcb_channels_and_fresh_zero_are_used_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            zero, loaded = root / "zero.csv", root / "loaded.csv"
            # Current zero is 2.510 V, deliberately unlike the old 2.499 V.
            write_capture(zero, [32127, 32129])
            write_capture(loaded, [32154, 32154])
            result = self.run_plot(loaded, "--profile", "pcb1", "--zero-csv", zero)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with loaded.with_name("loaded_points.csv").open(newline="") as handle:
                points = list(csv.DictReader(handle))
            self.assertEqual(len(points), 2)
            for point in points:
                self.assertAlmostEqual(float(point["VGS"]), 2.5)
                self.assertAlmostEqual(float(point["VDS"]), 1.0)
                self.assertAlmostEqual(float(point["ID_mA"]), 1.015625)
            self.assertTrue(loaded.with_name("loaded_curve.png").is_file())

    def test_pcb_requires_current_zero_measurement(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "loaded.csv"
            write_capture(capture, [32154])
            result = self.run_plot(capture, "--profile", "pcb1")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--zero-csv", result.stderr)
            self.assertFalse(capture.with_name("loaded_points.csv").exists())

    def test_gate_matched_zero_removes_gate_dependent_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            zero, loaded = root / "zero.csv", root / "loaded.csv"
            write_capture(zero, [32000, 32016, 32000, 32016])
            write_capture(loaded, [32026, 32042, 32026, 32042])
            result = self.run_plot(loaded, "--profile", "pcb1", "--zero-csv", zero,
                                   "--zero-by-point")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with loaded.with_name("loaded_points.csv").open(newline="") as handle:
                points = list(csv.DictReader(handle))
            for point in points:
                self.assertAlmostEqual(float(point["ID_mA"]), 1.015625)
                self.assertEqual(point["ID_ZERO_METHOD"], "point_and_DAC_matched")
                self.assertAlmostEqual(float(point["INA_OUT_V"]) - float(point["INA_ZERO_V"]),
                                       26 * 5.12 / 65536)

    def test_mismatched_gate_codes_stop_point_zero_subtraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            zero, loaded = root / "zero.csv", root / "loaded.csv"
            write_capture(zero, [32000, 32016])
            write_capture(loaded, [32026, 32042])
            contents = zero.read_text(encoding="utf-8")
            zero.write_text(contents.replace("1,1,80,", "1,1,100,"), encoding="utf-8")
            result = self.run_plot(loaded, "--profile", "pcb1", "--zero-csv", zero,
                                   "--zero-by-point")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("DAC", result.stderr)
            self.assertFalse(loaded.with_name("loaded_points.csv").exists())

    def test_adc_initialization_error_stops_measurement(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "bad.csv"
            write_capture(capture, [32154], init_error=1)
            result = self.run_plot(
                capture, "--profile", "pcb1", "--id-offset-v", "2.51"
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(capture.with_name("bad_points.csv").exists())


if __name__ == "__main__":
    unittest.main()
