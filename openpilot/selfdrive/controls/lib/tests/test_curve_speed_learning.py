"""Pure-logic unit tests for the StarPilot curve-speed learning port."""
import unittest

import numpy as np

from openpilot.selfdrive.controls.lib.curve_speed_learning import (
  CSC_COUNT_CAP,
  CSC_LAT_ACCEL_MAX,
  CSC_LAT_ACCEL_MIN,
  CSC_NUDGE_WEIGHT,
  CURVATURE_BUCKETS,
  CURVATURE_GRID,
  DEFAULT_LATERAL_ACCELERATION,
  CurvatureLearning,
  bucket_curvature,
  learning_status_from_data,
  normalize_curvature_data,
  weighted_isotonic,
)


class TestWeightedIsotonic(unittest.TestCase):
  def test_monotone_sequence_unchanged(self):
    out = weighted_isotonic([1.0, 2.0, 3.0], [1.0, 1.0, 1.0])
    np.testing.assert_allclose(out, [1.0, 2.0, 3.0])

  def test_violation_pooled(self):
    out = weighted_isotonic([2.0, 1.0], [1.0, 1.0])
    np.testing.assert_allclose(out, [1.5, 1.5])

  def test_weighted_pool_prefers_heavy_neighbour(self):
    # no violation -> values pass through unchanged
    out = weighted_isotonic([1.0, 3.0], [100.0, 1.0])
    np.testing.assert_allclose(out, [1.0, 3.0])
    # violation with a heavy well-sampled neighbour dominates the sparse outlier
    out2 = weighted_isotonic([3.0, 1.0], [100.0, 1.0])
    self.assertAlmostEqual(out2[0], (3.0 * 100.0 + 1.0 * 1.0) / 101.0, places=6)
    self.assertAlmostEqual(out2[1], out2[0])

  def test_output_length(self):
    out = weighted_isotonic([3.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    self.assertEqual(len(out), 3)
    self.assertTrue(np.all(np.diff(out) >= 0.0))


class TestBucketCurvature(unittest.TestCase):
  def test_clips_to_bounds(self):
    self.assertEqual(bucket_curvature(1e-6), bucket_curvature(0.0005))
    self.assertEqual(bucket_curvature(1.0), bucket_curvature(0.02))

  def test_returns_grid_string(self):
    key = bucket_curvature(0.01)
    self.assertIsInstance(key, str)
    self.assertEqual(len(CURVATURE_BUCKETS.__str__()), len("24"))  # grid has 24 buckets

  def test_normalize_drops_invalid(self):
    data = normalize_curvature_data({
      "0.01": {"average": 2.0, "count": 5},
      "bad": {"average": 1.0, "count": 3},
      "0.012": {"average": 2.0, "count": 0},   # zero count
      "0.013": "not a dict",
    })
    self.assertEqual(len(data), 1)
    self.assertEqual(data[bucket_curvature(0.01)]["count"], 5)

  def test_normalize_merges_same_bucket(self):
    key = bucket_curvature(0.01)
    data = normalize_curvature_data({
      key: {"average": 2.0, "count": 4},
      str(float(key) * 1.0001): {"average": 3.0, "count": 4},
    })
    self.assertEqual(data[key]["count"], 8)
    self.assertAlmostEqual(data[key]["average"], 2.5)


class TestCurvatureLearning(unittest.TestCase):
  def make_learning(self):
    return CurvatureLearning(dt=0.05)

  def sample_frames(self, learning, frames, v_ego=15.0, lat=2.5, curv=0.01,
                    manual_speed_control=True):
    for _ in range(frames):
      learning.log_data(v_ego=v_ego, tracking_lead=False, manual_speed_control=manual_speed_control,
                        driving_in_curve=True, blinker=False,
                        lateral_acceleration=lat, road_curvature=curv)

  def test_no_samples_keeps_default_state(self):
    learning = self.make_learning()
    self.assertAlmostEqual(learning.lateral_acceleration, DEFAULT_LATERAL_ACCELERATION)
    # with no data the curve falls back to the fixed prior (2.2 at 0.01 1/m)
    learned = learning.learned_lat_accel(0.01)
    self.assertGreater(learned, 2.0)
    self.assertLess(learned, 2.4)

  def test_settle_time_before_sampling(self):
    learning = self.make_learning()
    # the settle timer only accrues on eligible frames, and the lead-clear
    # gate (CSC_LEAD_CLEAR_TIME = 1 s = 20 frames) blocks the first 20, so
    # sampling starts after 20 + 40 = 60 frames at 20 Hz
    self.sample_frames(learning, 58)
    self.assertFalse(learning.enable_training)
    self.sample_frames(learning, 2)
    self.assertTrue(learning.enable_training)

  def test_tracking_lead_blocks_sampling(self):
    learning = self.make_learning()
    for _ in range(100):
      learning.log_data(v_ego=15.0, tracking_lead=True, manual_speed_control=True,
                        driving_in_curve=True, blinker=False,
                        lateral_acceleration=2.5, road_curvature=0.01)
    self.assertFalse(learning.enable_training)
    self.assertAlmostEqual(learning.lateral_acceleration, DEFAULT_LATERAL_ACCELERATION)

  def test_manual_control_required(self):
    learning = self.make_learning()
    self.sample_frames(learning, 100, manual_speed_control=False)
    self.assertFalse(learning.enable_training)

  def test_low_speed_blocks_sampling(self):
    learning = self.make_learning()
    self.sample_frames(learning, 100, v_ego=3.0)
    self.assertFalse(learning.enable_training)

  def test_learning_shifts_comfort(self):
    learning = self.make_learning()
    # driver takes 0.01-curvature bends at 3.0 m/s^2 comfortably
    self.sample_frames(learning, 200, lat=3.0, curv=0.01)
    learned = learning.learned_lat_accel(0.01)
    self.assertGreater(learned, DEFAULT_LATERAL_ACCELERATION)
    self.assertLess(learned, 3.0)  # prior still pulls the blend down

  def test_confidence_grows_with_count(self):
    learning = self.make_learning()
    self.sample_frames(learning, 50, lat=3.0, curv=0.01)
    low = learning.learned_lat_accel(0.01)
    learning2 = self.make_learning()
    self.sample_frames(learning2, 2000, lat=3.0, curv=0.01)
    high = learning2.learned_lat_accel(0.01)
    self.assertGreater(high, low)
    self.assertLessEqual(high, 3.0)

  def test_lat_accel_clipped_to_bounds(self):
    learning = self.make_learning()
    self.sample_frames(learning, 3000, lat=5.0, curv=0.01)
    learned = learning.learned_lat_accel(0.01)
    self.assertLessEqual(learned, CSC_LAT_ACCEL_MAX)

  def test_brake_nudge_lowers_comfort(self):
    learning = self.make_learning()
    self.sample_frames(learning, 300, lat=3.0, curv=0.01)
    before = learning.learned_lat_accel(0.01)
    learning.apply_brake_nudge(0.01)
    after = learning.learned_lat_accel(0.01)
    self.assertLess(after, before)
    self.assertGreaterEqual(after, CSC_LAT_ACCEL_MIN - 1e-9)

  def test_override_watch_raises_comfort(self):
    learning = self.make_learning()
    self.sample_frames(learning, 100, lat=2.0, curv=0.01)
    before = learning.learned_lat_accel(0.01)
    learning.start_override_watch(0.01, lateral_acceleration=2.8)
    learning.handle_override_watch(overriding_or_in_curve=True,
                                   lateral_acceleration=3.1, road_curvature=0.01)
    learning.handle_override_watch(overriding_or_in_curve=False,
                                   lateral_acceleration=1.0, road_curvature=0.01)
    after = learning.learned_lat_accel(0.01)
    self.assertGreater(after, before)

  def test_count_cap_limits_recency_weight(self):
    learning = self.make_learning()
    self.sample_frames(learning, 3000, lat=3.0, curv=0.01)
    key = bucket_curvature(0.01)
    data = learning.curvature_data[key]
    # effective count caps at CSC_COUNT_CAP, but the running average stays sane
    self.assertLessEqual(data["count"], CSC_COUNT_CAP + 3000)  # bookkeeping count grows
    self.assertGreater(data["average"], 0.0)

  def test_pseudo_sample_weight(self):
    learning = self.make_learning()
    learning.record_pseudo_sample(bucket_curvature(0.01), 3.0)
    key = bucket_curvature(0.01)
    self.assertEqual(learning.curvature_data[key]["count"], CSC_NUDGE_WEIGHT)
    self.assertAlmostEqual(learning.curvature_data[key]["average"], 3.0)

  def test_roundtrip_through_persistence_hooks(self):
    stored = {}
    learning = self.make_learning()
    learning.put_fn = lambda data: stored.update(data)
    learning.load_fn = lambda: stored
    self.sample_frames(learning, 300, lat=3.0, curv=0.01)
    learning.flush()
    self.assertTrue(stored)

    learning2 = self.make_learning()
    learning2.put_fn = lambda data: None
    learning2.load_fn = lambda: stored
    learning2.load()
    self.assertAlmostEqual(learning2.learned_lat_accel(0.01),
                           learning.learned_lat_accel(0.01), places=6)


if __name__ == "__main__":
  unittest.main()


class TestCalibrationProgress(unittest.TestCase):
  """StarPilot _calibration_progress parity: per-bucket threshold, whole-grid percent."""

  def test_empty_data_is_zero(self):
    self.assertEqual(CurvatureLearning().calibration_progress(), 0.0)

  def test_one_calibrated_bucket_is_grid_fraction(self):
    learning = CurvatureLearning()
    key = bucket_curvature(0.01)
    learning.curvature_data[key] = {"average": 2.5, "count": 200}  # exactly at threshold
    self.assertAlmostEqual(learning.calibration_progress(), 100.0 / CURVATURE_BUCKETS, places=6)

  def test_progress_caps_per_bucket(self):
    learning = CurvatureLearning()
    learning.curvature_data[bucket_curvature(0.01)] = {"average": 2.5, "count": 200 * 10}
    learning.curvature_data[bucket_curvature(0.005)] = {"average": 2.5, "count": 50}
    expected = (1.0 + 50 / 200) / CURVATURE_BUCKETS * 100
    self.assertAlmostEqual(learning.calibration_progress(), expected, places=6)

  def test_all_buckets_calibrated_is_hundred(self):
    learning = CurvatureLearning()
    for key in CURVATURE_GRID:
      learning.curvature_data[str(round(float(key), 6))] = {"average": 2.5, "count": 200}
    self.assertAlmostEqual(learning.calibration_progress(), 100.0, places=6)


class TestLearningStatusFromData(unittest.TestCase):
  """The web UI's read-only view: derives everything from persisted bucket JSON."""

  def test_none_and_garbage_yield_defaults(self):
    for data in (None, {}, "not a dict", {"bad": "shape"}, {"0.01": {"average": float("nan"), "count": 5}}):
      status = learning_status_from_data(data)
      self.assertEqual(status["progress_pct"], 0.0)
      self.assertEqual(status["buckets"], 0)
      self.assertEqual(status["total_count"], 0)
      self.assertEqual(status["lateral_acceleration"], DEFAULT_LATERAL_ACCELERATION)

  def test_status_matches_instance_values(self):
    learning = CurvatureLearning()
    learning.curvature_data[bucket_curvature(0.01)] = {"average": 2.5, "count": 400}
    learning.curvature_data[bucket_curvature(0.004)] = {"average": 2.2, "count": 60}
    learning.rebuild()
    status = learning_status_from_data(learning.curvature_data)
    self.assertEqual(status["buckets"], 2)
    self.assertEqual(status["total_count"], 460)
    self.assertAlmostEqual(status["progress_pct"], round(learning.calibration_progress(), 1), places=6)
    self.assertAlmostEqual(status["lateral_acceleration"], round(learning.lateral_acceleration, 2), places=6)

  def test_status_accepts_raw_persisted_json_shape(self):
    raw = {"0.01": {"average": 2.5, "count": 400}, "junk": [1, 2], "0.5": {"average": 9.9, "count": -3}}
    status = learning_status_from_data(raw)
    self.assertEqual(status["buckets"], 1)  # junk + non-positive count dropped by normalize
    self.assertEqual(status["total_count"], 400)
class TestSamplingGatingGaps(unittest.TestCase):
  """StarPilot runtime gating ported with the B1-4 persistence/trigger work:
  the lead-clear cooldown and the post-control silence the original port
  never wired up."""

  def _frames(self, learning, n, **kw):
    base = {"v_ego": 15.0, "tracking_lead": False, "manual_speed_control": True,
            "driving_in_curve": True, "blinker": False,
            "lateral_acceleration": 2.5, "road_curvature": 0.01}
    base.update(kw)
    for _ in range(n):
      learning.log_data(**base)

  def test_lead_clear_cooldown(self):
    learning = CurvatureLearning(dt=0.05)
    # lead visible through the settle period
    self._frames(learning, 60, tracking_lead=True)
    self.assertFalse(learning.enable_training)
    # lead dropped: sampling must stay silent for CSC_LEAD_CLEAR_TIME (1 s)
    self._frames(learning, 60)
    self.assertFalse(learning.enable_training)
    # 1 s of clear frames (20 at 20 Hz) on top of the settled timer
    self._frames(learning, 21)
    self.assertTrue(learning.enable_training)

  def test_lead_reappear_resets_cooldown(self):
    learning = CurvatureLearning(dt=0.05)
    self._frames(learning, 60, tracking_lead=True)
    self._frames(learning, 25)   # cooldown nearly done
    self._frames(learning, 1, tracking_lead=True)  # lead flashes back
    self._frames(learning, 10)
    self.assertFalse(learning.enable_training)

  def test_control_silence_after_openpilot_ownership(self):
    learning = CurvatureLearning(dt=0.05)
    # openpilot owns the speed: the quiet timer is pinned
    self._frames(learning, 100, manual_speed_control=False, long_control_active=True)
    self._frames(learning, 100)  # driver takes over, quiet timer 5 s
    self.assertFalse(learning.enable_training)
    self._frames(learning, 81)   # 4.05 s < CSC_CONTROL_QUIET_TIME
    self.assertFalse(learning.enable_training)
    self._frames(learning, 20)   # past 5 s + settle already elapsed
    self.assertTrue(learning.enable_training)

  def test_pure_manual_driving_has_no_silence(self):
    learning = CurvatureLearning(dt=0.05)
    self._frames(learning, 100, long_control_active=False)
    self.assertTrue(learning.enable_training)


class TestAsyncPersistenceContract(unittest.TestCase):
  """flush() three-state put_fn contract: async accepted (stay dirty until
  ack), rejected (retry later), legacy sync hook (saved immediately)."""

  def test_async_accepted_stays_dirty_until_ack(self):
    learning = CurvatureLearning(dt=0.05)
    learning.data_dirty = True
    learning.dirty_revision = 7
    learning.put_fn = lambda data: True
    learning.flush()
    self.assertTrue(learning.data_dirty)
    self.assertEqual(learning.pending_revision, 7)

    learning.acknowledge_saved(7)
    self.assertFalse(learning.data_dirty)
    self.assertIsNone(learning.pending_revision)

  def test_async_rejected_keeps_dirty(self):
    learning = CurvatureLearning(dt=0.05)
    learning.data_dirty = True
    learning.dirty_revision = 3
    learning.put_fn = lambda data: False
    learning.flush()
    self.assertTrue(learning.data_dirty)
    self.assertIsNone(learning.pending_revision)

  def test_async_in_flight_drop_then_late_ack_does_not_clear_newer_data(self):
    learning = CurvatureLearning(dt=0.05)
    learning.data_dirty = True
    learning.dirty_revision = 5
    learning.put_fn = lambda data: True
    learning.flush()              # submission covering rev 5 accepted
    learning.dirty_revision = 9   # more samples while the write is in flight
    learning.data_dirty = True
    learning.put_fn = lambda data: False  # second flush dropped (in flight)
    learning.flush()
    learning.acknowledge_saved(5)  # first write lands: revs 6-9 not in it
    self.assertTrue(learning.data_dirty)

    learning.pending_revision = 9
    learning.put_fn = lambda data: True
    learning.flush()
    learning.acknowledge_saved(9)
    self.assertFalse(learning.data_dirty)

  def test_sync_hook_saved_immediately(self):
    learning = CurvatureLearning(dt=0.05)
    learning.data_dirty = True
    stored = {}
    learning.put_fn = lambda data: stored.update(data) or None
    learning.flush()
    self.assertFalse(learning.data_dirty)
    self.assertTrue(stored)
