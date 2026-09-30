"""Tests for the Amap API key self-test behind the settings "Test" button.

The self-test has to tell apart the failure modes users actually hit:

  * no key stored              -> never touches the network
  * key works                  -> every probed service answers ``status == "1"``
  * key rejected / restricted  -> Amap's own ``info``/``infocode`` is surfaced
                                  together with the infocode hint

It also pins that *every* endpoint the live provider calls is probed: an Amap
Web service key can be restricted to individual services, so probing a single
endpoint would report "valid" for a key that cannot deliver speed limits.
"""
import pathlib

from openpilot.common.basedir import BASEDIR
from openpilot.sunnypilot.mapd.live_map_data import amap_map_data

NAVIGATION_SRC = pathlib.Path(BASEDIR) / "openpilot/selfdrive/ui/sunnypilot/layouts/settings/navigation.py"

OK_RESULT = {"status": "1", "info": "OK", "infocode": "10000"}


def _status_lines(message: str, status: str) -> int:
  # Match the status prefix only: a passing line ends with the word OK as well.
  return sum(1 for line in message.splitlines() if line.startswith(f"{status} - "))


def _patch_http(result, calls: list | None = None):
  """Replace the module HTTP helper; returns a restore callable."""
  original = amap_map_data._http_get_json

  def fake_get(url: str, timeout: float = 5.0):
    if calls is not None:
      calls.append(url)
    return result

  amap_map_data._http_get_json = fake_get
  return lambda: setattr(amap_map_data, "_http_get_json", original)


def test_no_key_does_not_touch_the_network():
  calls: list = []
  restore = _patch_http(OK_RESULT, calls)
  try:
    ok, message = amap_map_data.check_api_key("")
  finally:
    restore()

  assert ok is False
  assert "no api key" in message.lower()
  assert calls == []


def test_blank_key_is_treated_as_missing():
  calls: list = []
  restore = _patch_http(OK_RESULT, calls)
  try:
    ok, _ = amap_map_data.check_api_key("   ")
  finally:
    restore()

  assert ok is False
  assert calls == []


def test_all_services_ok():
  restore = _patch_http(OK_RESULT)
  try:
    ok, message = amap_map_data.check_api_key("key-123")
  finally:
    restore()

  assert ok is True
  # One "OK" line per probed service (road name + speed limit).
  assert _status_lines(message, "OK") == 2
  assert _status_lines(message, "FAIL") == 0
  assert "road name" in message
  assert "speed limit" in message


def test_every_provider_endpoint_is_probed_with_the_key():
  calls: list = []
  restore = _patch_http(OK_RESULT, calls)
  try:
    amap_map_data.check_api_key("key-123")
  finally:
    restore()

  assert len(calls) == 2
  assert any(url.startswith(amap_map_data.AMAP_GEOCODE_URL) for url in calls)
  assert any(url.startswith(amap_map_data.AMAP_DIRECTION_URL) for url in calls)
  assert all("key-123" in url for url in calls)


def test_invalid_key_surfaces_api_info_and_hint():
  restore = _patch_http({"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"})
  try:
    ok, message = amap_map_data.check_api_key("bad-key")
  finally:
    restore()

  assert ok is False
  assert "INVALID_USER_KEY" in message
  assert "10001" in message
  assert amap_map_data.AMAP_INFOCODE_HINTS["10001"] in message
  assert _status_lines(message, "FAIL") == 2


def test_service_restricted_key_is_reported_per_service():
  """One working service plus one rejected service must not report success."""
  results = iter([OK_RESULT, {"status": "0", "info": "SERVICE_NOT_AVAILABLE", "infocode": "10002"}])
  original = amap_map_data._http_get_json
  amap_map_data._http_get_json = lambda url, timeout=5.0: next(results)
  try:
    ok, message = amap_map_data.check_api_key("partial-key")
  finally:
    amap_map_data._http_get_json = original

  assert ok is False
  assert _status_lines(message, "OK") == 1
  assert _status_lines(message, "FAIL") == 1
  assert "SERVICE_NOT_AVAILABLE" in message


def test_network_failure_is_reported_as_no_response():
  restore = _patch_http(None)
  try:
    ok, message = amap_map_data.check_api_key("key-123")
  finally:
    restore()

  assert ok is False
  assert "no response" in message


def test_unexpected_network_error_is_reported_not_raised():
  original = amap_map_data._http_get_json

  def boom(url: str, timeout: float = 5.0):
    raise ConnectionResetError("peer reset")

  amap_map_data._http_get_json = boom
  try:
    ok, message = amap_map_data.check_api_key("key-123")
  finally:
    amap_map_data._http_get_json = original

  assert ok is False
  assert "peer reset" in message


def test_settings_test_button_is_wired_to_the_key_check():
  """Guard: the settings button, the off-thread runner and the dialog stay wired."""
  src = NAVIGATION_SRC.read_text(encoding="utf-8")
  assert "Test Amap API Key" in src
  assert "from openpilot.sunnypilot.mapd.live_map_data.amap_map_data import check_api_key" in src
  assert "threading.Thread(target=self._run_amap_key_test, daemon=True)" in src
  assert "gui_app.push_widget(HtmlModalSP(text=" in src
