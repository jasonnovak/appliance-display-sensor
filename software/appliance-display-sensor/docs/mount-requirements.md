# Mount design handoff

This document transfers the physical-mount work into a dedicated task while keeping it connected
to the Appliance Display Sensor repository. The mount task owns CAD, printability, mechanical fit,
and assembly documentation. The software task owns image capture, decoding, calibration, MQTT, and
Home Assistant behavior.

## Objective

Design two closely related mounts for a Raspberry Pi Camera Module 3 Standard:

1. A reliable custom fit for the reference dryer.
2. A more general, adjustable version suitable for washers, dryers, and other appliances with a
   display below or in front of a flat metal top.

The custom version should establish the simplest geometry that works. The generalized version
should be derived from physical test results rather than designed entirely in the abstract.

## Reference hardware

- Raspberry Pi Zero 2 W, positioned separately on the appliance top.
- Raspberry Pi Camera Module 3 Standard, visible-light variant.
- Camera board dimensions: approximately 25 x 24 x 11.5 mm.
- Camera focus range: approximately 100 mm to infinity.
- Planned camera cable: 300 mm Standard-to-Mini cable for the Pi Zero 2 W.
- Removable magnetic attachment to the appliance's metal top.

Official camera specifications and mechanical drawings are available from the
[Raspberry Pi Camera Module 3 product page](https://www.raspberrypi.com/products/camera-module-3/).

The physical camera should be measured when it arrives before finalizing retention tabs, lens
clearance, cable routing, or tolerances.

## Reference-appliance measurements

These are user-confirmed measurements, not estimates taken from photo perspective:

| Measurement | Value | Notes |
| --- | ---: | --- |
| Display window width | approximately 40 mm | Black visible display window |
| Display window height | approximately 15 mm | Black visible display window |
| Appliance top to top of display | approximately 40 mm | Vertical measurement |
| Appliance top to display center | approximately 47.5 mm | Derived from 40 mm + half the display height |
| Plastic bezel depth above display | approximately 50 mm | Top view, from metal boundary toward the front at the display location |

The plastic front bezel is rounded. It protrudes farther toward the middle than at its upper edge,
so the 50 mm value describes the location above the display and should not be treated as a uniform
rectangular extrusion.

The control-panel trim and bezel are plastic. The horizontal appliance top is metal and is the
preferred non-destructive attachment surface.

## Existing private photo references

The following photographs were supplied during feasibility discussion:

- `20260827_225746.jpg`: full control panel in room light with `41` illuminated.
- `20260827_225814.jpg`: full control panel in darkness with `41` illuminated.
- `20260827_230530.jpg`: top view showing approximately 50 mm of rounded plastic bezel between the
  metal top boundary and the front at the display location.
- `20260827_230550.jpg`: top of appliance to top of display, approximately 40 mm.
- `20260827_230612.jpg`: display width, approximately 40 mm.
- `20260827_230643.jpg`: display height, approximately 15 mm.
- `20260828_084637.jpg`: high oblique overview of the metal top, rounded front bezel, control
  panel, and adjacent appliance.
- `20260828_084645.jpg`: overhead/front overview showing the broad flat mounting surface.
- `20260828_084656.jpg`: full front and laundry-area context showing the dryer's placement and
  close adjacent washer.
- `20260828_083459.jpg`: close display reference showing the hour/minute form `1:10`.
- `20260828_085528.jpg`, `20260828_085532.jpg`, and `20260828_085541.jpg`: progressively closer
  references showing the seven-segment terminal text `End`.

These photos should be used as private design references. Do not copy full laundry-room
photographs into the public repository. If a public image becomes useful, crop it to the appliance
and remove image metadata and identifying reflections first.

## Optical placement envelope

Use an initial lens-to-display distance of approximately 100 to 150 mm. The exact position should
be selected using a temporary physical mock-up after the camera arrives.

The 50 mm bezel dimension affects the arm's reach from the metal mounting surface; it does not alter
the camera's optical working distance from the display. Keep these dimensions separate:

- **Optical working distance:** lens to display.
- **Cantilever reach:** magnetic attachment area to lens.

The camera should:

- see the complete 40 x 15 mm display with calibration margin;
- remain above or beside the display instead of covering it;
- avoid blocking buttons and normal appliance operation;
- aim close enough to perpendicular that reflections and perspective remain manageable;
- permit software perspective correction rather than requiring perfect mechanical alignment;
- retain its position during dryer vibration.

The adjacent appliance is close on the reference dryer's right side. A top-center or top-left base
is more promising than a right-side attachment.

## Custom mount requirements

The first printable mount should favor quick validation and easy dimensional changes:

- Magnetic base on the metal top with a rubber or non-marring contact layer.
- Short, stiff structure wherever the required camera position permits.
- Adjustable camera pitch during testing.
- Camera board retained without loading the lens assembly.
- Unobstructed autofocus mechanism and lens field of view.
- Ribbon-cable exit with a generous bend radius and strain relief.
- Pi Zero 2 W remains in a separate ventilated enclosure farther back on the top.
- No adhesive on the plastic control panel for the primary design.
- No drilling or appliance disassembly.

The custom design may use fixed appliance dimensions after the first optical-position test. It does
not need to solve universal adjustment immediately.

## General adjustable mount requirements

After the custom fit is validated, expose the important geometry as explicit CAD parameters:

- Base depth and width.
- Magnet count, diameter, thickness, and spacing.
- Reach from metal/plastic boundary to camera.
- Camera vertical drop.
- Camera pitch angle.
- Optional small yaw adjustment for off-center placement.
- Camera-board retention clearance.
- Cable exit direction and strain-relief location.

Prefer constrained adjustments that cannot slip under vibration. Captive screws, indexed teeth,
interlocking angle positions, or firmly clamped joints are more appropriate than a long flexible
gooseneck.

The generalized design should accommodate different appliance names and display layouts without
assuming washer or dryer in part names. Suggested neutral part names include `base`, `reach_arm`,
`angle_joint`, and `camera_cradle`.

## Mechanical and safety constraints

- Mount removal should not scratch or permanently mark the appliance.
- Magnets must not be able to slide off the rounded front edge.
- The camera and cable must remain clear of doors, lids, detergent drawers, controls, and vents.
- Avoid sharp cable bends and unsupported cable motion at either connector.
- Keep the Pi's Wi-Fi antenna region away from direct contact with sheet metal when practical.
- Do not enclose the Pi without ventilation.
- Select print material after checking actual appliance-top temperature. PETG is a reasonable
  starting candidate; do not assume PLA is adequate until temperatures are measured.
- Treat magnets as retention hardware requiring a documented load margin, not decorative feet.
- The design must not require access to mains wiring or the appliance interior.

## Recommended development sequence

1. Attach the additional wider-angle reference photos to the mount task.
2. Measure the received camera board and confirm cable orientation.
3. Make a cardboard, foam-board, or simple temporary arm that places the lens 100-150 mm from the
   display.
4. Capture the display in daylight and darkness while the dryer is stationary and running.
5. Select the shortest optical position that focuses reliably and leaves the display visible.
6. Record lens position relative to the metal/plastic boundary and appliance top.
7. Model and print the reference-appliance mount.
8. Test vibration, cable strain, magnet grip, removal, and repeatable repositioning.
9. Convert the validated dimensions into adjustable CAD parameters.
10. Publish CAD source, export files, BOM, assembly instructions, and a dimension worksheet.

## Expected deliverables

- Editable parametric CAD source.
- Reference-appliance configuration or dimension set.
- General adjustable configuration.
- Printable STL or 3MF exports.
- Magnet and fastener bill of materials.
- Camera installation and ribbon-cable routing instructions.
- Dimensioned assembly drawing.
- Printing orientation, support, tolerance, and material guidance.
- Physical test checklist and recorded results.
- Photos of the mount that do not expose private room details.

Store mount artifacts under:

```text
hardware/mount/
├── README.md
├── cad/
├── exports/
├── drawings/
└── test-results/
```

## Questions for the mount task

Resolve these with the user or physical testing rather than guessing:

- Which CAD system and editable source format should be used?
- What printer, nozzle, build volume, and materials are available?
- What flat metal area is available behind the rounded bezel for the base?
- How much front protrusion is acceptable during normal use?
- Should the Pi enclosure remain entirely separate or share the magnetic base?
- Which rubber-coated magnets or embedded magnet sizes are readily obtainable?
- Is tool-free adjustment important after calibration, or can adjustments use screws?
- Does the camera cradle need quick removal independent of the base?

## Ready-to-use task prompt

> Work on the physical camera mount for Appliance Display Sensor as a separate mechanical-design
> outcome in the same repository. Read `docs/mount-requirements.md` first and treat it as the source
> of truth. Start with a custom magnetic mount for the reference dryer, but structure the CAD so a
> general adjustable washer/dryer/appliance version can follow after physical testing. Keep work
> under `hardware/mount/`; do not change the decoder or MQTT software unless a documented mechanical
> interface requires coordination. Review the additional attached wider-angle appliance photos,
> identify any missing measurements, and propose the first mock-up geometry before final CAD.
