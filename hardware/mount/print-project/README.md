# Supplied Bambu Studio print project

`appliance-display-mount.3mf` is the project supplied by the owner for inclusion
with the build photos. It is preserved byte-for-byte; no geometry, printer settings,
support choices or pause commands have been changed during release preparation.

## Saved settings inspected

- Bambu Lab H2C, 0.4 mm nozzle; 0.20 mm Standard profile.
- Three plates; 0.20 mm first and subsequent layer heights.
- Four walls and 20% infill in the project-level settings.
- PETG and PLA profiles are present. Model parts select extruder 1 (PETG); saved
  support/interface selectors are 0 (default), not an explicit dedicated PLA interface.
- Project-level support is automatic tree/default; the arm overrides this with
  normal automatic/snug supports.
- Six support blockers are attached to the base's magnet pockets.
- Plate 1 has a pause command at approximately Z=3.8 mm (`M400 U1`). Check it in
  your actual sliced preview before inserting magnets.

These are saved configuration values, not proof of a successful print on every
printer or material. Select your actual profiles and re-slice. No machine-ready
plate G-code is embedded; the file includes the custom pause instruction.

## Final mesh verification

All five model meshes in this 3MF match their named final STLs in the release:

- `01-base-recessed-head.stl`
- `02-pi-lid.stl`
- `03-camera-cover-thicker-front.stl`
- `04-curved-cover-closed-end.stl`
- `05-main-arm-overlap-nose.stl`

The check restored each Bambu source offset and required a one-to-one vertex match
within 0.0001 mm, plus identical triangle connectivity and winding. The largest
measured vertex difference was approximately 0.0000011 mm. Nonprinting support
blockers are separate from model geometry and remain in the unchanged project.
See [mesh-verification.json](../mesh-verification.json) for per-part results and hashes.

The earlier release draft mistakenly selected older arm and cover exports. This
release corrects that selection; the supplied final 3MF was not at fault. Its
corresponding STEP exports replace the older combined FreeCAD assembly.

Original project design content is CERN-OHL-P-2.0; third-party printer/material
profiles keep their own terms, as described in the parent licensing notice.
