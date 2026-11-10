import unittest

from openpilot.sunnypilot.carrot.signal_assist import SignalAssist


def observation(t, state='red', ident=1, session='worker1', box=(640, 250, 680, 270)):
  return {'timestamp': t, 'frame_id': round(t * 20), 'session': session, 'tracks': [
    {'id': ident, 'box': box, 'state': state, 'age': 0., 'observations': 10, 'evidence': {'raw': state}}]}


def step(a, t, o=None, **kw):
  context = {'enabled': True, 'valid': True, 'drive': True, 'gas': False, 'speed': 0., 'model_distance': 3.,
                 'model_y': 0., 'comfort_brake': 2.4, 'lead': False, 'entry_allowed': True}
  context.update(kw)
  return a.update(t, o, **context)


def confirm(a, start=0., state='red', ident=1, **kw):
  for i in range(12):
    t = start + i * .05
    result = step(a, t, observation(t, state, ident), **kw)
  return result


class TestSignalAssist(unittest.TestCase):

  def test_hold_survives_unknown_and_a_moving_lead(self):
    a = SignalAssist()
    self.assertTrue(confirm(a).hold)
    self.assertTrue(step(a, 10., lead=True).hold)
    self.assertTrue(step(a, 100., observation(100., 'unknown'), lead=True).hold)

  def test_green_must_be_same_track_and_continuous(self):
    a = SignalAssist()
    confirm(a)
    self.assertTrue(confirm(a, 1., 'green', ident=2).hold)
    self.assertFalse(confirm(a, 2., 'green', ident=1).hold)
    self.assertFalse(step(a, 2.6).red_sign)

  def test_restart_cannot_supply_green_permission(self):
    a = SignalAssist()
    confirm(a)
    for i in range(20):
      t = 1 + i * .05
      self.assertTrue(step(a, t, observation(t, 'green', session='restarted')).hold)

  def test_bad_evidence_cannot_acquire_a_stop(self):
    for bad in ['duplicate', 'old', 'future', 'malformed']:
      with self.subTest(bad=bad):
        a = SignalAssist()
        for i in range(20):
          t = i * .05
          o = observation(0 if bad == 'duplicate' else t - 1 if bad == 'old' else t + 1 if bad == 'future' else t)
          if bad == 'malformed':
            o['tracks'][0]['box'] = [float('nan')] * 4
          r = step(a, t, o)
          self.assertFalse(r.hold)
          self.assertFalse(r.red_sign)

  def test_one_green_flash_cannot_release(self):
    a = SignalAssist()
    confirm(a)
    self.assertTrue(step(a, .6, observation(.6, 'green')).hold)
    self.assertTrue(step(a, .65, observation(.65, 'unknown')).hold)
    self.assertTrue(step(a, 2).hold)

  def supported_green(self, t, **changes):
    obs = observation(t, 'green')
    obs['tracks'][0].update(seen_red=True, support_state='green', support_since=t - .4, support_count=3)
    obs['tracks'][0].update(changes)
    return obs

  def test_fresh_same_track_producer_history_avoids_second_confirmation_streak(self):
    a = SignalAssist()
    self.assertTrue(confirm(a).hold)
    # Intermediate results can miss the consumer deadline; all three camera
    # observations were consecutive, and the final result is still fresh.
    r = step(a, 1.59, self.supported_green(1.4))
    self.assertTrue(r.released)
    self.assertFalse(r.hold)

  def test_bad_producer_history_cannot_bypass_green_confirmation(self):
    for changes in [
      {'id': 2}, {'seen_red': False}, {'support_state': 'red'},
      {'support_count': 2}, {'support_count': 11}, {'support_since': float('nan')},
      {'support_since': 1.2}, {'support_since': 0.}, {'age': .05},
      {'state': 'unknown'}, {'evidence': {'raw': 'red'}},
    ]:
      with self.subTest(changes=changes):
        a = SignalAssist()
        self.assertTrue(confirm(a).hold)
        self.assertTrue(step(a, 1.59, self.supported_green(1.4, **changes)).hold)

  def test_producer_history_does_not_extend_freshness_or_survive_restart(self):
    a = SignalAssist()
    confirm(a)
    self.assertTrue(step(a, 1.601, self.supported_green(1.4)).hold)
    obs = self.supported_green(1.8)
    obs['session'] = 'restarted'
    self.assertTrue(step(a, 1.99, obs).hold)

  def test_explicit_exit_overrides_hold(self):
    for override in [{'enabled': False}, {'valid': False}, {'drive': False}, {'gas': True}]:
      with self.subTest(override=override):
        a = SignalAssist()
        confirm(a)
        self.assertFalse(step(a, .6, **override).hold)

  def test_driver_gas_has_ten_second_reacquisition_cooldown(self):
    a = SignalAssist()
    confirm(a)
    step(a, .6, gas=True)
    self.assertFalse(confirm(a, 1.).hold)
    self.assertTrue(confirm(a, 11.).hold)

  def test_moving_red_uses_existing_plausible_distance(self):
    a = SignalAssist()
    r = confirm(a, speed=10., model_distance=40.)
    self.assertTrue(r.red_sign)
    self.assertFalse(r.hold)
    self.assertTrue(step(a, 5., speed=5., model_distance=20.).red_sign)
    self.assertTrue(step(a, 10., speed=0.).hold)

  def test_no_new_moving_red_for_ineligible_context(self):
    for context in [
      {'model_distance': 1.}, {'model_distance': 500.}, {'model_distance': float('nan')},
      {'lead': True}, {'entry_allowed': False}, {'turning': True}, {'model_y': 10.},
      {'speed': 30.}, {'comfort_brake': 0.},
    ]:
      with self.subTest(context=context):
        a = SignalAssist()
        args = {'speed': 10., 'model_distance': 40.}
        args.update(context)
        self.assertFalse(confirm(a, **args).red_sign)

  def test_off_axis_signal_does_not_arm(self):
    a = SignalAssist()
    for i in range(20):
      t = i * .05
      self.assertFalse(step(a, t, observation(t, box=(50, 250, 100, 270))).red_sign)

  def test_confirmation_breaks_on_gap(self):
    a = SignalAssist()
    for t in (0., .1, .2, .6, .7):
      self.assertFalse(step(a, t, observation(t)).hold)

  def test_rewind_clears_latch(self):
    a = SignalAssist()
    confirm(a, 10.)
    self.assertFalse(step(a, 1.).hold)

  def test_nested_red_lamp_does_not_replace_complete_housing(self):
    a = SignalAssist()
    for i in range(12):
      t = i * .05
      o = observation(t, box=(640, 250, 700, 280))
      o['tracks'].extend(observation(t, ident=2, box=(644, 256, 660, 264))['tracks'])
      r = step(a, t, o)
    self.assertTrue(r.hold)
    self.assertEqual(r.track_id, 1)
    self.assertFalse(confirm(a, 1., 'green', ident=1).hold)


if __name__ == "__main__":
  unittest.main()
