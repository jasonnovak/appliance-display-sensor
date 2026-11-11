# Product roadmap

For current release gates and supported scope, use the consolidated
[release status](../../../docs/release-status.md). This roadmap also includes future
work and historical evidence; an unchecked idea is not automatically a release blocker.

## Product thesis

Appliance Display Sensor is a simple, local countdown-display sensor first. It turns a fixed
appliance display into reliable Home Assistant entities for raw display text, remaining time,
estimated finish, running state, completion, and reading confidence.

The initial product is not a universal OCR system. Washers and dryers are the first documented
use cases, but the decoder and entity names remain appliance-neutral. A user who only needs a raw
number or glyph can build Home Assistant automations from the raw display-text entity without a
new appliance-specific code path.

Remaining time is explicitly a live appliance estimate. Sensor-controlled cycles may revise it
upward or downward, so no monotonic-countdown assumption is permitted. Estimated finish moves with
the displayed value, while completion requires configured terminal evidence such as `End` rather
than the passage of wall-clock time alone.

## Setup experience

### Basic path

A normal countdown installation should require only:

1. Open a live camera preview.
2. Draw one rectangle around the display.
3. Select the digit count and optional colon position.
4. Confirm a small set of readings, including a normal countdown and any terminal text such as
   `End`.
5. Enter the Home Assistant device name and MQTT connection.

Everything else should receive safe defaults. The interface should explain a failed calibration
in terms such as focus, brightness, crop, or segment confidence rather than exposing image-
processing terminology first.

### Advanced path

An expandable advanced section may provide individual digit boxes, per-segment profiles,
threshold and channel controls, status-symbol regions, capture bursts, illumination, retained
diagnostics, and alignment checks. Advanced controls must not block or clutter the basic path.

## Release sequence

### Next normal laundry load — manual follow-up

- Open **Camera and readability → Explain this camera view → Check this view** while a
  countdown is visible. Compare the result with the physical display; note any false warnings
  or missed alignment problems and whether the room lights are on or off.
- Do this during the next normal load, not a special test run. No scheduled polling is needed.

### Phase 0: camera-independent core — complete

- Seven-segment digits, a constrained letter set, blank positions, and an optional colon.
- Minute and hour/minute countdown semantics.
- Explicit configurable H:MM digit-position interpretation, independent of colon detection,
  is implemented in the setup page and enabled on the reference dryer. Real-cycle validation
  across hour/minute/terminal transitions remains part of Phase 1.
- Configurable terminal text, including `End`.
- Repeated-reading stabilization and completion latching across a blank display.
- Replay input, privacy-cropped diagnostics, and synthetic tests.
- MQTT state and generic Home Assistant discovery for time remaining, estimated finish, status,
  running, and confidence.

### Phase 1: reference-camera validation — in progress

Exit gate: the reference dryer is read reliably in daylight and darkness over complete cycles.

The first supervised-service adaptive cycle now passes end to end: `41` → `40` → `19` → `5` →
`4` → `2` → `1` → `End`, retained MQTT state reports `complete`, and blank frames preserve the
latched completion. This validates estimate jumps in both directions and the terminal-state path
under the tested lighting and temporary mount.

- Exercise the implemented Picamera2 input adapter over complete reference-appliance cycles and
  add camera-health reporting.
- Validate the final physical pose and repeatability; temporary-mount field of view, focus range,
  and display pixel coverage are already sufficient.
- Promote the validated provisional focus, exposure, gain, and frame timing into the live adapter,
  then test them across lighting extremes.
- Characterize rolling shutter and LED multiplexing at `1:10`, minute-only values, `End`, and
  blank.
- Validate the implemented configurable maximum-composited capture bursts across full cycles;
  add confidence/temporal consensus only if compositing does not cover a display topology.
- Record tightly cropped, metadata-stripped replay fixtures for regression testing.
- Report camera availability, frame age, exposure, focus position, and capture failures as health
  diagnostics.

### Phase 2: minimum usable public release — in progress

Exit gate: a new user can install, calibrate, reboot, and obtain stable Home Assistant entities
without editing pixel coordinates by hand.

October 2026 polish delivered: plain-language labels with tap/keyboard-accessible help, separated
basic/advanced settings, individually movable/resizable digit and colon boxes, explicit untested
edit/test/saved banners, preview-expiry synchronization, and a cropped binary detection preview.
The page now reports camera/frame/readability age, MQTT connectivity, and passive Pi temperature,
Wi-Fi signal and memory. Live capture remains available during initial MQTT/DNS outages. These
changes do not establish that the earlier Wi-Fi outages are resolved.

Live-camera Home Assistant health reporting is implemented: separate non-retained 10-second
heartbeats, 45-second expiry, camera status, display readability, last-readable timestamp/age,
60-second sustained unreadability problem flag, and passive Pi temperature/Wi-Fi/memory.
Blank displays and calibration tests do not raise the unreadability flag. Reporting is independent
of capture and the setup page; existing countdown/completion logic is unchanged. Validate the
diagnostic entities after deployment. Phone/speaker health alerts are optional user automations
and are not enabled automatically.

- A passive five-minute recent-reading summary is implemented in the setup page: fresh-candidate
  readable/blank/unreadable/error counts, sample span and age, saved/test labels, stale/offline
  handling, and resets on settings transitions. Memory is bounded; no image retention or MQTT
  changes. Validate during the next normal laundry load, comparing actual digits with readings;
  this is decoder consistency, not an accuracy score. No scheduled check is required.
- Refine the implemented local browser setup page with its live preview and draggable/resizable
  display ROI.
- Validate the new individual box editor and basic/advanced interaction with new users;
  retain exact JSON geometry as an advanced option.
- Validate the implemented cropped overlay and binary threshold preview on additional displays.
- On-demand initial channel/fixed-cutoff suggestions are implemented using one bounded display
  snapshot and up to ten candidates. Exact segment patterns/agreement checks reject unclear
  results; already fitting settings are left alone. Advice only copies to the form, expires,
  requires explicit testing/saving, and never auto-tunes camera exposure or corrects geometry.
  Validate the suggestions on additional real displays and lighting extremes.
- Home Assistant raw display-text entity is implemented alongside interpreted countdown entities.
- Store MQTT credentials outside public configuration exports.
- Versioned, credential-free optical profile export/import and preview-first previous-calibration
  recovery are implemented. Imports preserve current identity, MQTT and appliance semantics;
  incompatible resolution/rotation, unsupported versions and invalid geometry are rejected.
  Future schema migrations remain explicit work rather than silently accepting unknown versions.
- Supervised Raspberry Pi OS service, availability/reconnect recovery, and restart handling are
  implemented. Capped persistent journals and 30-second health recording are installed on the
  reference Pi. A separate opt-in public recorder installer now provides dry-run, configurable
  operator/interface, backup and rollback guidance. Its passive stdlib sampler excludes images,
  credentials and network addresses. Host-wide persistent journal policy requires a separate
  flag. Validate installation and retention on a fresh Raspberry Pi OS installation.
- Home Assistant automation examples, completion-actions blueprint, and Assist versus Google
  Assistant guidance are implemented; validate the instructions with a fresh installation.
- One-click privacy-cropped diagnostic download is implemented: display, segment and binary PNGs,
  recognition/health report and optical profile, generated in memory with bounded size. No full
  room frames, credentials, network addresses, identity or raw logs are included. Review the crop
  before sharing; test-mode settings and frame age are labelled.
- A guided first-run checklist is implemented for mount/alignment, countdown formats, bright/dim
  lighting, terminal/blank behaviour, Home Assistant/optional alerts and restart recovery.
  Confirmations are manual and browser-local, invalidated by saved optical-setting changes and
  paused during edits/tests/offline operation. They are not automatic certification; physical
  mount movement and external automation changes require a manual reset/re-check.

### Phase 3: optical robustness and optional indicators

Exit gate: common fixed indicator LEDs and moderate lighting/pose changes do not require custom
code.

- Add named symbol/status ROIs with independent on/off thresholds and hysteresis.
- Publish each configured symbol as an optional Home Assistant binary sensor.
- Optional shared segment-shape profiles are implemented: an enlarged digit preview, selectable
  a–g sample rectangles, dragging/resizing and percentage inputs, with Test/Save/Discard. Existing
  automatic sampling remains the default. Version 2 optical export/import preserves custom shapes;
  version 1 restores automatic sampling. Decoder and overlay use identical validated rectangles.
  Real-display custom-shape validation remains a manual check, not an accuracy guarantee; per-digit
  shape overrides remain future work. See [custom segment sampling](segment-sampling.md).
- Detect excessive brightness, darkness, clipping, blur, low confidence, and stale frames.
  On-demand **Explain this camera view** feedback now covers conservative crop/digit-edge
  symptoms, excessive lit area, missed sample regions, cutoff/contrast and format mismatches.
  It distinguishes a blank display from conditional advice for a lit-but-unreadable display.
  It does not diagnose blur automatically, auto-adjust optics, or certify alignment; validate
  these hints on more real displays. Existing live health reporting covers stale frames.
- Opt-in static-anchor drift warnings are implemented in the setup page: bounded, privately
  persisted edge templates, rate-limited translation matching, repeated-shift confirmation,
  explicit dark/ambiguous/stale states and optical-profile invalidation. No anchor is captured
  automatically. A passive Home Assistant **Mount alignment** enum now exposes the existing
  status over the expiring health heartbeat, including an uncheckable-but-latched movement state.
  No pixels/geometry are published, no reference is chosen automatically, and the current
  health-alert blueprints do not act on it. This is warning-only: it does not prevent acceptance
  of bad readings, notify users or correct geometry. Validate real-mount anchors across
  lighting/cycles before adding alerts, a readout interlock or automatic correction.
- Support optional capture-only illumination with brightness and settling time. Prefer local GPIO
  control; an MQTT pre-capture trigger may be added for externally controlled lighting.
- Make diagnostic image publication opt-in, display-cropped, size-bounded, and clearly labeled as
  a privacy feature.
- Add calibration profiles that can be shared independently of network credentials and device
  names.

### Phase 4: appliance intelligence

Exit gate: additional observations improve state reliability while remaining explainable and
optional.

- Fuse exhaust-temperature observations without making temperature hardware mandatory.
- Allow configured status indicators to corroborate running, cooling, paused, or complete states.
- Preserve the raw optical reading, each supporting observation, and its confidence so users can
  understand state decisions.
- Optional Home Assistant health-alert blueprint is implemented for sustained unreadability and
  camera/connection faults, with configurable delays and user-selected actions. It uses existing
  health entities and adds no periodic reminders or enabled notifications. YAML/template tests
  pass; live HA import, fault timing and delivery remain installation checks. Pending waits reset
  on HA restart/reload; existing faults may require a new transition.
  An Android variant adds an explicit phone picker, high-priority delivery, configurable TTL
  (default zero: immediate-or-discard), and optional extra actions. It does not bypass DND or
  remove fault-confirmation delays. Actual idle-phone delivery remains an installation check.
- An optional finish-estimate change blueprint is implemented using the existing timestamp and
  health entities. It compares finish timestamps rather than ordinary countdown ticks, supports
  earlier/later/both, and rechecks health/continuity and the latest estimate before user-selected
  actions. Configurable thresholds and quiet time add no periodic reminders, automatic recipients
  or completion inference. YAML/template tests cover normal ticks, faults/recovery and revisions;
  live HA import, traces and delivery remain installation checks. It is prepared, not enabled.
  See [estimate-change alerts](estimate-change-alerts.md). Cumulative drift, separate revision
  entities/events and apparently-stalled-cycle detection remain future work.
- A local countdown-history panel now preserves the last 30 accepted state changes in either
  direction, with timestamps, displayed-minute differences, confirmed terminal/unknown states,
  and capture-gap markers. It is memory-only, reset on settings changes/restart, and does not
  change countdown semantics or publish notifications. Validate on the next normal load.
  Displayed-minute differences include normal ticks; they are not wall-clock-corrected finish
  revisions. Optional estimate-revision entities/events for automations remain future work.
- Evaluate vibration, power, and audio only as optional evidence adapters. Audio completion tunes
  are not authoritative when nearby appliances can sound alike.

### Phase 5: packaging and broader inputs

- Publish the adjustable magnetic mount after physical fit and vibration testing.
- Source-only update/rollback tooling is implemented for the editable Pi installation: read-only
  change plans, stopped-service and import-ownership checks, incoming tests/config validation,
  hash-checked backups, and refusal to overwrite later edits during rollback. It never migrates
  dependencies, configuration or service units; packaging changes require manual review. Validate
  the full operator workflow on a fresh installation; reproducible images and broader release
  migrations/recovery remain future work. See [runtime updates](runtime-updates.md).
- Add manufacturer/model calibration presets only as editable starting data.
- Benchmark the native decoder against `ssocr` on the same real-image corpus; consider an
  optional backend only if it improves supported cases without complicating the basic path.
- Evaluate alternate camera hosts, including an ESP32 input or firmware port, after the Pi
  reference implementation and configuration contract are stable.
- Optional Google Home `RunCycle` bridge is implemented separately from the local-first core.
  Native countdown replies on the requesting speaker were confirmed on a reference dryer;
  permanent HA OS hosting, stable HTTPS, non-expiring revocable account links, and natural
  idle queries are working. Retest an active countdown on the permanent host next load and
  verify full host reboot recovery. It remains an optional developer integration, not certified
  or a shared hosted service. The [self-hosted setup guide](../../google-runcycle-bridge/docs/self-hosted-setup.md)
  includes an offline credential wizard, first-install preview/apply helper and source-only
  public release builder. Independent clean-host installation and backup restoration remain release checks.
  aarch64, other appliance types and iOS linking are outside the initially verified scope.
- Track Matter as a possible local native-appliance adapter. Matter's Operational State cluster
  carries running state, phases, and estimated seconds remaining, and Google maps it to
  `RunCycle`. Google Home currently lists Laundry Washer—but not Laundry Dryer—among its
  supported Matter device types, so a dryer must not be mislabeled as a washer and Matter is not
  yet a supported Google Home release path for the reference dryer.

### Later decoder possibilities

These remain extensions, not version 1 commitments:

- other segmented LCD layouts;
- fourteen-segment alphanumeric displays;
- fixed graphical-display OCR;
- non-countdown numeric displays where raw values are the primary entity.

Every decoder should return the same structured optical observation and remain separate from
MQTT publication and appliance semantics.

## Explicit version 1 non-goals

- Universal OCR or arbitrary screen understanding.
- Appliance control or button actuation.
- Electrical/mains monitoring built into the reference hardware.
- Safety-critical alarms.
- Requiring an account, cloud service, machine-learning model, or full-frame image retention.

## Ideas adopted from related projects

The following concepts are valuable enough to include while independently implementing them for
this project:

- live draggable ROIs and immediate recognition feedback;
- independent symbol ROIs with hysteresis;
- reusable segment profiles and per-digit spacing;
- configuration export/import with device-specific identity protection;
- capture-time illumination and settling delays;
- real-time brightness, threshold, segment, and health diagnostics;
- multiple-frame consensus for multiplexed displays;
- alignment-drift detection and guided setup checks.

See [prior art](prior-art.md) for attribution and for the important distinction between generic
display recognition and appliance-aware countdown state.

Measured progress toward the Phase 1 exit gate is recorded in
[reference camera validation](camera-validation.md).
