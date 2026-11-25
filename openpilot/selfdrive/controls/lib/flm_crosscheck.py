#!/usr/bin/env python3
"""FLM event-chain crosscheck (F4, low-risk wiring).

A second, advisory-only evaluation of the flm_workspace analysis evidence
through the ported sunnypilot.flm event chain. The upstream chain's fit path
(``adaptive_profile.evaluate_event_proposal`` -> ``event_bounded_ridge``) runs
a bounded TRAIN ridge solve with the upstream heldout-cohort gates; this
module feeds it blocks built from the workspace's own eligible samples so no
fabricated engine structures are involved:

- identity: the vehicle fingerprint identity digest (runtime_overrides).
- cohort:   the workspace speed band + turn direction label per sample.
- feature:  a single constant coordinate (1.0) — the fitted quantity is a
            constant lateral-accel tracking offset, i.e. the same direction a
            friction-threshold correction would move.
- residual target: desired - actual lateral acceleration per sample.

The verdict (qualified / collecting / rejected / unavailable + reason) is
purely informational: it goes into the report and the status JSON and gates
nothing. Any failure of the crosscheck must never fail the analysis itself —
the caller wraps it in try/except.
"""
from __future__ import annotations

import time
from typing import Any

from openpilot.sunnypilot.flm.adaptive_profile import (
  Block,
  Parameter,
  Sample,
  evaluate_event_proposal,
)
from openpilot.sunnypilot.flm.runtime_overrides import (
  FLM_BASELINE_REVISION,
  FLM_MAX_DELTA_FRACTION,
  FLM_DEFAULT_SLEW_PER_S,
  identity_for_fingerprint,
)

CROSSCHECK_STAGE_REVISION = "flm-crosscheck-v1"
CROSSCHECK_TRIAL_STEP = 0.005  # event_evaluate.TRIAL_STEP (sunnypilot/flm/event_evaluate.py:8)

# Provenance gates of adaptive_profile._evaluate: 8..24 blocks (:123), each
# 40..240 samples (:138), strictly increasing mono_ns across all blocks (:147),
# and every required cohort needs >= 2 train + >= 2 heldout blocks (:151).
MIN_BLOCKS = 8
MAX_BLOCKS = 24
MIN_BLOCK_SAMPLES = 40
MAX_BLOCK_SAMPLES = 240
MIN_BLOCKS_PER_COHORT = 4  # >= 2 land on each side of the chronological split


def crosscheck_samples(samples: list, car_fingerprint: str) -> dict[str, Any]:
  """Run the event-chain crosscheck over the analysis samples.

  ``samples`` is the flm_workspace FLMSample list. Returns a JSON-serializable
  summary; never raises on ordinary data conditions (returns a collecting /
  unavailable verdict instead).
  """
  # Lazy import: flm_workspace imports this module at the end of its analysis,
  # so the shared helpers must be resolved lazily to avoid a circular import.
  from openpilot.selfdrive.controls.lib.flm_workspace import _analysis_eligibility_mask, _speed_band_label

  eligible = _analysis_eligibility_mask(samples)
  identity = identity_for_fingerprint(car_fingerprint)

  blocks: list[Block] = []
  pending_cohort: str | None = None
  pending_rows: list[Sample] = []

  def flush() -> None:
    nonlocal pending_cohort, pending_rows
    if (pending_cohort is not None
        and MIN_BLOCK_SAMPLES <= len(pending_rows) <= MAX_BLOCK_SAMPLES):
      blocks.append(Block(
        identity=identity,
        block_id=f"crosscheck-{len(blocks):04d}",
        cohort=pending_cohort,
        stage_revision=CROSSCHECK_STAGE_REVISION,
        response_revision=FLM_BASELINE_REVISION,
        samples=tuple(pending_rows),
      ))
    pending_cohort = None
    pending_rows = []

  for sample, ok in zip(samples, eligible, strict=True):
    if not ok:
      flush()
      continue
    cohort = f"{_speed_band_label(float(sample.v_ego))}:{'left' if sample.desired_la >= 0.0 else 'right'}"
    if cohort != pending_cohort:
      flush()
      pending_cohort = cohort
    if len(pending_rows) >= MAX_BLOCK_SAMPLES:
      flush()
      pending_cohort = cohort
    mono_ns = int(float(sample.t) * 1e9)
    if mono_ns <= 0:
      flush()
      continue
    pending_rows.append(Sample(
      mono_ns=mono_ns,
      control_ns=mono_ns,
      applied_ns=mono_ns,
      features=(1.0,),
      residual_target=float(sample.desired_la - sample.actual_la),
      weight=1.0,
    ))
  flush()

  total_samples = sum(len(block.samples) for block in blocks)
  if len(blocks) < MIN_BLOCKS:
    return {"status": "collecting", "reason": "insufficient_blocks",
            "blocks": len(blocks), "samples": total_samples}

  # Keep only cohorts that can satisfy the 2-train + 2-heldout gate, then
  # re-check the block count.
  cohort_counts: dict[str, int] = {}
  for block in blocks:
    cohort_counts[block.cohort] = cohort_counts.get(block.cohort, 0) + 1
  required = {cohort for cohort, count in cohort_counts.items() if count >= MIN_BLOCKS_PER_COHORT}
  blocks = [block for block in blocks if block.cohort in required]
  if len(blocks) < MIN_BLOCKS:
    return {"status": "collecting", "reason": "insufficient_independent_cohorts",
            "blocks": len(blocks), "samples": total_samples, "cohorts": sorted(required)}

  parameters = (Parameter(
    name="friction.crosscheck.offset",
    stage_revision=CROSSCHECK_STAGE_REVISION,
    low=-FLM_MAX_DELTA_FRACTION,
    high=FLM_MAX_DELTA_FRACTION,
    max_step=FLM_MAX_DELTA_FRACTION,
    slew_per_s=FLM_DEFAULT_SLEW_PER_S,
  ),)

  result = evaluate_event_proposal(
    identity, parameters, tuple(blocks),
    trial_step=CROSSCHECK_TRIAL_STEP,
    now_ns=time.monotonic_ns(),
    required_cohorts=required,
    response_revision=FLM_BASELINE_REVISION,
  )

  summary: dict[str, Any] = {
    "status": result.status,
    "reason": result.reason,
    "blocks": len(blocks),
    "samples": total_samples,
    "cohorts": sorted(required),
  }
  if result.profile is not None:
    summary["coefficients"] = [float(c) for c in result.profile.coefficients]
    summary["cohortImprovements"] = [[cohort, float(value)] for cohort, value in result.profile.cohort_improvements]
    summary["baselineLoss"] = float(result.profile.baseline_loss)
    summary["candidateLoss"] = float(result.profile.candidate_loss)
  return summary
