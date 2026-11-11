# Contributing

Appliance Display Sensor is pre-alpha. Small changes with tests and clear calibration evidence are
preferred while the first physical installation is being validated.

## Development

```console
python -m pip install -e .[dev]
python -m unittest discover -s tests -v
ruff check .
```

## Design rules

- Do not hard-code washer, dryer, or manufacturer behavior into a decoder.
- Keep camera acquisition, visual decoding, semantics, and publishing separate.
- Prefer deterministic fixed-layout processing before introducing general AI/OCR dependencies.
- Preserve uncertainty; do not silently turn an invalid visual observation into a valid timer.
- Add synthetic tests for new digit layouts and transitions.

## Image privacy

Do not submit uncropped room photographs, EXIF location data, faces, reflections of people, network
credentials, or appliance serial numbers. Crop fixtures to the display, remove metadata, and confirm
that you have permission to publish them.

## Profiles

A generic profile should describe visual properties such as digit count, colon position, color, and
sampling coordinates. A manufacturer/model preset may be contributed as a convenience layer, but
it must use the generic decoder and should include the exact supported model identifier.

