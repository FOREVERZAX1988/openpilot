"""Profile storage: create, update, delete and the round trip through disk.

These paths had no tests, yet a profile is exactly where the reported "오류 3"
surfaced. Two silent-loss bugs are covered here: a create past the limit that
reports success while being dropped, and an update whose values clean down to
nothing, which used to delete the profile as a side effect.
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from openpilot.sunnypilot.carrot.server.services import setting_profiles


SNAPSHOT_CURRENT_SETTING_VALUES = setting_profiles.snapshot_current_setting_values


CATALOG = {
  "ApplyModelSpeed": {"default": 0, "min": -120, "max": 120},
  "TFollowDecelBoost": {"default": 50, "min": 0, "max": 100},
  "CruiseSpeed1": {"default": 30, "min": 0, "max": 160},
  "DriverMonitoringEnabled": {"default": 1, "search_only": True},
}


class TestSettingProfiles(unittest.TestCase):

  def setUp(self):
    tmp = tempfile.mkdtemp(prefix="setting_profiles_test_")
    self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    self.profile_store = os.path.join(tmp, "state", "setting_profiles.json")
    for target, name, value in (
      (setting_profiles, "CARROT_SETTING_PROFILES_PATH", self.profile_store),
      # get_settings_cached returns (data, groups, by_name, groups_list); only
      # by_name is used, as the set of allowed parameter names.
      (setting_profiles, "get_settings_cached", lambda: (None, None, CATALOG, None)),
      # No git and no live params in the test environment.
      (setting_profiles, "read_git_profile_meta", lambda: {}),
      (setting_profiles, "snapshot_current_setting_values",
       lambda: {
         "ApplyModelSpeed": 0,
         "TFollowDecelBoost": 50,
         "DriverMonitoringEnabled": 0,
       }),
    ):
      patcher = mock.patch.object(target, name, value)
      patcher.start()
      self.addCleanup(patcher.stop)

  def test_creating_and_reading_a_profile_round_trips(self):
    created = setting_profiles.create_setting_profile("mackorea 260720")
    self.assertEqual(created["name"], "mackorea 260720")
    self.assertEqual(created["values"], {"ApplyModelSpeed": 0, "TFollowDecelBoost": 50})

    read = setting_profiles.read_setting_profiles()["profiles"]
    self.assertEqual([p["id"] for p in read], [created["id"]])

  def test_a_nameless_profile_is_rejected(self):
    with self.assertRaises(ValueError):
      setting_profiles.create_setting_profile("   ")

  def test_unknown_parameters_are_dropped_from_stored_values(self):
    patcher = mock.patch.object(setting_profiles, "snapshot_current_setting_values",
                                lambda: {"ApplyModelSpeed": 5, "GhostParam": 1})
    patcher.start()
    self.addCleanup(patcher.stop)
    created = setting_profiles.create_setting_profile("p")
    self.assertNotIn("GhostParam", created["values"])
    self.assertEqual(created["values"]["ApplyModelSpeed"], 5)

  def test_search_only_parameters_are_excluded_from_new_profiles(self):
    created = setting_profiles.create_setting_profile("p")
    self.assertNotIn("DriverMonitoringEnabled", created["values"])

  def test_snapshot_does_not_read_search_only_parameters(self):
    requested = []

    def fake_get_param_values(names, defaults):
      requested.extend(names)
      return defaults

    for name, value in (
      ("get_param_values", fake_get_param_values),
      ("snapshot_current_setting_values", SNAPSHOT_CURRENT_SETTING_VALUES),
    ):
      patcher = mock.patch.object(setting_profiles, name, value)
      patcher.start()
      self.addCleanup(patcher.stop)

    values = setting_profiles.snapshot_current_setting_values()

    self.assertNotIn("DriverMonitoringEnabled", requested)
    self.assertNotIn("DriverMonitoringEnabled", values)

  def test_search_only_only_update_is_rejected_without_changing_profile(self):
    created = setting_profiles.create_setting_profile("p")

    with self.assertRaises(setting_profiles.SettingProfileError) as no_values:
      setting_profiles.update_setting_profile(
        created["id"], {"values": {"DriverMonitoringEnabled": 0}}
      )

    self.assertEqual(no_values.exception.code, "PROFILE_NO_VALUES")
    self.assertEqual(setting_profiles.get_setting_profile(created["id"])["values"], created["values"])

  def test_reading_an_old_profile_removes_search_only_values(self):
    os.makedirs(os.path.dirname(self.profile_store), exist_ok=True)
    with open(self.profile_store, "w", encoding="utf-8") as f:
      f.write(json.dumps({"profiles": [{
        "id": "old",
        "name": "old profile",
        "values": {
          "ApplyModelSpeed": 5,
          "DriverMonitoringEnabled": 0,
        },
      }]}))

    [profile] = setting_profiles.read_setting_profiles()["profiles"]
    self.assertEqual(profile["values"], {"ApplyModelSpeed": 5})

  # The new one used to be appended then trimmed away, reporting success.
  def test_creating_past_the_limit_fails_instead_of_silently_dropping(self):
    patcher = mock.patch.object(setting_profiles, "MAX_SETTING_PROFILES", 2)
    patcher.start()
    self.addCleanup(patcher.stop)
    setting_profiles.create_setting_profile("a")
    setting_profiles.create_setting_profile("b")

    with self.assertRaises(ValueError):
      setting_profiles.create_setting_profile("c")
    self.assertEqual(len(setting_profiles.read_setting_profiles()["profiles"]), 2)

  def test_renaming_keeps_the_values(self):
    created = setting_profiles.create_setting_profile("old")
    updated = setting_profiles.update_setting_profile(created["id"], {"name": "new"})
    self.assertEqual(updated["name"], "new")
    self.assertEqual(updated["values"], created["values"])

  def test_updating_values_replaces_them(self):
    created = setting_profiles.create_setting_profile("p")
    updated = setting_profiles.update_setting_profile(created["id"], {"values": {"CruiseSpeed1": 45}})
    self.assertEqual(updated["values"], {"CruiseSpeed1": 45})

  # The bug: cleaning down to {} used to delete the profile on the next read.
  def test_an_update_that_cleans_to_nothing_is_rejected_not_applied(self):
    created = setting_profiles.create_setting_profile("p")
    with self.assertRaises(ValueError):
      setting_profiles.update_setting_profile(created["id"], {"values": {"OnlyGhost": 1}})

    survived = setting_profiles.get_setting_profile(created["id"])
    self.assertIsNotNone(survived)
    self.assertEqual(survived["values"], created["values"], "the profile must keep its old values")

  def test_renaming_to_blank_is_rejected(self):
    created = setting_profiles.create_setting_profile("p")
    with self.assertRaises(ValueError):
      setting_profiles.update_setting_profile(created["id"], {"name": "   "})

  # The UI translates by code, so each rejection must carry a stable one.
  def test_rejections_carry_a_translatable_code(self):
    patcher = mock.patch.object(setting_profiles, "MAX_SETTING_PROFILES", 1)
    patcher.start()
    self.addCleanup(patcher.stop)
    created = setting_profiles.create_setting_profile("a")

    with self.assertRaises(setting_profiles.SettingProfileError) as limit:
      setting_profiles.create_setting_profile("b")
    self.assertEqual(limit.exception.code, "PROFILE_LIMIT")

    with self.assertRaises(setting_profiles.SettingProfileError) as no_values:
      setting_profiles.update_setting_profile(created["id"], {"values": {"Ghost": 1}})
    self.assertEqual(no_values.exception.code, "PROFILE_NO_VALUES")

    with self.assertRaises(setting_profiles.SettingProfileError) as no_name:
      setting_profiles.create_setting_profile("  ")
    self.assertEqual(no_name.exception.code, "PROFILE_NAME_REQUIRED")

  def test_updating_a_missing_profile_raises(self):
    with self.assertRaises(KeyError):
      setting_profiles.update_setting_profile("nope", {"name": "x"})

  def test_deleting_removes_only_the_target(self):
    a = setting_profiles.create_setting_profile("a")
    b = setting_profiles.create_setting_profile("b")
    setting_profiles.delete_setting_profile(a["id"])

    remaining = [p["id"] for p in setting_profiles.read_setting_profiles()["profiles"]]
    self.assertEqual(remaining, [b["id"]])

  def test_deleting_a_missing_profile_raises(self):
    with self.assertRaises(KeyError):
      setting_profiles.delete_setting_profile("nope")

  def test_a_corrupt_store_reads_as_empty(self):
    os.makedirs(os.path.dirname(self.profile_store), exist_ok=True)
    with open(self.profile_store, "w", encoding="utf-8") as f:
      f.write("{ not json")
    self.assertEqual(setting_profiles.read_setting_profiles(), {"profiles": []})

  def test_duplicate_ids_are_collapsed_on_read(self):
    os.makedirs(os.path.dirname(self.profile_store), exist_ok=True)
    entry = {"id": "dup", "name": "p", "values": {"ApplyModelSpeed": 1}}
    with open(self.profile_store, "w", encoding="utf-8") as f:
      f.write(json.dumps({"profiles": [entry, entry]}))
    self.assertEqual(len(setting_profiles.read_setting_profiles()["profiles"]), 1)

  def test_the_store_is_written_atomically(self):
    setting_profiles.create_setting_profile("p")
    self.assertFalse(os.path.exists(self.profile_store + ".tmp"))
    with open(self.profile_store, encoding="utf-8") as f:
      on_disk = json.load(f)
    self.assertEqual(len(on_disk["profiles"]), 1)


if __name__ == "__main__":
  unittest.main()
