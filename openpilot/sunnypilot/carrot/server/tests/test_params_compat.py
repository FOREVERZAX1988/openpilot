import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpilot.sunnypilot.carrot import carrot_navi
from openpilot.sunnypilot.carrot.server.services import params as params_service


class FakeUnknownKeyName(Exception):
  pass


class StaleParams:
  def __init__(self, root: Path) -> None:
    self.root = root

  def get_type(self, key: str):
    raise FakeUnknownKeyName(key)

  def get(self, key: str):
    raise FakeUnknownKeyName(key)

  def get_int(self, key: str):
    raise FakeUnknownKeyName(key)

  def put(self, key: str, value):
    raise FakeUnknownKeyName(key)

  def put_int(self, key: str, value: int):
    raise FakeUnknownKeyName(key)

  def get_param_path(self, key: str = "") -> str:
    return str(self.root / key) if key else str(self.root)


def int_setting(default: int = 0) -> dict:
  return {"min": 0, "max": 60, "default": default}


class TestParamsCompat(unittest.TestCase):

  def setUp(self):
    tmp = tempfile.mkdtemp(prefix="params_compat_test_")
    self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    self.tmp_path = Path(tmp)

  def patch(self, target, name, value):
    patcher = mock.patch.object(target, name, value)
    patcher.start()
    self.addCleanup(patcher.stop)

  def test_unregistered_json_setting_uses_atomic_file_fallback(self):
    stale_params = StaleParams(self.tmp_path)
    self.patch(params_service, "HAS_PARAMS", True)
    self.patch(params_service, "Params", lambda: stale_params)
    self.patch(params_service, "UnknownKeyName", FakeUnknownKeyName)

    params_service.set_param_value("FutureIntSetting", 42, int_setting())

    self.assertEqual((self.tmp_path / "FutureIntSetting").read_text(encoding="utf-8"), "42")
    self.assertEqual(params_service._read_param_value(stale_params, "FutureIntSetting", 0), 42)

  def test_unregistered_fallback_rejects_names_outside_settings(self):
    stale_params = StaleParams(self.tmp_path)
    self.patch(params_service, "HAS_PARAMS", True)
    self.patch(params_service, "Params", lambda: stale_params)
    self.patch(params_service, "UnknownKeyName", FakeUnknownKeyName)

    with self.assertRaises(FakeUnknownKeyName):
      params_service.set_param_value("NotInCarrotSettings", 1)

  def test_unregistered_read_fallback_rejects_path_traversal(self):
    stale_params = StaleParams(self.tmp_path)
    outside = self.tmp_path.parent / f"{self.tmp_path.name}_outside"
    outside.write_text("123", encoding="utf-8")

    try:
      self.assertEqual(params_service._read_param_value(stale_params, f"../{outside.name}", 0), 0)
    finally:
      outside.unlink(missing_ok=True)

  def test_unregistered_fallback_does_not_hide_other_write_failures(self):
    class BrokenParams(StaleParams):
      def put_int(self, key: str, value: int):
        raise OSError("disk full")

    broken_params = BrokenParams(self.tmp_path)
    self.patch(params_service, "HAS_PARAMS", True)
    self.patch(params_service, "Params", lambda: broken_params)
    self.patch(params_service, "UnknownKeyName", FakeUnknownKeyName)

    with self.assertRaisesRegex(OSError, "disk full"):
      params_service.set_param_value("FutureIntSetting", 1, int_setting())

  def test_web_params_cannot_write_internal_driver_monitoring_session_state(self):
    with self.assertRaisesRegex(ValueError, "controlled internally"):
      params_service.set_param_value("DriverMonitoringSessionDisabled", True, {"min": 0, "max": 1, "default": 0})

  def test_driver_monitoring_disable_clears_uncertain_alert_only_offroad(self):
    for enabled, is_onroad, clears_alert in (
      (False, False, True), (False, True, False), (True, False, False),
    ):
      with self.subTest(enabled=enabled, is_onroad=is_onroad, clears_alert=clears_alert):
        tc = self

        def make_fake_params(tc=tc, enabled=enabled, is_onroad=is_onroad):
          class FakeParams:
            def __init__(self):
              self.removed = []

            def get_bool(self, key: str) -> bool:
              tc.assertEqual(key, "IsOnroad")
              return is_onroad

            def put_bool(self, key: str, value: bool) -> None:
              tc.assertEqual((key, value), ("DriverMonitoringEnabled", enabled))

            def remove(self, key: str) -> None:
              self.removed.append(key)

          return FakeParams()

        fake_params = make_fake_params()
        self.patch(params_service, "HAS_PARAMS", True)
        self.patch(params_service, "Params", lambda fp=fake_params: fp)
        self.patch(params_service, "ParamKeyType", None)

        params_service.set_param_value(
          "DriverMonitoringEnabled",
          enabled,
          {"min": 0, "max": 1, "default": 1},
        )

        self.assertEqual(fake_params.removed, ["Offroad_DriverMonitoringUncertain"] if clears_alert else [])

  def test_failed_driver_monitoring_disable_does_not_clear_uncertain_alert(self):
    class BrokenParams:
      removed = []

      def put_bool(self, key: str, value: bool) -> None:
        raise OSError("disk full")

      def remove(self, key: str) -> None:
        self.removed.append(key)

    broken_params = BrokenParams()
    self.patch(params_service, "HAS_PARAMS", True)
    self.patch(params_service, "Params", lambda: broken_params)
    self.patch(params_service, "ParamKeyType", None)

    with self.assertRaisesRegex(OSError, "disk full"):
      params_service.set_param_value(
        "DriverMonitoringEnabled",
        False,
        {"min": 0, "max": 1, "default": 1},
      )

    self.assertEqual(broken_params.removed, [])

  def test_restore_rejects_internal_driver_monitoring_session_state(self):
    # The internal-key branch does not need a native Params registry, but the
    # preview API performs its environment check before iterating entries.
    self.patch(params_service, "HAS_PARAMS", True)
    self.patch(params_service, "ParamKeyType", object())
    self.patch(params_service, "Params", object)
    self.patch(params_service, "get_param_values", lambda names, defaults: {})

    preview = params_service.preview_param_restore_values({"DriverMonitoringSessionDisabled": True})
    self.assertEqual(preview["summary"], {"changed": 0, "same": 0, "skipped": 0, "invalid": 1, "selected": 0})
    self.assertEqual(preview["entries"][0]["reason"], "controlled internally")
    self.assertFalse(preview["entries"][0]["apply"])

    restored = params_service.restore_param_values_validated({"DriverMonitoringSessionDisabled": True})
    self.assertEqual(restored["result"], {"ok_cnt": 0, "fail_cnt": 0, "fails": []})

  def test_driver_monitoring_enabled_is_excluded_from_file_and_qr_backups(self):
    class FakeParamKeyType:
      BOOL = "bool"
      INT = "int"
      FLOAT = "float"
      TIME = "time"
      STRING = "string"
      JSON = "json"
      BYTES = "bytes"

    class BackupParams:
      def all_keys(self):
        return ["DriverMonitoringEnabled", "DriverMonitoringMode", "CarrotVisionEnabled"]

      def get_type(self, key):
        return FakeParamKeyType.INT if key == "DriverMonitoringMode" else FakeParamKeyType.BOOL

      def get_default_value(self, key):
        return "0" if key == "DriverMonitoringMode" else "1"

      def get(self, key, **_kwargs):
        return {
          "DriverMonitoringEnabled": "0",
          "DriverMonitoringMode": "1",
          "CarrotVisionEnabled": "1",
        }[key]

    self.patch(params_service, "HAS_PARAMS", True)
    self.patch(params_service, "ParamKeyType", FakeParamKeyType)
    self.patch(params_service, "Params", BackupParams)

    self.assertEqual(params_service.get_all_param_values_for_backup(), {
      "DriverMonitoringMode": "1",
      "CarrotVisionEnabled": "1",
    })
    # Keep the existing QR schema so older QR codes still decode the key and the
    # restore filter can safely ignore its value.
    self.assertEqual(params_service._backup_param_names(), [
      "DriverMonitoringEnabled",
      "DriverMonitoringMode",
      "CarrotVisionEnabled",
    ])

    qr = params_service.build_params_qr_payload({
      "DriverMonitoringEnabled": "0",
      "DriverMonitoringSessionDisabled": "1",
      "DriverMonitoringMode": "1",
      "CarrotVisionEnabled": "1",
    })
    self.assertEqual(qr["count"], 2)
    self.assertEqual(params_service.parse_params_qr_payload(qr["payload"]), {
      "DriverMonitoringMode": "1",
      "CarrotVisionEnabled": "1",
    })

    # Simulate a QR made before the exclusion policy. The stable schema still
    # decodes the key, but restore refuses to apply it even when selected.
    old_qr = params_service._build_params_qr_payload_v4({
      "DriverMonitoringEnabled": "0",
      "DriverMonitoringMode": "1",
    })
    old_values = params_service.parse_params_qr_payload(old_qr["payload"])
    self.assertEqual(old_values, {
      "DriverMonitoringEnabled": "0",
      "DriverMonitoringMode": "1",
    })
    self.patch(params_service, "get_param_values", lambda names, defaults: {
      "DriverMonitoringEnabled": True,
      "DriverMonitoringMode": 0,
    })
    restored = params_service.restore_param_values_validated(
      old_values,
      selected_keys=["DriverMonitoringEnabled"],
    )
    entries = {entry["key"]: entry for entry in restored["preview"]["entries"]}
    self.assertEqual(entries["DriverMonitoringEnabled"]["reason"], "excluded from backup restore")
    self.assertFalse(entries["DriverMonitoringEnabled"]["apply"])
    self.assertEqual(restored["result"], {"ok_cnt": 0, "fail_cnt": 0, "fails": []})

  def test_driver_monitoring_enabled_from_old_backup_is_not_restored(self):
    self.patch(params_service, "HAS_PARAMS", True)
    self.patch(params_service, "ParamKeyType", object())
    self.patch(params_service, "Params", object)
    self.patch(params_service, "get_param_values", lambda names, defaults: {})

    preview = params_service.preview_param_restore_values(
      {"DriverMonitoringEnabled": "0"},
      selected_keys=["DriverMonitoringEnabled"],
    )
    self.assertEqual(preview["summary"], {"changed": 0, "same": 0, "skipped": 1, "invalid": 0, "selected": 0})
    self.assertEqual(preview["entries"][0]["reason"], "excluded from backup restore")
    self.assertFalse(preview["entries"][0]["apply"])

    restored = params_service.restore_param_values_from_backup({"DriverMonitoringEnabled": "0"})
    self.assertEqual(restored, {"ok_cnt": 0, "fail_cnt": 0, "fails": []})

  def test_reset_defaults_restores_driver_monitoring_enabled_to_on(self):
    class FakeParamKeyType:
      BOOL = "bool"
      INT = "int"
      FLOAT = "float"
      TIME = "time"
      STRING = "string"
      JSON = "json"
      BYTES = "bytes"

    writes = []
    tc = self

    class RestoreParams:
      def get_type(self, key):
        tc.assertEqual(key, "DriverMonitoringEnabled")
        return FakeParamKeyType.BOOL

      def get_bool(self, key):
        tc.assertEqual(key, "DriverMonitoringEnabled")
        return False

    self.patch(params_service, "HAS_PARAMS", True)
    self.patch(params_service, "ParamKeyType", FakeParamKeyType)
    self.patch(params_service, "Params", RestoreParams)
    self.patch(params_service, "_catalog_definitions", dict)
    self.patch(params_service, "get_param_values", lambda names, defaults: {"DriverMonitoringEnabled": False})
    self.patch(params_service, "set_param_value", lambda key, value, definition=None: writes.append((key, value)))

    restored = params_service.restore_param_values_validated(
      {"DriverMonitoringEnabled": "1"},
      source="reset_defaults",
    )

    self.assertEqual(restored["preview"]["summary"], {
      "changed": 1,
      "same": 0,
      "skipped": 0,
      "invalid": 0,
      "selected": 1,
    })
    self.assertIs(restored["preview"]["entries"][0]["value"], True)
    self.assertEqual(restored["result"], {"ok_cnt": 1, "fail_cnt": 0, "fails": []})
    self.assertEqual(writes, [("DriverMonitoringEnabled", True)])

  def test_old_params_backup_file_is_filtered_before_download(self):
    backup_path = self.tmp_path / "params_backup.json"
    backup_path.write_text(json.dumps({
      "DriverMonitoringEnabled": "0",
      "DriverMonitoringSessionDisabled": "1",
      "DriverMonitoringMode": "1",
    }), encoding="utf-8")
    self.assertEqual(params_service.read_param_backup_values(str(backup_path)), {"DriverMonitoringMode": "1"})

  def test_map_param_reader_reads_map_fps_file_while_native_registry_is_stale(self):
    stale_params = StaleParams(self.tmp_path)
    (self.tmp_path / "ClusterNaviMapFps").write_text("3", encoding="utf-8")

    reader = carrot_navi.ClusterNaviMapParamReader(stale_params)

    self.assertEqual(reader._read_int("ClusterNaviMapFps", 1), 3)


if __name__ == "__main__":
  unittest.main()
