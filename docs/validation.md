# Candidate preparation validation — 2026-11-11

- Pi source suite: 198 tests run successfully, two Linux-only checks skipped on
  Windows (health-recorder installer and editable-environment/update-lock integration).
- Bridge suite: 79 tests passed, including OAuth, state handling, setup generation
  and license/credential exclusion from public packages.
- New generic Picamera2 example parsed with the application's configuration loader;
  MQTT starts disabled. It still needs a fresh physical camera installation check.
- All local Markdown links in the candidate resolve.
- Current five STLs and STEP files are copied byte-for-byte from the selected
  design exports. This preparation does not regenerate or change geometry.
- Public packaging uses a reviewed inventory; model bundles exclude unselected 3MFs,
  machine-ready G-code, obsolete bases and private CAD audit logs. The owner-supplied
  final 3MF is included with its H2C settings documented. Each model mesh matches
  its named final STL after restoring source offsets: bijective vertices within
  0.0001 mm and identical triangle connectivity/winding. The greatest measured
  vertex difference is about 0.0000011 mm. Nonprinting support blockers are excluded
  from that part comparison and retained unchanged in the project.
- Five supplied build photos, one installed photo and three setup-page screenshots
  are included with metadata removed without pixel changes.
- Release text and model metadata were checked for known personal paths, endpoint names and
  private-key markers. A synthetic private-IP redaction fixture in the test suite
  is intentional. This is a bounded release review, not a general security audit.

The software checks used existing Windows Python 3.14 dependencies. They are not
evidence of a fresh Pi OS/HA OS installation or Linux installer checks. The owner
reports physical testing complete on the reference installation; independent install
and recovery validation remain in [physical-tests.md](physical-tests.md).
