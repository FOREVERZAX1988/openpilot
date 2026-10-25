"""modeld must not wait for a CarParams the preview will never be handed.

CarParams is CLEAR_ON_MANAGER_START and only the car daemon writes it, from the
fingerprint, at every start -- it is onroad. So while the driving view is
previewed the blocking read is a deadlock: modeld comes up, connects the cameras,
loads its models and then publishes no modelV2 at all, and the view draws no path.
These pin what the preview reads instead, the car's own CarParamsPersistent, and
that it stays a read: still a blocking one, for the car daemon, when there is
nothing to fall back to.
"""
from unittest import mock

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.modeld.modeld import car_params

PERSISTED = b"the car's own last fingerprint"


class TestCarParamsWhilePreviewing(OpenpilotTestCase):
  def params(self, values, previewing=False):
    """A store with exactly what car_params is allowed to touch: no puts."""
    p = mock.Mock(spec=["get", "get_bool"])
    p.get.side_effect = lambda key, block=False: values.get(key)
    p.get_bool.return_value = previewing
    return p

  def test_the_preview_reads_the_cars_own_persisted_params(self):
    p = self.params({"CarParamsPersistent": PERSISTED}, previewing=True)
    self.assertEqual(car_params(p), PERSISTED, "the persisted fingerprint is the car's own")
    self.assertEqual(p.get.mock_calls, [mock.call("CarParams"), mock.call("CarParamsPersistent")])

  def test_the_preview_never_blocks_on_a_carparams_that_cannot_come(self):
    p = self.params({"CarParamsPersistent": PERSISTED}, previewing=True)
    car_params(p)
    self.assertNotIn(mock.call("CarParams", block=True), p.get.mock_calls,
                     "blocking here is the deadlock: the car daemon is onroad")

  def test_a_carparams_that_is_there_wins_and_the_persisted_one_is_left_alone(self):
    p = self.params({"CarParams": b"current", "CarParamsPersistent": PERSISTED}, previewing=True)
    self.assertEqual(car_params(p), b"current")
    self.assertEqual(p.get.mock_calls, [mock.call("CarParams")])

  def test_offroad_without_the_preview_it_still_waits_for_the_car_daemon(self):
    p = self.params({"CarParamsPersistent": PERSISTED})
    car_params(p)
    self.assertEqual(p.get.mock_calls, [mock.call("CarParams"), mock.call("CarParams", block=True)])

  def test_the_preview_does_not_write_anything(self):
    p = self.params({"CarParamsPersistent": PERSISTED}, previewing=True)
    car_params(p)
    self.assertEqual([c for c in p.method_calls if c[0] != "get"], [mock.call.get_bool("IsOnroadPreview")])
