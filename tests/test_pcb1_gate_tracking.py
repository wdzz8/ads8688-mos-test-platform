"""Analog gate checks must reject the observed clipping with healthy bus flags."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from capture_pcb1_powered import validate_gate_tracking


def make_rows(voltages):
    return [{"point": point, "row_valid": 1,
             "row_ch0": round(32768 + voltage / 0.0003125)}
            for point, voltage in enumerate(voltages)]


class GateTrackingTests(unittest.TestCase):
    def test_verified_staircase_with_small_repeat_noise_is_accepted(self):
        reference = make_rows([-0.008 + point * 0.1026 for point in range(32)])
        loaded = make_rows([-0.007 + point * 0.1026 for point in range(32)])
        self.assertEqual(len(validate_gate_tracking(loaded, reference)), 32)

    def test_clipped_analog_gate_is_rejected(self):
        clipped = make_rows([0.626 + point * 0.0494 for point in range(32)])
        with self.assertRaisesRegex(ValueError, "endpoints"):
            validate_gate_tracking(clipped)

    def test_midrange_clipping_is_rejected_even_when_endpoints_are_correct(self):
        voltages = [-0.008 + point * 0.1026 for point in range(32)]
        voltages[21] = voltages[20]
        with self.assertRaisesRegex(ValueError, "step"):
            validate_gate_tracking(make_rows(voltages))


if __name__ == "__main__":
    unittest.main()
