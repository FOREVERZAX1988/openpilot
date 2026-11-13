# sunnypilot/flm — Firestar Lateral Method core math (StarPilot port)

Verbatim port of the StarPilot FLM (Firestar Lateral Method) **fit / acceptance /
coordinate core**, staged per `docs/starpilot-vs-sp-comparison.md` (P3-FLM: port the
layered learning core, never the 344-file live subsystem) and task B3-3. Everything
in this package is **inert offline math**: no process imports it yet, nothing here
reads Params, writes native parameters, or touches a torque/PID output.

## Ported (verbatim unless noted)

Two modules carry documented adaptations beyond the import-domain rewrite,
disclosed per verification-audit erratum (they are runtime-safe; only the
wording "verbatim" needed correcting):

| Module | Source | Role |
|---|---|---|
| `adaptive_profile.py` | `starpilot/flm/adaptive_profile.py` | **ADAPTED (7 lines)**: `FullSurfaceEnvelope` runtime import replaced with `from __future__ import annotations` + TYPE_CHECKING guard (full_surface_profile is restore/store wiring-batch scope; the annotation is never evaluated at runtime). Block/Sample provenance contract, train/heldout split, excitation + confound gates, ridge fit, cohort-wise T95 heldout acceptance, `ProfileOwner` slew-limited admission, `readmit_profile` |
| `event_bounded_ridge.py` | `starpilot/flm/event_bounded_ridge.py` | Deterministic box-constrained ridge solve (≤3⁴ face enumeration), not componentwise clamping |
| `canonical_surface_adapter.py` | `starpilot/flm/canonical_surface_adapter.py` | full30 coordinate catalog (NAMES/GROUPS/RAW_DOMAINS), coordinate bounds, manifest/anchor digests, `validate_trial`, `CanonicalSurfaceEffects` admission + envelope |
| `automatic.py` | `starpilot/flm/automatic.py` | **ADAPTED (4 lines)**: `FLMSample` imported from `evidence_types` (a byte-identical copy of the frozen dataclass) instead of gm_evidence, whose 1350-line live-collection body is wiring-batch scope. Linear `latAccelFactor` identification from bank-corrected physical windows, `admit_linear_factor` envelope (±30 % step, 0.7–1.3× vehicle factor) |
| `torque_surface.py` | carved from `starpilot/flm/torque_surface.py` | GM universal surface stage math (`GmSurface`, `_gm_get_flm_full_surface_*`), frozen `_gm_*` constants, `SurfaceInput` |
| `evidence_types.py` | `starpilot/flm/gm_evidence.py` | frozen `FLMSample` record contract only |

## Not ported on purpose (wiring batch, needs controls-safety adjudication)

- Ioniq 6 frozen reconstruction and `GmFlmBinding` (torque_surface carve boundary).
- `pid_stages`, `torque_stages`/`torque_adapter`, `physical_response` (controller
  execution stages), restore/store (`full_surface_store`, `full_surface_profile`),
  `event_evaluate` plumbing. The live-collection body stays unported —
  `shadow_producer.py` re-derives its own bounded 20 Hz collection instead
  (below), so `gm_evidence`/`event_collector`/`fullrate_collector` are not
  needed.
- ~~Any import of this package from `latcontrol_torque`, `torqued` or
  `SpeedBinLearner`.~~ Two adjudicated exceptions now exist, both conditional
  verdicts from controls-safety-engineer with default-off Params keys:
  **Seam B** (`runtime_overrides` consumed by `latcontrol_torque` through
  `ProfileOwner`), and **Seam A shadow** (`torqued` drives `shadow_producer`,
  verdicts published but never consumed by the learn path).

## Seam A shadow (`shadow_producer.py`)

Ported from StarPilot's `flm/learning_producer.py` — an unwired reconstruction
in that tree; this fork is the first to drive it from `torqued`'s main loop.
**Shadow only**: verdicts are telemetry on CustomReserved19's append fields
(`flmShadowStatus`/`flmShadowReason`/`flmShadowLatAccelFactor`/
`flmShadowTrainWindows`/`flmShadowHeldoutWindows`, capnp append-only, empty
when `FlmShadowEnabled` is off). Nothing in the learn path reads them.

Adaptations from the source (all disclosed, behaviour-preserving where the
source was live):

| Concern | Source | Here |
|---|---|---|
| identity / enable | `learning_source.identity_for` + `controller_selection.read_selection` (their unwired capability binding) | `{'carFingerprint', 'lateralTuning', 'basis'}` with `basis[0]` = the offline `latAccelFactor`; enabled by the `FlmShadowEnabled` param, re-checked at 1 Hz, hard split on change |
| `linear_conversion_verified` | capability-contract constant | `CP.lateralTuning.which() == 'torque'` — the car runs a linear torque controller by construction |
| vehicle envelope | separate measured `vehicle_factor` | degenerates to the baseline band: this fork has no independent measured factor, so `evaluate_linear_factor`'s 0.7–1.3× vehicle check folds into the ±30 % baseline step check |
| `cmd_torque` sample field | `cc.actuators.torque` | `cc.actuators.torque` — same name here; this fork's `Actuators.torque` IS the lateral command (`steer` does not exist in the fork schema; earlier note claiming `actuators.torque` was longitudinal was wrong and the `.steer` read it caused would have failed every update at runtime) |
| publication | their `autoSteeringLearning` message | CustomReserved19 append fields via `verdict()`; their message does not exist in this fork |
| clock | `time.CLOCK_BOOTTIME` direct | import-time `getattr` fallback (Linux device behaviour identical) |

Thresholds (`MIN_TOTAL_POINTS = 4000`, `TORQUE_BUCKETS`, `MIN_BUCKET_POINTS`)
carry over 1:1: both forks run torqued at `DT_MDL = 0.05` (20 Hz points) and
share `STEER_BUCKET_BOUNDS`/`MIN_BUCKET_POINTS`/`MIN_POINTS_TOTAL`. The
controls-safety-engineer Seam A verdict still requires a **device-side replay
calibration of the accumulation rate** before any non-shadow gating; until
then this stays telemetry regardless of the verdicts it produces. A
`qualified_fit` verdict is statistical model evidence, not a tracking
guarantee.

## Self-limitation

A qualified profile from this math is **statistical model evidence, not a
physical safety limit or a tracking guarantee** (same wording discipline as the
StarPilot upstream README). All 30 knob highs combined are not safe combination
admission; upstream's canonical envelope (`abs(delta) <= 0.25 * baseline + 1e-12`)
is what bounds any future composed stage.
