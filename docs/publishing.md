# Publishing plan

Public repository: [jasonnovak/appliance-display-sensor](https://github.com/jasonnovak/appliance-display-sensor). Keep Pi code, HA blueprints,
bridge and model sources in one repository with the component layout in the README.
This candidate directory is the publication source; the development workspace is not.

## Before publication

1. Finish or explicitly document the pending checks in `physical-tests.md`.
2. Review the source/archives for private material and current dependency notices.
3. Use the repository above and choose an experimental release tag. The current
   prepared artifact is `preview-2026-11-11`, not a claim of stable v1 support.
4. Create the repository from this candidate only. Do not import the development
   workspace's history, private configs, debug images, research or credentials.
5. Verify repository URLs in install examples, HA blueprint import links and the
   MakerWorld description. Update them if the repository moves.
6. Run the software tests, rebuild artifacts and publish ZIPs and SHA256 checksums
   as a clearly labelled prerelease. Record what was actually tested.

## Rebuild artifacts

From the candidate repository root, run:

```sh
python tools/build_artifacts.py
```

The explicit `release-files.json` inventory controls inclusion. Unknown files are
never swept into a ZIP. Add new reviewed files to that inventory deliberately.
Outputs in `dist/` include the complete source release and a mount-only MakerWorld
bundle. Each includes a SHA256 manifest and has an external checksum.

## MakerWorld handoff

Use the mount ZIP's photos, supplied 3MF, README/print instructions and CERN license.
The five STLs match the model parts in the supplied final 3MF; corresponding STEP
files are included. Link back to GitHub for software and updates. Five owner-supplied
build photos are included.
The prepared text is in `hardware/mount/MAKERWORLD.md`.

An H2C project is included with saved settings and a magnet pause; no universal
printer profile or machine-ready G-code is included. Validate the profile for the
printer/material you choose to publish. Select CERN-OHL-P-2.0 if
the platform offers it; if it does not, review the platform's offered terms before
uploading rather than declaring an incompatible second license. The project does
not grant a no-commercial-use restriction.

## Home Assistant distribution

MQTT discovery and the four blueprint files are the initial HA distribution path.
The Google bridge's documented local-app installation is optional. A one-click HA
app repository and HACS listing are not part of this candidate. Google developer
account linking remains a manual step for each self-hosting household.
