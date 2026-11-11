# Release status — 2026-11-11

This document is the release candidate's current status. Older optical logs record
historical experiments, not calibration defaults or proof for the final mount.

## Implemented

- Pi camera capture, fixed-layout digit decoding, adaptive countdown interpretation,
  explicit H:MM mode independent of the colon, and terminal/blank handling.
- Browser calibration, digit and segment editing, optical profiles, readability and
  camera health, recent readings, diagnostic downloads and optional drift warnings.
- MQTT discovery, HA countdown and diagnostic entities, completion/health/estimate
  change blueprints, Pi service and source-update/rollback tools.
- Optional RunCycle bridge, permanent HA OS hosting, self-hosted setup wizard,
  fresh-install helper and separate public/private packaging.
- Apache-2.0 software and CERN-OHL-P-2.0 design licensing.

## Evidence and open gates

On 2026-11-11 the owner reported that physical testing had already been completed
on the reference installation. This is owner-reported validation, not an independent
qualification or newly measured result. The detailed items below distinguish that
confirmation from fresh-install and isolated recovery testing.

| Area | Existing evidence | Still needed |
| --- | --- | --- |
| Countdown | Reference dryer adaptive cycle through End and blank; synthetic/replay tests; owner reports physical testing complete | Independent installation and per-condition results |
| Calibration | Live calibration used on the reference installation | A fresh user's install and calibration without developer intervention |
| HA | Live MQTT discovery and completion alert confirmed | Current blueprint import/action checks; fault recovery and backup restore |
| Google bridge | Active query answered on the speaker asked before host migration; permanent-host idle query confirmed; owner reports physical testing complete | Detailed permanent-host active-query and reboot/reconnect results |
| Mount | Final 3MF/STL equivalence; assembled photos; owner reports physical testing complete | Independent replication on other printers/appliances |
| Packaging | Allowlisted source and model artifacts with licenses and checksums | Independent Pi/HA OS installation from this candidate |

Use [physical-tests.md](physical-tests.md) for the operator checklist. Do not mark
these checks passed merely because an earlier prototype worked. Existing observations
can count when the same geometry, calibration and deployed software were used.

## Initial support boundary

The reference system is Pi Zero 2 W, Camera Module 3 Standard, Pi OS Lite 64-bit,
one calibrated dryer display, Android Google Home linking and amd64 HA OS for the
optional bridge. aarch64 bridge hosting, iOS linking and other appliance types are
unverified and are not prerequisites for an explicitly limited experimental release.

The calibration page is for a trusted LAN; do not publish it through the bridge
tunnel. Drift warnings do not automatically realign the camera or block every
incorrect reading. Decoder confidence is not a measured accuracy percentage.

Status-symbol ROIs, illumination control, sensor fusion, ESP32 support, Matter,
multi-household hosting, Google certification and automatic release upgrades are
future work, not promises for this release. No user should need the author's
Google project, domain, MQTT credentials or personal calibration.
