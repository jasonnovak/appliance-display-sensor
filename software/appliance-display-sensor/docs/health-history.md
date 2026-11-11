# Optional Pi health history

The setup page and Home Assistant show current health. This separate recorder keeps a small
system sample every 30 seconds for later outage investigation, even when the sensor process
has stopped. It is optional, local-only and independent of the camera, MQTT and setup page.
It does not repair faults, reboot the Pi, restart the sensor or send notifications.

## Preview and install

From the repository directory on Raspberry Pi OS:

```console
bash scripts/install_health_recorder.sh --dry-run
bash scripts/install_health_recorder.sh
```

The installer asks for sudo, uses your non-root operator account, verifies the systemd units,
backs up existing recorder files under `/var/backups/appliance-display-health/install-*`, and
enables `appliance-display-health.timer`. It does **not** restart the main sensor or change
calibration/MQTT configuration. Reinstalling updates only the recorder's script and units.
An older `health-sample.sh` is left in place, unused, for rollback.

Use `--user USER` if installing from a root shell. `--interface wlan1` selects another Linux
interface; the default is `wlan0`. Missing interface metrics are recorded as `null`, not zero.
The sampler uses `/usr/bin/python3` and only the standard library; no additional packages or
application environment are needed. `vcgencmd` readings are `null` when unavailable or denied.

### Optional persistence across reboots

By default the existing journal policy is untouched. If it is volatile, history disappears
after reboot. To explicitly request persistent, capped storage:

```console
bash scripts/install_health_recorder.sh --persistent-journal --dry-run
bash scripts/install_health_recorder.sh --persistent-journal
```

**This changes the host-wide system journal, not just this recorder.** The installed drop-in
requests a 50 MiB persistent journal limit, 8 MiB files, 256 MiB free-space reserve, 16 MiB
runtime limit, up to seven days of history and a 30-second sync interval. Other drop-ins may
override these values. Frequent logs can make retained history much shorter than seven days.
Persistent recording adds SD-card writes; an abrupt power cut can still lose recent samples.
The installer restarts journald and flushes its runtime journal only when this flag is selected.
It never explicitly vacuums or deletes journal history; retention policies can remove old logs.

## Inspect history

```console
systemctl list-timers appliance-display-health.timer
systemctl status appliance-display-health.service
journalctl -u appliance-display-health.service --since '1 hour ago' --no-pager -o cat
journalctl -u appliance-display-health.service -b -1 --no-pager -o cat
journalctl --disk-usage
```

Use sudo for journal access if your operator lacks permission. A successful oneshot sampler
normally shows **inactive (dead)** between samples; the timer should stay active. The previous
boot command is useful only when persistent logs from that boot exist.

Each JSON record includes UTC time, boot ID, uptime, load, temperature, available memory,
swap use, free disk space, Wi-Fi signal, interface byte/error counters, raw Pi throttling flags,
and the sensor unit's state/PID/restart count. Counters may reset on reboot or interface reset;
`NRestarts` describes systemd's current restart accounting, not lifetime failures. Raw throttling
flags include both current and since-boot conditions; a nonzero value alone does not mean the
Pi is currently throttling.

The recorder reads no app config, credentials, images, display text, SSIDs, IP addresses or
access-point identifiers. It makes no network probes. Nevertheless timestamps/boot IDs and
usage history are private operational data. Review logs before sharing. Other system journal
entries and history from older recorder versions may contain additional identifying data.
These logs are **not** added to the setup page's shareable display-diagnostics ZIP.

## Disable or roll back

Stop future samples without deleting history:

```console
sudo systemctl disable --now appliance-display-health.timer
sudo systemctl stop appliance-display-health.service
```

This leaves the journal policy unchanged. To roll back an upgrade, first stop the timer as above,
inspect the installer's printed backup directory, and restore its `appliance-display-health.service`,
`appliance-display-health.timer` and (if present) `health-sample.py` to their original locations.
Then run `sudo systemctl daemon-reload` and enable the timer again. The legacy shell sampler
remains available if the backed-up service refers to it.

To undo the optional host-wide policy, restore the backed-up
`90-appliance-display-diagnostics.conf`, or remove only
`/etc/systemd/journald.conf.d/90-appliance-display-diagnostics.conf` if the installer created it
and no prior file existed. Restart journald afterward. This does not remove saved journal data;
do not delete unrelated journal policies or logs.
