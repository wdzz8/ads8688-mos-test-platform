from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.manual_voltage_calibration import main, make_pair, reading_volts


class ManualReferenceTests(unittest.TestCase):
    def test_units_are_explicit_and_exact(self):
        self.assertAlmostEqual(reading_volts("194.6", "mV"), 0.1946)
        self.assertAlmostEqual(reading_volts("-8", "uV"), -0.000008)
        for text, unit in [("nan", "V"), ("inf", "V"), ("194.6mV", "V"),
                           ("194.6", "V"), ("1", "A")]:
            with self.subTest(text=text, unit=unit), self.assertRaises(ValueError):
                reading_volts(text, unit)

    def test_pair_keeps_display_and_uses_both_real_snapshots(self):
        report = {"quantity": "VG", "meter": "DM40A", "before": {
            "dac_code": 256, "VG_V_mean": 0.1946, "csv": "before.csv"}}
        after = {"dac_code": 256, "VG_V_mean": 0.1948, "csv": "after.csv"}
        pair = make_pair(report, after, "194.1", "mV", "unknown", "manual")
        self.assertAlmostEqual(pair["ADC_minus_DMM_V"], 0.0006)
        self.assertEqual(pair["display_text"], "194.1")
        self.assertFalse(pair["absolute_calibration_completed"])
        after["VG_V_mean"] = 0.2
        with self.assertRaisesRegex(ValueError, "Gate changed"):
            make_pair(report, after, "194.1", "mV", "unknown", "")

    def test_changed_dac_code_rejects_manual_reference(self):
        report = {"quantity": "VG", "meter": "DM40A", "before": {
            "dac_code": 256, "VG_V_mean": 0.1946, "csv": "before.csv"}}
        with self.assertRaisesRegex(ValueError, "Gate changed"):
            make_pair(report, {"dac_code": 2560, "VG_V_mean": 0.1946},
                      "194.1", "mV", "unknown", "")

    def test_failed_adc_capture_preserves_unpaired_display_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.json"
            report = {"quantity": "VG", "meter": "DM40A", "port": "COM_TEST",
                      "stage": "awaiting_meter_reading", "dac_code": 2560,
                      "before": {"dac_code": 2560, "VG_V_mean": 2.0442}}
            path.write_text(json.dumps(report), encoding="utf-8")
            status = {"output_enabled": False, "voltage_out_V": 0}

            def failed_capture(*args):
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["meter_submission"]["reference_V"], 2.0533)
                raise SystemExit("all ADC channels FFFF")

            with patch("scripts.manual_voltage_calibration.off", return_value=status), \
                    patch("scripts.manual_voltage_calibration.snapshot", side_effect=failed_capture), \
                    redirect_stdout(io.StringIO()):
                result = main(["record", "--report", str(path),
                               "--reading", "2.0533", "--unit", "V"])
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result, 1)
            self.assertEqual(saved["stage"], "failed")
            self.assertEqual(saved["meter_submission"]["display_text"], "2.0533")
            self.assertEqual(saved["meter_submission"]["pairing_status"], "rejected")
            self.assertNotIn("pair", saved)
            self.assertFalse(saved["off_after"]["output_enabled"])


if __name__ == "__main__":
    unittest.main()
