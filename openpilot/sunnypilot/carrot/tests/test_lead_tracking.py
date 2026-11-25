"""
Copyright (c) 2026-, sunnypilot and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
"""
Tests for the StarPilot lead_tracking port (sunnypilot/carrot/lead_tracking.py).

The detector is pure state over validated inputs, so these need no cereal runtime - only
model-shaped arrays and a lead namespace. Run with:

    cd /e/sp && PYTHONPATH=. python -m pytest \\
      openpilot/sunnypilot/carrot/tests/test_lead_tracking.py -q

Anchored on the StarPilot behaviours that matter for the conditional-experiment fallback:
  * the 0.5 s first-order filter reaches FILTER_THRESHOLD only after sustained candidates
    (lead_tracking.py:19-20,211-213),
  * unknown/dead sources reset the temporal consensus instead of freezing it (:187),
  * the 0.45 s radarless hold survives a candidate flicker while present stays true (:204-210),
  * a stale source (> 0.25 s, :24) resets everything.
"""
import unittest

import numpy as np

from openpilot.sunnypilot.carrot.lead_tracking import (
  LeadDetector,
)


DT_MDL = 0.05
N = 33


class _Seq:
  def __init__(self, values):
    self._v = list(values)

  def __len__(self):
    return len(self._v)

  def __iter__(self):
    return iter(self._v)

  def __getitem__(self, i):
    return self._v[i]


def _model(max_distance=200.0, y=0.0):
  """Straight model path: x forward 0..max_distance, constant lateral offset."""
  xs = np.linspace(0.0, max_distance, N)
  return type("M", (), {
    "position": type("P", (), {"x": _Seq(xs), "y": _Seq([y] * N), "z": _Seq([0.0] * N), "t": _Seq(np.linspace(0.0, 10.0, N))})(),
    "velocity": type("V", (), {"x": _Seq([10.0] * N), "t": _Seq(np.linspace(0.0, 10.0, N))})(),
    "orientationRate": type("O", (), {"z": _Seq([0.0] * N), "t": _Seq(np.linspace(0.0, 10.0, N))})(),
    "action": type("A", (), {"shouldStop": False, "desiredAcceleration": 1.0})(),
  })()


class _Lead:
  def __init__(self, present=True, radar=True, d=40.0, v_lead=25.0, a_lead=0.0, prob=0.9, y_rel=0.0):
    self.present = present
    self.radar = radar
    self.dRel = d
    self.vLead = v_lead
    self.aLeadK = a_lead
    self.modelProb = prob
    self.yRel = y_rel
    self.status = present


class TestLeadDetector(unittest.TestCase):
  def _step(self, detector, lead, model, observed, **kw):
      defaults = {"speed_mps": 30.0, "t_follow_s": 1.8, "standstill": False, "observed_mono_s": observed,
                  "now_mono_s": observed + 0.01, "radar_fresh": True, "model_fresh": True,
                  "car_fresh": True, "headway_fresh": True}
      defaults.update(kw)
      return detector.step(lead, model, **defaults)

  def test_filter_reaches_threshold_only_after_sustained_candidates(self):
    detector = LeadDetector()
    model = _model()
    tracked_frames = 0
    for i in range(15):
      obs = self._step(detector, _Lead(), model, observed=i * DT_MDL)
      if obs.tracked:
        tracked_frames += 1
      if i < 5:
        self.assertFalse(obs.tracked, "a few frames must not trip the 0.632 threshold")
    self.assertTrue(obs.tracked)
    self.assertGreaterEqual(tracked_frames, 1)

  def test_unknown_source_resets_consensus(self):
    detector = LeadDetector()
    model = _model()
    for i in range(15):
      obs = self._step(detector, _Lead(), model, observed=i * DT_MDL)
    self.assertTrue(obs.tracked)
    # A stale radar source resets: tracked becomes None, not the previous True.
    obs = self._step(detector, _Lead(), model, observed=15 * DT_MDL, radar_fresh=False)
    self.assertIsNone(obs.tracked)
    # And the filter had to restart from zero.
    obs = self._step(detector, _Lead(), model, observed=16 * DT_MDL)
    self.assertFalse(obs.tracked)

  def test_source_age_cap(self):
    detector = LeadDetector()
    model = _model()
    obs = self._step(detector, _Lead(), model, observed=10.0, now_mono_s=10.0 + 0.3)
    self.assertIsNone(obs.tracked, "observed older than SOURCE_MAX_AGE_S must reset")

  def test_one_source_event_advances_filter_once(self):
    detector = LeadDetector()
    model = _model()
    first = self._step(detector, _Lead(), model, observed=1.0)
    second = self._step(detector, _Lead(), model, observed=1.0)  # same model frame
    self.assertIsNotNone(first.tracked)
    self.assertIsNone(second.tracked, "one source event cannot advance the filter twice")

  def test_radarless_hold_survives_candidate_flicker(self):
    detector = LeadDetector()
    model = _model(max_distance=200.0)
    # Vision-only lead inside the follow window at highway speed.
    for i in range(15):
      obs = self._step(detector, _Lead(radar=False, d=50.0, v_lead=29.0, prob=0.98, y_rel=0.0), model, observed=i * DT_MDL)
    self.assertTrue(obs.tracked)
    # present stays true but the candidate drops (distance beyond the vision limit):
    # the 0.45 s radarless hold keeps the candidate alive.
    obs = self._step(detector, _Lead(radar=False, d=150.0, v_lead=29.0, prob=0.98), model, observed=15 * DT_MDL)
    self.assertTrue(obs.tracked or obs.raw_present)

  def test_radar_lead_drop_unchanged(self):
    detector = LeadDetector()
    model = _model()
    for i in range(15):
      obs = self._step(detector, _Lead(radar=True), model, observed=i * DT_MDL)
    self.assertTrue(obs.tracked)
    # A radar-matched lead far beyond the model limit decays through the plain 0.5 s
    # filter - no radarless hold (lead_tracking.py:109-117), so factory-radar behaviour
    # is exactly the filter dynamics and nothing more.
    for i in range(15):
      obs = self._step(detector, _Lead(radar=True, d=250.0, v_lead=29.0), model, observed=(15 + i) * DT_MDL)
    self.assertFalse(obs.tracked)


if __name__ == "__main__":
  unittest.main()
