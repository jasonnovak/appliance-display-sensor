# Appliance Display Sensor

Appliance Display Sensor turns a non-smart appliance display into local home-automation
sensors. A fixed camera observes a calibrated display region, deterministic image processing
reads the countdown, and MQTT exposes the result to Home Assistant.

The initial release targets fixed seven-segment LED/LCD countdown displays. Independent status
indicator regions are planned, not included in this release. Washers and dryers are the first documented use cases, but appliance type is not
hard-coded into the decoder.

> **Project status:** experimental release candidate. Live decoding, browser calibration,
> MQTT/HA entities, health reporting and update tools are implemented. The reference
> dryer has completed real adaptive cycles through End and blank. Fresh-install checks
> and final-mount/lighting/recovery validation remain open. See the consolidated
> [release status](../../docs/release-status.md) and [physical tests](../../docs/physical-tests.md).

Optional Google speaker support is documented separately in the
[self-hosted voice bridge guide](../google-runcycle-bridge/docs/self-hosted-setup.md).
It adds native countdown answers on the requesting speaker using your own developer
integration and HTTPS endpoint. It is not required for local sensing, MQTT or HA alerts.

## Principles

- **Appliance-neutral:** `Washer`, `Dryer`, or any other name is instance configuration.
- **Local-first:** full images do not need to leave the Raspberry Pi.
- **Deterministic before AI:** a calibrated seven-segment decoder is smaller, faster, and easier
  to validate than general OCR for the initial problem.
- **Non-invasive:** no appliance disassembly and no connection to mains wiring.
- **Composable:** temperature, vibration, or power data can later corroborate the optical reading.

## Current capabilities

- Calibrated display and digit rectangles
- Configurable segment slant for italicized seven-segment displays
- Blue, green, red, grayscale, or maximum-channel extraction
- Fixed or Otsu thresholding
- Configurable seven-segment digits, blank positions, an optional colon, and a constrained letter
  subset (including the `End` glyphs)
- Minute countdowns such as `41` and hour/minute countdowns such as `1:10`
- Configurable terminal messages, reading confidence, repeated-reading stabilization, and
  completion latching after the display goes blank
- A configurable unreadable-frame grace period that holds the last valid countdown through brief
  glare, rolling-shutter, or LED-multiplexing gaps
- Adaptive-cycle estimates that may move earlier or later without being rejected as an invalid
  countdown
- Live Picamera2 input with configurable resolution, rotation, exposure, gain, autofocus, focus
  position, warmup, frame interval, and maximum-composited capture bursts for multiplexed LEDs
- Ordered directory replay through the same frame-processing pipeline planned for live capture
- Display-only diagnostic overlays with segment scores and accepted-state information, including
  bounded automatic snapshots for accepted transitions
- Generic Home Assistant MQTT discovery for:
  - Raw display text
  - Time remaining
  - Estimated finish
  - Status
  - Running
  - Reading confidence
- Live-camera Home Assistant diagnostics for camera freshness, display readability, last-readable
  time/age, sustained reading problems, and passive Pi health, with expiring heartbeat updates
- Synthetic display generation and unit tests
- A local browser calibration page with a live frame, draggable display ROI, generated/manual
  digit boxes, optical controls, detection feedback, safe preview, and atomic save/rollback

## Planned hardware reference

- Raspberry Pi Zero 2 W
- Raspberry Pi Camera Module 3 Standard
- 300 mm Standard-to-Mini camera cable
- Removable magnetic top mount

Camera Module 3 does not provide a microphone, and the Pi Zero 2 W has no onboard audio input.
Audio-event detection would therefore require a separate microphone. It is not part of the initial
design because nearby appliances can play similar completion tunes; a visual terminal message is
more directly attributable to the observed appliance.

Other cameras and computers can be supported as long as an input adapter supplies an OpenCV
image array.

Physical mount development is tracked separately in the
[mount design handoff](docs/mount-requirements.md) so CAD work and software work can proceed in
focused tasks while sharing the same repository.

## Quick development demo

Python 3.11 or newer is required.

```console
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e .[dev]
python scripts/generate_fixture.py --text 1:23 --output sample-display.png
python -m appliance_display_sensor --config configs/example-seven-segment.yaml --no-mqtt
```

The expected decoded state includes:

```json
{
  "confidence": 1.0,
  "device_identifier": "appliance-display-01",
  "device_name": "Appliance Display",
  "display_text": "1:23",
  "remaining_minutes": 83,
  "running": true,
  "status": "running"
}
```

Run the tests with:

```console
python -m unittest discover -s tests -v
```

For the dependency-free checklist, pixel-advice and anchor UI logic tests, a development machine
with Node.js can run `node --test tests/test_calibration_ui.cjs tests/test_pixel_advice_ui.cjs tests/test_alignment_ui.cjs`.
Node.js is not required on the Pi or for normal use.

For the reference Raspberry Pi runtime, copy the repository to Raspberry Pi OS Lite and run:

```console
bash scripts/bootstrap_pi.sh
```

This installs the Raspberry Pi OS camera and OpenCV packages, creates a Picamera2-compatible
virtual environment, installs the project, and runs the camera-independent tests. See
[Raspberry Pi setup](docs/raspberry-pi-setup.md) for the full handoff.
For subsequent source-only changes, see [safe updates and rollback](docs/runtime-updates.md).

The [camera-independent development workflow](docs/development-workflow.md) explains directory
replay, continuous-loop simulation, and diagnostic overlays. The current
[reference-camera validation](docs/camera-validation.md) records the measured Camera Module 3
settings and real-sequence results leading into the Picamera2 adapter.

For MQTT entity behavior, completion automations, and the current difference between Home
Assistant Assist and Google Assistant voice access, see the
[Home Assistant guide](docs/home-assistant.md).

## Configuration model

The user-facing device identity is separate from the optical decoder:

```yaml
device:
  identifier: upstairs-washer
  name: Upstairs Washer
  appliance_type: washer  # Optional metadata

display:
  decoder: seven_segment
  roi: [0, 0, 420, 150]
  digit_boxes:
    - [25, 15, 70, 120]
    - [175, 15, 70, 120]
    - [285, 15, 70, 120]
  colon_box: [120, 38, 24, 74]
  colon_after: 1
  allowed_glyphs: [blank, "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "E", "n", "d"]

semantics:
  no_colon_unit: minutes
  terminal_texts: ["End"]

stability:
  confirmations: 2
  latch_completion_until_next_cycle: true
  unknown_grace_seconds: 15

calibration:
  enabled: false
  host: 127.0.0.1
  port: 8090
```

Changing `name` to `Dryer`, `Dishwasher`, or `Workshop Timer` does not select different decoder
code. `appliance_type` is optional metadata reserved for integrations and automations that benefit
from semantic appliance categories.

Manufacturer/model-specific presets may eventually provide starting calibration coordinates, but
they remain data files layered over the generic decoder.

See [Configuration and calibration](docs/configuration.md) for the coordinate model and
[Browser calibration](docs/browser-calibration.md) for the guided setup page.

## Architecture

```text
image file now / Camera Module 3 later
                    │
                    ▼
        crop + channel + threshold
                    │
                    ▼
          seven-segment decoder
                    │
                    ▼
      duration semantics + stabilization
                    │
                    ▼
        MQTT + Home Assistant discovery
```

The decoder produces visual facts—glyphs, colon state, and confidence. A separate semantic layer
interprets those facts as minutes or a terminal state. A publisher exposes generic entities beneath
the configured device identity. See [Architecture](docs/architecture.md) for the extension
boundaries.

## Privacy

The intended production pipeline crops to the calibrated display immediately. Diagnostic captures
are opt-in and ignored by Git. Public test fixtures should contain only the display region, should
have metadata removed, and must not show a home interior or identifying information.

The full laundry-room photographs used during initial feasibility discussion are deliberately not
included in this repository.

## Scope and non-goals

Version 1 will support fixed seven-segment countdown displays. The architecture permits additional
decoders later, but the project does not currently claim universal OCR, arbitrary graphical-screen
recognition, appliance control, or safety-critical monitoring.

## Roadmap

The project stays countdown-first: a basic installation should require only a camera preview,
one display rectangle, a digit/colon layout, a few confirmed sample readings, and a device name.
Advanced controls must not be required for a typical washer or dryer.

The optional [custom segment sampling editor](docs/segment-sampling.md) adjusts the seven sample
regions visually and includes them in reusable optical profiles. Existing automatic sampling and
countdown interpretation remain unchanged unless a custom layout is explicitly tested and saved.

The release sequence is:

1. Validate Camera Module 3 capture, optics, and multiplexed-display handling.
2. Deliver a guided browser calibration workflow and a usable Raspberry Pi service.
3. Add optional status-symbol regions, reusable optical profiles, and stronger diagnostics.
4. Add appliance-state corroboration such as exhaust temperature without coupling it to the
   optical decoder.
5. Generalize input and decoder backends only after the countdown sensor is reliable.

The detailed [product roadmap](docs/roadmap.md) records release gates, the simple and advanced
setup paths, and ideas adopted from related display-reading projects. See also
[prior art and related projects](docs/prior-art.md).

## Related projects

Appliance Display Sensor builds on a long history of optical display reading. Particularly useful
references include [ESP32 Display Reader](https://github.com/DocBig/ESP32-Display-Reader), Home
Assistant's legacy [Seven Segments OCR](https://www.home-assistant.io/integrations/seven_segments/)
integration, and [AI-on-the-edge-device](https://github.com/jomjol/AI-on-the-edge-device). Their
relationship to this project's narrower countdown and appliance-state goals is documented in
[prior art](docs/prior-art.md).

## License

[Apache-2.0](LICENSE) for original software and its documentation; see [NOTICE](NOTICE).
Mount and case designs, CAD generators, print exports and design documentation under
`hardware/` use [CERN-OHL-P-2.0](LICENSE-HARDWARE). Third-party components retain their
own licenses. This revision adopts Apache-2.0 on 2026-10-27; earlier MIT grants remain valid.
