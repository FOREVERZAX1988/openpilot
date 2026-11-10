import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from openpilot.sunnypilot.carrot.server.services import setting_unit_index as unit_index


class TestSettingUnitIndex(unittest.TestCase):

  def setUp(self):
    tmp = tempfile.mkdtemp(prefix="unit_index_test_")
    self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    self.store_path = os.path.join(tmp, "state", "setting_unit_index.json")
    patcher = mock.patch.object(unit_index, "CARROT_SETTING_UNIT_INDEX_PATH", self.store_path)
    patcher.start()
    self.addCleanup(patcher.stop)

  def test_a_missing_store_reads_as_empty(self):
    self.assertEqual(unit_index.read_setting_unit_index(), {"units": {}})

  def test_a_saved_multiplier_survives_a_reload(self):
    unit_index.update_setting_unit_index({"units": {"ApplyModelSpeed": 3}})
    self.assertEqual(unit_index.read_setting_unit_index(), {"units": {"ApplyModelSpeed": 3}})

  def test_updates_merge_instead_of_replacing(self):
    unit_index.update_setting_unit_index({"units": {"A": 1}})
    unit_index.update_setting_unit_index({"units": {"B": 2}})
    self.assertEqual(unit_index.read_setting_unit_index()["units"], {"A": 1, "B": 2})

  # Index 0 is the default multiplier, so persisting it would only add noise.
  def test_returning_to_the_default_multiplier_drops_the_entry(self):
    unit_index.update_setting_unit_index({"units": {"A": 3}})
    unit_index.update_setting_unit_index({"units": {"A": 0}})
    self.assertEqual(unit_index.read_setting_unit_index()["units"], {})

  def test_an_out_of_range_index_is_rejected(self):
    unit_index.update_setting_unit_index({"units": {"A": 99, "B": -1, "C": 2}})
    self.assertEqual(unit_index.read_setting_unit_index()["units"], {"C": 2})

  def test_unusable_names_and_values_are_ignored(self):
    unit_index.update_setting_unit_index({"units": {"": 2, "   ": 2, "A": "x", "B": None, "C": 1}})
    self.assertEqual(unit_index.read_setting_unit_index()["units"], {"C": 1})

  def test_a_corrupt_store_falls_back_to_empty(self):
    os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
    with open(self.store_path, "w", encoding="utf-8") as f:
      f.write("{ not json")
    self.assertEqual(unit_index.read_setting_unit_index(), {"units": {}})

  def test_a_non_object_payload_is_tolerated(self):
    self.assertEqual(unit_index.sanitize_setting_unit_index({"units": ["nope"]}), {"units": {}})
    self.assertEqual(unit_index.sanitize_setting_unit_index(None), {"units": {}})
    self.assertEqual(unit_index.update_setting_unit_index("nope"), {"units": {}})

  def test_the_store_is_written_atomically_and_readable(self):
    unit_index.update_setting_unit_index({"units": {"A": 1}})
    with open(self.store_path, encoding="utf-8") as f:
      self.assertEqual(json.load(f), {"units": {"A": 1}})
    self.assertFalse(os.path.exists(self.store_path + ".tmp"))

  def test_the_entry_count_is_bounded(self):
    patcher = mock.patch.object(unit_index, "MAX_SETTING_UNIT_ENTRIES", 3)
    patcher.start()
    self.addCleanup(patcher.stop)
    unit_index.write_setting_unit_index({"units": {f"P{i}": 1 for i in range(10)}})
    self.assertEqual(len(unit_index.read_setting_unit_index()["units"]), 3)


if __name__ == "__main__":
  unittest.main()
