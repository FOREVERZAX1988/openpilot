import unittest

from openpilot.selfdrive.controls.lib.latcontrol_vehicle_tunes import (
  FLM_FRICTION_SPEED_KNOTS,
  clear_flm_runtime_overrides,
  flm_runtime_overrides_active,
  get_standard_friction_threshold,
  normalize_flm_overrides,
  set_flm_runtime_overrides,
)


class TestFlmRuntimeOverrides(unittest.TestCase):
  def setUp(self):
    clear_flm_runtime_overrides()

  def tearDown(self):
    clear_flm_runtime_overrides()

  def test_no_overrides_means_inactive(self):
    self.assertFalse(flm_runtime_overrides_active())
    set_flm_runtime_overrides({})
    self.assertFalse(flm_runtime_overrides_active())

  def test_overrides_become_active(self):
    set_flm_runtime_overrides({"vehicleKnobs": {"frictionOffset": 0.01}})
    self.assertTrue(flm_runtime_overrides_active())

  def test_malformed_overrides_are_dropped(self):
    # A bundle with neither a friction curve nor knobs carries no
    # information and must not count as active.
    set_flm_runtime_overrides({"unrelated": 1})
    self.assertFalse(flm_runtime_overrides_active())

  def test_friction_curve_interpolates_over_speed(self):
    values = [0.10, 0.12, 0.14, 0.16, 0.18]
    set_flm_runtime_overrides({"baseFrictionThresholds": {
      "standard": {"speedKnots": list(FLM_FRICTION_SPEED_KNOTS), "values": values},
    }})
    self.assertTrue(flm_runtime_overrides_active())

    # A knot value must come back exactly.
    self.assertAlmostEqual(get_standard_friction_threshold(0.0), 0.10)
    self.assertAlmostEqual(get_standard_friction_threshold(25.0), 0.18)

    # A value between knots interpolates linearly.
    self.assertAlmostEqual(get_standard_friction_threshold(5.0), 0.12)
    self.assertAlmostEqual(get_standard_friction_threshold(7.5), 0.13)

  def test_friction_curve_of_the_wrong_length_is_ignored(self):
    set_flm_runtime_overrides({"baseFrictionThresholds": {
      "standard": {"speedKnots": list(FLM_FRICTION_SPEED_KNOTS), "values": [0.1, 0.2]},
    }})
    # The bundle is structurally valid, so it stays active, but the curve
    # cannot be used and the default must be returned instead.
    from openpilot.selfdrive.controls.lib.latcontrol_vehicle_tunes import _standard_friction_threshold_default
    self.assertAlmostEqual(get_standard_friction_threshold(10.0),
                           _standard_friction_threshold_default(10.0))

  def test_other_families_do_not_affect_standard(self):
    set_flm_runtime_overrides({"baseFrictionThresholds": {
      "gm": {"speedKnots": list(FLM_FRICTION_SPEED_KNOTS), "values": [0.01] * len(FLM_FRICTION_SPEED_KNOTS)},
    }})
    from openpilot.selfdrive.controls.lib.latcontrol_vehicle_tunes import _standard_friction_threshold_default
    self.assertAlmostEqual(get_standard_friction_threshold(10.0),
                           _standard_friction_threshold_default(10.0))

  def test_normalize_rejects_garbage(self):
    self.assertEqual(normalize_flm_overrides(None), {})
    self.assertEqual(normalize_flm_overrides("nope"), {})
    self.assertEqual(normalize_flm_overrides(123), {})

  def test_normalize_keeps_valid_knobs(self):
    normalized = normalize_flm_overrides({"vehicleKnobs": {"a": 0.5, "b": "x"}})
    self.assertAlmostEqual(normalized["vehicleKnobs"]["a"], 0.5)
    # A non-numeric knob is dropped rather than poisoning the bundle.
    self.assertNotIn("b", normalized["vehicleKnobs"])

  def test_clearing_removes_the_overrides(self):
    set_flm_runtime_overrides({"vehicleKnobs": {"a": 0.5}})
    self.assertTrue(flm_runtime_overrides_active())
    clear_flm_runtime_overrides()
    self.assertFalse(flm_runtime_overrides_active())

  def test_nonfinite_threshold_value_drops_the_whole_curve(self):
    # A NaN knot would poison every interpolated frame value, so the family
    # curve must be dropped all-or-nothing and the default returned.
    from openpilot.selfdrive.controls.lib.latcontrol_vehicle_tunes import _standard_friction_threshold_default
    values = [0.10, float('nan'), 0.14, 0.16, 0.18]
    set_flm_runtime_overrides({"baseFrictionThresholds": {
      "standard": {"speedKnots": list(FLM_FRICTION_SPEED_KNOTS), "values": values},
    }})
    self.assertFalse(flm_runtime_overrides_active())
    self.assertAlmostEqual(get_standard_friction_threshold(10.0),
                           _standard_friction_threshold_default(10.0))

  def test_below_floor_threshold_value_drops_the_whole_curve(self):
    # Same floor as the upstream flm GmSurface friction curve (>= 0.05).
    from openpilot.selfdrive.controls.lib.latcontrol_vehicle_tunes import _standard_friction_threshold_default
    values = [0.10, 0.12, 0.14, 0.16, 0.049]
    set_flm_runtime_overrides({"baseFrictionThresholds": {
      "standard": {"speedKnots": list(FLM_FRICTION_SPEED_KNOTS), "values": values},
    }})
    self.assertFalse(flm_runtime_overrides_active())
    self.assertAlmostEqual(get_standard_friction_threshold(10.0),
                           _standard_friction_threshold_default(10.0))

  def test_nonfinite_and_absurd_knobs_are_dropped(self):
    normalized = normalize_flm_overrides({"vehicleKnobs": {
      "nan": float('nan'), "inf": float('inf'), "huge": 1e308,
      "bool": True, "ok": 2.8,
    }})
    self.assertEqual(set(normalized["vehicleKnobs"]), {"ok"})
    self.assertAlmostEqual(normalized["vehicleKnobs"]["ok"], 2.8)

  def test_frame_time_knob_read_is_fail_closed_against_edited_globals(self):
    from openpilot.selfdrive.controls.lib.latcontrol_vehicle_tunes import _flm_vehicle_knob
    # Simulate a global mutated past normalize (hand-edited memory/cache):
    set_flm_runtime_overrides({"vehicleKnobs": {"ok": 0.5}})
    import openpilot.selfdrive.controls.lib.latcontrol_vehicle_tunes as tunes
    self.assertAlmostEqual(_flm_vehicle_knob("ok", 1.0), 0.5)
    tunes._FLM_ACTIVE_OVERRIDES["vehicleKnobs"]["ok"] = float('nan')
    self.assertAlmostEqual(_flm_vehicle_knob("ok", 1.0), 1.0)
    tunes._FLM_ACTIVE_OVERRIDES["vehicleKnobs"]["ok"] = 1e308
    self.assertAlmostEqual(_flm_vehicle_knob("ok", 1.0), 1.0)
    tunes._FLM_ACTIVE_OVERRIDES["vehicleKnobs"]["ok"] = True
    self.assertAlmostEqual(_flm_vehicle_knob("ok", 1.0), 1.0)
    tunes._FLM_ACTIVE_OVERRIDES["vehicleKnobs"]["ok"] = 0.5
    self.assertAlmostEqual(_flm_vehicle_knob("ok", 1.0), 0.5)


if __name__ == "__main__":
  unittest.main()
