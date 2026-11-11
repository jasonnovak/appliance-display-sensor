#!/usr/bin/env python3
"""One bounded, passive system sample. Standalone stdlib; never reads app config."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil
import subprocess


def interface_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,14}", value):
        raise argparse.ArgumentTypeError("Use a Linux interface name, e.g. wlan0")
    return value


def read(root: Path, relative: str) -> str:
    try:
        with (root / relative).open(encoding="utf-8") as stream:
            return stream.read(8192)
    except (OSError, UnicodeError):
        return ""


def number(value: str, *, integer: bool = False) -> float | int | None:
    try:
        result = int(value) if integer else float(value)
        return result if math.isfinite(result) else None
    except (ValueError, OverflowError):
        return None


def command(arguments: list[str]) -> str:
    try:
        return subprocess.run(arguments, capture_output=True, text=True, timeout=4,
                              check=True).stdout[:8192]
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return ""


def sample(interface: str = "wlan0", root: Path = Path("/")) -> dict[str, object]:
    interface_name(interface)
    result: dict[str, object] = {"schema_version": 1,
        "time": datetime.now(timezone.utc).isoformat()}
    boot = read(root, "proc/sys/kernel/random/boot_id").strip()
    result["boot_id"] = boot if re.fullmatch(r"[0-9a-f-]{36}", boot) else None
    result["uptime_seconds"] = number(read(root, "proc/uptime").partition(" ")[0])
    load = read(root, "proc/loadavg").split()
    result["load_average"] = [number(v) for v in load[:3]] if len(load) >= 3 else None
    temperature = number(read(root, "sys/class/thermal/thermal_zone0/temp"))
    result["temperature_c"] = round(temperature / 1000, 1) if temperature is not None else None
    memory = {}
    for line in read(root, "proc/meminfo").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in {"MemAvailable:", "SwapTotal:", "SwapFree:"}:
            memory[parts[0][:-1]] = number(parts[1], integer=True)
    result["memory_available_kib"] = memory.get("MemAvailable")
    total, free = memory.get("SwapTotal"), memory.get("SwapFree")
    result["swap_used_kib"] = max(0, total - free) if None not in (total, free) else None
    result["wifi_signal_dbm"] = None
    for line in read(root, "proc/net/wireless").splitlines():
        name, separator, counters = line.partition(":")
        if separator and name.strip() == interface:
            fields = counters.split()
            if len(fields) >= 3:
                result["wifi_signal_dbm"] = number(fields[2])
    for field in ("rx_bytes", "tx_bytes", "rx_errors", "tx_errors"):
        result[field] = number(read(root, f"sys/class/net/{interface}/statistics/{field}"),
                               integer=True)
    try:
        result["disk_free_bytes"] = shutil.disk_usage(root).free
    except OSError:
        result["disk_free_bytes"] = None
    flags = command(["vcgencmd", "get_throttled"]).strip()
    match = re.fullmatch(r"throttled=(0x[0-9a-fA-F]{1,8})", flags)
    result["throttled_flags"] = match.group(1) if match else None
    # Fixed property allowlist; do not log status output, environment, command
    # lines, Wi-Fi scans, IP addresses or subprocess error text.
    properties = command(["systemctl", "show", "appliance-display-sensor.service",
        "--no-pager", "-p", "LoadState", "-p", "ActiveState", "-p", "SubState",
        "-p", "NRestarts", "-p", "MainPID"])
    values = dict(line.split("=", 1) for line in properties.splitlines() if "=" in line)
    allowed = {
        "LoadState": {"loaded", "not-found", "error", "bad-setting", "masked", "merged", "stub"},
        "ActiveState": {"active", "inactive", "failed", "activating", "deactivating",
                        "reloading", "maintenance", "refreshing"},
        "SubState": {"running", "dead", "failed", "exited", "start", "start-pre", "start-post",
                     "stop", "stop-sigterm", "stop-sigkill", "stop-post", "auto-restart",
                     "auto-restart-queued", "reload", "condition", "cleaning"},
    }
    service = {key: values.get(key) if values.get(key) in options else None
               for key, options in allowed.items()}
    for key in ("NRestarts", "MainPID"):
        service[key] = number(values.get(key, ""), integer=True)
    result["service"] = service
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", type=interface_name, default="wlan0")
    args = parser.parse_args()
    print(json.dumps(sample(args.interface), separators=(",", ":"), allow_nan=False))


if __name__ == "__main__":
    main()
