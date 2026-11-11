# Prior art and related projects

This document records nearby open projects so Appliance Display Sensor can reuse established
ideas, avoid inflated novelty claims, and keep its narrower product goal clear. Links and project
status were reviewed on 2026-08-28.

## ESP32 Display Reader

[DocBig/ESP32-Display-Reader](https://github.com/DocBig/ESP32-Display-Reader) reads fixed
seven-segment and symbol regions on an ESP32 camera, publishes MQTT state, and creates Home
Assistant entities. Its browser interface demonstrates several especially useful setup ideas:

- live draggable and resizable numeric and symbol ROIs;
- individual digit gaps and editable segment profiles;
- symbol thresholds with hysteresis;
- camera and threshold diagnostics;
- multiple-frame voting;
- optional PWM or WS2812B illumination and an MQTT pre-capture trigger;
- configuration export/import, web installation, and OTA updates.

Its current recognition/state model is more generic than this project's countdown semantics. It
does not replace hour/minute parsing, configurable terminal text such as `End`, completion latching
after the display blanks, estimated finish, or explainable fusion with another appliance sensor.

The repository README labels the project MIT, but at the time of review the repository did not
contain a license-text file and GitHub did not identify a repository license. Concepts may be
studied and independently implemented with attribution; implementation code should not be copied
unless the licensing terms are made unambiguous.

## Home Assistant Seven Segments OCR

Home Assistant's legacy [Seven Segments OCR integration](https://www.home-assistant.io/integrations/seven_segments/)
uses `ssocr` on a crop from a Home Assistant camera entity. It proves that exposing a raw optical
number is useful, and `ssocr` should be a benchmark against the same real-image corpus.

It is not the reference architecture for this project because setup is manual, recognition runs
inside Home Assistant, and it does not provide a device-side calibration experience or appliance
lifecycle semantics.

## AI-on-the-edge-device

[AI-on-the-edge-device](https://github.com/jomjol/AI-on-the-edge-device) is a mature ESP32 camera
system for digitizing water, gas, and electricity meters. Meter reading is a different product
problem, but its guided alignment, illumination, administration, update, backup, and diagnostic
patterns are valuable references.

The project reinforces two roadmap choices: detect camera/alignment drift rather than silently
publishing bad values, and make reusable optical configuration separable from per-device network
identity.

## Positioning

Appliance Display Sensor should not claim to be the first camera-based seven-segment reader. Its
intended contribution is the combination of:

- a simple countdown-first setup;
- local and non-invasive sensing;
- raw optical output plus countdown/terminal semantics;
- reliable completion state after a short-lived terminal message disappears;
- useful Home Assistant entities such as remaining time and estimated finish;
- optional, explainable corroboration from status indicators or other sensors.

That positioning lets generic raw-value automations remain possible without making universal OCR
part of the initial product.
