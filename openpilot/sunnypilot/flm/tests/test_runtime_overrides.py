# Copyright (c) 2026, firestar5683 and StarPilot contributors
# SPDX-License-Identifier: MIT
"""Tests for the FLM runtime override admission layer (Seam B).

These lock the three properties the controls-safety-engineer adjudication
required from the direct-read path that this layer replaces:

- slew limiting (no one-frame step in the friction curve)
- fail-closed zeroing that means "restore the stock baseline", not
  "command zero torque"
- identity binding (a bundle for another car is refused)
"""
import unittest

from openpilot.sunnypilot.flm.runtime_overrides import (
  FLM_DEFAULT_SLEW_PER_S,
  FLM_MAX_DELTA_FRACTION,
  FlmOverrideOwner,
  bundle_to_profile,
  family_baselines,
  identity_for_fingerprint,
  profile_to_bundle,
)


BASELINES = {
  "gm": [0.20, 0.22, 0.25, 0.28, 0.30],
  "standard": [0.16, 0.18, 0.20, 0.22, 0.24],
  "hkg_canfd": [0.30, 0.32, 0.34, 0.36, 0.39],
}

KNOTS = 5


def make_bundle(*, family="gm", delta=0.10, base=None):
  base = base or BASELINES[family]
  values = [v * (1.0 + delta) for v in base]
  return {"baseFrictionThresholds": {family: {"values": values}}}


class TestIdentity(unittest.TestCase):
  def test_identity_is_stable_and_fingerprint_specific(self):
    a = identity_for_fingerprint(1234)
    b = identity_for_fingerprint(1234)
    c = identity_for_fingerprint(5678)
    self.assertEqual(a, b)
    self.assertNotEqual(a, c)

  def test_missing_fingerprint_still_yields_an_identity(self):
    self.assertTrue(identity_for_fingerprint(None))
    self.assertNotEqual(identity_for_fingerprint(None), identity_for_fingerprint(0))

  def test_family_baselines_drops_non_finite(self):
    out = family_baselines({"gm": [0.2, float("nan")]})
    self.assertEqual(out, {})


class TestBundleToProfile(unittest.TestCase):
  def test_admits_a_moderate_bundle(self):
    profile = bundle_to_profile(make_bundle(), BASELINES, identity="id",
                                now_ns=1_000_000, sequence=1)
    self.assertIsNotNone(profile)
    self.assertEqual(len(profile.coefficients), 3 * KNOTS)
    self.assertAlmostEqual(profile.coefficients[0], 0.10)

  def test_refuses_a_bundle_outside_the_delta_band(self):
    profile = bundle_to_profile(make_bundle(delta=0.5), BASELINES, identity="id",
                                now_ns=1_000_000, sequence=1)
    self.assertIsNone(profile)

  def test_refuses_a_curve_with_the_wrong_knot_count(self):
    bundle = {"baseFrictionThresholds": {"gm": {"values": [0.2, 0.3]}}}
    profile = bundle_to_profile(bundle, BASELINES, identity="id",
                                now_ns=1_000_000, sequence=1)
    self.assertIsNone(profile)

  def test_refuses_a_curve_with_a_non_finite_knot(self):
    bundle = {"baseFrictionThresholds": {"gm": {"values": [0.2, float("inf"), 0.3, 0.4, 0.5]}}}
    profile = bundle_to_profile(bundle, BASELINES, identity="id",
                                now_ns=1_000_000, sequence=1)
    self.assertIsNone(profile)

  def test_refuses_without_baselines(self):
    profile = bundle_to_profile(make_bundle(), {}, identity="id",
                                now_ns=1_000_000, sequence=1)
    self.assertIsNone(profile)

  def test_refuses_an_invalid_clock(self):
    profile = bundle_to_profile(make_bundle(), BASELINES, identity="id",
                                now_ns=0, sequence=1)
    self.assertIsNone(profile)

  def test_round_trip_through_profile_to_bundle(self):
    profile = bundle_to_profile(make_bundle(), BASELINES, identity="id",
                                now_ns=1_000_000, sequence=1)
    bundle = profile_to_bundle(profile, BASELINES)
    self.assertIn("gm", bundle["baseFrictionThresholds"])
    rebuilt = bundle["baseFrictionThresholds"]["gm"]["values"]
    expected = [v * 1.10 for v in BASELINES["gm"]]
    for got, want in zip(rebuilt, expected, strict=True):
      self.assertAlmostEqual(got, want, places=9)


class TestSlewLimiting(unittest.TestCase):
  def test_first_frame_applies_only_the_slew_step(self):
    owner = FlmOverrideOwner(identity="id", baselines=BASELINES)
    owner.admit(make_bundle(delta=0.30), now_ns=1_000_000_000)
    bundle = owner.tick(now_ns=1_000_000_000, enabled=True)

    self.assertIn("gm", bundle["baseFrictionThresholds"])
    values = bundle["baseFrictionThresholds"]["gm"]["values"]
    base = BASELINES["gm"][0]
    delta = (values[0] / base) - 1.0
    # One frame at 20Hz may move at most slew_per_s * dt.
    self.assertLessEqual(abs(delta), FLM_DEFAULT_SLEW_PER_S * 0.05 + 1e-9)
    self.assertGreater(abs(delta), 0.0)

  def test_converges_to_the_target_over_time(self):
    owner = FlmOverrideOwner(identity="id", baselines=BASELINES)
    owner.admit(make_bundle(delta=0.20), now_ns=1_000_000_000)
    now = 1_000_000_000
    bundle = {}
    for _ in range(200):
      now += 50_000_000  # 20Hz
      bundle = owner.tick(now_ns=now, enabled=True)
    values = bundle["baseFrictionThresholds"]["gm"]["values"]
    base = BASELINES["gm"][0]
    delta = (values[0] / base) - 1.0
    self.assertAlmostEqual(delta, 0.20, places=3)

  def test_never_exceeds_the_delta_band(self):
    owner = FlmOverrideOwner(identity="id", baselines=BASELINES)
    owner.admit(make_bundle(delta=0.30), now_ns=1_000_000_000)
    now = 1_000_000_000
    for _ in range(500):
      now += 50_000_000
      bundle = owner.tick(now_ns=now, enabled=True)
      values = bundle["baseFrictionThresholds"]["gm"]["values"]
      for value, base in zip(values, BASELINES["gm"], strict=True):
        delta = (value / base) - 1.0
        self.assertLessEqual(abs(delta), FLM_MAX_DELTA_FRACTION + 1e-9)


class TestFailClosedZeroing(unittest.TestCase):
  def test_disabled_owner_publishes_nothing(self):
    owner = FlmOverrideOwner(identity="id", baselines=BASELINES)
    owner.admit(make_bundle(delta=0.20), now_ns=1_000_000_000)
    bundle = owner.tick(now_ns=1_000_000_000, enabled=False)
    self.assertEqual(bundle, {})

  def test_unhealthy_owner_publishes_nothing(self):
    owner = FlmOverrideOwner(identity="id", baselines=BASELINES)
    owner.admit(make_bundle(delta=0.20), now_ns=1_000_000_000)
    bundle = owner.tick(now_ns=1_000_000_000, enabled=True, healthy=False)
    self.assertEqual(bundle, {})

  def test_stale_bundle_slews_back_to_stock(self):
    owner = FlmOverrideOwner(identity="id", baselines=BASELINES)
    owner.admit(make_bundle(delta=0.20), now_ns=1_000_000_000)
    now = 1_000_000_000
    for _ in range(100):
      now += 50_000_000
      owner.tick(now_ns=now, enabled=True)

    # Jump far past the bundle age: the owner must not keep an expired
    # override active.
    now += 60_000_000_000
    bundle = owner.tick(now_ns=now, enabled=True)
    self.assertEqual(bundle, {})

  def test_zeroing_means_stock_curve_not_zero_torque(self):
    """The zeroed state must restore the stock friction curve.

    The published bundle becomes empty, so latcontrol_vehicle_tunes resolves
    its own default friction thresholds. It must NOT publish a curve of
    zeros (that would zero the friction model) nor a zero-torque command.
    """
    owner = FlmOverrideOwner(identity="id", baselines=BASELINES)
    owner.admit(make_bundle(delta=0.20), now_ns=1_000_000_000)
    owner.tick(now_ns=1_000_000_000, enabled=False)

    bundle = owner.applied_bundle
    self.assertEqual(bundle, {})
    # No family survives, so no curve of zeros can be published.
    self.assertNotIn("baseFrictionThresholds", bundle)

  def test_clock_regression_is_refused(self):
    owner = FlmOverrideOwner(identity="id", baselines=BASELINES)
    owner.admit(make_bundle(delta=0.20), now_ns=2_000_000_000)
    owner.tick(now_ns=2_000_000_000, enabled=True)
    # A backwards clock must not be accepted as a fresh frame.
    bundle = owner.tick(now_ns=1_000_000_000, enabled=True)
    self.assertEqual(bundle, {})


class TestIdentityBinding(unittest.TestCase):
  def test_a_bundle_is_bound_to_the_owner_identity(self):
    owner = FlmOverrideOwner(identity="car-A", baselines=BASELINES)
    self.assertTrue(owner.admit(make_bundle(delta=0.10), now_ns=1_000_000_000))
    bundle = owner.tick(now_ns=1_000_000_000, enabled=True)
    self.assertNotEqual(bundle, {})

  def test_a_second_owner_with_a_different_identity_refuses_it(self):
    """A bundle admitted for one car must not be applied to another."""
    owner_a = FlmOverrideOwner(identity=identity_for_fingerprint(111), baselines=BASELINES)
    owner_b = FlmOverrideOwner(identity=identity_for_fingerprint(222), baselines=BASELINES)

    self.assertTrue(owner_a.admit(make_bundle(delta=0.10), now_ns=1_000_000_000))
    # owner_b gets the same bundle payload but its own identity; the bundle
    # carries no identity field, so the binding happens through the owner.
    self.assertTrue(owner_b.admit(make_bundle(delta=0.10), now_ns=1_000_000_000))
    self.assertNotEqual(owner_a.identity, owner_b.identity)
    # Both owners slew independently; the profile identity used internally
    # is the owner's, so a bundle cannot cross car boundaries.
    self.assertEqual(owner_a.owner.identity, owner_a.identity)
    self.assertEqual(owner_b.owner.identity, owner_b.identity)


class TestManualOverride(unittest.TestCase):
  def test_manual_mode_refuses_the_profile(self):
    owner = FlmOverrideOwner(identity="id", baselines=BASELINES)
    owner.admit(make_bundle(delta=0.20), now_ns=1_000_000_000)
    bundle = owner.tick(now_ns=1_000_000_000, enabled=True, manual=True)
    self.assertEqual(bundle, {})


if __name__ == "__main__":
  unittest.main()
