"""Cheap, passive system observations; no commands, network probes, or secrets."""
from __future__ import annotations

import threading
import time
from pathlib import Path


class SystemHealth:
    def __init__(self, root: Path = Path("/")):
        self.root = root
        self._lock = threading.Lock()
        self._sampled_at: float | None = None
        self._sample: dict[str, float | None] = {}

    def _read(self, relative: str) -> str:
        try:
            return (self.root / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""

    def snapshot(self) -> dict[str, float | None]:
        with self._lock:
            now = time.monotonic()
            if self._sampled_at is not None and now - self._sampled_at < 10:
                return dict(self._sample)
            sample: dict[str, float | None] = dict.fromkeys(
                ["temperature_c", "memory_available_mb", "wifi_signal_dbm", "uptime_seconds"]
            )
            try:
                sample["temperature_c"] = round(
                    float(self._read("sys/class/thermal/thermal_zone0/temp")) / 1000, 1
                )
            except ValueError:
                pass
            for line in self._read("proc/meminfo").splitlines():
                if line.startswith("MemAvailable:"):
                    try:
                        sample["memory_available_mb"] = round(float(line.split()[1]) / 1024, 1)
                    except (ValueError, IndexError):
                        pass
            for line in self._read("proc/net/wireless").splitlines():
                if line.lstrip().startswith("wlan0:"):
                    try:
                        sample["wifi_signal_dbm"] = float(line.split()[3])
                    except (ValueError, IndexError):
                        pass
            try:
                sample["uptime_seconds"] = float(self._read("proc/uptime").split()[0])
            except (ValueError, IndexError):
                pass
            self._sample = sample
            self._sampled_at = now
            return dict(sample)
