import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpilot.sunnypilot.carrot.server.services import param_changes


def read_records(path: Path):
  return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestParamChanges(unittest.TestCase):

  def setUp(self):
    tmp = tempfile.mkdtemp(prefix="param_changes_test_")
    self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    self.tmp_path = Path(tmp)
    self.log_path = self.tmp_path / "state" / "param_changes.jsonl"
    self.baseline_path = self.tmp_path / "state" / "fingerprint_baseline.json"
    for target, name, value in (
      (param_changes, "CARROT_PARAM_CHANGES_PATH", str(self.log_path)),
      (param_changes, "CARROT_FINGERPRINT_BASELINE_PATH", str(self.baseline_path)),
    ):
      patcher = mock.patch.object(target, name, value)
      patcher.start()
      self.addCleanup(patcher.stop)
    # clean_baseline fixture: drift detection cache must be isolated per test
    param_changes._known_values.clear()
    self.addCleanup(param_changes._known_values.clear)

  def test_missing_log_reads_as_empty_and_verifies_clean(self):
    self.assertEqual(param_changes.read_param_changes(), [])
    self.assertEqual(param_changes.verify_param_changes(), {
      "ok": True, "valid": True, "checked": 0, "broken_at": None, "reason": "",
    })

  def test_append_records_the_before_and_after_value(self):
    record = param_changes.append_param_change("ApplyModelSpeed", 0, -1, source="web_ui", engaged=True)

    self.assertEqual(record["name"], "ApplyModelSpeed")
    self.assertEqual(record["prev"], 0)
    self.assertEqual(record["next"], -1)
    self.assertEqual(record["source"], "web_ui")
    self.assertIs(record["engaged"], True)
    self.assertEqual(record["prev_hash"], param_changes.GENESIS_HASH)
    self.assertEqual(len(record["hash"]), 64)
    self.assertEqual(len(read_records(self.log_path)), 1)

  def test_records_link_into_a_chain(self):
    first = param_changes.append_param_change("A", 1, 2)
    second = param_changes.append_param_change("B", 3, 4)

    self.assertEqual(first["prev_hash"], param_changes.GENESIS_HASH)
    self.assertEqual(second["prev_hash"], first["hash"])
    self.assertIs(param_changes.verify_param_changes()["valid"], True)

  def test_unknown_sources_are_not_silently_accepted(self):
    self.assertEqual(param_changes.append_param_change("A", 1, 2, source="made_up")["source"], "unknown")
    self.assertEqual(param_changes.append_param_change("B", 1, 2, source="")["source"], "unknown")
    # The driving code writes params too, so this source has to be expressible.
    self.assertEqual(param_changes.append_param_change("C", 1, 2, source="device")["source"], "device")

  def test_a_nameless_change_is_rejected(self):
    self.assertIsNone(param_changes.append_param_change("", 1, 2))
    self.assertIsNone(param_changes.append_param_change("   ", 1, 2))
    self.assertEqual(param_changes.read_param_changes(), [])

  def test_history_is_newest_first_and_filterable(self):
    param_changes.append_param_change("A", 1, 2)
    param_changes.append_param_change("B", 1, 2)
    param_changes.append_param_change("A", 2, 3)

    self.assertEqual([r["name"] for r in param_changes.read_param_changes()], ["A", "B", "A"])
    self.assertEqual([r["next"] for r in param_changes.read_param_changes(name="A")], [3, 2])
    self.assertEqual(len(param_changes.read_param_changes(limit=2)), 2)

  def test_history_is_filterable_by_source(self):
    param_changes.append_param_change("A", 1, 2, source="web_ui")
    param_changes.append_param_change("B", 1, 2, source="profile")
    param_changes.append_param_change("C", 1, 2, source="profile")

    profile_changes = param_changes.read_param_changes(source="profile")
    self.assertEqual([r["name"] for r in profile_changes], ["C", "B"])
    self.assertEqual(len(param_changes.read_param_changes(source="web_ui")), 1)
    self.assertEqual(param_changes.read_param_changes(source="nope"), [])

  def test_name_and_source_filters_combine(self):
    param_changes.append_param_change("A", 1, 2, source="web_ui")
    param_changes.append_param_change("A", 2, 3, source="profile")

    narrowed = param_changes.read_param_changes(name="A", source="profile")
    self.assertEqual([r["next"] for r in narrowed], [3])

  def test_edited_content_is_detected_at_the_edited_record(self):
    param_changes.append_param_change("A", 1, 2)
    param_changes.append_param_change("B", 3, 4)
    param_changes.append_param_change("C", 5, 6)

    records = read_records(self.log_path)
    records[1]["next"] = 999
    self.log_path.write_text(
      "".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for r in records),
      encoding="utf-8",
    )

    result = param_changes.verify_param_changes()
    self.assertIs(result["valid"], False)
    self.assertEqual(result["broken_at"], 1)
    self.assertEqual(result["checked"], 1)

  def test_a_removed_record_breaks_the_chain(self):
    param_changes.append_param_change("A", 1, 2)
    param_changes.append_param_change("B", 3, 4)
    param_changes.append_param_change("C", 5, 6)

    records = read_records(self.log_path)
    del records[1]
    self.log_path.write_text(
      "".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for r in records),
      encoding="utf-8",
    )

    self.assertEqual(param_changes.verify_param_changes()["broken_at"], 1)

  def test_a_truncated_write_is_reported_rather_than_crashing(self):
    param_changes.append_param_change("A", 1, 2)
    with self.log_path.open("a", encoding="utf-8") as f:
      f.write('{"ts": 1, "name": "B", "prev"\n')

    result = param_changes.verify_param_changes()
    self.assertIs(result["valid"], False)
    self.assertEqual(result["broken_at"], 1)
    self.assertIn("JSON", result["reason"])

  def test_the_ring_keeps_the_newest_records_and_stays_verifiable(self):
    patcher = mock.patch.object(param_changes, "MAX_PARAM_CHANGE_RECORDS", 5)
    patcher.start()
    self.addCleanup(patcher.stop)
    for index in range(9):
      param_changes.append_param_change("A", index, index + 1)

    records = read_records(self.log_path)
    self.assertEqual(len(records), 5)
    self.assertEqual([r["prev"] for r in records], [4, 5, 6, 7, 8])
    # Trimming re-anchors the chain; otherwise every log would read as broken
    # forever after the first overflow.
    self.assertIs(param_changes.verify_param_changes()["valid"], True)

  def test_a_log_write_failure_never_breaks_the_setting_write(self):
    def explode(*args, **kwargs):
      raise OSError("disk full")

    patcher = mock.patch.object(param_changes.os, "makedirs", explode)
    patcher.start()
    self.addCleanup(patcher.stop)
    self.assertIsNone(param_changes.append_param_change("A", 1, 2))

  def test_fingerprint_is_stable_and_order_independent(self):
    left = param_changes.param_fingerprint({"B": 2, "A": 1})
    right = param_changes.param_fingerprint({"A": 1, "B": 2})

    self.assertEqual(left["digest"], right["digest"])
    self.assertEqual(left["fingerprint"], left["digest"][:8])
    self.assertEqual(left["count"], 2)

  def test_fingerprint_changes_when_a_single_value_changes(self):
    before = param_changes.param_fingerprint({"ApplyModelSpeed": 0})
    after = param_changes.param_fingerprint({"ApplyModelSpeed": -1})

    self.assertNotEqual(before["fingerprint"], after["fingerprint"])

  def test_fingerprint_handles_an_empty_parameter_set(self):
    self.assertEqual(param_changes.param_fingerprint({})["count"], 0)

  # --- fingerprint baseline --------------------------------------------------

  def test_no_baseline_reads_as_none(self):
    self.assertIsNone(param_changes.read_fingerprint_baseline())

  def test_a_saved_baseline_round_trips(self):
    param_changes.write_fingerprint_baseline("abc123", ts=1000)
    self.assertEqual(param_changes.read_fingerprint_baseline(), {"fingerprint": "abc123", "ts": 1000})

  def test_a_corrupt_or_empty_baseline_reads_as_none(self):
    self.baseline_path.parent.mkdir(parents=True, exist_ok=True)
    self.baseline_path.write_text("{ bad", encoding="utf-8")
    self.assertIsNone(param_changes.read_fingerprint_baseline())
    self.baseline_path.write_text('{"fingerprint": ""}', encoding="utf-8")
    self.assertIsNone(param_changes.read_fingerprint_baseline())

  # "Distinct parameters", not raw records: three presses of one setting is one.
  def test_count_changes_since_counts_distinct_parameters(self):
    param_changes.append_param_change("A", 1, 2, ts=100)
    param_changes.append_param_change("A", 2, 3, ts=150)
    param_changes.append_param_change("B", 1, 2, ts=200)
    # An older change is excluded by the timestamp cutoff.
    param_changes.append_param_change("C", 1, 2, ts=50)

    self.assertEqual(param_changes.count_changes_since(100), 2)  # A, B (not the ts=50 C)

  def test_count_changes_since_respects_the_allowed_set(self):
    param_changes.append_param_change("Real", 1, 2, ts=100)
    param_changes.append_param_change("GitPullTime", 1, 2, ts=100)
    self.assertEqual(param_changes.count_changes_since(0, allowed={"Real"}), 1)

  # --- drift detection -------------------------------------------------------
  # The driving code writes MyDrivingMode straight to Params, so those changes can
  # never reach append_param_change() on their own.

  def test_the_first_sighting_seeds_the_baseline_without_logging(self):
    self.assertEqual(param_changes.observe_param_values({"MyDrivingMode": 1, "A": 2}), 0)
    self.assertEqual(param_changes.read_param_changes(), [])

  def test_a_value_changed_outside_the_web_server_is_recorded(self):
    param_changes.observe_param_values({"MyDrivingMode": 1})
    self.assertEqual(param_changes.observe_param_values({"MyDrivingMode": 2}), 1)

    record = param_changes.read_param_changes()[0]
    self.assertEqual(record["name"], "MyDrivingMode")
    self.assertEqual(record["prev"], 1)
    self.assertEqual(record["next"], 2)
    self.assertEqual(record["source"], "device")

  def test_an_unchanged_read_records_nothing(self):
    param_changes.observe_param_values({"A": 1})
    self.assertEqual(param_changes.observe_param_values({"A": 1}), 0)
    self.assertEqual(param_changes.read_param_changes(), [])

  # Otherwise every write would be logged twice: once by us, once as "device".
  def test_our_own_write_is_not_reported_as_an_outside_change(self):
    param_changes.observe_param_values({"A": 1})
    param_changes.append_param_change("A", 1, 5, source="web_ui")

    self.assertEqual(param_changes.observe_param_values({"A": 5}), 0)
    self.assertEqual([r["source"] for r in param_changes.read_param_changes()], ["web_ui"])

  def test_several_drifted_values_are_each_recorded(self):
    param_changes.observe_param_values({"A": 1, "B": 1, "C": 1})
    self.assertEqual(param_changes.observe_param_values({"A": 2, "B": 1, "C": 3}), 2)
    self.assertEqual(sorted(r["name"] for r in param_changes.read_param_changes()), ["A", "C"])

  # GitPullTime and DeviceType change on every read and are not settings; they
  # must never reach the change history.
  def test_allowed_restricts_watching_to_real_settings(self):
    allowed = {"ApplyModelSpeed"}
    param_changes.observe_param_values({"ApplyModelSpeed": 0, "GitPullTime": 1}, allowed=allowed)
    self.assertEqual(param_changes.observe_param_values({"ApplyModelSpeed": 1, "GitPullTime": 2}, allowed=allowed), 1)

    changes = param_changes.read_param_changes()
    self.assertEqual([r["name"] for r in changes], ["ApplyModelSpeed"])

  def test_without_allowed_everything_is_watched(self):
    param_changes.observe_param_values({"A": 1, "B": 1})
    self.assertEqual(param_changes.observe_param_values({"A": 2, "B": 2}), 2)

  def test_an_unusable_payload_is_ignored(self):
    self.assertEqual(param_changes.observe_param_values(None), 0)
    self.assertEqual(param_changes.observe_param_values({}), 0)
    self.assertEqual(param_changes.observe_param_values("nope"), 0)


if __name__ == "__main__":
  unittest.main()
