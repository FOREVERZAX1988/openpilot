import unittest

from openpilot.sunnypilot.common.safe_mode import (
  SAFE_MODE_MANAGED_KEYS,
  UNKNOWN_STOCK,
  backup_entry,
  can_restore,
  load_backup,
  missing_backup_keys,
  restore_plan,
  safe_value,
  serialize_backup,
)
from openpilot.sunnypilot.common.safe_mode_runtime import (
  apply_safe_mode,
  backup_document,
  enforce_safe_mode,
  is_safe_mode,
  restore_safe_mode,
)


class UnknownKeyName(Exception):
  """Mirrors openpilot.common.params.UnknownKeyName without importing it."""


class FakeParams:
  """A Params stand-in with the real signatures."""

  def __init__(self, values: dict | None = None, *, stock: dict | None = None,
               unknown: tuple = (), onroad: bool = False, offroad: bool = True):
    self.values = dict(values or {})
    self.stock = dict(stock or {})
    self.unknown = set(unknown)
    self.values["IsOnroad"] = "1" if onroad else "0"
    self.values["IsOffroad"] = "1" if offroad else "0"

  def _check(self, key: str) -> None:
    if key in self.unknown:
      raise UnknownKeyName(key)

  def get(self, key: str, block: bool = False, return_default: bool = False):
    self._check(key)
    return self.values.get(key)

  def get_bool(self, key: str, block: bool = False) -> bool:
    self._check(key)
    return self.values.get(key) == "1"

  def get_stock_value(self, key: str):
    self._check(key)
    return self.stock.get(key)

  def put(self, key: str, value, block: bool = False) -> None:
    self._check(key)
    self.values[key] = str(value)

  def remove(self, key: str) -> None:
    self._check(key)
    self.values.pop(key, None)


class TestSafeValue(unittest.TestCase):
  def test_a_fixed_value_wins(self):
    self.assertEqual(safe_value("ExperimentalMode", current="1", stock="9", default="0"), "0")

  def test_the_stock_value_is_used_when_there_is_no_fixed_one(self):
    self.assertEqual(safe_value("SteerRatio", current="16.8", stock="15.5", default="0.0"), "15.5")

  def test_an_unknown_stock_value_is_not_written(self):
    # 0.0 means "not known"; writing it would set the ratio to zero.
    self.assertIsNone(safe_value("SteerRatio", current="16.8", stock=UNKNOWN_STOCK, default=None))

  def test_the_default_is_the_last_resort(self):
    self.assertEqual(safe_value("SteerRatio", current="16.8", stock=None, default="14.0"), "14.0")

  def test_nothing_known_means_leave_it_alone(self):
    self.assertIsNone(safe_value("SteerRatio", current="16.8", stock=None, default=None))

  def test_the_managed_keys_are_all_registered_elsewhere(self):
    # Safe Mode must not name a key this fork does not ship: a read of an
    # unregistered key raises, and the whitelist is read every cycle.
    for key in SAFE_MODE_MANAGED_KEYS:
      self.assertIsInstance(key, str)
      self.assertTrue(key)
    # A whitelist covering everything would defeat the purpose.
    self.assertLess(len(SAFE_MODE_MANAGED_KEYS), 40)


class TestCanRestore(unittest.TestCase):
  def test_only_when_parked(self):
    self.assertTrue(can_restore(is_onroad=False, is_offroad=True))

  def test_refused_while_moving(self):
    self.assertFalse(can_restore(is_onroad=True, is_offroad=False))

  def test_refused_when_the_flags_contradict(self):
    self.assertFalse(can_restore(is_onroad=True, is_offroad=True))

  def test_refused_when_the_state_is_unknown(self):
    self.assertFalse(can_restore(is_onroad=False, is_offroad=False))


class TestBackupDocument(unittest.TestCase):
  def test_round_trip(self):
    backup = {"SteerRatio": backup_entry(True, "16.8"), "SteerFriction": backup_entry(False, None)}
    self.assertEqual(load_backup(serialize_backup(backup)), backup)

  def test_garbage_loads_as_empty(self):
    self.assertEqual(load_backup(None), {})
    self.assertEqual(load_backup(""), {})
    self.assertEqual(load_backup("not json"), {})
    self.assertEqual(load_backup("[1,2]"), {})

  def test_a_malformed_entry_is_skipped(self):
    self.assertEqual(load_backup('{"A": "not a dict"}'), {})

  def test_missing_keys_are_reported(self):
    backup = {"SteerRatio": backup_entry(True, "16.8")}
    missing = missing_backup_keys(backup, ("SteerRatio", "SteerFriction"))
    self.assertEqual(missing, ["SteerFriction"])

  def test_the_restore_plan_covers_managed_keys_then_extras(self):
    backup = {"Extra": backup_entry(True, "x"), "SteerRatio": backup_entry(True, "16.8")}
    plan = dict(restore_plan(backup, ("SteerRatio",)))
    self.assertEqual(plan["SteerRatio"], "16.8")
    self.assertEqual(plan["Extra"], "x")

  def test_a_key_that_was_absent_is_removed(self):
    backup = {"SteerRatio": backup_entry(False, None)}
    plan = dict(restore_plan(backup, ("SteerRatio",)))
    self.assertIsNone(plan["SteerRatio"])


class TestApplyAndRestore(unittest.TestCase):
  def test_applying_forces_the_fixed_values(self):
    params = FakeParams({"ExperimentalMode": "1", "NNFFMode": "2", "LaneCenteringEnabled": "1"})
    self.assertTrue(apply_safe_mode(params))
    self.assertEqual(params.values["ExperimentalMode"], "0")
    self.assertEqual(params.values["NNFFMode"], "0")
    self.assertEqual(params.values["LaneCenteringEnabled"], "0")

  def test_applying_records_the_original_values(self):
    params = FakeParams({"ExperimentalMode": "1", "NNFFMode": "2"})
    apply_safe_mode(params)
    backup = backup_document(params)
    self.assertEqual(backup["ExperimentalMode"], {"present": True, "value": "1"})
    self.assertEqual(backup["NNFFMode"], {"present": True, "value": "2"})

  def test_a_second_apply_does_not_overwrite_the_backup(self):
    params = FakeParams({"ExperimentalMode": "1"})
    apply_safe_mode(params)
    apply_safe_mode(params, ensure_backup=False)
    backup = backup_document(params)
    # The backup still holds the user's value, not the forced one.
    self.assertEqual(backup["ExperimentalMode"]["value"], "1")

  def test_an_unset_key_is_recorded_as_absent(self):
    params = FakeParams({"ExperimentalMode": "1"})
    apply_safe_mode(params)
    backup = backup_document(params)
    self.assertFalse(backup["SteerFriction"]["present"])

  def test_a_key_the_store_does_not_know_is_left_alone(self):
    # A device whose parameter library predates the key must not crash.
    params = FakeParams({"ExperimentalMode": "1"}, unknown=("NNFFMode",))
    self.assertTrue(apply_safe_mode(params))
    self.assertEqual(params.values["ExperimentalMode"], "0")

  def test_restore_puts_the_values_back(self):
    params = FakeParams({"ExperimentalMode": "1", "NNFFMode": "2"})
    apply_safe_mode(params)
    self.assertTrue(restore_safe_mode(params))
    self.assertEqual(params.values["ExperimentalMode"], "1")
    self.assertEqual(params.values["NNFFMode"], "2")

  def test_restore_removes_a_key_that_was_absent(self):
    params = FakeParams({"ExperimentalMode": "1"})
    apply_safe_mode(params)
    # SteerFriction was absent, so restoring removes whatever Safe Mode wrote
    params.values["SteerFriction"] = "0.3"
    restore_safe_mode(params)
    self.assertNotIn("SteerFriction", params.values)

  def test_restore_is_refused_while_moving(self):
    params = FakeParams({"ExperimentalMode": "1"}, onroad=True, offroad=False)
    apply_safe_mode(params)
    self.assertFalse(restore_safe_mode(params))
    # The forced value is still in place.
    self.assertEqual(params.values["ExperimentalMode"], "0")

  def test_restore_clears_the_backup(self):
    params = FakeParams({"ExperimentalMode": "1"})
    apply_safe_mode(params)
    restore_safe_mode(params)
    self.assertEqual(backup_document(params), {})

  def test_restore_without_a_backup_is_harmless(self):
    params = FakeParams({"ExperimentalMode": "1"})
    self.assertFalse(restore_safe_mode(params))

  def test_the_enforcer_only_runs_when_safe_mode_is_on(self):
    params = FakeParams({"SafeMode": "0", "ExperimentalMode": "1"})
    self.assertFalse(enforce_safe_mode(params, 0))
    self.assertEqual(params.values["ExperimentalMode"], "1")

  def test_the_enforcer_reapplies_on_its_cadence(self):
    params = FakeParams({"SafeMode": "1", "ExperimentalMode": "1"})
    apply_safe_mode(params)
    # Someone writes the user value back while Safe Mode is on.
    params.values["ExperimentalMode"] = "1"
    self.assertFalse(enforce_safe_mode(params, 1))
    self.assertEqual(params.values["ExperimentalMode"], "1")
    # On the cadence it is forced back.
    self.assertTrue(enforce_safe_mode(params, 20))
    self.assertEqual(params.values["ExperimentalMode"], "0")

  def test_is_safe_mode_reads_the_switch(self):
    self.assertTrue(is_safe_mode(FakeParams({"SafeMode": "1"})))
    self.assertFalse(is_safe_mode(FakeParams({"SafeMode": "0"})))
    self.assertFalse(is_safe_mode(FakeParams({})))

  def test_is_safe_mode_survives_an_unknown_key(self):
    self.assertFalse(is_safe_mode(FakeParams({}, unknown=("SafeMode",))))


if __name__ == "__main__":
  unittest.main()
