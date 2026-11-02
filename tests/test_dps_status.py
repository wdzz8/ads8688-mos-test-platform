"""Synthetic serial responses validate the parser, not physical DPS operation."""

import struct
import unittest

from scripts.dps_status import ProtocolError, crc16_modbus, read_registers, read_status


def frame(payload):
    return payload + struct.pack("<H", crc16_modbus(payload))


def register_reply(values):
    return frame(bytes((1, 3, len(values) * 2)) + struct.pack(f">{len(values)}H", *values))


class FakeSerial:
    baudrate = 9600

    def __init__(self, responses, fragment_size=1):
        self.responses = list(responses)
        self.buffer = b""
        self.requests = []
        self.fragment_size = fragment_size

    def reset_input_buffer(self):
        self.buffer = b""

    def write(self, request):
        self.requests.append(request)
        self.buffer = self.responses.pop(0)
        return len(request)

    def flush(self):
        pass

    def read(self, count):
        count = min(count, self.fragment_size)
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data


class DpsStatusTests(unittest.TestCase):
    def test_crc_known_vectors(self):
        self.assertEqual(crc16_modbus(b"123456789"), 0x4B37)
        self.assertEqual(frame(bytes.fromhex("01030000000a")),
                         bytes.fromhex("01030000000ac5cd"))

    def test_fragmented_status_and_only_read_requests(self):
        values = [100, 20, 99, 2, 0, 1200, 0, 0, 0, 0]
        connection = FakeSerial([register_reply([3005, 15]), register_reply(values)])
        status = read_status(connection)
        self.assertEqual(status["voltage_set_V"], 1.0)
        self.assertEqual(status["current_limit_A"], 0.020)
        self.assertEqual(status["voltage_out_V"], 0.99)
        self.assertEqual(status["current_out_A"], 0.002)
        self.assertEqual(status["voltage_in_V"], 12.0)
        self.assertFalse(status["output_enabled"])
        self.assertEqual([r[1] for r in connection.requests], [3, 3])
        self.assertEqual([r[2:6] for r in connection.requests],
                         [bytes.fromhex("000b0002"), bytes.fromhex("0000000a")])

    def test_wrong_model_stops_before_reading_scaled_status(self):
        connection = FakeSerial([register_reply([5015, 15])])
        with self.assertRaisesRegex(ProtocolError, "expected 3005"):
            read_status(connection)
        self.assertEqual(len(connection.requests), 1)

    def test_bad_crc_is_rejected(self):
        response = bytearray(register_reply([3005, 15]))
        response[-1] ^= 1
        with self.assertRaisesRegex(ProtocolError, "CRC mismatch"):
            read_registers(FakeSerial([bytes(response)]), 1, 11, 2)

    def test_valid_device_exception_is_reported(self):
        with self.assertRaisesRegex(ProtocolError, "exception 0x02"):
            read_registers(FakeSerial([frame(bytes((1, 0x83, 2)))]), 1, 11, 2)

    def test_wrong_address_function_and_length_are_rejected(self):
        for header in [bytes((2, 3, 4)), bytes((1, 6, 4)), bytes((1, 3, 2))]:
            with self.subTest(header=header):
                with self.assertRaises(ProtocolError):
                    read_registers(FakeSerial([header]), 1, 11, 2)

    def test_truncated_reply_fails_without_returning_values(self):
        with self.assertRaises(TimeoutError):
            read_registers(FakeSerial([register_reply([3005, 15])[:-1]]), 1, 11, 2)

    def test_invalid_request_does_not_touch_serial(self):
        connection = FakeSerial([])
        for address, start, count in [(0, 11, 2), (1, 65535, 2), (1, 0, 126)]:
            with self.subTest(address=address, start=start, count=count):
                with self.assertRaises(ValueError):
                    read_registers(connection, address, start, count)
        self.assertEqual(connection.requests, [])


if __name__ == "__main__":
    unittest.main()
