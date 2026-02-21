# IQ.Pilot User Changelog

This changelog is written for everyday users and focuses on what changed in real-world use.

## February 9, 2026 - IQ.Pilot Launch
- IQ.Pilot v1.0a launched.
- Core IQ.Pilot + Konn3kt integration work was added.
- UI branding pass completed (fonts, styling, visuals).
- Firehose was removed from the UI.
- Sunnylink was removed.
- Early setup and reliability improvements landed (error handling, API/setup cleanup).

## February 10, 2026 - Device Support and Stability
- Better support for mici + tizi devices.
- Manual registration by QR was added.
- Volkswagen PQ support was enabled and expanded.
- Large bugfix pass improved stability, controls behavior, and general reliability.
- Cruise/button logic and control flow were further refined.

## February 11, 2026 - Major Vehicle Expansion
- Tesla vehicle control support was expanded.
- Honda MVL tuning (lateral + longitudinal) was added.
- Volkswagen support expanded across PQ and MLB with multiple fixes.
- Additional PQ bring-up improvements were added (including Passat NMS-focused work).
- More runtime bugfixes landed (including joystick and icon related fixes).

## February 12, 2026 - Sensor/Data Fixes
- Higher steering-angle offset tolerance was added (helps users with temporary steering sensor misalignment).
- Fuel level handling was fixed and improved.
- Additional Volkswagen PQ follow-up fixes were merged.

## February 13, 2026 - Driver Monitoring Rollback
- Driver Monitoring model changes were reverted to the previous behavior to reduce over-aggressive alerts.

## February 15-16, 2026 - Volkswagen PQ Maturity
- Heavy Volkswagen PQ control development and bugfixes.
- Improved engagement consistency and overall drive behavior.
- Better lateral/longitudinal interaction and cruise-control response tuning.

## February 17, 2026 - Volkswagen Stopping Behavior Tuning
- Volkswagen stopping/braking behavior received additional tuning updates.
- Continued comfort and stop-response refinements for better real-world behavior.

## Summary
- IQ.Pilot moved quickly from initial launch to broad stabilization.
- Biggest user-facing gains in this period were:
  - Better Tesla and Volkswagen support.
  - Added Honda MVL tuning support.
  - Fewer false/noisy fault behaviors.
  - Driver Monitoring behavior rollback.
  - Better onboarding/registration and UI polish.
