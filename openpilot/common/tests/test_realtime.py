import unittest
from unittest import mock

from openpilot.common import realtime


class TestCoreAffinity(unittest.TestCase):
  def test_get_available_cores_falls_back_to_cpu_count(self):
    with mock.patch.object(realtime.os, 'sched_getaffinity', side_effect=OSError):
      with mock.patch.object(realtime.os, 'cpu_count', return_value=8):
        self.assertEqual(realtime.get_available_cores(), set(range(8)))

  def test_get_available_cores_reports_current_mask(self):
    with mock.patch.object(realtime.os, 'sched_getaffinity', return_value={0, 1, 2, 3}):
      self.assertEqual(realtime.get_available_cores(), {0, 1, 2, 3})

  def test_offline_core_does_not_raise(self):
    """modeld boots with config_realtime_process(7, 54). Power save offlines the big
    cluster, and os.sched_setaffinity() on an offline CPU raises EINVAL. The pin must
    be skipped rather than killing the daemon."""
    with mock.patch.object(realtime, 'PC', False), \
         mock.patch.object(realtime, 'get_online_cores', return_value={0, 1, 2, 3}), \
         mock.patch.object(realtime.os, 'sched_setaffinity') as setaffinity:
      self.assertEqual(realtime.set_core_affinity([7]), set())
      setaffinity.assert_not_called()

  def test_partial_overlap_pins_available_cores_only(self):
    with mock.patch.object(realtime, 'PC', False), \
         mock.patch.object(realtime, 'get_online_cores', return_value={0, 1, 4, 5}), \
         mock.patch.object(realtime.os, 'sched_setaffinity') as setaffinity:
      self.assertEqual(realtime.set_core_affinity([5, 6, 7]), {5})
      setaffinity.assert_called_once_with(0, [5])

  def test_fully_available_cores_are_pinned(self):
    with mock.patch.object(realtime, 'PC', False), \
         mock.patch.object(realtime, 'get_online_cores', return_value=set(range(8))), \
         mock.patch.object(realtime.os, 'sched_setaffinity') as setaffinity:
      self.assertEqual(realtime.set_core_affinity([7]), {7})
      setaffinity.assert_called_once_with(0, [7])

  def test_oserror_is_swallowed(self):
    """Even a racing hotplug (core goes offline between the check and the call) must
    not take the process down."""
    with mock.patch.object(realtime, 'PC', False), \
         mock.patch.object(realtime, 'get_online_cores', return_value={0, 1, 2, 3}), \
         mock.patch.object(realtime.os, 'sched_setaffinity', side_effect=OSError(22, 'Invalid argument')):
      self.assertEqual(realtime.set_core_affinity([0]), set())

  def test_noop_on_pc(self):
    with mock.patch.object(realtime, 'PC', True), \
         mock.patch.object(realtime.os, 'sched_setaffinity') as setaffinity:
      self.assertEqual(realtime.set_core_affinity([7]), set())
      setaffinity.assert_not_called()


class TestConfigRealtimeProcess(unittest.TestCase):
  def test_priority_is_set_even_when_affinity_is_skipped(self):
    """A daemon that cannot be pinned should still get its RT priority."""
    with mock.patch.object(realtime, 'PC', False), \
         mock.patch.object(realtime, 'get_online_cores', return_value={0, 1, 2, 3}), \
         mock.patch.object(realtime.os, 'sched_setscheduler') as setscheduler, \
         mock.patch.object(realtime.os, 'sched_setaffinity') as setaffinity:
      realtime.config_realtime_process(7, 54)
      setscheduler.assert_called_once()
      setaffinity.assert_not_called()


class TestOnlineCores(unittest.TestCase):
  def test_parses_kernel_cpu_list(self):
    for spec, expected in [("0-3,6-7", {0, 1, 2, 3, 6, 7}), ("0", {0}), ("0-1", {0, 1})]:
      with mock.patch.object(realtime.Path, 'read_text', return_value=spec):
        self.assertEqual(realtime.get_online_cores(), expected)

  def test_falls_back_to_cpu_count_when_sysfs_unreadable(self):
    with mock.patch.object(realtime.Path, 'read_text', side_effect=OSError), \
         mock.patch.object(realtime.os, 'cpu_count', return_value=8):
      self.assertEqual(realtime.get_online_cores(), set(range(8)))

  def test_malformed_range_falls_back(self):
    with mock.patch.object(realtime.Path, 'read_text', return_value="7-4"), \
         mock.patch.object(realtime.os, 'cpu_count', return_value=4):
      self.assertEqual(realtime.get_online_cores(), set(range(4)))


class TestRepinAfterSelfPin(unittest.TestCase):
  def test_pinned_process_can_still_move_to_an_online_core(self):
    """Regression: the UI bootstraps with config_realtime_process(0, ...), which
    narrows its affinity mask to {0}. Deciding "online" from that mask made every
    later re-pin a no-op, so the UI stayed on core 0 (dropped frames) even after
    power save re-onlined the big cluster."""
    with mock.patch.object(realtime, 'PC', False), \
         mock.patch.object(realtime, 'get_online_cores', return_value={0, 1, 2, 3, 6, 7}), \
         mock.patch.object(realtime.os, 'sched_getaffinity', return_value={0}), \
         mock.patch.object(realtime.os, 'sched_setaffinity') as setaffinity:
      # 4/5 still offline -> no pin, and never an EINVAL attempt
      self.assertEqual(realtime.set_core_affinity([5, 4]), set())
      setaffinity.assert_not_called()
      # once a big core is online, widening off core 0 must work
      self.assertEqual(realtime.set_core_affinity([7]), {7})
      setaffinity.assert_called_once_with(0, [7])


if __name__ == '__main__':
  unittest.main()
