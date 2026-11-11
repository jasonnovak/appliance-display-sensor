"""Guarded, offline source-only updates for an editable Raspberry Pi installation.

Run as the normal operator, never sudo. Incoming source/tests are trusted executable
code, not a sandbox. Dependency, packaging and configuration migrations are excluded.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import uuid

PACKAGE = Path("src/appliance_display_sensor")
SERVICE = "appliance-display-sensor.service"
BACKUPS = Path("debug/runtime-updates")
MAX_FILES = 256
MAX_BYTES = 32 * 1024 * 1024


class UpdateError(Exception):
    pass


def checked_path(path: Path) -> Path:
    """Reject links in every existing component, including broken final links."""
    path = path.absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise UpdateError(f"Symbolic links are not supported: {path}")
    return path.resolve()


def inventory(package: Path) -> dict[str, str]:
    checked_path(package)
    if not package.is_dir():
        raise UpdateError(f"Runtime package not found: {package}")
    result = {}
    total = 0
    for directory, dirs, files in os.walk(package, followlinks=False):
        for name in dirs + files:
            checked_path(Path(directory) / name)
        dirs[:] = sorted(name for name in dirs if name != "__pycache__")
        for name in sorted(files):
            path = Path(directory) / name
            if not path.is_file() or path.suffix not in {".py", ".html"}:
                raise UpdateError(f"Unexpected runtime file (not replaced): {path}")
            total += path.stat().st_size
            if len(result) >= MAX_FILES or total > MAX_BYTES:
                raise UpdateError("Runtime exceeds the source update size limit")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result[path.relative_to(package).as_posix()] = digest
    if "__init__.py" not in result or "__main__.py" not in result:
        raise UpdateError("Runtime is incomplete")
    return result


def metadata(project: Path) -> str:
    path = checked_path(project / "pyproject.toml")
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise UpdateError("Invalid pyproject.toml; packaging requires manual review") from error
    # Test-only dependencies are not installed by this tool and do not change the
    # editable runtime's packaging. Keep every other metadata/dependency guard.
    project_data = document.get("project", {})
    optional = project_data.get("optional-dependencies", {})
    optional.pop("dev", None)
    if not optional:
        project_data.pop("optional-dependencies", None)
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def plan(source: Path, target: Path) -> tuple[dict, dict]:
    source, target = checked_path(source), checked_path(target)
    if source == target or source.is_relative_to(target / PACKAGE):
        raise UpdateError("Incoming source must be a separate checkout")
    if metadata(source) != metadata(target):
        raise UpdateError("pyproject.toml differs: packaging/dependency changes need manual review")
    before, after = inventory(target / PACKAGE), inventory(source / PACKAGE)
    return before, after


def changes(before: dict, after: dict) -> dict[str, list[str]]:
    return {
        "add": sorted(after.keys() - before.keys()),
        "change": sorted(key for key in before.keys() & after.keys() if before[key] != after[key]),
        "remove": sorted(before.keys() - after.keys()),
    }


def stopped(target: Path) -> None:
    run = subprocess.run(
        ["systemctl", "show", SERVICE, "--property=LoadState,ActiveState,MainPID,WorkingDirectory"],
        check=True, capture_output=True, text=True, timeout=10,
    )
    values = dict(line.split("=", 1) for line in run.stdout.splitlines() if "=" in line)
    if (values.get("LoadState") != "loaded" or values.get("ActiveState") != "inactive"
            or values.get("MainPID") != "0"
            or Path(values.get("WorkingDirectory", "/")).resolve() != target.resolve()):
        raise UpdateError("Stop the sensor service first; its WorkingDirectory must match "
                          "the target. Also close any manually started sensor processes.")


@contextmanager
def update_lock(target: Path):
    if sys.platform != "linux" or os.geteuid() == 0:
        raise UpdateError("Apply/rollback require Linux and the normal operator account, not sudo")
    import fcntl
    lock = checked_path(target / ".runtime-update.lock")
    with lock.open("a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise UpdateError("Another runtime update is in progress") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def validate(source: Path, target: Path, config: Path) -> None:
    """Use the installed interpreter, without pip/network/system changes."""
    python = target / ".venv/bin/python"
    # Venv interpreters normally are symlinks; do not subject this executable to
    # the data-path no-symlink policy. Verify editable import ownership explicitly.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)
    check = subprocess.run(
        [str(python), "-c", "import appliance_display_sensor as a; print(a.__file__)"],
        cwd=target, env=env, capture_output=True, text=True, timeout=30, check=True,
    )
    if Path(check.stdout.strip()).resolve() != (target / PACKAGE / "__init__.py").resolve():
        raise UpdateError("Installed interpreter does not import this editable runtime")
    if not list((source / "tests").glob("test_*.py")):
        raise UpdateError("Incoming checkout has no test suite")
    env["PYTHONPATH"] = str(source / "src")
    print("Running incoming camera-independent tests (trusted code, normal account)...", flush=True)
    subprocess.run([str(python), "-m", "unittest", "discover", "-s", "tests"],
                   cwd=source, env=env, timeout=300, check=True)
    # Config errors can contain credentials. Never relay the validation output.
    code = ("from appliance_display_sensor.config import load_config; "
            "import sys; load_config(sys.argv[1])")
    result = subprocess.run([str(python), "-c", code, str(config)], cwd=target, env=env,
                            capture_output=True, timeout=30)
    if result.returncode:
        raise UpdateError("Incoming code cannot load the current configuration; no files replaced")


def copy_runtime(source: Path, destination: Path, expected: dict) -> None:
    destination.mkdir(mode=0o700)
    for relative in expected:
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, path)
    if inventory(destination) != expected:
        raise UpdateError("Runtime changed while copying; no replacement performed")


def write_manifest(backup: Path, manifest: dict) -> None:
    temporary = backup / "manifest.tmp"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, backup / "manifest.json")


def apply_update(source: Path, target: Path, config: Path) -> Path | None:
    source, target, config = checked_path(source), checked_path(target), checked_path(config)
    with update_lock(target):
        stopped(target)
        before, after = plan(source, target)
        if before == after:
            print("Runtime already matches; nothing changed.")
            return None
        config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
        initial_metadata = metadata(target)
        validate(source, target, config)
        if plan(source, target) != (before, after) or metadata(target) != initial_metadata:
            raise UpdateError("Source/target changed during validation; use a stable checkout")
        if hashlib.sha256(config.read_bytes()).hexdigest() != config_hash:
            raise UpdateError("Configuration changed during validation; retry")
        backups = checked_path(target / BACKUPS)
        backups.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
        backup = backups / backup_name
        backup.mkdir(mode=0o700)
        if backup.stat().st_dev != (target / PACKAGE).stat().st_dev:
            raise UpdateError("Backup and runtime must be on the same filesystem")
        copy_runtime(source / PACKAGE, backup / "incoming", after)
        manifest = {"version": 1, "target": str(target), "before": before, "after": after,
                    "metadata_sha256": hashlib.sha256(initial_metadata.encode()).hexdigest(),
                    "state": "prepared"}
        write_manifest(backup, manifest)
        stopped(target)
        if (inventory(target / PACKAGE) != before or metadata(target) != initial_metadata
                or hashlib.sha256(config.read_bytes()).hexdigest() != config_hash):
            raise UpdateError("Installed runtime/configuration changed before replacement")
        print(f"Recovery backup: {backup}", flush=True)
        os.replace(target / PACKAGE, backup / "previous")
        try:
            os.replace(backup / "incoming", target / PACKAGE)
        except BaseException:
            os.replace(backup / "previous", target / PACKAGE)
            raise
        manifest["state"] = "applied"
        write_manifest(backup, manifest)
        print("Source updated; configuration, secrets, environment and service unit unchanged.")
        print("Start and verify the camera, MQTT and setup page before accepting the update.")
        return backup


def rollback(backup: Path, target: Path, dry_run: bool = False) -> None:
    backup, target = checked_path(backup), checked_path(target)
    if backup.parent != checked_path(target / BACKUPS):
        raise UpdateError("Select a backup directly inside this target's debug/runtime-updates")
    manifest = json.loads(checked_path(backup / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or manifest.get("target") != str(target):
        raise UpdateError("Backup does not belong to this runtime")
    if hashlib.sha256(metadata(target).encode()).hexdigest() != manifest.get("metadata_sha256"):
        raise UpdateError("Packaging metadata changed; rollback requires manual review")
    current = inventory(target / PACKAGE) if (target / PACKAGE).exists() else None
    if current == manifest["before"]:
        print("Runtime already matches the pre-update version; nothing changed.")
        return
    if current is not None and current != manifest["after"]:
        raise UpdateError("Runtime has later/local changes; refusing to overwrite them")
    previous = checked_path(backup / "previous")
    if inventory(previous) != manifest["before"]:
        raise UpdateError("Backup integrity check failed")
    if dry_run:
        print("Rollback verified; no files or services changed.")
        return
    stopped(target)
    restored = backup / ("restore-" + uuid.uuid4().hex[:8])
    copy_runtime(previous, restored, manifest["before"])
    replaced = backup / ("replaced-" + uuid.uuid4().hex[:8])
    if current is not None:
        os.replace(target / PACKAGE, replaced)
    try:
        os.replace(restored, target / PACKAGE)
    except BaseException:
        if current is not None:
            os.replace(replaced, target / PACKAGE)
        raise
    manifest["state"] = "rolled_back"
    write_manifest(backup, manifest)
    print("Runtime rolled back; configuration and credentials unchanged. Start and verify it.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    apply = commands.add_parser("apply", help="Install only src/appliance_display_sensor")
    apply.add_argument("--source", type=Path, required=True, help="Separate trusted full checkout")
    apply.add_argument("--config", type=Path, help="Current config (default: config.local.yaml)")
    apply.add_argument("--dry-run", action="store_true", help="List changes only; do not run tests")
    restore = commands.add_parser("rollback", help="Restore one checked source backup")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        target = checked_path(args.target)
        if args.command == "apply":
            if args.dry_run:
                before, after = plan(args.source, target)
                print(json.dumps(changes(before, after), indent=2))
                print("Dry run: no files or services changed; tests/config not checked.")
            else:
                apply_update(args.source, target, args.config or target / "config.local.yaml")
        elif args.dry_run:
            rollback(args.backup, target, dry_run=True)
        else:
            with update_lock(target):
                rollback(args.backup, target)
    except UpdateError as error:
        print(f"Update refused: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print("Update failed. Keep the sensor stopped until runtime integrity is checked. "
              "Use the printed recovery backup for rollback if replacement began.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
