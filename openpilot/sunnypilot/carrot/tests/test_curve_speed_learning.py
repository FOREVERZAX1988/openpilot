"""
Copyright (c) 2026-, sunnypilot and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
"""
Tests for the StarPilot curve-speed learning port (sunnypilot/carrot/curve_speed_learning/).

Pure logic and a Params-free runtime shell, so these run without cereal. Run with:

    cd /e/sp && PYTHONPATH=. python -m pytest \\
      openpilot/sunnypilot/carrot/tests/test_curve_speed_learning.py -q

Properties anchored on starpilot/curve_speed/learning.py:
  * an empty curve returns the prior fit and never leaves the baseline (invariance),
  * 24 log-spaced buckets, history weight capped at 600 (:9-20),
  * the monotone fit never falls as curvature tightens (:54-66),
  * v1 JSON documents round-trip; corrupt ones load as invalid, never partially (:93-128),
  * nudges clamp to [1.2, 3.2] with weight 20 (:18-19, 23, 160-163),
  * the runtime's comfort_fn is None while disabled or sample-less (baseline invariance).
"""
import os
import tempfile
import unittest

from openpilot.sunnypilot.carrot.curve_speed_learning.learning import (
  BUCKET_COUNT,
  CURVATURES,
  LearnedCurve,
  bucket_index,
  interpolate,
)

try:
  # openpilot.common.params loads a native lib (libparams_c.so) that does not exist on
  # every host; the runtime shell needs Params, the pure learning core does not.
  from openpilot.sunnypilot.carrot.curve_speed_learning.runtime import CurveSpeedLearningRuntime
  _RUNTIME_AVAILABLE = True
except (ImportError, OSError):
  CurveSpeedLearningRuntime = None
  _RUNTIME_AVAILABLE = False


class TestLearnedCurve(unittest.TestCase):
  def test_grid_has_24_log_buckets(self):
    self.assertEqual(BUCKET_COUNT, 24)
    self.assertEqual(len(CURVATURES), 24)
    ratios = [b / a for a, b in zip(CURVATURES, CURVATURES[1:], strict=False)]
    # grid values are rounded to 6 decimals (KEYS), so the log spacing is equal only to ~3e-4
    self.assertTrue(all(abs(r - ratios[0]) < 1e-3 for r in ratios), "log-spaced grid")

  def test_bucket_index_nearest_log(self):
    self.assertEqual(bucket_index(0.0005), 0)
    self.assertEqual(bucket_index(0.02), 23)
    self.assertEqual(bucket_index(-0.0015), bucket_index(0.0015), "sign ignored")

  def test_empty_curve_comfort_is_the_prior(self):
    curve = LearnedCurve()
    prior = interpolate(0.003, (0.001, 0.003, 0.01, 0.03, 0.1), (1.5, 1.8, 2.2, 2.6, 2.9))
    # comfort interpolates the prior across the 24-point fit grid, so 0.003 sits between
    # grid nodes; assert it tracks the prior within a node width.
    self.assertAlmostEqual(curve.comfort(0.003), prior, delta=0.05)

  def test_observe_pulls_comfort_toward_samples(self):
    curve = LearnedCurve()
    for _ in range(500):
      curve.observe(0.01, 1.5)
    self.assertLess(curve.comfort(0.01), 2.2, "500 samples at 1.5 must drag the fit below the 2.2 prior")
    self.assertGreaterEqual(curve.comfort(0.01), 1.2)

  def test_fit_is_monotone_in_curvature(self):
    curve = LearnedCurve()
    for k, a in ((0.002, 1.3), (0.006, 2.8), (0.015, 1.4)):
      for _ in range(300):
        curve.observe(k, a)
    values = [curve.comfort(k) for k in CURVATURES]
    self.assertTrue(all(b >= a - 1e-9 for a, b in zip(values, values[1:], strict=False)), "isotonic fit never falls")

  def test_history_weight_cap(self):
    curve = LearnedCurve()
    for _ in range(5000):
      curve.observe(0.01, 1.5)
    curve.observe(0.01, 3.0)
    # effective history capped at HISTORY_WEIGHT=600: one new sample moves the average by 1/601
    self.assertLess(curve.comfort(0.01), 1.6)

  def test_nudge_clamps_and_weights(self):
    curve = LearnedCurve()
    curve.nudge(0.01, 99.0)
    doc = curve.document()["buckets"]
    self.assertEqual(list(doc.values())[0]["count"], 20, "NUDGE_WEIGHT=20")
    self.assertAlmostEqual(list(doc.values())[0]["average"], 3.2, places=9, msg="clamped to MAX_COMFORT")

  def test_document_roundtrip(self):
    curve = LearnedCurve()
    curve.observe(0.008, 2.1)
    reloaded = LearnedCurve.load(curve.document())
    self.assertTrue(reloaded.valid)
    self.assertAlmostEqual(reloaded.curve.comfort(0.008), curve.comfort(0.008), places=12)

  def test_corrupt_document_never_partial(self):
    bad = {"version": 1, "buckets": {"0.008": {"average": "x", "count": 1}}}
    result = LearnedCurve.load(bad)
    self.assertFalse(result.valid)
    self.assertFalse(result.curve.dirty)

  def test_legacy_document_loads(self):
    result = LearnedCurve.load({"0.008": {"average": 2.0, "count": 5}})
    self.assertTrue(result.valid)
    self.assertTrue(result.migrated)


class _FakeParams:
  """Params-shaped stub over a temp dir: get_bool/get/put plus the get_param_path the
  persistence writer needs (curve_speed_persistence.read_saved)."""

  def __init__(self):
    self.data = {}
    self._dir = os.path.join(tempfile.mkdtemp(prefix="curve_learning_test_"), "params", "d")
    os.makedirs(self._dir, exist_ok=True)

  def get_param_path(self, key):
    return os.path.join(self._dir, key)

  def get_bool(self, key, default=False):
    return bool(self.data.get(key, default))

  def get(self, key, default=None):
    return self.data.get(key, default)

  def put(self, key, value):
    self.data[key] = str(value)


@unittest.skipUnless(_RUNTIME_AVAILABLE, "openpilot.common.params native lib unavailable on this host")
class TestRuntimeBaselineInvariance(unittest.TestCase):
  def _runtime(self, params):
    return CurveSpeedLearningRuntime(params)

  def test_comfort_fn_none_when_disabled_or_unlearned(self):
    params = _FakeParams()
    runtime = self._runtime(params)
    self.assertIsNone(runtime.comfort_fn(), "disabled -> baseline")
    params.data["CurveSpeedLearning"] = "1"
    runtime.refresh_params(0.0)
    self.assertIsNone(runtime.comfort_fn(), "enabled but sample-less -> baseline")

  def test_comfort_fn_appears_after_a_sample(self):
    params = _FakeParams()
    params.data["CurveSpeedLearning"] = "1"
    runtime = self._runtime(params)
    runtime.refresh_params(0.0)
    runtime.curve.observe(0.01, 2.0)
    runtime._has_samples = True
    fn = runtime.comfort_fn()
    self.assertIsNotNone(fn)
    self.assertAlmostEqual(fn(0.01), runtime.curve.comfort(0.01), places=12)

  def test_feedback_key_consumed_and_cleared(self):
    params = _FakeParams()
    params.data["CurveSpeedLearning"] = "1"
    params.data["CurveSpeedFeedback"] = "up"
    runtime = self._runtime(params)
    runtime.refresh_params(0.0)
    self.assertEqual(params.data["CurveSpeedFeedback"], "", "feedback consumed on read")
    # no scene yet -> no nudge recorded, key still cleared
    self.assertFalse(runtime.curve.dirty)


if __name__ == "__main__":
  unittest.main()
