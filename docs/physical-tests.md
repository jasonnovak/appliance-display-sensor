# Physical checks before the first beta

## Owner report — 2026-11-11

The owner reports that the physical checks below were already tested during use of
the reference installation. No new physical tests were run during release preparation.
Individual dates and measurements were not supplied, so the checklist remains a
reproducible procedure rather than an invented per-test results log. A fresh install,
isolated backup restore and detailed recovery checks remain separate validation work.

Leave each checkbox open until observed on the candidate hardware/software. Record
the date, mount revision, lighting and result; a short note is enough. These are
manual checks during normal laundry, not scheduled reminders.

## 1. Final printed assembly — once

- [ ] Confirm the final five-part set: recessed-head base, Pi lid, thicker camera
  front cover, closed-end cable cover and overlap-nose arm, matching the supplied 3MF.
- [ ] With M3x8 screw and nut gently snug, check with a straightedge that no metal
  protrudes below the base. Test on a protected work surface before the appliance.
- [ ] Check magnet seating/holding, stable arm and camera, lid/cover fit, accessible
  SD and power ports, cable slack and no ribbon pinch or sharp crease.
- [ ] Check that ordinary loading/unloading and opening the door do not strike the
  mount or obstruct reading/using the appliance controls.
- [ ] During a normal warm, vibrating cycle, confirm no mount creep or camera drift.
  Compare the camera view before/after. Record reported Pi temperature and any
  throttling/health warnings; do not infer thermal performance from room temperature.

## 2. Countdown and lights — normal loads

- [ ] With the final mount fixed, check a visible hour value such as 1:12, a
  minute-only value such as 21, and 1 minute against both the UI and HA. For a
  three-position H:MM display, confirm this works without relying on the colon.
- [ ] Check the same saved profile with the room light on and off. Include daylight
  when available. Do not change alignment between checks.
- [ ] Observe an automatic/adaptive load: HA follows genuine upward/downward time
  changes, sustained unreadability is reported honestly, and End produces one
  completion action. The subsequent blank screen must not start a new cycle.
- [ ] Inspect the recent-reading summary and cropped overlay if values are wrong;
  record the physical display as ground truth, not just the confidence percentage.

## 3. Google voice — next active load

- [ ] Ask “How much time is left on the dryer?” during a visible countdown.
  The spoken time agrees with the current display, allowing a normal minute boundary.
- [ ] Repeat on a second speaker: only the speaker asked replies, with no legacy
  whole-house routine. Leave separate completion announcements enabled if desired.
- [ ] After the display goes blank, a new query gives no timer/not-ready as appropriate,
  rather than an old remaining time. A blank display alone is not completion evidence.

## 4. Planned recovery — when convenient

- [ ] Reboot the Pi normally and confirm camera, setup page, MQTT and HA recover.
- [ ] During a planned HA host restart, confirm the bridge and tunnel auto-start,
  the existing Google link survives, and a fresh countdown query works.
- [ ] Perform a brief controlled network/MQTT interruption when safe to do so;
  health becomes unavailable and recovers, with no false completion alert or stale
  spoken countdown. Do not pull power to simulate a clean restart.

## Installation checks (separate from laundry)

- [ ] Fresh Pi install from the source candidate, configure camera/MQTT, calibrate,
  install the service, reboot, and obtain HA entities using only the guide.
- [ ] Fresh HA bridge installation and phone account linking with a separate test
  setup; check the installer refuses to overwrite an existing installation.
- [ ] Import each optional HA blueprint being advertised, select entities/actions,
  and check its trace and phone/speaker delivery. Do not enable duplicate finish alerts.
- [ ] Restore a backup in an isolated test setup and verify calibration, credentials
  and Google grants persist. Do not run two bridges with the same identity in parallel.

Result record: date / candidate hash / hardware revision / test / observation / pass or issue.
