"""Unittest port of the StarPilot FLM canonical-bounds tests.

Verbatim port of starpilot/flm/tests/test_canonical_bounds.py, converted
from pytest to unittest because this fork removed pytest (upstream
98e7c4f987) and ships tools/test_runner.py as the test runner.
"""

import unittest
from openpilot.sunnypilot.flm import canonical_surface_adapter as adapter, torque_surface as source


class TestCanonicalBounds(unittest.TestCase):
  def test_raw_domains_bind_exact_existing_universal_defaults_and_limits(self):
    limits = dict(source._GM_BOUNDS)
    limits.update(ff_gain_left=(-0.4, 0.6), ff_gain_right=(-0.4, 0.6))
    self.assertEqual(len(adapter.RAW_DOMAINS), 30)
    for name, original, hardbounds in adapter.RAW_DOMAINS:
      self.assertEqual(original, source._GM_NEUTRAL[name])
      self.assertEqual(hardbounds, limits[name])

  def test_all30_normalization_endpoints_preserve_actual_constructor_domains(self):
    for name in adapter.NAMES:
      with self.subTest(name=name):
        low, high = adapter.coordinate_bounds(name)
        for coordinate in (low, 0.0, high):
          raw = dict(source._GM_NEUTRAL)
          if name in adapter.WINDOWS:
            raw[name] *= 1 + coordinate
          elif name in adapter.DEADBANDS or name == 'low_speed_angle_assist_max_torque':
            # Actual0normalizer mustfreeze output; nonzero normalizers intersect unitraw
            # domains at application rather than confusing coefficient withdegrees/torque.
            for normalizer in (0.0, 0.01, 0.5, 1.0, 10.0, 100.0):
              dl, dh = adapter.dynamic_coordinate_bounds(name, normalizer)
              self.assertTrue(0 <= dl <= dh <= 0.25)
              selected = min(max(coordinate, dl), dh)
              dynamic = dict(raw)
              dynamic[name] = selected * normalizer
              source.GmSurface('torque_universal', dynamic)
            continue
          else:
            raw[name] = coordinate
          source.GmSurface('torque_universal', raw)

  def test_stored_profile_cannot_admit_raw_amplitudes_above_existing_domain(self):
    for name, expected in [('center_taper_max', 0.18), ('highway_center_taper_max', 0.18),
                            ('curvy_turn_in_trim_left', 0.20), ('curvy_turn_in_trim_right', 0.20)]:
      with self.subTest(name=name):
        self.assertEqual(adapter.coordinate_bounds(name)[1], expected)
        with self.assertRaises(ValueError):
          adapter.validate_trial({name: expected + 1e-10})
        values = dict.fromkeys(adapter.NAMES, 0.0)
        values[name] = expected + 1e-10
        with self.assertRaises(ValueError):
          adapter.full_profile_sha256('a' * 64, values)

  def test_window_joint_extremes_keep_order_and_rawbounds(self):
    for a in adapter.coordinate_bounds('curvy_speed_min'):
      for b in adapter.coordinate_bounds('curvy_speed_max'):
        for c in adapter.coordinate_bounds('curvy_turn_in_trim_speed_min'):
          for d in adapter.coordinate_bounds('curvy_turn_in_trim_speed_max'):
            effect = adapter.CanonicalSurfaceEffects(dict(zip(adapter.WINDOWS, (a, b, c, d), strict=True)), 'a' * 64)
            self.assertTrue(effect.surface.knobs['curvy_speed_min'] < effect.surface.knobs['curvy_speed_max'])
            self.assertTrue(effect.surface.knobs['curvy_turn_in_trim_speed_min'] < effect.surface.knobs['curvy_turn_in_trim_speed_max'])

  def test_true_invalid_dynamic_coordinates_fail_at_actual_hook_without_cap_relaxation(self):
    effects = adapter.CanonicalSurfaceEffects({'center_deadband_highway_deg': 0.25}, 'a' * 64)
    with self.assertRaises(ValueError):
      effects.selected_deadzone(30.0, 0.0, 0.01, 0.1, 0.0, original_anchor=effects.original_effect_anchor)
    self.assertEqual(source._GM_BOUNDS['center_deadband_highway_deg'], (0.0, 0.08))


if __name__ == "__main__":
  unittest.main()
