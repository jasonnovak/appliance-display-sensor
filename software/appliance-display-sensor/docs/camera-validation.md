# Reference camera validation — historical September 2026 evidence

Current final-mount checks are tracked in [physical tests](../../../docs/physical-tests.md).
The focus/exposure values below are historical examples, not the current user profile.

This document records optical findings from the Raspberry Pi Zero 2 W, Camera Module 3 Standard,
and reference dryer. The numbers below are starting data for this installation, not universal
camera defaults.

## First mounted captures — 2026-09-04

- The camera is detected as an IMX708 and supports the expected 1536x864, 2304x1296, and
  4608x2592 modes.
- The temporary mount gives ample display coverage and focus detail. The mounted module is upside
  down, so capture uses a 180-degree rotation.
- Autofocus selected a lens position near `6.75`; locking that position prevents focus breathing
  during a cycle.
- Full auto exposure was unsuitable in dim light. At a reported lux value near `5.5`, it selected
  roughly 66.6 ms and analog gain 7.8, washing the panel in blue LED bloom.
- With analog gain 1, 1 ms and 2.5 ms exposures sometimes caught blank or partial multiplex
  phases. A 5 ms exposure remained inconsistent. An 8.333 ms (1/120 second) exposure was the
  shortest tested setting that captured complete digits in every bracket frame; 10 ms and
  16.667 ms were also consistent.

The provisional repeatable capture settings are therefore:

```text
resolution:       2304x1296
rotation:         180 degrees
exposure:         8333 microseconds
analog gain:      1
focus mode:       manual
lens position:    6.75
```

Picamera2 live capture must request `RGB888` to obtain the `(B, G, R)` NumPy channel order used
by OpenCV. Picamera2's packed-format names are counterintuitive here; requesting `BGR888` swaps
the red and blue channels and prevents a profile calibrated from OpenCV-loaded JPEGs from seeing
the blue display in its configured channel.

## Real-sequence results

A three-minute, fixed-setting sequence captured 89 frames at two-second intervals during an empty
sensor-controlled cycle. The appliance had already revised its initial estimate from 40 minutes
to 4 minutes before the sequence began. Every frame decoded to the visually correct value:

| Display text | Frames |
| --- | ---: |
| `4` | 30 |
| `3` | 1 |
| `2` | 30 |
| `1` | 28 |

Decoder confidence ranged from 0.7952 through 0.9184, averaging 0.8662. The one-frame `3` did not
become stable because the configured two-confirmation rule correctly filtered a value visible for
only one observation. The accepted stable sequence was `4` → `2` → `1`.

A subsequent 87-frame sequence taken after the display switched off produced 87 blank/unknown
observations at confidence 1.0 and no false numeric readings.

An earlier daylight cycle captured `End` for approximately 25 seconds followed by blank. The
camera-to-display alignment changed between that capture and the dim-light calibration, likely
from temporary-mount or camera seating movement, so the older `End` frames cannot validate the
newer pixel coordinates. This is useful evidence that a saved optical profile needs a rigid pose
and an alignment-drift check.

The real display also required a configurable segment slant. Its lower segments are shifted left
relative to its upper segments; applying a `segment_slant_ratio` of `0.18` allowed the same generic
decoder to read `4`, `3`, `2`, and `1` without weakening confidence thresholds.

## Live supervised-service result

After correcting the digit-box height, a fresh adaptive cycle produced the accepted sequence
`41` → `40` → `19` → `5` → `4` → `2` → `1` → `End`. The live `End` observation was accepted at
0.842 overall confidence; its individual glyphs measured approximately 0.84, 0.90, and 0.88.
Subsequent blank frames retained the stable `complete` state, and the MQTT broker's retained state
reported `display_text: End`, `remaining_minutes: 0`, and `running: false`.

## Historical remaining reference-camera gate

- Repeat `1:10`, minute-only values, `End`, and blank without moving the final mount.
- Confirm the provisional exposure in full daylight and darkness.
- Validate the implemented configurable maximum-composited capture bursts on the final mount and
  record the lowest burst count that reliably reconstructs all digit positions.
- At the time of this log, pose-drift handling was still pending. Optional static-anchor
  warnings are now implemented, but they do not automatically block all bad readings.

The reference service now uses bounded transition diagnostics so the next terminal-message test
will preserve the live `End` frame even after the panel goes blank.

That live snapshot showed valid `E` and `n` glyphs but a missed bottom segment on the final `d`:
the calibrated 205-pixel digit boxes extended below the physical glyph. Reducing their height to
175 pixels preserved the exact `4`, `3`, `2`, and `1` results across the existing 89-frame real
sequence and decoded the captured `End` overlay as `E`/`n`/`d` at approximately 0.85, 0.88, and
0.90 confidence. The subsequent live cycle confirmed the corrected geometry.

Full room images and local calibration files remain under ignored `debug/` paths. Any future
public fixtures must be tightly cropped to the display and stripped of metadata.
