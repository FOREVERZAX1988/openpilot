"""Tests for the heldout acceptance discipline (StarPilot flm/automatic.py
port) applied to the per-speed-bin torque fits."""
import unittest

import numpy as np

from openpilot.sunnypilot.selfdrive.locationd.bin_fit_acceptance import (
  MIN_FOLD_POINTS,
  cross_validate_improvement,
  fit_offset,
  improvement_significant,
  loss,
  split_halves,
)

RNG = np.random.default_rng(2026)


def make_points(n, true_slope, noise=0.05, steer_range=(0.05, 0.9)):
  steer = RNG.uniform(*steer_range, size=n)
  lat = true_slope * steer + RNG.normal(0., noise, size=n)
  return np.column_stack([steer, np.ones(n), lat])


def tls_fit(points):
  """The same [steer, 1, lat] total-least-squares as SpeedBinLearner.fit_torque_points,
  minus the torqued import."""
  _, _, v = np.linalg.svd(points, full_matrices=False)
  slope, offset = -v.T[0:2, 2] / v.T[2, 2]
  return slope, offset


class TestPrimitives(unittest.TestCase):
  def test_split_halves_chronological(self):
    points = np.arange(24).reshape(12, 2)
    first, second = split_halves(points)
    np.testing.assert_array_equal(first, points[:6])
    np.testing.assert_array_equal(second, points[6:])

  def test_fit_offset_recovers_true_offset(self):
    points = make_points(500, 1.8, noise=0.0)
    points[:, 2] += 0.3
    self.assertAlmostEqual(fit_offset(points, 1.8), 0.3, places=6)

  def test_loss_zero_for_exact_model(self):
    points = make_points(100, 1.8, noise=0.0)
    self.assertAlmostEqual(loss(points, 1.8, 0.), 0., places=9)

  def test_improvement_significant_table(self):
    # n=2 needs the T95[1] margin: a large consistent improvement passes
    self.assertTrue(improvement_significant([1.0, 1.2]))
    # mean above zero but the margin swallows it (0.06 - 4.303*0.057 < 0)
    self.assertFalse(improvement_significant([0.1, 0.02]))
    # too few estimates
    self.assertFalse(improvement_significant([1.0]))
    # contradictory estimates
    self.assertFalse(improvement_significant([1.0, -1.0]))


class TestCrossValidation(unittest.TestCase):
  def test_wrong_seed_accepts_good_candidate(self):
    """Data from a 1.8 model, seed says 1.0: the candidate generalizes much
    better than the seed on unseen folds -> accepted."""
    points = make_points(400, 1.8, noise=0.05)
    accepted, improvements, reason = cross_validate_improvement(points, tls_fit, seed_slope=1.0)
    self.assertTrue(accepted, reason)
    self.assertTrue(all(imp > 0 for imp in improvements))

  def test_correct_seed_rejects_churn(self):
    """Data from the seed itself: no real improvement -> rejected, the bin
    keeps its seed instead of chasing noise."""
    points = make_points(400, 1.0, noise=0.05)
    accepted, _, reason = cross_validate_improvement(points, tls_fit, seed_slope=1.0)
    self.assertFalse(accepted)
    self.assertEqual(reason, 'heldout improvement not significant')

  def test_not_enough_points_rejects(self):
    points = make_points(2 * MIN_FOLD_POINTS - 1, 1.8)
    accepted, _, reason = cross_validate_improvement(points, tls_fit, seed_slope=1.0)
    self.assertFalse(accepted)
    self.assertEqual(reason, 'not enough points')

  def test_nan_points_reject(self):
    """NaN contamination poisons the fits -> non-finite improvement -> rejected."""
    points = make_points(400, 1.8, noise=0.05)
    points[10, 2] = np.nan
    accepted, _, reason = cross_validate_improvement(points, tls_fit, seed_slope=1.0)
    self.assertFalse(accepted)
    self.assertIn(reason, ('non-finite improvement', 'singular fold fit'))


if __name__ == '__main__':
  unittest.main()
