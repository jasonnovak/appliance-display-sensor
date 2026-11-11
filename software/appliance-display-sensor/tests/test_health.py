from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from appliance_display_sensor.health import SystemHealth


class SystemHealthTests(unittest.TestCase):
    def test_missing_system_files_are_not_errors(self):
        with TemporaryDirectory() as directory:
            sample = SystemHealth(Path(directory)).snapshot()
        self.assertTrue(all(value is None for value in sample.values()))

    def test_passive_readings_are_cached_and_refresh(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            files = {
                "sys/class/thermal/thermal_zone0/temp": "59610",
                "proc/meminfo": "MemAvailable: 153600 kB\n",
                "proc/net/wireless": "wlan0: 0000 62. -48. -256 0 0 0 0 0 0\n",
                "proc/uptime": "120.5 400.0\n",
            }
            for name, value in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value, encoding="utf-8")
            health = SystemHealth(root)
            with patch("appliance_display_sensor.health.time.monotonic", return_value=0):
                sample = health.snapshot()
            self.assertEqual(sample["temperature_c"], 59.6)
            self.assertEqual(sample["memory_available_mb"], 150)
            self.assertEqual(sample["wifi_signal_dbm"], -48)
            self.assertEqual(sample["uptime_seconds"], 120.5)
            (root / "proc/uptime").write_text("130 400", encoding="utf-8")
            with patch("appliance_display_sensor.health.time.monotonic", return_value=5):
                self.assertEqual(health.snapshot()["uptime_seconds"], 120.5)
            with patch("appliance_display_sensor.health.time.monotonic", return_value=11):
                self.assertEqual(health.snapshot()["uptime_seconds"], 130)
