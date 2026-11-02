"""Exercise failure handling with a synthetic DPS; hardware evidence is separate."""

import struct
import unittest
from unittest.mock import patch

from scripts.dps_control import DpsController, encode_setting, write_register
from scripts.dps_status import ProtocolError, crc16_modbus


def frame(payload):
    return payload + struct.pack("<H", crc16_modbus(payload))


class SimulatedDps:
    baudrate = 9600

    def __init__(self):
        self.registers = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 1198,
                          6: 0, 7: 0, 8: 0, 9: 0, 11: 3005, 12: 14}
        self.requests = []
        self.writes = []
        self.buffer = b""
        self.ignore_register = None
        self.corrupt_enable_ack = False
        self.disconnect_once_enabled = False
        self.protect_once_enabled = False

    def reset_input_buffer(self):
        self.buffer = b""

    def flush(self):
        pass

    def write(self, request):
        self.requests.append(request)
        assert crc16_modbus(request[:-2]) == int.from_bytes(request[-2:], "little")
        address, function, register, count = struct.unpack(">BBHH", request[:6])
        if function == 0x10:
            assert count == 1 and request[6] == 2
            value = int.from_bytes(request[7:9], "big")
            self.writes.append((register, value, self.registers[9]))
            if register != self.ignore_register:
                self.registers[register] = value
            self.buffer = frame(struct.pack(">BBHH", address, function, register, count))
            if register == 9 and value == 1 and self.corrupt_enable_ack:
                self.buffer = self.buffer[:-1] + bytes([self.buffer[-1] ^ 1])
        else:
            assert function == 3
            if self.registers[9] and self.disconnect_once_enabled:
                self.disconnect_once_enabled = False
                self.buffer = b""
                return len(request)
            if self.registers[9] and self.protect_once_enabled:
                self.registers[7] = 2
            self.registers[2] = self.registers[0] if self.registers[9] else 0
            values = [self.registers.get(i, 0) for i in range(register, register + count)]
            self.buffer = frame(bytes((address, function, count * 2))
                                + struct.pack(f">{count}H", *values))
        return len(request)

    def read(self, count):
        # Every frame arrives in fragments, including exceptions and write ACKs.
        count = min(count, 2)
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data


@patch("scripts.dps_control.time.sleep")
class DpsControlTests(unittest.TestCase):
    def test_configure_disables_before_setpoints_and_keeps_output_off(self, _sleep):
        board = SimulatedDps()
        board.registers[9] = 1
        result = DpsController(board).configure("1.00", "0.020")
        self.assertEqual(result["voltage_set_V"], 1)
        self.assertEqual(result["current_limit_A"], 0.020)
        self.assertFalse(result["output_enabled"])
        self.assertEqual(board.writes[0][:2], (9, 0))
        self.assertTrue(all(enabled == 0 for reg, val, enabled in board.writes if reg != 9))
        self.assertNotIn((9, 1), [(reg, val) for reg, val, _ in board.writes])

    def test_wrong_model_has_no_writes(self, _sleep):
        board = SimulatedDps()
        board.registers[11] = 5015
        with self.assertRaises(ProtocolError):
            DpsController(board).configure("1.00", "0.020")
        self.assertEqual(board.writes, [])

    def test_invalid_settings_do_not_touch_hardware(self, _sleep):
        for value in ("NaN", "Infinity", "-0.01", "5.01", "1.001"):
            with self.subTest(value=value):
                board = SimulatedDps()
                with self.assertRaises(ValueError):
                    DpsController(board).configure(value, "0.020")
                self.assertEqual(board.requests, [])
        self.assertEqual(encode_setting("0.029", 1000, 0.05, "current"), 29)

    def test_readback_mismatch_prevents_enabling(self, _sleep):
        board = SimulatedDps()
        board.ignore_register = 1
        with self.assertRaisesRegex(ProtocolError, "readback"):
            DpsController(board).pulse("1.00", "0.020", 1)
        self.assertFalse(board.registers[9])
        self.assertNotIn((9, 1), [(reg, val) for reg, val, _ in board.writes])

    def test_pulse_finishes_with_verified_output_off(self, _sleep):
        board = SimulatedDps()
        with patch("scripts.dps_control.time.monotonic", side_effect=[0, 0.01, 0.02]):
            result = DpsController(board).pulse("1.00", "0.020", 0.001)
        self.assertTrue(result["samples"][0]["output_enabled"])
        self.assertEqual(result["samples"][0]["voltage_out_V"], 1)
        self.assertFalse(result["after"]["output_enabled"])
        self.assertEqual(board.writes[-1][:2], (9, 0))

    def test_corrupted_enable_ack_still_sends_output_off(self, _sleep):
        board = SimulatedDps()
        board.corrupt_enable_ack = True
        with self.assertRaisesRegex(ProtocolError, "CRC"):
            DpsController(board).pulse("1.00", "0.020", 1)
        self.assertEqual(board.writes[-1][:2], (9, 0))
        self.assertFalse(board.registers[9])

    def test_pulse_does_not_start_another_sample_at_deadline(self, _sleep):
        board = SimulatedDps()
        with patch("scripts.dps_control.time.monotonic", side_effect=[0, 0.1, 0.2, 1]):
            result = DpsController(board).pulse("1.00", "0.020", 1)
        self.assertEqual(len(result["samples"]), 1)
        self.assertFalse(board.registers[9])

    def test_failed_shutdown_is_reported_as_failure(self, _sleep):
        class IgnoredShutdown(SimulatedDps):
            def write(self, request):
                if request[1] == 0x10 and request[2:4] == b"\x00\x09":
                    value = int.from_bytes(request[7:9], "big")
                    if value == 0 and self.registers[9] == 1:
                        self.ignore_register = 9
                return super().write(request)

        board = IgnoredShutdown()
        with patch("scripts.dps_control.time.monotonic", side_effect=[0, 0.01, 0.02]):
            with self.assertRaisesRegex(ProtocolError, "Output-off could not be verified"):
                DpsController(board).pulse("1.00", "0.020", 0.001)
        self.assertEqual(board.registers[9], 1)

    def test_transient_receive_timeout_after_enabling_sends_output_off(self, _sleep):
        board = SimulatedDps()
        board.disconnect_once_enabled = True
        with self.assertRaises(TimeoutError):
            DpsController(board).pulse("1.00", "0.020", 1)
        self.assertEqual(board.writes[-1][:2], (9, 0))
        self.assertFalse(board.registers[9])

    def test_existing_protection_never_enables(self, _sleep):
        board = SimulatedDps()
        board.registers[7] = 2
        with self.assertRaisesRegex(ProtocolError, "protection is active"):
            DpsController(board).pulse("1.00", "0.020", 1)
        self.assertNotIn((9, 1), [(reg, val) for reg, val, _ in board.writes])

    def test_protection_during_pulse_stops_output(self, _sleep):
        board = SimulatedDps()
        board.protect_once_enabled = True
        with self.assertRaisesRegex(ProtocolError, "reported protection"):
            DpsController(board).pulse("1.00", "0.020", 1)
        self.assertFalse(board.registers[9])

    def test_write_mismatched_ack_and_exception_are_rejected(self, _sleep):
        class BadAck(SimulatedDps):
            def write(self, request):
                super().write(request)
                self.buffer = response
                return len(request)

        for response in (
            frame(bytes.fromhex("011000010001")),  # Wrong echoed register.
            frame(bytes.fromhex("011000000002")),  # Wrong count.
            frame(bytes.fromhex("021000000001")),  # Wrong address.
            frame(bytes.fromhex("019002")),        # Modbus exception.
        ):
            with self.subTest(response=response.hex()):
                with self.assertRaises(ProtocolError):
                    write_register(BadAck(), 1, 0, 100)


if __name__ == "__main__":
    unittest.main()
