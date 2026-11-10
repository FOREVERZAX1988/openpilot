import unittest

from openpilot.sunnypilot.carrot.signal_start_guard import SignalStartGuard


# A small extra red near the optical centre used to pin the sole stop anchor.
SMALL = [670, 280, 682, 286]
LEFT = [590, 286, 626, 304]
RIGHT = [666, 288, 706, 308]


def step(guard, t, tracks, **kw):
  context = {'enabled': True, 'valid': True, 'drive': True, 'gas': False, 'speed': 0., 'departure': True}
  context.update(kw)
  obs = {'timestamp': t, 'frame_id': round(t * 1000), 'session': 'camera',
             'tracks': [{'box': b, 'raw': c} for b, c in tracks]}
  return guard.update(t + .2, obs, **context)


def held():
  guard = SignalStartGuard()
  for t in (0., .2, .4):
    step(guard, t, [(SMALL, 'red'), (LEFT, 'red'), (RIGHT, 'red')])
  assert guard.hold and guard.box == SMALL
  return guard


class TestSignalStartGroup(unittest.TestCase):

  def test_two_independent_red_housings_turn_green_when_primary_disappears(self):
    guard = held()
    for t in (.6, .8, 1., 1.2):
      self.assertTrue(step(guard, t, [(LEFT, 'green'), (RIGHT, 'green')]).hold)
    result = step(guard, 1.4, [(LEFT, 'green'), (RIGHT, 'green')])
    self.assertTrue(result.released)
    self.assertFalse(result.hold)

  def test_group_cannot_release_without_fresh_red_anchored_transitions(self):
    for kind in ['unseen', 'red_conflict', 'duplicate', 'gap', 'invalid', 'stale', 'restart']:
      with self.subTest(kind=kind):
        guard = held()
        for t in (.6, .8, 1., 1.2, 1.4):
          tracks = [(LEFT, 'green'), (RIGHT, 'green')]
          if kind == 'unseen':
            tracks = [([720, 286, 756, 304], 'green'), ([800, 288, 840, 308], 'green')]
          if kind == 'red_conflict':
            tracks += [(SMALL, 'red')]
          if kind == 'duplicate':
            tracks = [(LEFT, 'green'), (LEFT, 'green')]
          if kind == 'gap':
            t *= 5
          if kind == 'restart':
            guard.session = 'old'
          if kind == 'stale':
            guard.update(t + 1., {'timestamp': t, 'frame_id': round(t * 1000), 'session': 'camera', 'tracks': []},
                         enabled=True, valid=True, drive=True, gas=False, speed=0., departure=True)
            continue
          result = step(guard, t, tracks, valid=not (kind == 'invalid' and t == 1.))
          self.assertTrue(result.hold)
          self.assertFalse(result.released)
        self.assertTrue(guard.hold)

  def test_overlapping_red_anchors_cannot_make_two_housings(self):
    guard = SignalStartGuard()
    # Outside the single-transition band, two overlapping fits are not a pair.
    left = [470, 286, 506, 304]
    overlap = [487, 286, 523, 304]
    for t in (0., .2, .4):
      step(guard, t, [(SMALL, 'red'), (left, 'red'), (overlap, 'red')])
    for t in (.6, .8, 1., 1.2, 1.4):
      self.assertTrue(step(guard, t, [(left, 'green'), (overlap, 'green')]).hold)

  def test_one_central_transition_releases_lost_primary(self):
    for box in [LEFT, RIGHT]:
      with self.subTest(box=box):
        guard = held()
        for t in (.6, .8, 1., 1.2):
          self.assertTrue(step(guard, t, [(box, 'green')]).hold)
        result = step(guard, 1.4, [(box, 'green')])
        self.assertTrue(result.released)
        self.assertFalse(result.hold)
        self.assertEqual(result.reason, 'green_transition')

  def test_one_peripheral_transition_does_not_replace_lost_primary(self):
    guard = SignalStartGuard()
    side = [800, 286, 840, 304]
    for t in (0., .2, .4):
      step(guard, t, [(SMALL, 'red'), (side, 'red')])
    for t in (.6, .8, 1., 1.2, 1.4):
      self.assertTrue(step(guard, t, [(side, 'green')]).hold)

  def test_central_green_without_its_own_confirmed_red_cannot_release(self):
    guard = SignalStartGuard()
    for t in (0., .2, .4):
      step(guard, t, [(SMALL, 'red')] + ([(RIGHT, 'red')] if t == .4 else []))
    for t in (.6, .8, 1., 1.2, 1.4):
      self.assertTrue(step(guard, t, [(RIGHT, 'green')]).hold)

  def test_two_offcentre_transitions_keep_existing_pair_fallback(self):
    guard = SignalStartGuard()
    pair = [[500, 286, 536, 304], [800, 286, 840, 304]]
    for t in (0., .2, .4):
      step(guard, t, [(SMALL, 'red')] + [(b, 'red') for b in pair])
    for t in (.6, .8, 1., 1.2):
      self.assertTrue(step(guard, t, [(b, 'green') for b in pair]).hold)
    result = step(guard, 1.4, [(b, 'green') for b in pair])
    self.assertTrue(result.released)
    self.assertEqual(result.reason, 'green_group')

  def test_repeated_frames_do_not_advance_group_votes(self):
    guard = held()
    for _ in range(20):
      self.assertTrue(step(guard, .6, [(LEFT, 'green'), (RIGHT, 'green')]).hold)

  def test_group_is_bounded_and_disable_clears_anchors(self):
    guard = held()
    for i in range(20):
      step(guard, .6 + i * .2, [([410 + i * 20, 180, 422 + i * 20, 186], 'red')])
    self.assertLessEqual(len(guard.red_anchors), 8)
    self.assertFalse(step(guard, 5., [], enabled=False).hold)
    self.assertFalse(guard.red_anchors)


if __name__ == "__main__":
  unittest.main()
