# Custom segment sampling

Most displays should keep automatic sampling. Align each digit box first, then use thickness
and slant if needed. Custom sampling is an advanced option for a display whose physical strokes
do not fit those generated sample regions. It does not track a bumped camera or repair focus,
exposure, missing pixels, different digit shapes, or incorrect countdown interpretation.

## Use the editor

1. Open **Advanced recognition settings → Custom segment sampling · advanced**.
2. Select a preview digit with enough illuminated segments to inspect. The enlarged image uses
   the current form's digit crop. Yellow marks the selected sample, blue the others; these colours
   show geometry, not recognition confidence. The main detection result still uses applied settings.
3. **Customize this layout** copies the automatic samples of the selected digit into the form.
   That normalized layout is shared by every digit, including blank positions and terminal letters.
4. Select a segment: a top, b upper right, c lower right, d bottom, e lower left, f upper left,
   g middle. Move its rectangle or drag the lower-right handle to resize. Percentage fields provide
   the same adjustment without dragging. Samples should lie inside a stroke and avoid neighbours.
5. Inspect every digit position, then **Test changes**. Check the cropped detection overlay and
   individual segment readings. Testing pauses HA publication until saved, discarded, or expired.
6. Save only after checking varied digits, hour/minute displays and terminal text under both light
   and dark conditions. **Use automatic sampling** restores thickness/slant in the form; it also
   needs Test/Save to take effect. Discard returns to the saved configuration.

Do not make a sample tiny merely to obtain high confidence on one frame. Tiny or overlapping
samples can produce confident wrong readings. Rectangles must stay inside the digit and cover at
least one pixel in every digit box; these checks ensure valid geometry, not reliable recognition.
Different widths/heights rescale the shared layout. Per-position custom shapes are not supported.

The camera preview refreshes periodically, not as a continuous video. Disconnection warnings apply
to this preview too. The editor does not automatically tune, apply, save, notify, or move boxes.

## Reuse and configuration

**Export saved profile** includes custom sampling, without network credentials or device identity.
Custom layouts export as optical profile version 2. Automatic layouts continue to export as
version 1. Import accepts both: version 1 explicitly restores automatic sampling rather than
keeping an old custom layout. Old software rejects version 2 instead of silently ignoring it.
Imports require matching image resolution/rotation and enter test mode, not an immediate save.
Profiles are starting points; moving a camera or using another display still needs calibration.

The optional YAML field is `display.segment_sample_boxes`, a mapping with exactly the keys a–g.
Each value is `[left, top, width, height]` normalized to 0–1 relative to each complete digit box.
Missing or `null` means automatic. Custom rectangles override sample thickness and slant only;
pixel cutoff, lit-area requirement, glyph confidence, colon handling and countdown semantics remain
unchanged. Saved thickness/slant are retained for switching back to automatic mode.

Validation: decoder/overlay parity, malformed geometry, subpixel rejection across all positions,
legacy profile reset, versioned export/import and form controls have automated coverage. The
browser workflow is checked with synthetic digits; varied real-display custom layouts remain a
manual installation check. There is no need to change a working dryer calibration to try this upgrade.
