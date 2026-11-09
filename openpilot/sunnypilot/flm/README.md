# sunnypilot/flm — Firestar Lateral Method core math (StarPilot port)

Verbatim port of the StarPilot FLM (Firestar Lateral Method) **fit / acceptance /
coordinate core**, staged per `docs/starpilot-vs-sp-comparison.md` (P3-FLM: port the
layered learning core, never the 344-file live subsystem) and task B3-3. Everything
in this package is **inert offline math**: no process imports it yet, nothing here
reads Params, writes native parameters, or touches a torque/PID output.

## Ported (verbatim, import domain rewritten only)

| Module | Source | Role |
|---|---|---|
| `adaptive_profile.py` | `starpilot/flm/adaptive_profile.py` | Block/Sample provenance contract, train/heldout split, excitation + confound gates, ridge fit, cohort-wise T95 heldout acceptance, `ProfileOwner` slew-limited admission, `readmit_profile` |
| `event_bounded_ridge.py` | `starpilot/flm/event_bounded_ridge.py` | Deterministic box-constrained ridge solve (≤3⁴ face enumeration), not componentwise clamping |
| `canonical_surface_adapter.py` | `starpilot/flm/canonical_surface_adapter.py` | full30 coordinate catalog (NAMES/GROUPS/RAW_DOMAINS), coordinate bounds, manifest/anchor digests, `validate_trial`, `CanonicalSurfaceEffects` admission + envelope |
| `automatic.py` | `starpilot/flm/automatic.py` | linear `latAccelFactor` identification from bank-corrected physical windows, `admit_linear_factor` envelope (±30 % step, 0.7–1.3× vehicle factor) |
| `torque_surface.py` | carved from `starpilot/flm/torque_surface.py` | GM universal surface stage math (`GmSurface`, `_gm_get_flm_full_surface_*`), frozen `_gm_*` constants, `SurfaceInput` |
| `evidence_types.py` | `starpilot/flm/gm_evidence.py` | frozen `FLMSample` record contract only |

## Not ported on purpose (wiring batch, needs controls-safety adjudication)

- Ioniq 6 frozen reconstruction and `GmFlmBinding` (torque_surface carve boundary).
- `pid_stages`, `torque_stages`/`torque_adapter`, `physical_response` (controller
  execution stages), live collection (event_collector / fullrate_collector /
  gm_evidence body), restore/store (`full_surface_store`, `full_surface_profile`),
  `event_evaluate` plumbing.
- Any import of this package from `latcontrol_torque`, `torqued` or
  `SpeedBinLearner`. Wiring `ProfileOwner`/`evaluate` outputs into a control
  path changes actuator behaviour and is gated on a controls-safety-engineer
  decision plus a default-off Params key registered through `params-contract`.

## Self-limitation

A qualified profile from this math is **statistical model evidence, not a
physical safety limit or a tracking guarantee** (same wording discipline as the
StarPilot upstream README). All 30 knob highs combined are not safe combination
admission; upstream's canonical envelope (`abs(delta) <= 0.25 * baseline + 1e-12`)
is what bounds any future composed stage.
