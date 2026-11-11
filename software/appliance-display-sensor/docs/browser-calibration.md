# Browser calibration

The sensor includes an optional local setup page for aligning and tuning a live Picamera2 camera
without hand-editing pixel coordinates.

## Enable it

The page is disabled by default. On a trusted local network, add:

```yaml
calibration:
  enabled: true
  host: 0.0.0.0
  port: 8090
```

Restart the service, then open `http://PI_ADDRESS:8090/`. Binding to `0.0.0.0` makes the page
reachable from the local network. It is intentionally not a cloud service and should not be
forwarded through a router or exposed to the public internet.

## Workflow

1. Position the camera and open the live frame.
2. Drag the blue display rectangle or resize it with its lower-right handle.
3. Select the digit count and colon position, then create starting digit boxes if needed. This
   replaces the geometry in the form, not the saved configuration. Select a digit or colon in
   **Move / resize** to adjust its individual box. Include unlit segments in the physical glyph.
4. Use **Test changes** to apply exposure, gain, focus, threshold, channel, segment, and
   geometry settings without writing them to disk. Increase **Frames combined per reading** to `3` or `4`
   if a multiplexed display alternates between individually illuminated digit positions.
5. Open **Inspect detection** to compare the cropped segment overlay and black-and-white pixel
   preview. These use the tested/saved settings; outlines for untested edits are amber and do
   not yet describe the recognition result. Tap any **?** button for setting-specific help.
6. Use **Save settings** only when the reading is correct, or **Discard changes** to restore the
   saved settings. Low-level recognition controls and exact coordinates are under **Advanced**.

Test mode pauses MQTT state transitions, so experimental thresholds and boxes cannot create a
false Home Assistant reading. Discard restores the saved optical settings. An abandoned unsaved
preview automatically expires after ten minutes and restores the saved settings.

## Optional bumped-camera warning

This is an opt-in **setup-page warning**, not a readout interlock. It neither blocks nor changes
OCR, retained Home Assistant state, MQTT messages or completion alerts. It is available only
while the calibration server/session is enabled. There is currently no Home Assistant alignment
entity, notification automation, automatic geometric correction or rotation/scale correction.

1. With the mount fixed and the displayed digits/colon visually correct, expand **Bumped-camera
   warning** under the alignment preview. Finish saving/discarding any optical test first.
2. Choose **Choose / move anchor**. Select **Alignment anchor** in Move / resize, then move/resize
   the purple box onto distinctive **fixed printed text or texture on the appliance itself**.
   Exact coordinates are also available. Width/height must each be 32–160 native camera pixels.
   The blue display and digit boxes are untouched. Keep at least 8 pixels from digit/colon boxes
   and avoid every changing LED, reflection, hand, laundry item, wall or flexible mount part.
3. Confirm that the physical mount, digits/colon and selected fixed feature are correct, then
   choose **Confirm alignment & store reference**. This stores only this anchor's edge features,
   coordinates, frame size and an optical-profile hash—not a full room frame or credentials.
4. Allow two fresh checks (about 5–10 seconds) for **Anchor aligned**. Test both room-light
   conditions. If fixed text vanishes in darkness, the checker cannot validate that lighting:
   choose a better anchor or leave this optional feature unconfigured. Do not weaken OCR settings
   or add continuous illumination just to make this warning pass.

Checks run at most once every five seconds. A distinctive match shifted more than four native
pixels must recur three times consistently before **Possible movement** appears (normally
10–15 seconds). Two matching unshifted checks clear that warning. Dim, missing, blurred,
repeating or ambiguous features show **Cannot verify**, not **Anchor aligned**; an existing
movement warning is retained within the service run until alignment is positively re-established.
After a service restart, the stored reference is loaded but checks start afresh; startup never
assumes alignment. Stale capture is
reported separately. Small vibration is tolerated, and changed digits outside the anchor do not
participate in matching. Match scores are not accuracy probabilities.

The translation search extends 32 pixels around the reference location. Larger movement,
rotation or changed perspective may become **Cannot verify**, not a measured displacement.
An aligned anchor does not guarantee all digit boxes are correct: a poorly chosen or moving
anchor can mislead this heuristic. Inspect the physical mount and actual display when warned.

The private reference is `CONFIG_PATH.alignment.npz`, atomically replaced without changing the
YAML config. It survives service restarts; incompatible saved optics/frame geometry requires a
new user-confirmed reference. Calibration tests pause checks. Files are size/shape/type bounded,
loaded without pickle, and excluded from Git, optical-profile exports and diagnostic ZIP images.
Diagnostics include only alignment status/offset metadata. **Forget stored reference** deletes
that one private reference, leaving optics, MQTT and countdown state alone.

API actions are `POST /api/alignment/reference` with exactly `anchor_box`, current `revision`, and
`confirmed: true`, and `POST /api/alignment/forget` with `confirmed: true`; both require JSON.
They use the same trusted-local-network boundary as the setup page. No anchor is captured,
replaced or uploaded automatically. Validate on the real final mount before relying on warnings.

Home Assistant's **Mount alignment** diagnostic now mirrors this optional checker over the
expiring health heartbeat. No images or coordinates are published and no notifications are
enabled. See [alignment entity values](home-assistant.md#optional-mount-alignment-diagnostic),
especially `uncheckable`, `movement_unverified`, and `stale`, before using it in automations.

## Optional pixel-setting suggestions

Under **Camera and readability**, expand **Need a starting point? Suggest pixel settings**.
Turn on a known countdown, align all digit/colon boxes, and choose **Find pixel settings**.
This read-only request tries blue, green, red, grayscale and brightest-colour channels with up to
two fixed brightness cutoffs each. Otsu separates the dark/lit pixel classes; the class-mean
midpoint is also tried and preferred on equal match scores. Saved recognition remains unchanged.

The single current display crop must be fresh (at most five seconds old), at most one million
pixels, and captured with saved settings. Tests/pending camera changes, capture errors and a
concurrent request are rejected. Constant/low-contrast frames, invalid/approximate glyph patterns
or similarly plausible conflicting readings do not yield a recommendation. If saved settings
already fit as well, the page suggests no change. These heuristics cannot prove that the display
is on or correctly aligned: reflections or poor geometry may still create a plausible value.

If advice is offered, compare its text with every actual digit and the colon. **Copy suggestion
to form** changes only local channel/cutoff fields. It does not apply optics, save anything or
pause MQTT. Choose **Test changes**, inspect the result, then **Save settings** or **Discard
changes** using the normal workflow. Advice expires after one minute and is invalidated by edits,
tests, configuration revisions or a lost connection. A match percentage is a sampling-fit score,
not an accuracy probability. Recheck bright/dim lighting and several readings before saving.

The read-only endpoint is `GET /api/suggestions`; it returns advice and snapshot metadata, not
images, credentials or identity. There is no continuous auto-tuning, alignment correction, focus
search or exposure adjustment. A bumped mount, clipped boxes, missing LED segments and blur need
to be addressed first. Suggestions are starting points, not manufacturer/model presets.

## Installation checklist

Expand **Installation checklist** below the health panel. Its seven manual checks cover secure
mount/alignment, countdown formats and estimate jumps, bright and dim lighting, completion and
blank behaviour, Home Assistant/optional alerts, and recovery after a safe Pi reboot. Mark checks
only after observing them with the saved settings; no check is passed automatically. A complete
checklist is a user confirmation, not an accuracy guarantee or proof of long-term stability.

Progress is saved in this browser's local storage for this sensor address, alongside a signature
of the public optical settings. It survives page reloads and service restarts, but is not stored
on the Pi, shared with Home Assistant, included in profile/diagnostic exports, or transferred to
another browser/address. It stores no images or credentials. If browser storage is unavailable,
the page warns that progress lasts only for the current visit.

Confirmations are paused while disconnected, testing or editing. Discarding a temporary test
keeps the previous confirmations; changing saved optical settings clears them, including when
detected on reopening the page. Checkmarks do not detect physical movement or changes to external
Home Assistant automations: use **Reset checklist confirmations** and repeat affected checks.
Checklist controls never save calibration, publish MQTT, reboot the Pi or trigger notifications.

## Health panel and offline behaviour

The panel separates the setup-page connection, camera/frame freshness, MQTT connection, and the
last readable display. A blank or unreadable display is not a camera outage. Temperature, Wi-Fi
signal and available memory are sampled passively at most every ten seconds; unsupported system
measurements show **Not available**, not a fabricated healthy reading. Signal is not a packet-loss
measurement. MQTT reports broker connectivity, not confirmation that Home Assistant consumed a
particular message.

Live-camera startup no longer waits for the MQTT broker. If a guest network cannot resolve or
reach the broker, the camera and calibration page remain usable while MQTT retries with bounded
backoff. Home Assistant still cannot update until routing/DNS/broker access is restored. Broker
credentials and network rules are never changed by calibration. Existing one-shot and replay
commands retain their synchronous MQTT connection behaviour.

## Recent reading quality

Expand **Sensor health → Recent reading quality · last 5 minutes** to compare more than one
snapshot. Four counts show fresh candidate observations: readable countdown/terminal text,
blank patterns, unreadable patterns or formats, and processing errors. Percentages use captured
observations as their denominator—not elapsed time, uptime, or the held Home Assistant state.
They are not accuracy scores: check recognized numbers against the appliance. Blank patterns
are expected when the display is off; a visibly lit screen classified as blank needs inspection.

The panel labels saved versus applied test settings, actual sample span and latest-sample age.
Capture gaps do not manufacture samples. Stale/error camera status labels any remaining counts
as historical; a disconnected browser hides them until reconnection. Untested form edits are
not included. Counts expire after five minutes, with one-second bucket precision, and reset on
Test, Save, Discard, preview expiry, and service restart. Moving the physical mount does not
reset the history; allow five minutes for previous-position observations to age out.

Collection is passive and bounded to at most 301 count-only buckets in memory, even when the
page is closed. No images/history files, new MQTT entities, notifications, or settings changes
are produced. Settings-handoff frames are excluded so previous camera settings do not seed
the new summary. `GET /api/state` includes the `reading_quality` report.

## Countdown history

Expand **Sensor health → Countdown history · last 30 changes** for a memory-only list of
accepted readings, newest first. Times are shown in the browser's local time zone (the API
uses UTC). Entries include the first accepted countdown, changes in either direction, confirmed
terminal text, and unknown states after the existing grace/confirmation rules allow them.
Brief unreadable frames that leave the accepted state unchanged do not add entries. Completion
latched across a blank screen remains complete rather than generating a false unknown event.

A `40 → 19 min (-21 min)` entry is simply the difference between consecutive accepted displayed
values. It is **not** a wall-clock-corrected finish-time adjustment, proof of adaptive sensing,
a cycle boundary, or an error verdict. Normal one-minute ticks are also included. Capture gaps
over the camera stale threshold add a “frames resumed” entry when frames return and break the
comparison; accepted unknown/error states also break it. A live camera or accepted value is not
proof the decoder is correct, so compare unexpected changes against the physical display.

The list labels saved versus tested settings, discarded older entries, and stale/disconnected
status. It resets with Test, Save, Discard, preview expiry, and service restart, just like the
recent-quality counters. It records at most 30 entries while the setup page is closed; no images,
raw exception text, files, MQTT entities/events, notification triggers, or state changes are
produced. This is local troubleshooting history, not a durable cycle log or proof of HA delivery.
`GET /api/state` includes `reading_history`; it is not added to exported diagnostic bundles.

## Explain this camera view

Under **Camera and readability**, open **Explain this camera view** and select **Check this
view**. It analyzes one fresh display crop using saved settings or an already applied test.
Untested form edits must be tested or discarded first. No settings, MQTT state, or files are
changed by the check, and it does not pause recognition.

The check explains measurable symptoms: bright segment cores reaching the display crop edge
or crossing digit-box edges, boxes treated mostly as lit, light missed by sampling strips,
poor segment fit, contrast below a fixed cutoff, and patterns that do not match the configured
countdown format. Boundary hints suppress broad colour glow and small colon-like patches.
The hints are conservative heuristics, not proof of clipping or a definitive diagnosis of blur
or incorrect exposure. Focus is a suggested visual check when segment matching is poor.

A blank reading is described conditionally: if the appliance is off, leave settings alone;
if it is lit, verify crop/channel/cutoff against a known countdown. H:MM feedback keeps colon
detection diagnostic-only. A clean snapshot is not a guarantee that the actual value is correct.

Results identify saved/test mode and snapshot text; they clear after one minute, on edits or
settings changes, or on disconnection. Re-check after moving the mount even if settings have
not changed. The server requires a frame no older than five seconds, rejects pending camera
settings/capture errors and crops over one million pixels, and serializes checks with pixel
suggestions. There is no background image analysis for this feature.

The read-only endpoint is `GET /api/readability-feedback`. It returns bounded guidance and
per-digit light/contrast measurements, with no full-frame pixels, credentials or broker details.

## Configuration safety

The setup API accepts camera optics, display geometry/recognition, unreadable-frame grace,
and the countdown-format selector. Device identity, MQTT topics, usernames, and passwords
cannot be changed through the
page, and credentials are never included in its API responses.

Saving first copies the existing file to `config.local.yaml.bak`, validates the candidate through
the normal configuration loader and against the latest camera frame, then atomically replaces the
configuration. The current implementation keeps one rollback copy.

## Optical profile backup and recovery

Open **Backup and recovery** below the save/test controls:

- **Export saved profile** downloads a versioned JSON snapshot of the saved optical calibration,
  even when a temporary test is active. It excludes credentials, MQTT/network settings, device
  identity, local file paths, and full-frame images.
- **Import into test mode** validates a previously exported profile, confirms the action inline,
  and starts a temporary test. It does not save automatically. The camera resolution and rotation
  must match; unsupported versions, incomplete files, private fields, invalid numbers and invalid
  geometry are rejected. A matching resolution does not guarantee alignment after moving a mount.
- **Test previous calibration** reads the one-level `.bak` rollback copy and copies only optical
  settings into test mode. It never restores the old MQTT address, password, topics, or identity,
  even if those differed in the backup. The button is unavailable before the first saved change.

Check alignment and recognition, then **Save settings** to commit or **Discard changes** to keep
the current saved calibration. Test mode pauses MQTT state transitions and expires after ten
minutes. Saving a recovered profile makes the previously current calibration the new rollback
copy. Profiles do not transfer appliance semantics, terminal-message rules or glyph allowlists.

HTTP endpoints are `GET /api/profile`, `POST /api/profile/preview`, and
`POST /api/restore/preview`. Import bodies use the exact exported JSON format and are limited to
64 KiB. No endpoint downloads the full private configuration or its rollback file.

## Cropped diagnostic download

Under **Inspect detection**, choose **Download cropped diagnostics (.zip)**. This takes one
snapshot using the server's tested settings (or saved settings when no test is active), not
untested browser edits. It does not save calibration, pause MQTT, or upload anything.

The archive contains `display.png`, `segments.png`, `binary.png`, `report.json`,
`optical-profile.json`, and a README. The report includes recognition scores, frame age, pending
camera-settings status, passive system health and MQTT connection status. It excludes full-frame
images, credentials, broker/network addresses, device identity, local paths, raw logs and error
strings. Images are freshly encoded without source EXIF. Review the images before sharing:
a misplaced display rectangle can still include background, and the display itself may be private.

Generation is memory-only and single-flight, with a one-million-pixel crop limit and an 8 MiB
archive limit. A whole-frame rectangle or missing camera frame is rejected without a full-frame
fallback. A snapshot is not evidence of long-term reliability. To replay `display.png`, use a
separate test configuration with ROI `[0,0,crop_width,crop_height]`; the included optical profile
retains the original live-camera ROI and must not be changed for cropped replay on the live Pi.

The download endpoint is `GET /api/diagnostics.zip`. It has the same trusted-local-network access
boundary as the rest of the setup page.

Run `scripts/install_service.sh` again after upgrading an older service installation. The current
systemd template grants the service write access to the configuration directory so atomic save
and rollback work under `ProtectSystem=strict`. A dedicated runtime configuration directory gives
the narrowest permission boundary; using the project-root `config.local.yaml` makes that project
directory writable to the already unprivileged service account.

The full-frame preview is visible to anyone who can reach the local setup port and may include
more than the appliance display. Disable the page or bind it to `127.0.0.1` when remote calibration
is not needed. Retained automatic diagnostics remain display-cropped.

The full preview is downscaled and JPEG-encoded at most once per camera frame, then shared by all
open tabs. Hidden tabs suspend frame requests. These limits are important on a Pi Zero 2 W; older
versions of the page should not be left open in multiple tabs.
