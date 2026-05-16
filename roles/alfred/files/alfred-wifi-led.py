#!/usr/bin/env python3
"""Drive the Alfred WiFi status LED from OS-level NetworkManager state."""

import argparse
import ctypes
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time

I2C_RDWR = 0x0707
I2C_M_RD = 0x0001
STOP = False


class I2CMessage(ctypes.Structure):
    _fields_ = [
        ("addr", ctypes.c_uint16),
        ("flags", ctypes.c_uint16),
        ("length", ctypes.c_uint16),
        ("buffer", ctypes.POINTER(ctypes.c_uint8)),
    ]


class I2CRdwrData(ctypes.Structure):
    _fields_ = [
        ("messages", ctypes.POINTER(I2CMessage)),
        ("message_count", ctypes.c_uint32),
    ]


def i2c_read_byte(bus_path, address):
    read_buffer = (ctypes.c_uint8 * 1)()
    messages = (I2CMessage * 1)(I2CMessage(address, I2C_M_RD, 1, read_buffer))
    transaction = I2CRdwrData(messages, len(messages))
    with open(bus_path, "rb+", buffering=0) as bus:
        fcntl.ioctl(bus.fileno(), I2C_RDWR, transaction)
    return int(read_buffer[0])


def i2c_write_byte(bus_path, address, value):
    write_buffer = (ctypes.c_uint8 * 1)(value & 0xFF)
    messages = (I2CMessage * 1)(I2CMessage(address, 0, 1, write_buffer))
    transaction = I2CRdwrData(messages, len(messages))
    with open(bus_path, "rb+", buffering=0) as bus:
        fcntl.ioctl(bus.fileno(), I2C_RDWR, transaction)


def i2c_read_register(bus_path, address, register):
    write_buffer = (ctypes.c_uint8 * 1)(register)
    read_buffer = (ctypes.c_uint8 * 1)()
    messages = (I2CMessage * 2)(
        I2CMessage(address, 0, 1, write_buffer),
        I2CMessage(address, I2C_M_RD, 1, read_buffer),
    )
    transaction = I2CRdwrData(messages, len(messages))
    with open(bus_path, "rb+", buffering=0) as bus:
        fcntl.ioctl(bus.fileno(), I2C_RDWR, transaction)
    return int(read_buffer[0])


def i2c_write_register(bus_path, address, register, value):
    write_buffer = (ctypes.c_uint8 * 2)(register, value & 0xFF)
    messages = (I2CMessage * 1)(I2CMessage(address, 0, 2, write_buffer))
    transaction = I2CRdwrData(messages, len(messages))
    with open(bus_path, "rb+", buffering=0) as bus:
        fcntl.ioctl(bus.fileno(), I2C_RDWR, transaction)


def _stop(_signum, _frame):
    global STOP
    STOP = True


def env(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def env_bool(name, default):
    value = env(name, "1" if default else "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


def env_int(name, default):
    try:
        return int(env(name, str(default)), 0)
    except ValueError as exc:
        raise SystemExit(f"invalid integer for {name}: {env(name, str(default))}") from exc


def run(argv):
    try:
        return subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return exc


class Config:
    def __init__(self):
        self.backend = env("WIFI_LED_BACKEND", "panel").strip().lower()
        self.interface = env("WIFI_LED_INTERFACE", "wlan0").strip()
        self.interval = max(1, env_int("WIFI_LED_INTERVAL", 2))
        self.require_default_route = env_bool("WIFI_LED_REQUIRE_DEFAULT_ROUTE", True)
        self.degraded_rssi_dbm = env_int("WIFI_LED_DEGRADED_RSSI_DBM", -75)
        self.health_host = env("WIFI_LED_HEALTH_HOST", "").strip()
        self.act_led = env("WIFI_LED_ACT_LED", "/sys/class/leds/ACT").strip()
        self.panel_bus = env("WIFI_LED_PANEL_I2C_BUS", "/dev/i2c-1").strip()
        self.panel_address = env_int("WIFI_LED_PANEL_I2C_ADDRESS", 0x22)
        self.panel_mux_address = env_int("WIFI_LED_PANEL_MUX_ADDRESS", 0x70)
        self.panel_mux_channel = env_int("WIFI_LED_PANEL_MUX_CHANNEL", 0)
        self.panel_green_port = env_int("WIFI_LED_PANEL_GREEN_PORT", 0)
        self.panel_green_pin = env_int("WIFI_LED_PANEL_GREEN_PIN", 0)
        self.panel_red_port = env_int("WIFI_LED_PANEL_RED_PORT", 0)
        self.panel_red_pin = env_int("WIFI_LED_PANEL_RED_PIN", 1)
        if self.backend not in {"panel", "act", "disabled"}:
            raise SystemExit(f"invalid WIFI_LED_BACKEND {self.backend!r}; expected panel, act, or disabled")
        if self.panel_mux_channel < -1 or self.panel_mux_channel > 7:
            raise SystemExit("invalid WIFI_LED_PANEL_MUX_CHANNEL; expected -1 or 0..7")


def network_state(cfg):
    if not cfg.interface or not os.path.exists(f"/sys/class/net/{cfg.interface}"):
        return "red", ["interface-missing"]

    reasons = []
    connected = False
    nmcli = run(["nmcli", "-t", "-f", "GENERAL.STATE", "device", "show", cfg.interface])
    if isinstance(nmcli, subprocess.CompletedProcess) and nmcli.returncode == 0:
        match = re.search(r"(\d+)", nmcli.stdout)
        state_code = int(match.group(1)) if match else None
        if state_code == 100:
            connected = True
        elif state_code in {40, 50, 60, 70, 80, 90}:
            return "orange", [f"networkmanager-state-{state_code}"]
        else:
            return "red", [f"networkmanager-state-{state_code or 'unknown'}"]
    else:
        try:
            operstate = PathLike(f"/sys/class/net/{cfg.interface}/operstate").read().strip()
            connected = operstate == "up"
            if not connected:
                return "red", [f"operstate-{operstate or 'unknown'}"]
        except OSError:
            return "red", ["operstate-unavailable"]

    if not connected:
        return "red", ["not-connected"]

    if cfg.require_default_route:
        route = run(["ip", "-4", "route", "show", "default", "dev", cfg.interface])
        if not isinstance(route, subprocess.CompletedProcess) or route.returncode != 0 or not route.stdout.strip():
            reasons.append("no-default-route")

    iw = run(["iw", "dev", cfg.interface, "link"])
    if isinstance(iw, subprocess.CompletedProcess) and iw.returncode == 0:
        if "Not connected" in iw.stdout:
            return "red", ["iw-not-connected"]
        match = re.search(r"signal:\s*(-?\d+)\s*dBm", iw.stdout)
        if match and int(match.group(1)) < cfg.degraded_rssi_dbm:
            reasons.append(f"weak-rssi-{match.group(1)}dBm")

    if cfg.health_host:
        ping = run(["ping", "-I", cfg.interface, "-c", "1", "-W", "1", cfg.health_host])
        if not isinstance(ping, subprocess.CompletedProcess) or ping.returncode != 0:
            reasons.append("health-host-unreachable")

    return ("orange", reasons) if reasons else ("green", ["connected"])


class PathLike:
    def __init__(self, path):
        self.path = path

    def read(self):
        with open(self.path, "r", encoding="utf-8") as handle:
            return handle.read()

    def write(self, value):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(str(value))


class PanelBackend:
    needs_periodic_apply = False

    def __init__(self, cfg):
        self.cfg = cfg

    def _read_reg(self, register):
        return i2c_read_register(self.cfg.panel_bus, self.cfg.panel_address, register)

    def _write_reg(self, register, value):
        i2c_write_register(self.cfg.panel_bus, self.cfg.panel_address, register, value)

    def _select_panel_channel(self):
        if self.cfg.panel_mux_channel < 0:
            return None
        original = i2c_read_byte(self.cfg.panel_bus, self.cfg.panel_mux_address)
        mask = 1 << self.cfg.panel_mux_channel
        if original != mask:
            i2c_write_byte(self.cfg.panel_bus, self.cfg.panel_mux_address, mask)
        return original

    def _restore_mux(self, original):
        if original is not None:
            i2c_write_byte(self.cfg.panel_bus, self.cfg.panel_mux_address, original)

    def _set_bit(self, port, pin, level):
        mask = 1 << pin
        config_register = 6 + port
        output_register = 2 + port
        config = self._read_reg(config_register)
        self._write_reg(config_register, config & ~mask)
        output = self._read_reg(output_register)
        if level:
            output |= mask
        else:
            output &= ~mask
        self._write_reg(output_register, output)

    def apply(self, status):
        if status == "green":
            green, red = True, False
        elif status == "orange":
            green, red = True, True
        else:
            green, red = False, True
        mux_state = self._select_panel_channel()
        try:
            self._set_bit(self.cfg.panel_green_port, self.cfg.panel_green_pin, green)
            self._set_bit(self.cfg.panel_red_port, self.cfg.panel_red_pin, red)
        finally:
            self._restore_mux(mux_state)

    def wait(self, _status, seconds):
        wait_for(seconds)


class ActBackend:
    needs_periodic_apply = True

    def __init__(self, cfg):
        self.cfg = cfg
        if not os.path.isdir(cfg.act_led):
            raise SystemExit(f"ACT LED path not found: {cfg.act_led}")
        trigger = os.path.join(cfg.act_led, "trigger")
        if os.path.exists(trigger):
            PathLike(trigger).write("none")

    def _brightness(self, value):
        PathLike(os.path.join(self.cfg.act_led, "brightness")).write("1" if value else "0")

    def apply(self, status):
        if status == "green":
            self._brightness(True)
        elif status == "orange":
            self._brightness(True)
        else:
            self._brightness(False)

    def wait(self, status, seconds):
        end = time.monotonic() + seconds
        if status == "green":
            wait_for(seconds)
            return
        delay = 1.0 if status == "orange" else 0.25
        state = True
        while not STOP and time.monotonic() < end:
            self._brightness(state)
            state = not state
            wait_for(min(delay, max(0, end - time.monotonic())))


class DisabledBackend:
    needs_periodic_apply = False

    def apply(self, _status):
        return

    def wait(self, _status, seconds):
        wait_for(seconds)


def wait_for(seconds):
    deadline = time.monotonic() + seconds
    while not STOP and time.monotonic() < deadline:
        time.sleep(min(0.2, deadline - time.monotonic()))


def backend_for(cfg):
    if cfg.backend == "panel":
        return PanelBackend(cfg)
    if cfg.backend == "act":
        return ActBackend(cfg)
    return DisabledBackend()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="evaluate and apply one status update")
    parser.add_argument("--print-status", action="store_true", help="print JSON status records to stdout")
    parser.add_argument("--check-config", action="store_true", help="parse configuration without touching hardware")
    args = parser.parse_args()

    cfg = Config()
    if args.check_config:
        print(json.dumps({"backend": cfg.backend, "interface": cfg.interface, "panelAddress": hex(cfg.panel_address), "panelMuxAddress": hex(cfg.panel_mux_address), "panelMuxChannel": cfg.panel_mux_channel}))
        return 0

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    backend = backend_for(cfg)
    last = None

    while not STOP:
        status, reasons = network_state(cfg)
        record = {"status": status, "reasons": reasons, "interface": cfg.interface, "backend": cfg.backend}
        changed = status != last
        if args.print_status or changed:
            print(json.dumps(record), flush=True)
        try:
            if backend.needs_periodic_apply or changed:
                backend.apply(status)
        except OSError as exc:
            print(json.dumps({"status": "error", "error": str(exc), "backend": cfg.backend}), file=sys.stderr, flush=True)
        else:
            last = status
        if args.once:
            return 0
        backend.wait(status, cfg.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
