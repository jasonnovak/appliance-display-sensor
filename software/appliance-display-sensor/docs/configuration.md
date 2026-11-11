# Configuration and calibration

The example configuration uses synthetic coordinates. Real coordinates will be generated during
camera calibration.

## Coordinate system

Every rectangle is written as:

```yaml
[x, y, width, height]
```

`display.roi` is relative to the full camera frame. `digit_boxes` and `colon_box` are relative to
the cropped display ROI.

```text
full image
┌───────────────────────────────────────┐
│             display.roi               │
│       ┌─────────────────────────┐     │
│       │ [digit]  :  [digit] ... │     │
│       └─────────────────────────┘     │
└───────────────────────────────────────┘
```

This two-level coordinate system prevents changes outside the display from affecting digit
calibration.

## Input settings

`input.type` supports `image_file` for a single development frame, `image_directory` for an
ordered replay sequence, and `picamera2` for a locally attached Raspberry Pi camera. A
command-line `--replay-directory` override can be used without changing the configuration:

```yaml
input:
  type: image_directory
  path: ../debug/replay
```

The camera remains a separate input adapter and does not change the display or semantic
configuration model.

The measured reference-camera configuration currently uses:

```yaml
input:
  type: picamera2
  camera_index: 0
  resolution: [2304, 1296]
  rotation: 180
  exposure_time_us: 8333
  analogue_gain: 1.0
  autofocus_mode: manual
  lens_position: 6.75
  warmup_seconds: 2.0
  frame_interval_seconds: 1.0
  capture_burst_count: 4
```

Exposure time and analog gain are either both omitted for automatic exposure or both specified for
locked exposure. `autofocus_mode` supports `default`, `auto`, `continuous`, and `manual`; manual
mode requires a lens position. These values are installation-specific starting data, not universal
defaults. `capture_burst_count` takes consecutive camera frames and combines them with a per-pixel
maximum before decoding. This reconstructs digit positions that the appliance illuminates at
different points in its multiplexing cycle while retaining only one composite frame. Start with
`1`; use `3` or `4` when live observations alternate between partial digits. Use
`--max-frames 3 --no-mqtt` for a finite hardware smoke test.

## Display settings

- `channel`: `blue`, `green`, `red`, `gray`, or `max`.
- `threshold.method`: `fixed` for a locked camera or `otsu` for automatic threshold selection.
- `threshold.value`: fixed brightness threshold from 0 through 255.
- `min_segment_fill`: required illuminated fraction in a segment sample region.
- `colon_min_fill`: required illuminated fraction in the larger colon region.
- `min_digit_confidence`: minimum match quality against the configured glyph set.
- `segment_thickness_ratio`: width of each sampling region relative to a digit box.
- `segment_slant_ratio`: horizontal top-to-bottom segment shift relative to digit width. Positive
  values describe digits that lean left toward the bottom; zero describes upright digits.
- `colon_after`: number of digit positions before the colon.
- `allowed_glyphs`: symbols the decoder may select. The built-in seven-segment set is `blank`,
  `0`-`9`, `E`, `n`, and `d`. Restricting the candidates to symbols actually used by an appliance
  reduces false matches.

## Duration semantics

`semantics.countdown_format` defaults to `auto` for existing installations. In this mode,
detected colon text such as `1:23` means hours and minutes. With the colon off,
`no_colon_unit` determines whether `41` means minutes or seconds; `112` can mean 112 minutes.

The reference laundry use case uses:

```yaml
semantics:
  countdown_format: H:MM
  no_colon_unit: minutes
  terminal_texts: ["End"]
```

Terminal text comparison is case-insensitive. A recognized terminal message produces `complete`
with zero minutes remaining instead of trying to parse the letters as a number.

Choose **Countdown format → H:MM** in the setup page, then Test changes and Save settings,
for a display with exactly three positions: hour, minute tens, minute units. This mode
uses digit positions, independent of the colon box, colon position or detected colon light:
`112` becomes `1:12` (72 minutes), a blank hour plus `21` means 21 minutes, and two
leading blanks plus `1` means 1 minute. A full hour reading requires both minute digits;
internal/trailing blanks and minutes above 59 are rejected. All-blank remains unknown.
H:MM always uses minutes, regardless of `no_colon_unit`.

H:MM ignores phantom colon light in `End` and uses digit-only confidence. Raw colon state,
colon confidence and optical text remain available in diagnostics; interpreted text is
used by the setup page and Home Assistant. Digit alignment and readable segments are
still required. This mode cannot distinguish a suppressed leading digit from a genuinely
missed leading digit; verify the entire display across hour and minute readings.

Version 1 **optical** profile exports/imports and optical rollback do not change countdown
format. The format is stored in the main configuration and included in diagnostic reports.

Countdown values are treated as the appliance's current estimate, not as a strictly decreasing
clock. Sensor-controlled cycles may increase or decrease the displayed time; either direction is
accepted after the normal confirmation threshold, and `estimated_finish` is recalculated from the
new observation.

A numeric `0` is not completion by default because an appliance may still be sensing, cooling, or
about to display a separate terminal message. An appliance that uses zero as its authoritative
completion indication can configure it explicitly:

```yaml
semantics:
  terminal_texts: ["0"]
```

## Stability and short-lived terminal messages

The reference dryer displays `End` for approximately 20 seconds and then blanks the screen. Live
capture should use:

```yaml
stability:
  confirmations: 2
  latch_completion_until_next_cycle: true
  unknown_grace_seconds: 15
```

After `End` is confirmed, blank observations retain the completed state. A new numeric countdown
must pass the normal confirmation threshold before the state changes back to running. This keeps
finish alerts and voice queries correct after the physical display has turned off.

While a cycle is running, `unknown_grace_seconds` retains the last valid reading through a short
run of unreadable frames. This is important for multiplexed LED displays, which can appear partly
or entirely blank during an individual camera exposure. After the grace period, the usual
confirmation count is still required before `unknown` is published. Startup on a genuinely blank
display is not delayed because there is no prior valid reading to retain.

## Browser calibration

The optional local setup page edits only camera, display, and stability fields. It never returns
MQTT credentials to the browser. See [Browser calibration](browser-calibration.md) for enabling,
using, and securing it.

## Bounded transition diagnostics

An installation can retain a small, privacy-cropped set of diagnostic overlays whenever a state
change is accepted:

```yaml
diagnostics:
  transition_directory: debug/transitions
```

The directory contains fixed `latest`, `latest-running`, `latest-complete`, and `latest-unknown`
filenames rather than an unbounded frame history. This is particularly useful when a short-lived
terminal message fails recognition: the unknown-transition image is not overwritten when the
same unknown state subsequently becomes a completely blank panel. Omit the setting or use `null`
to disable automatic snapshots.

## Device identity

`device.name` is the name shown in Home Assistant. Entity names remain generic, so the resulting
UI naturally reads `Washer Time remaining` or `Dryer Time remaining` depending on the configured
device name.

`device.identifier` must be stable and unique within an MQTT/Home Assistant installation.

`device.appliance_type` is optional metadata. Leaving it null does not reduce decoder capability.

## Credentials

Do not commit MQTT passwords. Store the password in an ignored file and reference it relative to
the configuration:

```yaml
mqtt:
  enabled: true
  host: homeassistant.local
  port: 1883
  username: appliance_display_sensor
  password_file: secrets/mqtt_password
```

Set the password file to owner-read/write only (`chmod 600 secrets/mqtt_password`). Inline
`mqtt.password` remains supported for compatibility, but it must not be combined with
`mqtt.password_file` and should not be used in a shareable configuration.
