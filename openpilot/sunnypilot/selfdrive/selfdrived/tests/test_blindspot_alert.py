"""
Copyright (c) 2026-, sunnypilot and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Blind-spot audible advisory (StarPilot port): the gate function and the
selfdrived wiring contract. All inputs are stubs; no messaging is needed.
"""
import sys
import types
from types import SimpleNamespace as NS

# common.params → swaglog → common.hardware → gpio imports fcntl at module load. It is only
# *used* from hardware functions never called here, so on PC a bare module keeps the import
# chain alive. Must run before the imports below.
try:
  import fcntl  # noqa: F401
except ImportError:
  sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))

# common.params loads libparams_c.so via ctypes at import time; no Windows build exists.
# AlertManager only needs the symbol for typing - it never instantiates Params here.
try:
  from openpilot.common.params import Params  # noqa: F401
except (OSError, FileNotFoundError):
  _params_mod = types.ModuleType('openpilot.common.params')

  class _ParamsStub:
    def __init__(self, *args, **kwargs):
      raise RuntimeError("real Params is unavailable on PC")

  _params_mod.Params = _ParamsStub
  sys.modules['openpilot.common.params'] = _params_mod

# The PC msgq shim is Python-2 syntax (octal literals), so anything importing
# openpilot.cereal.messaging transitively must be stubbed, not imported.
_msgq = types.ModuleType('msgq')
for _n in ('fake_event_handle', 'drain_sock_raw', 'MultiplePublishersError', 'IpcError',
           'Context', 'Poller', 'SubSocket', 'PubSocket', 'SocketEventHandle',
           'toggle_fake_events', 'set_fake_prefix', 'get_fake_prefix',
           'delete_fake_prefix', 'wait_for_one_event'):
  setattr(_msgq, _n, type(_n, (Exception,), {}) if 'Error' in _n else (lambda *a, **k: None))
sys.modules['msgq'] = _msgq

_messaging = types.ModuleType('openpilot.cereal.messaging')
for _n in ('SubMaster', 'PubMaster', 'new_message', 'log_from_bytes', 'drain_sock_raw',
           'sub_sock', 'pub_sock'):
  setattr(_messaging, _n, lambda *a, **k: None)
sys.modules['openpilot.cereal.messaging'] = _messaging

from openpilot.selfdrive.selfdrived.alertmanager import AlertManager
from openpilot.sunnypilot.selfdrive.selfdrived.blindspot_alert import (
  ALERT_TYPE,
  CAR_STATE_MAX_AGE_NS,
  KEYS,
  blindspot_alert,
)
from openpilot.sunnypilot.selfdrive.selfdrived.events import EVENTS_SP
from openpilot.sunnypilot.selfdrive.selfdrived.events_base import ET, AudibleAlert, Priority

NOW = 10_000_000_000


class Messages(dict):
  def __init__(self, active=False, healthy=True):
    super().__init__(deviceState=NS(started=True), carControl=NS(latActive=active))
    self.logMonoTime = dict.fromkeys(('deviceState', 'carControl'), NOW - 10_000_000)
    self.healthy = healthy

  def all_checks(self, _services):
    return self.healthy


def car(**kw):
  return NS(**({'leftBlinker': True, 'rightBlinker': False, 'leftBlindspot': True, 'rightBlindspot': False,
               'canValid': True, 'canTimeout': False, 'vEgo': 8.0, 'standstill': False} | kw))


def alert(loud=False, without_lateral=True, mute=False, lane_change_blocked=False, cs=None, sm=None):
  return blindspot_alert(car(**(cs or {})), sm or Messages(), loud=loud, without_lateral=without_lateral,
                         lane_change_blocked=lane_change_blocked, mute_at_standstill=mute,
                         now_ns=NOW, car_ns=NOW - 10_000_000)


class TestGate:
  def test_signal_with_param_on_alerts(self):
    got = alert()
    assert got is not None
    assert got.alert_type == ALERT_TYPE
    assert got.audible_alert == AudibleAlert.warningSoft
    assert got.priority == Priority.LOW

  def test_params_off_never_alerts(self):
    assert alert(loud=False, without_lateral=False) is None
    # loud alone needs an actually blocked lane change
    assert alert(loud=True, without_lateral=False, lane_change_blocked=False) is None

  def test_no_signal_or_wrong_side_never_alerts(self):
    assert alert(cs={'leftBlindspot': False}) is None
    assert alert(cs={'leftBlinker': False, 'rightBlinker': True, 'rightBlindspot': False}) is None
    # signal on one side, car detected on the other
    assert alert(cs={'leftBlinker': False, 'rightBlinker': True, 'rightBlindspot': False}) is None

  def test_loud_path_is_independent_of_blinkers(self):
    # StarPilot semantics: the loud advisory keys off the blocked lane change,
    # not off the driver's own signal
    got = alert(loud=True, without_lateral=False, lane_change_blocked=True, cs={'leftBlinker': False, 'leftBlindspot': False})
    assert got is not None

  def test_standstill_mute_only_applies_without_lateral_when_enabled(self):
    for cs in ({'standstill': True}, {'vEgo': 0.49}):
      assert alert(cs=cs) is not None
      assert alert(cs=cs, mute=True) is None
      # the loud blocked-lane-change advisory is never muted at standstill
      assert alert(loud=True, without_lateral=False, lane_change_blocked=True, cs=cs, mute=True) is not None

  def test_engaged_lateral_suppresses_disengaged_advisory(self):
    assert alert(sm=Messages(active=True)) is None

  def test_stale_or_invalid_inputs_stay_silent(self):
    cases = [
      {'now_ns': NOW, 'car_ns': 0},                       # no carState at all
      {'now_ns': NOW, 'car_ns': NOW + 1},                 # carState from the future
      {'now_ns': NOW, 'car_ns': NOW - CAR_STATE_MAX_AGE_NS - 1},  # carState older than 200 ms
      {'now_ns': 1, 'car_ns': NOW - 10_000_000},          # clock behind every stamp
    ]
    for kw in cases:
      assert blindspot_alert(car(), Messages(), loud=False, without_lateral=True,
                             lane_change_blocked=False, **kw) is None

    stale = Messages()
    stale.logMonoTime['deviceState'] = NOW - 2_500_000_000
    assert blindspot_alert(car(), stale, loud=False, without_lateral=True,
                           lane_change_blocked=False, now_ns=NOW, car_ns=NOW - 10_000_000) is None
    fresh_but_unhealthy = Messages(healthy=False)
    assert blindspot_alert(car(), fresh_but_unhealthy, loud=False, without_lateral=True,
                           lane_change_blocked=False, now_ns=NOW, car_ns=NOW - 10_000_000) is None
    parked = Messages()
    parked['deviceState'].started = False
    assert blindspot_alert(car(), parked, loud=False, without_lateral=True,
                           lane_change_blocked=False, now_ns=NOW, car_ns=NOW - 10_000_000) is None
    for cs in ({'canValid': False}, {'canTimeout': True}):
      assert alert(cs=cs) is None

  def test_missing_fields_degrade_to_silence(self):
    # a car platform whose carState lacks the BSD fields entirely (default-False
    # in capnp, but a stub here): the advisory must stay silent, not crash
    bare = NS(canValid=True, canTimeout=False)
    assert blindspot_alert(bare, Messages(), loud=False, without_lateral=True,
                           lane_change_blocked=False, now_ns=NOW, car_ns=NOW - 10_000_000) is None


class TestWiringContract:
  def test_params_are_declared_and_panel_visible(self):
    import ast
    import os
    here = os.path.dirname(__file__)
    with open(os.path.join(here, '../../../../common/params_keys.h'), encoding='utf-8') as f:
      declared = f.read()
    for key in KEYS:
      assert f'"{key}"' in declared
    # _DEFAULT_NAV_PARAMS from carrot/config.py without importing it: the module
    # instantiates Params() at import time, which cannot load on a PC host
    # (same reason audit_param_consistency.py parses it)
    with open(os.path.join(here, '../../../carrot/config.py'), encoding='utf-8') as f:
      tree = ast.parse(f.read())
    nav_params = None
    for node in ast.walk(tree):
      if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(getattr(t, 'id', '') == '_DEFAULT_NAV_PARAMS' for t in targets):
          nav_params = {k.value: ast.literal_eval(v) for k, v in zip(node.value.keys, node.value.values, strict=True)}
    assert nav_params is not None
    for key in KEYS:
      assert key in nav_params and nav_params[key] == 0
    from openpilot.sunnypilot.carrot.tools.sp_param_labels import PARAM_LABELS
    for key in KEYS:
      assert len(PARAM_LABELS[key]) == 4 and PARAM_LABELS[key][2]  # zh title present

  def test_existing_chime_alerts_are_untouched(self):
    # the advisory is injected, not mapped, so neither the e2e chime family
    # (green light / lead depart) nor the upstream blocked-lane-change alert
    # may change shape
    from openpilot.cereal import custom
    e2e = EVENTS_SP[custom.OnroadEventSP.EventName.e2eChime]
    assert e2e[ET.PERMANENT].audible_alert == AudibleAlert.prompt
    assert e2e[ET.PERMANENT].priority == Priority.MID

  def test_advisory_survives_warning_filter_but_never_masks_takeover(self):
    from openpilot.selfdrive.selfdrived.alertmanager import AlertEntry
    got = alert()
    manager = AlertManager()
    manager.add_many(1, [got])
    manager.process_alerts(1, {ET.WARNING})
    assert manager.current_alert.alert_type == ALERT_TYPE
    takeover = NS(alert_text_1='Take Control', alert_text_2='', priority=Priority.HIGHEST,
                  start_frame=1, alert_type='takeover', event_type='immediateDisable')
    manager.alerts['takeover'] = AlertEntry(alert=takeover, start_frame=1, end_frame=10_000, added_frame=1)
    manager.process_alerts(2, set())
    assert manager.current_alert.alert_type == 'takeover'
