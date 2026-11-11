# Source updates and rollback

`scripts/update_runtime.py` provides **offline, source-only** maintenance for the standard
editable Raspberry Pi installation. It replaces only `src/appliance_display_sensor`, keeping
a recoverable copy of the previous runtime. It never runs `sudo`, starts/stops services, installs
packages, changes Wi-Fi, or writes calibration, alignment references or MQTT secrets.

This is not a general release/package manager. Parsed `pyproject.toml` metadata must match between
the installed and incoming projects, except for the optional `dev` dependency group. Comments,
formatting and test-only dependencies may differ; even version changes require manual review.
The tool does not install missing optional test dependencies. Runtime dependency upgrades,
service-unit changes, configuration migrations and OS recovery are
outside this tool. Documentation, tests, scripts and HA blueprints are not installed by it.

## Before updating

- Use a trusted complete source checkout in a separate directory. Its Python tests execute as
  your normal account with that account's permissions; they are **not sandboxed**. Do not run
  this tool with sudo or use an unreviewed download.
- Finish laundry and any calibration preview. Save changes or cancel the preview before stopping.
- Keep a separate private backup of configuration/secrets and, for OS/dependency recovery, an SD
  card backup. Runtime backups do not contain these files and cannot restore a damaged card.
- Review the change list. Applying replaces the entire runtime package, including local source
  edits; these are preserved in the backup. Unexpected files and symlinks in the runtime are
  rejected instead of silently removed. Backups are kept until you explicitly remove them.
- Close manually started sensor/camera processes. The tool checks the standard systemd service
  is inactive with no main PID and belongs to the target directory; it cannot identify every
  separately launched process. Do not concurrently edit files, start the service, or update it
  using another tool. A lock excludes other instances of this updater.

The examples use `/home/admin/appliance-display-sensor` for the installed project and
`/home/admin/appliance-display-sensor-next` for a reviewed complete incoming checkout. Substitute
your actual paths. Run commands in the Pi SSH session, not Windows PowerShell.

## Preview, apply, verify

The dry run is read-only, works while the service is running, and lists added/changed/removed
runtime files. It does **not** run tests or prove configuration/camera compatibility:

```console
cd /home/admin/appliance-display-sensor
.venv/bin/python scripts/update_runtime.py apply --source /home/admin/appliance-display-sensor-next --dry-run
```

When ready, stop the sensor explicitly, then apply as the **normal operator**:

```console
sudo systemctl stop appliance-display-sensor
.venv/bin/python scripts/update_runtime.py apply --source /home/admin/appliance-display-sensor-next
```

The apply command checks editable-import ownership, runs the incoming camera-independent Python
tests with the installed interpreter, and validates the current `config.local.yaml` with incoming
code. For an external live config, add `--config /absolute/path/to/config.local.yaml`. Configuration
validation errors are not printed because they could contain credentials. Web UI JavaScript tests
should also pass on the development machine before a UI update; Node is not required on the Pi.

After validation, the tool rechecks file hashes, stages a bounded clean package, and prints a
backup path under `debug/runtime-updates/`. It moves the previous package there and places the new
one at the live path. Python cache files are not reused. No files are recursively deleted.

On success, start and inspect it:

```console
sudo systemctl start appliance-display-sensor
systemctl --no-pager --full status appliance-display-sensor
journalctl -u appliance-display-sensor --since "2 minutes ago" --no-pager
```

Check the setup page, a fresh camera frame and HA health/MQTT updates. An `active` service alone
does not prove useful readings. During the next normal load, compare the physical display and
countdown/terminal detection. No recurring checks or notifications are installed.

If validation fails before replacement, the previous runtime remains intact but the service
stays stopped. Inspect the error; start the old version when safe. If replacement began or you
are unsure, verify/restore the printed backup first. Do not blindly restart a partial installation.

## Roll back

Use the specific backup path printed by apply. Previewing rollback is read-only:

```console
.venv/bin/python scripts/update_runtime.py rollback --backup /home/admin/appliance-display-sensor/debug/runtime-updates/BACKUP_NAME --dry-run
```

Stop the service, restore as the normal operator, then start it after successful restoration:

```console
sudo systemctl stop appliance-display-sensor
.venv/bin/python scripts/update_runtime.py rollback --backup /home/admin/appliance-display-sensor/debug/runtime-updates/BACKUP_NAME
sudo systemctl start appliance-display-sensor
```

Enter these separately: if rollback fails, **do not run the start command** until investigated.
Rollback checks backup integrity, target ownership, packaging metadata, and that the runtime
still matches the version that backup replaced. Later updates/local edits cause refusal rather
than overwriting them. Roll back multiple updates in reverse order. The replaced version and
original backup remain recoverable. An already restored runtime is a no-op.

There are two directory renames, not one transactional filesystem operation. Ordinary failure of
the second rename restores the old path immediately. An interruption between renames can leave
the live package absent; rollback can restore it from the printed backup. This is not a guarantee
against power-loss/filesystem corruption. Keep power stable and retain an SD card backup.

Rollback restores **code only**. It does not undo calibration saves performed after an update;
if old code cannot use newer settings, recover a compatible calibration separately. Schema changes
need a reviewed migration plan rather than this source-only workflow.
