"""Project-owned DPS3005 diagnostics; no manufacturer application required.

Only Modbus function 0x03 (read holding registers) is implemented. Register
addresses/scales were cross-checked against the public libsigrok DPS driver:
https://github.com/sigrokproject/libsigrok/tree/master/src/hardware/rdtech-dps
The actual board and communication settings still need hardware validation.
"""

import argparse
import json
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import serial
from serial.tools import list_ports


class ProtocolError(ValueError):
    """A reply could not be validated as the requested Modbus response."""


def crc16_modbus(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def _read_exactly(connection, count):
    received = bytearray()
    while len(received) < count:
        chunk = connection.read(count - len(received))
        if not chunk:
            raise TimeoutError(
                f"DPS reply timed out: received {len(received)}/{count} bytes "
                "in this part of the response. Check the port, COMM, baud and address."
            )
        received.extend(chunk)
    return bytes(received)


def read_registers(connection, address, start, count):
    if not 1 <= address <= 255:
        raise ValueError("DPS address must be between 1 and 255.")
    if not 1 <= count <= 125 or not 0 <= start <= 65536 - count:
        raise ValueError("Invalid holding-register range.")
    request = struct.pack(">BBHH", address, 0x03, start, count)
    request += struct.pack("<H", crc16_modbus(request))

    # Allow a complete RTU inter-frame gap, including at the slower baud rates.
    time.sleep(4 * 11 / connection.baudrate)
    connection.reset_input_buffer()
    if connection.write(request) != len(request):
        raise OSError("The complete read request could not be sent.")
    connection.flush()
    header = _read_exactly(connection, 3)
    if header[0] != address:
        raise ProtocolError(f"Unexpected device address: {header[0]}.")
    if header[1] not in (0x03, 0x83):
        raise ProtocolError(f"Unexpected Modbus function: 0x{header[1]:02X}.")
    if header[1] == 0x03 and header[2] != count * 2:
        raise ProtocolError(f"Unexpected byte count: {header[2]}, expected {count * 2}.")
    reply = header + _read_exactly(
        connection, 2 if header[1] == 0x83 else count * 2 + 2
    )
    if crc16_modbus(reply[:-2]) != int.from_bytes(reply[-2:], "little"):
        raise ProtocolError("CRC mismatch; no values from this response are accepted.")
    if header[1] == 0x83:
        raise ProtocolError(f"DPS returned Modbus exception 0x{header[2]:02X}.")
    return list(struct.unpack(f">{count}H", reply[3:-2]))


def read_status(connection, address=1):
    model, firmware = read_registers(connection, address, 0x0B, 2)
    if model != 3005:
        raise ProtocolError(
            f"Model register is {model}, expected 3005. "
            "Confirm the physical model before interpreting its units."
        )
    values = read_registers(connection, address, 0x00, 10)
    return {
        "source": "device_modbus_readback",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "firmware_raw": firmware,
        "voltage_set_V": values[0] / 100.0,
        "current_limit_A": values[1] / 1000.0,
        "voltage_out_V": values[2] / 100.0,
        "current_out_A": values[3] / 1000.0,
        "power_out_W": values[4] / 100.0,
        "voltage_in_V": values[5] / 100.0,
        "key_lock_raw": values[6],
        "protection_raw": values[7],
        "regulation_raw": values[8],
        "output_enabled": bool(values[9]) if values[9] in (0, 1) else None,
        "raw_registers_00_09": values,
    }


def enumerate_ports():
    result = []
    for port in sorted(list_ports.comports(), key=lambda item: item.device):
        result.append({
            "port": port.device,
            "description": port.description,
            "hwid": port.hwid,
            "vid": port.vid,
            "pid": port.pid,
            "bluetooth": "BTHENUM" in port.hwid.upper(),
        })
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="MOS 平台 DPS 端口检查和状态读取")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ports", help="列出串口，不打开设备")
    status_parser = commands.add_parser("status", help="只读取已确认端口上的 DPS3005")
    status_parser.add_argument("--port", required=True, help="已确认属于 DPS 的 COM 口")
    status_parser.add_argument("--baud", type=int, default=9600,
                               choices=(2400, 4800, 9600, 19200))
    status_parser.add_argument("--address", type=int, default=1, choices=range(1, 256),
                               metavar="1..255")
    status_parser.add_argument("--output", type=Path, help="另存实际回读 JSON")
    args = parser.parse_args(argv)

    try:
        if args.command == "ports":
            result = {"ports": enumerate_ports()}
        else:
            ports = enumerate_ports()
            if args.port.upper() not in {p["port"].upper() for p in ports}:
                raise ValueError(f"Port {args.port} does not exist; run the ports command first.")
            # Set the modem-control lines before opening the explicitly chosen port.
            connection = serial.Serial(
                port=None, baudrate=args.baud, bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                timeout=1.5, write_timeout=1.5,
            )
            connection.port = args.port
            connection.dtr = False
            connection.rts = False
            with connection:
                result = read_status(connection, args.address)
            result["transport"] = {
                "port": args.port, "baud": args.baud, "address": args.address,
            }
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        print(rendered)
        if args.command == "status" and args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        return 0
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
