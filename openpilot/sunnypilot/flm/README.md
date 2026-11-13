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
| `torque_surface.py` | carved from `starpilot/flm/torque_surface.py` | GM universal surface stage math (`GmSurface`, `_gm_get_flm_full_surface_*`), frozen `_gm_*` constants, `SurfaceInput`. **2026-11-13 wiring batch 1**: `GmFlmBinding` appended (the document round trip between `torque_settings` and the saved FLM state; `Ioniq 6` reconstruction still excluded — its `_DEFAULTS` bind `lateral/ioniq6_policy`, deferred with that chain) |
| `evidence_types.py` | `starpilot/flm/gm_evidence.py` | frozen `FLMSample` record contract only |

### Wiring batch 2/3 (2026-11-13) — lifecycle / restore-store / observation chain

22 more modules, same discipline (verbatim + import rewrite; imports
verified locally and on device; flm suite 87/87 OK on both):

| Group | Modules |
|---|---|
| lifecycle/persistence | `learned_lifecycle`, `persistence_module`, `calibration_lifecycle`, `event_storage`, `sunnypilot/saved_document.py` (POSIX fcntl commit) |
| restore/store | `restore_support`, `restore_activation`, `event_windows`, `event_episodes`, `event_physical`, `normalized_trace_archive` |
| observation/plant | `torque_observation`, `physical_observation`, `physical_input_observation`, `plant_lag`, `producer_clock_equivalence`, `evidence_noise`, `evidence_phases`, `clipping_quality`, `native_primitives` |
| torque/feedback chain | `torque_eligibility`, `torque_emission_replay` (+ opendbc `car/steering_projection.py`, verbatim), `event_mean_evidence`, `candidate_feedback`, `feedback_replay`, `event_activation` |

Shared contracts: `runtime_identity` += `SourceState`; `replay_constants`
holds MAX_FRAME_GAP_NS/MAX_REPLAY_FRAMES extracted from the 1,724-line
`controller_replay` (still unported).

**Deliberately excluded** (bound to StarPilot's daemon restore-replay
architecture — sp validates restore via `ProfileOwner.replay_validation`
instead): `event_raw_fit`, `event_restore_fit`, `torque_raw_fit`,
`source_plant_fit`, and the collectors `gm_evidence`/`fullrate_collector`/
`event_collection`. Dormant lazy imports into unported modules (e.g.
`controller_replay.SelectedControllerFactory` in `feedback_replay`) raise
a clear ModuleNotFoundError if ever reached; nothing in sp reaches them.

### Wiring batch 1 (2026-11-13) — deferred-scope modules now ported, still default-off

Import-domain rewrite only (`openpilot.starpilot.*` → `openpilot.sunnypilot.*`);
verified locally 87/87 (`flm/tests` incl. `test_physical_response` port and
`test_wiring_batch_smoke`); device-side 87/87 OK (0 skip) on HEAD 2c0d6b4ea8.

| Module | Source | Role |
|---|---|---|
| `selected_effects.py` | verbatim | effect selection over `adaptive_profile` + `canonical_surface_adapter`; `_selected_source` keeps dormant lazy imports (`manual_coordinates` ported; `offroad_runtime` not ported — the branch never fires until route effects exist) |
| `torque_stages.py` / `pid_stages.py` | verbatim | per-frame controller stage math (execution wiring later, controls-safety gated) |
| `torque_adapter.py` | verbatim | Parameter/ProfileOwner adapter glue |
| `physical_response.py` | verbatim | plant lag fit with train/heldout block split (7/7 tests green, values match upstream) |
| `full_surface_profile.py` / `full_surface_store.py` | verbatim | restore/store of full surfaces (`remember_full`/`load_prior`/`rollback_full`) |
| `event_evaluate.py` | verbatim + 1 line | `POLICY` inlined (constant only; the 1,063-line `event_controller_replay` deliberately stays unported) |
| `manual_coordinates.py` / `manual_trial.py` | verbatim | manual coordinate validation/serialize; `manual_coordinates.load` reads through `torque_settings` |
| `runtime_identity.py` | extracted from `runtime_adapter_registry.py` | `digest`/`car_params_digest`/`physical_model_revision` only — the 1,064-line registry is not ported |
| `saved_source.py` (package root) | verbatim | bounded, symlink-safe param reads (`O_NONBLOCK`/`O_NOFOLLOW` — POSIX-only, device-verified) |
| `sunnypilot/lateral/` (new) | `starpilot/lateral/` | config/contract layer only: `controller_selection`, `learning_preferences`, `torque_supported`, `torque_tuning`, `torque_shaping`, `bolt_shaping`, `torque_settings`, `gm_geometry_runtime`. Nothing here actuates a car; `torque_runtime`, `bolt_policy`, `ioniq6_policy` (the actuation-adjacent chain) stay unported |

## Not ported on purpose (wiring batch, needs controls-safety adjudication)

- Ioniq 6 frozen reconstruction (`Ioniq6Surface` + `lateral/ioniq6_policy`,
  which binds 26 frozen constants + shaping helpers), `torque_runtime`,
  `bolt_policy`, and the whole live-collection body (`gm_evidence`,
  `event_collector`, `fullrate_collector`, `offroad_*` daemon,
  `live_tracking_*` multiprocess subsystem, `runtime_adapter_registry` /
  `global_runtime` orchestration, replay suites). `shadow_producer.py`
  re-derives its own bounded 20 Hz collection instead.
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
