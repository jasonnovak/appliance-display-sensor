# Camera-independent development workflow

Directory replay exercises the same decoder, semantic mapping, stabilizer, diagnostics, and MQTT
publication decisions used by the live camera adapter. It allows state behavior to be tested
without pretending that synthetic images determine the final optical calibration.

## Build a replay sequence

Place supported images in a directory and name them in observation order. Each reading should
normally appear at least as many times as `stability.confirmations` requires:

```text
debug/replay/
├── 01-41.png
├── 02-41.png
├── 03-40.png
├── 04-40.png
├── 05-End.png
├── 06-End.png
├── 07-blank.png
└── 08-blank.png
```

`debug/` is ignored by Git because replay and diagnostic images may contain private surroundings.
Public fixtures should be tightly cropped, stripped of metadata, and intentionally reviewed before
being placed elsewhere in the repository.

Synthetic frames can be generated with:

```console
python scripts/generate_fixture.py --text 41 --output debug/replay/01-41.png
python scripts/generate_fixture.py --text End --output debug/replay/05-End.png
python scripts/generate_fixture.py --text blank --output debug/replay/07-blank.png
```

## Run one replay pass

```console
python -m appliance_display_sensor \
  --config configs/example-seven-segment.yaml \
  --replay-directory debug/replay \
  --diagnostics-dir debug/diagnostics \
  --no-mqtt \
  --compact
```

On Windows PowerShell, place the command on one line or use PowerShell backticks instead of the
backslashes shown above.

Each JSON event contains:

- `candidate`: the interpretation of the current frame;
- `stable`: the last state that passed the confirmation rule, or null while still pending;
- `stable_changed`: true only when a new stable status/countdown value is accepted;
- `source`: the image that produced the observation.

New MQTT state is published when `stable_changed` is true. After reconnecting to the broker, the
publisher also resends its latest accepted state, discovery, and online availability, even if the
display has not changed. With `--no-mqtt`, the complete decision path can be inspected without
connecting to Home Assistant.

## Simulate a continuous source

```console
python -m appliance_display_sensor --config configs/example-seven-segment.yaml \
  --replay-directory debug/replay --loop --interval 1 --no-mqtt --compact
```

Stop the loop with Ctrl+C. Diagnostic filenames are derived from source filenames and overwritten
on later loops, so this mode does not create an unbounded sequence of images.

## Diagnostic overlays

Each overlay contains only `display.roi`, not the entire input frame. It shows:

- each configured digit position;
- active and inactive segment sample regions;
- selected glyph and confidence;
- colon region and state;
- current candidate and stable status.

These overlays are the primary calibration aid for Camera Module 3 and replayed captures.

## Camera handoff

Reference camera testing is underway; measured optical results are recorded in
[camera-validation.md](camera-validation.md). The Picamera2 adapter now supplies live frames to the
same `FrameProcessor`, terminal-message semantics, stability rules, diagnostics, and MQTT
state-change policy used by replay. Real frames have supplied provisional ROI, exposure, focus,
segment-slant, and LED-multiplexing settings for the reference dryer.
