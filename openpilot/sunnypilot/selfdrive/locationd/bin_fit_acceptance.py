#!/usr/bin/env python3
"""Heldout acceptance for the per-speed-bin torque fits.

StarPilot flm/automatic.py heldout discipline, adapted to the per-bin TLS
fit (speed_bin_learner): a candidate slope is only adopted when it
generalizes better than the seed on data it was not fit on - block-based
cross-fit improvements with a conservative T95 significance margin - not
merely when the bucket has enough points.

- two chronological folds; each fold's candidate is evaluated on the
  other fold (unseen data), against a seed baseline given the same
  offset freedom (seed offset fit on the candidate's training fold);
- accepted when mean(improvements) - T95[n-1] * SE > 0, i.e. the
  improvement's one-sided 95% lower bound is positive (StarPilot's
  automatic.py acceptance statistic);
- rejected fits are not adopted: the bin keeps its current value and the
  points stay, so more data can settle the estimate.

Pure logic; the TLS fit itself is injected so this stays importable and
unit-testable on a PC host.
"""
import numpy as np

# Conservative upper-rounded two-sided 95% Student-t quantiles for df1..23.
# Intervals assume independent, approximately normal block estimates; they are
# statistical model evidence, not physical safety limits or tracking guarantees.
# StarPilot flm/automatic.py verbatim.
T95 = (12.707, 4.303, 3.183, 2.777, 2.571, 2.447, 2.365, 2.307,
       2.263, 2.229, 2.202, 2.179, 2.161, 2.145, 2.132, 2.120,
       2.110, 2.102, 2.094, 2.087, 2.080, 2.074, 2.069)

MIN_IMPROVEMENT_ESTIMATES = 2
MIN_FOLD_POINTS = 8  # a fold smaller than this cannot support a t-test


def split_halves(points):
  """Chronological split: first half / second half of the point set."""
  n = len(points)
  mid = n // 2
  return points[:mid], points[mid:]


def fit_offset(points, slope):
  """Best constant offset for a fixed slope: mean(lat - slope*steer)."""
  points = np.asarray(points, dtype=float)
  return float(np.mean(points[:, 2] - slope * points[:, 0]))


def loss(points, slope, offset):
  """Mean squared residual of lat = slope*steer + offset."""
  points = np.asarray(points, dtype=float)
  residual = points[:, 2] - slope * points[:, 0] - offset
  return float(np.mean(residual ** 2))


def improvement_significant(improvements) -> bool:
  """StarPilot acceptance statistic: mean - T95[n-1] * SE > 0."""
  n = len(improvements)
  if n < MIN_IMPROVEMENT_ESTIMATES or n > len(T95):
    return False
  values = np.asarray(improvements, dtype=float)
  mean = float(np.mean(values))
  se = float(np.std(values, ddof=1) / np.sqrt(n))
  return mean - T95[n - 1] * se > 0.


def cross_validate_improvement(points, fit_fn, seed_slope):
  """Two-fold cross-fit acceptance for one bin's candidate fit.

  fit_fn(points) -> (slope, offset, ...) (SpeedBinLearner.fit_torque_points).
  Returns (accepted, improvements, reason): improvements are the per-fold
  heldout loss reductions vs the seed baseline; reason explains a rejection.
  """
  points = np.asarray(points, dtype=float)
  if len(points) < 2 * MIN_FOLD_POINTS:
    return False, [], 'not enough points'

  first, second = split_halves(points)
  try:
    # the TLS fit is injected (SpeedBinLearner.fit_torque_points); LinAlgError
    # and friends mean the fold is degenerate - not adoptable evidence
    fit_a = fit_fn(first)
    fit_b = fit_fn(second)
    slope_a, offset_a = fit_a[0], fit_a[1]
    slope_b, offset_b = fit_b[0], fit_b[1]
  except Exception:
    return False, [], 'singular fold fit'

  # seed baseline with the same offset freedom, fit on the candidate's fold
  seed_offset_a = fit_offset(first, seed_slope)
  seed_offset_b = fit_offset(second, seed_slope)

  improvements = [
    loss(second, seed_slope, seed_offset_a) - loss(second, slope_a, offset_a),
    loss(first, seed_slope, seed_offset_b) - loss(first, slope_b, offset_b),
  ]
  if not all(np.isfinite(improvements)):
    return False, improvements, 'non-finite improvement'

  if improvement_significant(improvements):
    return True, improvements, ''
  return False, improvements, 'heldout improvement not significant'
