# Architecture

Appliance Display Sensor deliberately separates optical decoding from appliance semantics and
home-automation naming.

## Data flow

1. **Input adapter** supplies a BGR or grayscale image. Single files, ordered directory replay,
   and live Picamera2 capture are implemented.
2. **Display calibration** crops the fixed display region.
3. **Preprocessor** selects a color channel and thresholds illuminated pixels.
4. **Decoder** samples calibrated segment regions and returns configured glyphs, blank positions,
   colon state, validity, and confidence.
5. **Semantic adapter** interprets `41` as 41 minutes, `1:10` as 70 minutes, or `End` as complete.
6. **Stabilizer** requires repeated observations before accepting a change and can latch a
   confirmed terminal state through a subsequent blank display.
7. **Change detector** marks only newly accepted status/countdown values for publication.
8. **Publisher** sends generic state and Home Assistant discovery messages over MQTT.

## Identity is configuration

The core does not branch on washer or dryer types. These two configurations use identical image
processing:

```yaml
device:
  identifier: laundry-washer
  name: Washer
  appliance_type: washer
```

```yaml
device:
  identifier: laundry-dryer
  name: Dryer
  appliance_type: dryer
```

The optional `appliance_type` may later help a native-appliance adapter or opinionated automation
choose appropriate vocabulary. In particular, a future Google cloud-to-cloud adapter could map
`washer` or `dryer` plus the generic remaining-time state to Google's read-only `RunCycle` trait.
A future Matter adapter could map the same state to the Operational State cluster without changing
the decoder. Neither adapter may determine which display decoder runs, and both must remain
optional publishers outside the local-first core.

## Decoder extension boundary

The current implementation is `SevenSegmentDecoder`. Future decoders should return the same kind
of structured observation rather than publishing MQTT themselves. Possible future implementations
include:

- segmented LCD variations;
- fourteen-segment alphanumeric displays;
- constrained OCR for a fixed graphical display;
- fixed icon/status-region readers.

Only implemented and tested decoders should be advertised as supported.

## Camera extension boundary

Image-file input keeps decoding reproducible without camera hardware. The Picamera2 adapter owns:

- autofocus during setup and fixed lens position during operation;
- locked exposure, analog gain, and white balance;
- multi-frame capture to handle multiplexed LEDs and rolling shutter;
- immediate display-region cropping;
- optional diagnostic-frame retention.

The camera adapter should not contain digit-recognition logic.

Camera Module 3 has no microphone. A separate microphone input could become an optional evidence
adapter, but completion tunes should not be treated as authoritative when multiple nearby
appliances may emit similar audio. Visual terminal glyphs and appliance-specific status regions
are the primary evidence for completion.

## State extension boundary

The initial state comes from the display alone. Later evidence sources can strengthen the state
without changing the decoder:

- exhaust temperature;
- vibration;
- power consumption;
- fixed status LEDs.

Fusion should preserve each observation and confidence value so users can understand why a state
was selected.
