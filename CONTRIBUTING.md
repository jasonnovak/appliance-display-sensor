# Contributing

This is an experimental fixed-display sensor. Keep camera capture, recognition,
countdown interpretation and MQTT separate. Do not infer completion from elapsed
time or reject legitimate adaptive time changes. New display support needs real,
privacy-cropped examples as well as tests.

## Software checks

In `software/appliance-display-sensor`, use the Pi bootstrap environment or a
Python 3.11+ environment with the project's development dependencies, then run:

```sh
python -m unittest discover -s tests -v
```

In `software/google-runcycle-bridge`, use a separate environment:

```sh
python -m pip install -r requirements.txt pytest
python -m pytest -q
```

Camera-independent tests do not prove optical reliability, HA installation or Google
account linking. Record those separately in the physical/release checklists.

## Contributions and private data

Software contributions use Apache-2.0. Original mount/case design contributions
use CERN-OHL-P-2.0. Preserve third-party licenses and identify imported content.
Do not submit credentials, local calibration containing identity/network details,
uncropped room images, faces, reflections, serial numbers or image-location metadata.
Use the setup page's display-only diagnostic export and inspect it before sharing.

For CAD changes, record revision, actual printer/material, fit checks and whether
the change affects cable clearance, magnet pause, camera pose or screw recess.
Keep the five-part set and print instructions consistent. Do not substitute an old
base or embed unverified personal printer settings in the general release.
