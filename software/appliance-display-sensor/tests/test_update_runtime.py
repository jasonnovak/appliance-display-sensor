import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
script = PROJECT / "scripts/update_runtime.py"
spec = importlib.util.spec_from_file_location("update_runtime", script)
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class RuntimeUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.target, self.source = self.root / "installed", self.root / "incoming"
        for project in (self.target, self.source):
            package = project / updater.PACKAGE
            package.mkdir(parents=True)
            (project / "pyproject.toml").write_text('[project]\nname="example"\n')
            (package / "__init__.py").write_text("")
            (package / "__main__.py").write_text("old = True\n")
        self.config = self.target / "config.local.yaml"
        self.config.write_text("private calibration")
        (self.target / "secrets").mkdir()
        (self.target / "secrets/mqtt_password").write_text("private password")
        (self.source / updater.PACKAGE / "__main__.py").write_text("new = True\n")
        (self.source / updater.PACKAGE / "new.py").write_text("new = True\n")
        self.output = io.StringIO()
        self.addCleanup(patch.stopall)
        patch.object(updater, "update_lock", lambda _: contextlib.nullcontext()).start()
        self.stopped = patch.object(updater, "stopped").start()
        self.validate = patch.object(updater, "validate").start()
        patch("sys.stdout", self.output).start()

    def apply(self):
        return updater.apply_update(self.source, self.target, self.config)

    def private_unchanged(self):
        self.assertEqual(self.config.read_text(), "private calibration")
        self.assertEqual((self.target / "secrets/mqtt_password").read_text(), "private password")

    def test_apply_and_rollback_keep_private_data_and_old_source(self):
        before, after = updater.plan(self.source, self.target)
        backup = self.apply()
        self.assertEqual(updater.inventory(self.target / updater.PACKAGE), after)
        self.assertEqual(updater.inventory(backup / "previous"), before)
        self.assertEqual(json.loads((backup / "manifest.json").read_text())["state"], "applied")
        self.validate.assert_called_once()
        self.private_unchanged()
        updater.rollback(backup, self.target)
        self.assertEqual(updater.inventory(self.target / updater.PACKAGE), before)
        self.assertEqual(updater.inventory(backup / "previous"), before)
        self.assertFalse((self.target / updater.PACKAGE / "new.py").exists())
        self.private_unchanged()
        updater.rollback(backup, self.target)  # Idempotent, does not discard data.

    def test_dry_run_is_read_only_and_does_not_run_tests_or_stop_services(self):
        before = sorted(self.root.rglob("*"))
        self.assertEqual(updater.main(["--target", str(self.target), "apply",
                                      "--source", str(self.source), "--dry-run"]), 0)
        self.assertEqual(sorted(self.root.rglob("*")), before)
        self.validate.assert_not_called()
        self.stopped.assert_not_called()
        self.assertIn('"new.py"', self.output.getvalue())

    def test_packaging_change_and_same_checkout_are_refused(self):
        with self.assertRaises(updater.UpdateError):
            updater.plan(self.target, self.target)
        (self.source / "pyproject.toml").write_text("dependencies changed")
        with self.assertRaises(updater.UpdateError):
            self.apply()
        self.assertFalse((self.target / updater.BACKUPS).exists())

    def test_only_dev_dependencies_and_toml_formatting_may_differ(self):
        base = '[project]\nname="example"\n'
        (self.source / "pyproject.toml").write_text(
            base + '[project.optional-dependencies]\ndev=["test-tool>=1"]\n')
        updater.plan(self.source, self.target)
        for difference in ('dependencies=["runtime-tool>=1"]\n', 'version="2"\n',
                           '[project.optional-dependencies]\ncamera=["camera-tool"]\n'):
            (self.source / "pyproject.toml").write_text(base + difference)
            with self.assertRaises(updater.UpdateError):
                updater.plan(self.source, self.target)

    def test_tests_fail_before_any_backup_or_replacement(self):
        before = updater.inventory(self.target / updater.PACKAGE)
        self.validate.side_effect = subprocess.CalledProcessError(1, "tests")
        with self.assertRaises(subprocess.CalledProcessError):
            self.apply()
        self.assertEqual(updater.inventory(self.target / updater.PACKAGE), before)
        self.assertFalse((self.target / updater.BACKUPS).exists())

    def test_changes_during_validation_are_refused(self):
        for file in (self.config, self.source / updater.PACKAGE / "new.py",
                     self.target / updater.PACKAGE / "__main__.py"):
            original = file.read_bytes()
            self.validate.side_effect = lambda *args: file.write_bytes(b"changed during test")
            with self.assertRaises(updater.UpdateError):
                self.apply()
            file.write_bytes(original)
        self.assertFalse((self.target / updater.BACKUPS).exists())

    def test_later_edits_and_corrupt_backup_are_not_overwritten(self):
        backup = self.apply()
        path = self.target / updater.PACKAGE / "new.py"
        original = path.read_bytes()
        path.write_text("user edit")
        with self.assertRaises(updater.UpdateError):
            updater.rollback(backup, self.target)
        self.assertEqual(path.read_text(), "user edit")
        path.write_bytes(original)
        (backup / "previous/__main__.py").write_text("corrupted")
        with self.assertRaises(updater.UpdateError):
            updater.rollback(backup, self.target)

    def test_interrupted_directory_swap_can_be_recovered(self):
        backup = self.apply()
        # Simulate interruption after the old package was moved aside but before
        # the incoming directory acquired the live path. No recursive deletion.
        (self.target / updater.PACKAGE).rename(backup / "interrupted-new")
        updater.rollback(backup, self.target)
        content = (self.target / updater.PACKAGE / "__main__.py").read_text()
        self.assertEqual(content, "old = True\n")

    def test_failed_second_rename_restores_old_package(self):
        replace = updater.os.replace
        def fail_incoming(source, destination):
            if Path(source).name == "incoming":
                raise OSError("injected failure")
            return replace(source, destination)
        before = updater.inventory(self.target / updater.PACKAGE)
        with patch.object(updater.os, "replace", side_effect=fail_incoming):
            with self.assertRaises(OSError):
                self.apply()
        self.assertEqual(updater.inventory(self.target / updater.PACKAGE), before)

    def test_unknown_files_are_not_silently_dropped(self):
        (self.target / updater.PACKAGE / "user-notes.txt").write_text("keep")
        with self.assertRaises(updater.UpdateError):
            self.apply()

    def test_pycache_is_ignored_but_never_deletes_the_original(self):
        cache = self.target / updater.PACKAGE / "__pycache__"
        cache.mkdir()
        (cache / "old.pyc").write_bytes(b"old cache")
        backup = self.apply()
        self.assertTrue((backup / "previous/__pycache__/old.pyc").exists())
        self.assertFalse((self.target / updater.PACKAGE / "__pycache__").exists())

    def test_symlinked_runtime_is_rejected(self):
        path = self.source / updater.PACKAGE / "linked.py"
        try:
            path.symlink_to(self.config)
        except OSError:
            self.skipTest("Host does not allow test symlinks")
        with self.assertRaises(updater.UpdateError):
            self.apply()

    def test_wrong_backup_target_and_changed_metadata_refused(self):
        backup = self.apply()
        with self.assertRaises(updater.UpdateError):
            updater.rollback(backup, self.source)
        (self.target / "pyproject.toml").write_text("changed")
        with self.assertRaises(updater.UpdateError):
            updater.rollback(backup, self.target)

    def test_rollback_dry_run_preserves_files(self):
        backup = self.apply()
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.stopped.reset_mock()
        updater.rollback(backup, self.target, dry_run=True)
        after = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        self.stopped.assert_not_called()


class RuntimeUpdateServiceTests(unittest.TestCase):
    def test_requires_inactive_owned_service(self):
        target = Path(".").resolve()
        valid = f"LoadState=loaded\nActiveState=inactive\nMainPID=0\nWorkingDirectory={target}\n"
        variants = (valid, valid.replace("inactive", "active"),
                    valid.replace("MainPID=0", "MainPID=9"), valid.replace("loaded", "not-found"),
                    valid.replace(str(target), "/elsewhere"))
        for text in variants:
            with patch.object(updater.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, stdout=text)) as run:
                if text == valid:
                    updater.stopped(target)
                else:
                    with self.assertRaises(updater.UpdateError):
                        updater.stopped(target)
                self.assertEqual(run.call_args.args[0][:2], ["systemctl", "show"])

    def test_validation_does_not_print_config_failure_contents(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "tests").mkdir()
            (root / "tests/test_one.py").write_text("")
            returns = [subprocess.CompletedProcess([], 0, stdout=str(root / updater.PACKAGE /
                                                                   "__init__.py") + "\n"),
                       subprocess.CompletedProcess([], 0),
                       subprocess.CompletedProcess([], 1, stderr=b"SECRET config contents")]
            with patch.object(updater.subprocess, "run", side_effect=returns) as run:
                with self.assertRaises(updater.UpdateError) as error:
                    updater.validate(root, root, root / "config.local.yaml")
                self.assertNotIn("SECRET", str(error.exception))
                self.assertTrue(run.call_args.kwargs["capture_output"])

    @unittest.skipUnless(sys.platform == "linux", "Linux editable-venv and lock integration")
    def test_real_validation_apply_and_rollback_in_disposable_installation(self):
        if os.geteuid() == 0:
            self.skipTest("Updater intentionally refuses root")
        import venv
        with TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory).resolve()
            target, source = root / "target", root / "source"
            for project in (target, source):
                package = project / updater.PACKAGE
                package.mkdir(parents=True)
                (project / "pyproject.toml").write_text('[project]\nname="fixture"\n')
                (package / "__init__.py").write_text("")
                (package / "__main__.py").write_text("version = 'old'\n")
                (package / "config.py").write_text(
                    "from pathlib import Path\ndef load_config(path):\n"
                    "    assert Path(path).read_text() == 'private config'\n")
            config = target / "config.local.yaml"
            config.write_text("private config")
            (source / updater.PACKAGE / "__main__.py").write_text("version = 'new'\n")
            (source / "tests").mkdir()
            (source / "tests/test_fixture.py").write_text(
                "import unittest\nfrom appliance_display_sensor.__main__ import version\n"
                "class Example(unittest.TestCase):\n"
                "    def test_new_import(self): self.assertEqual(version, 'new')\n")
            venv.EnvBuilder(with_pip=False).create(target / ".venv")
            site = next((target / ".venv/lib").glob("python*/site-packages"))
            (site / "editable-fixture.pth").write_text(str(target / "src") + "\n")
            with patch.object(updater, "stopped"):
                backup = updater.apply_update(source, target, config)
                # Exercise the actual flock collision, not only a mocked context manager.
                with updater.update_lock(target):
                    with self.assertRaises(updater.UpdateError):
                        with updater.update_lock(target):
                            self.fail("Second update acquired the lock")
                self.assertEqual(updater.main(["--target", str(target), "rollback",
                                               "--backup", str(backup)]), 0)
            self.assertEqual(config.read_text(), "private config")
            self.assertIn("old", (target / updater.PACKAGE / "__main__.py").read_text())


if __name__ == "__main__":
    unittest.main()
