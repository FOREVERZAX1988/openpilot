"""A settings control follows the store, not the value it was built with.

The device UI and the web panel write the same store. The controls used to read their key
once, at construction, and were refreshed only on an offroad/engaged transition, so a
value set from the browser sat invisible on the device -- and a switch tapped on the device
could be flipped back by the store it was about to be written to. Both directions are what
these tests pin down.
"""
import unittest

from openpilot.system.ui.sunnypilot.widgets.option_control import OptionControlSP
from openpilot.system.ui.sunnypilot.widgets.toggle import PENDING_WRITE_TIMEOUT, SYNC_INTERVAL, ToggleSP


class FakeStore:
  """A Params stand-in whose writes land asynchronously, like the real one."""

  def __init__(self, values=None):
    self.committed = dict(values or {})
    self.in_flight = {}
    self.reads = []
    self.writes = []

  # -- reads ---------------------------------------------------------------
  def get_bool(self, key, default=False):
    self.reads.append(key)
    return bool(self.committed.get(key, default))

  def get(self, key, return_default=False):
    self.reads.append(key)
    return self.committed.get(key)

  # -- writes --------------------------------------------------------------
  def put_bool(self, key, value, block=False):
    self.writes.append((key, bool(value)))
    self.in_flight[key] = bool(value)

  def put(self, key, value, block=False):
    self.writes.append((key, value))
    self.in_flight[key] = value

  def settle(self):
    """The write reaches the file."""
    self.committed.update(self.in_flight)
    self.in_flight.clear()


class TestToggleFollowsTheStore(unittest.TestCase):
  def make(self, **kwargs) -> ToggleSP:
    toggle = ToggleSP(**kwargs)
    toggle.params = self.store = FakeStore()
    return toggle

  def test_a_value_from_the_other_surface_arrives(self):
    toggle = self.make(param="KeyA")
    self.assertFalse(toggle.get_state())

    self.store.committed["KeyA"] = True   # the web panel wrote it
    self.assertTrue(toggle.sync(now=10.0))
    self.assertTrue(toggle.get_state())

  def test_a_write_of_its_own_is_not_undone_by_the_async_gap(self):
    toggle = self.make(param="KeyA")
    toggle.set_state(True)
    toggle._pending_state = True
    toggle._pending_until = 10.0 + PENDING_WRITE_TIMEOUT

    # the store does not show the write yet: the switch must stay where the driver put it
    self.assertFalse(toggle.sync(now=10.0 + SYNC_INTERVAL))
    self.assertTrue(toggle.get_state())

    self.store.committed["KeyA"] = True
    self.assertFalse(toggle.sync(now=10.0 + 2 * SYNC_INTERVAL))
    self.assertTrue(toggle.get_state())

  def test_the_store_wins_once_the_write_never_lands(self):
    toggle = self.make(param="KeyA")
    toggle.set_state(True)
    toggle._pending_state = True
    toggle._pending_until = 10.0 + PENDING_WRITE_TIMEOUT

    # a refused write (Safe Mode holding the key down) has to show, not be hidden forever
    self.assertTrue(toggle.sync(now=10.0 + PENDING_WRITE_TIMEOUT + 0.1))
    self.assertFalse(toggle.get_state())

  def test_a_paused_switch_does_not_move(self):
    toggle = self.make(param="KeyA")
    toggle.set_sync_paused(True)
    self.store.committed["KeyA"] = True
    self.assertFalse(toggle.sync(now=10.0))
    self.assertFalse(toggle.get_state())

    toggle.set_sync_paused(False)
    self.assertTrue(toggle.sync(now=10.0))

  def test_reads_are_bounded(self):
    toggle = self.make(param="KeyA")
    toggle.sync(now=10.0)
    toggle.sync(now=10.0 + SYNC_INTERVAL / 2)
    self.assertEqual(len(self.store.reads), 1)

  def test_a_mirror_switch_follows_without_writing(self):
    # Experimental Mode's write belongs to its callback (the risk dialog), so the switch
    # may only mirror the key
    toggle = self.make(sync_param="KeyB")
    self.store.committed["KeyB"] = True
    self.assertTrue(toggle.sync(now=10.0))
    self.assertTrue(toggle.get_state())

    toggle._handle_mouse_release(None)
    self.assertEqual(self.store.writes, [])

  def test_a_toggle_without_a_key_never_reads(self):
    toggle = self.make()
    self.assertFalse(toggle.sync(now=10.0))
    self.assertEqual(self.store.reads, [])


class TestOptionControlFollowsTheStore(unittest.TestCase):
  def make(self) -> OptionControlSP:
    control = OptionControlSP("KeyC", 0, 10)
    control.params = self.store = FakeStore()
    return control

  def test_a_value_from_the_other_surface_arrives(self):
    control = self.make()
    self.assertEqual(control.get_value(), 0)

    self.store.committed["KeyC"] = 4
    self.assertTrue(control.sync(now=10.0))
    self.assertEqual(control.get_value(), 4)

  def test_a_value_it_just_set_is_not_undone_by_the_async_gap(self):
    control = self.make()
    control.set_value(6)
    self.assertEqual(control.get_value(), 6)
    self.assertEqual(self.store.writes, [("KeyC", 6)])

    # the store still reads the old value back: the control keeps the driver's number
    self.assertFalse(control.sync(now=10.0))
    self.assertEqual(control.get_value(), 6)

    self.store.settle()
    self.assertFalse(control.sync(now=10.0 + SYNC_INTERVAL))
    self.assertEqual(control.get_value(), 6)

  def test_an_unset_key_keeps_showing_the_minimum(self):
    control = self.make()
    self.assertFalse(control.sync(now=10.0))
    self.assertEqual(control.get_value(), 0)


if __name__ == "__main__":
  unittest.main()
