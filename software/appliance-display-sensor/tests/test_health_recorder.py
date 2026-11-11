import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("health_sample", PROJECT / "scripts/health_sample.py")
recorder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recorder)


class HealthRecorderTests(unittest.TestCase):
    def test_missing_metrics_remain_unknown(self):
        with TemporaryDirectory() as directory, patch.object(recorder, "command", return_value=""):
            result = recorder.sample(root=Path(directory))
        for key in ("boot_id", "uptime_seconds", "temperature_c", "load_average",
                    "memory_available_kib", "swap_used_kib", "wifi_signal_dbm",
                    "rx_bytes", "throttled_flags"):
            self.assertIsNone(result[key], key)
        self.assertTrue(all(value is None for value in result["service"].values()))
        json.dumps(result, allow_nan=False)

    def test_passive_metrics_and_fixed_commands(self):
        files = {
            "proc/sys/kernel/random/boot_id": "12345678-1234-1234-1234-123456789abc",
            "proc/uptime": "120.5 99",
            "proc/loadavg": "0.1 0.2 0.3 1/4 1234",
            "sys/class/thermal/thermal_zone0/temp": "60100",
            "proc/meminfo": "MemAvailable: 150000 kB\nSwapTotal: 1000 kB\nSwapFree: 800 kB\n",
            "proc/net/wireless": "wlan0: 0000 51. -49. -256 0 0\nwlan1: 0000 61. -39. -256\n",
            "sys/class/net/wlan1/statistics/rx_bytes": "12345",
        }
        def command(args):
            if args[0] == "vcgencmd":
                return "throttled=0x50000\n"
            return ("LoadState=loaded\nActiveState=active\nSubState=running\n"
                    "NRestarts=2\nMainPID=42\n")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, contents in files.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents, encoding="utf-8")
            with patch.object(recorder, "command", side_effect=command) as run:
                result = recorder.sample("wlan1", root)
        self.assertEqual(result["temperature_c"], 60.1)
        self.assertEqual(result["uptime_seconds"], 120.5)
        self.assertEqual(result["wifi_signal_dbm"], -39)
        self.assertEqual(result["swap_used_kib"], 200)
        self.assertEqual(result["rx_bytes"], 12345)
        self.assertEqual(result["service"]["NRestarts"], 2)
        self.assertEqual(result["throttled_flags"], "0x50000")
        self.assertEqual([call.args[0][0] for call in run.call_args_list],
                         ["vcgencmd", "systemctl"])

    def test_subprocess_errors_and_missing_pi_tools_are_silent(self):
        for error in (FileNotFoundError("private/path"),
                      subprocess.TimeoutExpired("private command", 4),
                      subprocess.CalledProcessError(1, "secret command", stderr="secret")):
            with patch.object(recorder.subprocess, "run", side_effect=error):
                self.assertEqual(recorder.command(["systemctl"]), "")
        with patch.object(recorder.subprocess, "run") as run:
            run.return_value.stdout = "ok"
            self.assertEqual(recorder.command(["systemctl"]), "ok")
            self.assertEqual(run.call_args.kwargs["timeout"], 4)

    def test_interface_cannot_be_option_or_path(self):
        for value in ("../etc", "/etc", "--help", "wlan0;id", "wlan0\nsecret", "a" * 16, ""):
            with self.assertRaises(argparse.ArgumentTypeError):
                recorder.interface_name(value)
        self.assertEqual(recorder.interface_name("wlan0"), "wlan0")

    def test_output_whitelist_drops_unexpected_text(self):
        with TemporaryDirectory() as directory, patch.object(recorder, "command", return_value=
                "ActiveState=SECRET\nSubState=SECRET\nEnvironment=PASSWORD\nMainPID=nan\n"):
            result = recorder.sample(root=Path(directory))
        payload = json.dumps(result, allow_nan=False)
        for value in ("SECRET", "PASSWORD", "Environment"):
            self.assertNotIn(value, payload)
        self.assertIsNone(recorder.number("nan"))
        self.assertIsNone(recorder.number("inf"))

    def test_unit_is_bounded_and_installer_is_opt_in(self):
        unit = (PROJECT / "packaging/systemd/appliance-display-health.service.in").read_text()
        self.assertIn("TimeoutStartSec=15", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("ProtectHome=true", unit)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", unit)
        main = (PROJECT / "scripts/install_service.sh").read_text()
        self.assertNotIn("install_health_recorder", main)

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("bash"), "Linux installer check")
    def test_installer_dry_run_and_validation(self):
        import pwd
        user = pwd.getpwuid(__import__("os").getuid()).pw_name
        if user == "root":
            self.skipTest("Dry-run must use a non-root operator")
        script = str(PROJECT / "scripts/install_health_recorder.sh")
        for flags in ([], ["--persistent-journal"]):
            run = subprocess.run(["bash", script, "--dry-run", "--user", user, *flags],
                                 capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("no files or services changed", run.stdout)
            self.assertIn("HOST-WIDE" if flags else "left unchanged", run.stdout)
        for flags in (["--interface", "../bad"], ["--user", "root"], ["--unknown"],
                      ["--interface"], ["--user", "bad&user"]):
            run = subprocess.run(["bash", script, "--dry-run", *flags],
                                 capture_output=True, text=True, timeout=10)
            self.assertNotEqual(run.returncode, 0)


if __name__ == "__main__":
    unittest.main()
