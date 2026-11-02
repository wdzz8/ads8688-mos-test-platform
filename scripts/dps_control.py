"""DPS3005 bench control with verified writes and a bounded output pulse.

Uses Modbus 0x10 to write a single register, as documented by the public
libsigrok rdtech-dps driver. Initial bench envelope: 0..5 V, 0..50 mA.
A software stop requires a working PC/serial link; it is not hardware protection.
"""

import argparse
import json
import math
import struct
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import serial

if __package__:
    from .dps_status import (
        ProtocolError, _read_exactly, crc16_modbus, enumerate_ports,
        read_registers, read_status,
    )
else:
    from dps_status import (
        ProtocolError, _read_exactly, crc16_modbus, enumerate_ports,
        read_registers, read_status,
    )


def encode_setting(value, scale, maximum, name):
    """Reject nonfinite, out-of-range and unrepresentable requests before I/O."""
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"Invalid {name}.") from error
    if not number.is_finite() or not 0 <= number <= Decimal(str(maximum)):
        raise ValueError(f"{name} must be between 0 and {maximum}.")
    raw = number * scale
    if raw != raw.to_integral_value():
        raise ValueError(f"{name} must use increments of {1 / scale:g}.")
    return int(raw)


def write_register(connection, address, register, value):
    """Validate address, function, CRC and echoed register/count; never retry."""
    if not 1 <= address <= 255:
        raise ValueError("DPS address must be between 1 and 255.")
    if register not in (0, 1, 9) or not isinstance(value, int):
        raise ValueError("Only voltage, current limit and output switch are writable.")
    limits = {0: 500, 1: 50, 9: 1}
    if not 0 <= value <= limits[register]:
        raise ValueError("Value exceeds the initial bench envelope.")
    payload = struct.pack(">BBHHBH", address, 0x10, register, 1, 2, value)
    request = payload + struct.pack("<H", crc16_modbus(payload))
    time.sleep(4 * 11 / connection.baudrate)
    connection.reset_input_buffer()
    if connection.write(request) != len(request):
        raise OSError("The complete write request could not be sent.")
    connection.flush()
    header = _read_exactly(connection, 3)
    if header[0] != address or header[1] not in (0x10, 0x90):
        raise ProtocolError("Unexpected address or function in write response.")
    reply = header + _read_exactly(connection, 2 if header[1] == 0x90 else 5)
    if crc16_modbus(reply[:-2]) != int.from_bytes(reply[-2:], "little"):
        raise ProtocolError("CRC mismatch in write response.")
    if header[1] == 0x90:
        raise ProtocolError(f"DPS returned write exception 0x{header[2]:02X}.")
    if reply[2:6] != struct.pack(">HH", register, 1):
        raise ProtocolError("Write acknowledgement has the wrong register/count.")


class DpsController:
    def __init__(self, connection, address=1):
        self.connection = connection
        self.address = address
        self.identified = False
        self.events = []

    def status(self, stage):
        status = read_status(self.connection, self.address)
        self.identified = True
        self.events.append({"stage": stage, "status": status})
        return status

    def _write_verified(self, register, value):
        if not self.identified:
            raise ProtocolError("Identify the DPS3005 before writing.")
        self.events.append({"stage": "write_attempt", "register": register,
                            "value": value})
        write_register(self.connection, self.address, register, value)
        actual = read_registers(self.connection, self.address, register, 1)[0]
        if actual != value:
            raise ProtocolError(
                f"Register {register} readback is {actual}, expected {value}."
            )

    def off(self):
        if not self.identified:
            self.status("identify_before_off")
        self._write_verified(9, 0)
        status = self.status("output_off_verified")
        if status["output_enabled"] is not False:
            raise ProtocolError("The output-off state could not be verified.")
        return status

    def configure(self, voltage, current_limit):
        voltage_raw = encode_setting(voltage, 100, 5, "voltage (V)")
        current_raw = encode_setting(current_limit, 1000, 0.05, "current limit (A)")
        self.status("before_configure")
        # Disable and verify before changing setpoints. Stage at zero voltage
        # before setting current; never enable as a side effect of configure.
        self.off()
        self._write_verified(0, 0)
        self._write_verified(1, current_raw)
        if voltage_raw:
            self._write_verified(0, voltage_raw)
        status = self.status("configured_output_off")
        if (status["raw_registers_00_09"][:2] != [voltage_raw, current_raw]
                or status["output_enabled"] is not False):
            raise ProtocolError("Final setpoints/output state do not match the request.")
        return status

    def pulse(self, voltage, current_limit, seconds, interval=0.5):
        if (not math.isfinite(seconds) or not 0 < seconds <= 30
                or not math.isfinite(interval) or not 0.1 <= interval <= 2):
            raise ValueError("Pulse duration must be 0..30 s; interval 0.1..2 s.")
        if encode_setting(voltage, 100, 5, "voltage (V)") == 0:
            raise ValueError("Pulse voltage must be positive.")
        if encode_setting(current_limit, 1000, 0.05, "current limit (A)") == 0:
            raise ValueError("Pulse current limit must be positive.")
        self.configure(voltage, current_limit)
        samples = []
        failure = None
        try:
            configured = self.events[-1]["status"]
            if configured["protection_raw"] != 0:
                raise ProtocolError("DPS protection is active; output was not enabled.")
            started = time.monotonic()
            self._write_verified(9, 1)
            deadline = started + seconds
            while not samples or time.monotonic() < deadline:
                status = self.status("pulse_sample")
                elapsed = time.monotonic() - started
                samples.append({"elapsed_s": elapsed, **status})
                if status["output_enabled"] is not True or status["protection_raw"] != 0:
                    raise ProtocolError("DPS disabled output or reported protection during pulse.")
                if status["raw_registers_00_09"][:2] != configured["raw_registers_00_09"][:2]:
                    raise ProtocolError("Setpoints changed during pulse.")
                if status["voltage_out_V"] > float(voltage) + 0.1:
                    raise ProtocolError("Reported voltage exceeds the requested voltage + 0.1 V.")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(interval, remaining))
        except (Exception, KeyboardInterrupt) as error:
            failure = error
        try:
            final = self.off()
        except (Exception, KeyboardInterrupt) as stop_error:
            raise ProtocolError(
                f"Output-off could not be verified: {stop_error}; "
                f"preceding error: {failure}. Check the physical output."
            ) from stop_error
        if failure is not None:
            raise failure
        return {"samples": samples, "after": final}


def main(argv=None):
    parser = argparse.ArgumentParser(description="DPS3005低压台架控制（最大5V/50mA）")
    parser.add_argument("command", choices=("configure", "off", "pulse"))
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=9600, choices=(2400, 4800, 9600, 19200))
    parser.add_argument("--address", type=int, default=1, choices=range(1, 256), metavar="1..255")
    parser.add_argument("--voltage", default="0.00")
    parser.add_argument("--current-limit", default="0.020")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True, help="保存成功或失败的实际记录")
    args = parser.parse_args(argv)
    report = {"source": "device_modbus_control", "command": args.command,
              "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "transport": {"port": args.port, "baud": args.baud, "address": args.address},
              "requested": {"voltage_V": args.voltage, "current_limit_A": args.current_limit,
                            "duration_s": args.seconds if args.command == "pulse" else None},
              "success": False}
    # Establish the evidence file before any hardware changes.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    controller = None
    try:
        if args.port.upper() not in {p["port"].upper() for p in enumerate_ports()}:
            raise ValueError("Requested port does not exist.")
        connection = serial.Serial(
            port=None, baudrate=args.baud, bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
            timeout=1.5, write_timeout=1.5,
        )
        connection.port = args.port
        connection.dtr = connection.rts = False
        with connection:
            controller = DpsController(connection, args.address)
            try:
                if args.command == "configure":
                    report["after"] = controller.configure(args.voltage, args.current_limit)
                elif args.command == "off":
                    report["after"] = controller.off()
                else:
                    report.update(controller.pulse(args.voltage, args.current_limit,
                                                   args.seconds, args.interval))
                report["success"] = True
            except (Exception, KeyboardInterrupt):
                if controller.identified:
                    try:
                        report["shutdown_after_error"] = controller.off()
                    except (Exception, KeyboardInterrupt) as stop_error:
                        report["shutdown_error"] = str(stop_error)
                raise
    except (Exception, KeyboardInterrupt) as error:
        report["success"] = False
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        report["events"] = controller.events if controller else []
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
