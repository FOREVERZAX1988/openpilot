"""TeslaTurnSignals 灯控会话核心生命周期测试（sp 适配版）。

cp 同名测试在 selfdrive/car/tests/test_tesla_turn_signals.py（pytest，965 行）。本
文件把其中不依赖设备环境的用例 1:1 移植为 unittest（断言逐条保留，parametrize →
subTest，pytest.raises → assertRaises）：

- helper（template/state/intent/feedback/echo/opened/cancelling/channel_frame）与 cp
  逐行对应；intent 用鸭子 meta（NS(raw=…)/str desire）替代 capnp meta——字段语义一致。
- CAN 灯反馈帧用真实 CANPacker（tesla_model3_party / tesla_model3_vehicle DBC）。

未适配项（如实记录，均为 sp 未移植的车端依赖，非语义裁剪）：
- cp test_driver_takes_ownership_without_cancelling_manual_lamp、
  test_sustained_requests_use_fresh_counters_echo_and_real_c_safety、
  test_native_panda_template_race_is_rejected_and_never_retried_as_active：依赖
  opendbc libsafety（panda C safety 钩子），PC/Windows 环境无编译产物。
- cp test_real_capnp_inputs_and_can_serialization、test_schema_defaults：依赖
  openpilot.cereal capnp 绑定（本环境 pycapnp 加载 log.capnp 崩溃）。
- cp test_detected_extension_and_real_can1_stalk_reach_lamp_sender：依赖 cp 的
  opendbc tesla carstate 改造（stalk 解码），sp 未移植（card.py 待办，见交接报告）。
"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

# PC/CI 兜底：opendbc 通常由 scons/launcher 注入 sys.path；直接跑 unittest 时补上。
_REPO = Path(__file__).parents[4]
for _p in (_REPO / 'opendbc_repo',):
  if _p.is_dir() and str(_p) not in sys.path:
    sys.path.insert(0, str(_p))

from opendbc.can import CANPacker
from opendbc.car.tesla.values import CAR, TeslaFlags, TeslaSafetyFlags
from openpilot.selfdrive.car.tesla_turn_signals import (
  BODY, CANCEL_NS, CONTEXT_NS, FEEDBACK_DEGRADED_NS, FRONT, FRONT_FAULT_GRACE_NS, SESSION_NS, UI,
  TeslaTurnSignals, body_checksum, body_frame,
)

N = 10_000_000_000


def template(counter=4):
  data = bytearray.fromhex("a58c61b45ac34700")
  data[6] = (counter << 4) | 7
  data[7] = body_checksum(data)
  return bytes(data)


def state(**kwargs):
  values = {"leftBlinkerStalkCount": 0, "rightBlinkerStalkCount": 0, "turnSignalDriverValid": True,
            "turnSignalDriverDirection": 0, "canValid": True, "vehicleSensorsInvalid": False, "gearShifter": "drive"}
  return NS(**(values | kwargs))


def intent(direction=1, request=1, turn=False):
  # cp 用 capnp meta；等价鸭子对象：autoTurnSignalDirection.raw + autoTurnSignalRequestId + desire。
  return NS(autoTurnSignalDirection=NS(raw=direction), autoTurnSignalRequestId=request,
            desire=("turnLeft" if direction == 1 else "turnRight") if turn else "none")


def feedback(c, now, ui=(0, 0), front=(0, 0), body=True):
  p = CANPacker("tesla_model3_party")
  v = CANPacker("tesla_model3_vehicle")
  frames = [p.make_can_msg("UI_warning", 0, {"leftBlinkerBlinking": ui[0], "rightBlinkerBlinking": ui[1]}),
            v.make_can_msg("ID3F5VCFRONT_lighting", 1,
                           {"VCFRONT_turnSignalLeftStatus": front[0], "VCFRONT_turnSignalRightStatus": front[1]})]
  if body:
    frames.append((BODY, template(), 1))
  c.observe([(now, frames)], now)


def update(c, now=N, direction=1, request=1, fresh=True, cs=None, active=True, turn=False, hold=False):
  return c.update(cs or state(), NS(latActive=active), intent(direction, request, turn), fresh, now, turn_hold_allowed=hold)


def echo(c, frame, now, source=0x81):
  c.observe([(now, [(frame.address, frame.dat, source)])], now)


def opened(direction=1, turn=False):
  c = TeslaTurnSignals(True)
  feedback(c, N)
  frame = update(c, direction=direction, turn=turn)[0]
  echo(c, frame, N + 1)
  feedback(c, N + 2, ui=(2, 0) if direction == 1 else (0, 2),
           front=(1, 0) if direction == 1 else (0, 1))
  assert c.session.on_seen
  return c


def channel_frame(channel, direction=1, lit=True, fault=False):
  if channel == UI:
    values = [0, 0]
    values[direction - 1] = 3 if fault else 2 if lit else 1
    return CANPacker("tesla_model3_party").make_can_msg(
      "UI_warning", 0, {"leftBlinkerBlinking": values[0], "rightBlinkerBlinking": values[1]})
  values = [0, 0]
  values[direction - 1] = 2 if fault else int(lit)
  return CANPacker("tesla_model3_vehicle").make_can_msg(
    "ID3F5VCFRONT_lighting", 1, {"VCFRONT_turnSignalLeftStatus": values[0], "VCFRONT_turnSignalRightStatus": values[1]})


def cancelling(direction=1):
  c = opened(direction)
  sent = update(c, N + 3, direction=0)[0]
  assert sent.dat[1] & 3 == 3
  echo(c, sent, N + 4)
  return c


def car_params(flags=None, safety_param=None, **kwargs):
  values = {
    "brand": "tesla", "carFingerprint": CAR.TESLA_MODEL_3, "passive": False,
    "flags": (TeslaFlags.HAS_VEHICLE_BUS | TeslaFlags.AUTO_TURN_SIGNALS) if flags is None else flags,
    "safetyConfigs": [NS(safetyModel="tesla",
                         safetyParam=(TeslaSafetyFlags.AUTO_TURN_SIGNALS if safety_param is None else safety_param))],
  }
  values.update(kwargs)
  return NS(**values)


class TestTeslaTurnSignals(unittest.TestCase):

  def test_stopped_hold_is_only_for_an_existing_confirmed_turn(self):
    for direction in (1, 2):
      for gate in ["", "lane", "unlit", "no_echo", "moving", "nan", "not_stopped", "permission", "stale", "new_id"]:
        with self.subTest(direction=direction, gate=gate):
          c = opened(direction, turn=gate != "lane")
          if gate == "unlit":
            c.session.on_seen = False
          elif gate == "no_echo":
            c.session.active_echoes = 0
          now = N + 50_000_000
          feedback(c, now, ui=(2, 0) if direction == 1 else (0, 2), front=(1, 0) if direction == 1 else (0, 1))
          if gate == "unlit":
            c.session.on_seen = False
          cs = state(vEgo=float("nan") if gate == "nan" else 1. if gate == "moving" else 0., standstill=gate != "not_stopped")
          sends = update(c, now, direction, request=2 if gate == "new_id" else 1, fresh=gate != "stale",
                         cs=cs, active=False, hold=gate != "permission", turn=True)
          self.assertEqual(c.session.cancelling, bool(gate))
          self.assertEqual([send.dat[1] & 3 for send in sends], [3 if gate else direction])
          # A lane session cannot be relabelled into a turn by a later model message.
          self.assertEqual(c.session.turn, gate != "lane")

  def test_stopped_permission_never_initiates_a_new_turn(self):
    for direction in (1, 2):
      with self.subTest(direction=direction):
        c = TeslaTurnSignals(True)
        feedback(c, N)
        self.assertFalse(update(c, direction=direction, cs=state(vEgo=0., standstill=True), active=False, hold=True, turn=True))
        self.assertIsNone(c.session)
        self.assertEqual(c.status, "blocked:lateral_inactive")

  def test_recorded_front_two_one_waveform_does_not_cancel_or_falsely_confirm_light(self):
    for direction in (1, 2):
      with self.subTest(direction=direction):
        c = TeslaTurnSignals(True)
        feedback(c, N)
        sent = update(c, direction=direction)[0]
        echo(c, sent, N + 1)
        active_count = 1
        for tick in range(1, 41):
          now = N + tick * 50_000_000
          phase = 2 if (tick - 1) % 14 < 7 else 1
          raw = bytes.fromhex(("0200c838820d0800" if phase == 2 else "0100c838820d0400") if direction == 1 else
                              ("0800c838820c2000" if phase == 2 else "0400c838820c1000"))
          c.observe([(now, [channel_frame(UI, direction), (FRONT, raw, 1)])], now)
          self.assertFalse(c.session.cancelling)
          if tick < 8:
            self.assertFalse(c.session.on_seen)
            self.assertEqual(c.ready_request_id(now), 0)
          else:
            self.assertEqual(c.ready_request_id(now), 1)
          if tick % 10 == 0:
            c.observe([(now, [(BODY, template(tick % 16), 1)])], now)
          for sent in update(c, now, direction=direction):
            self.assertEqual(sent.dat[1] & 3, direction)
            echo(c, sent, now + 1)
            active_count += 1
        self.assertEqual(active_count, 5)
        self.assertTrue(c.session.on_seen)

  def test_front_two_persistent_fault_has_fixed_deadline_not_renewed_by_more_frames(self):
    for direction in (1, 2):
      for on_seen in (False, True):
        with self.subTest(direction=direction, on_seen=on_seen):
          c = opened(direction) if on_seen else TeslaTurnSignals(True)
          if not on_seen:
            feedback(c, N)
            echo(c, update(c, direction=direction)[0], N + 1)
          start = N + 50_000_000
          for tick in range(12):
            now = start + tick * 50_000_000
            feedback(c, now, ui=(2, 0) if direction == 1 else (0, 2),
                     front=(2, 0) if direction == 1 else (0, 2))
            if tick < 10:
              self.assertFalse(c.session.cancelling)
            else:
              self.assertEqual(c.status, "cancelling:invalid_lamp_feedback")
              self.assertEqual(c.ready_request_id(now), 0)
            for sent in update(c, now, direction=direction):
              self.assertEqual(sent.dat[1] & 3, direction if tick < 10 else 3)
              echo(c, sent, now + 1)
          self.assertEqual(c.blocked_id, 1)

  def test_front_two_deadline_checked_before_recovery_frame_can_clear_it(self):
    for direction in (1, 2):
      for late in (False, True):
        with self.subTest(direction=direction, late=late):
          c = opened(direction)
          start = N + 50_000_000
          feedback(c, start, ui=(2, 0) if direction == 1 else (0, 2),
                   front=(2, 0) if direction == 1 else (0, 2), body=False)
          now = start + FRONT_FAULT_GRACE_NS - int(not late)
          c.context_time = now
          feedback(c, now, ui=(2, 0) if direction == 1 else (0, 2),
                   front=(1, 0) if direction == 1 else (0, 1), body=False)
          self.assertEqual(c.session.cancelling, late)
          self.assertEqual(c.ready_request_id(now), 0 if late else 1)

  def test_front_two_fault_deadline_runs_without_another_front_frame(self):
    c = opened()
    start = N + 50_000_000
    feedback(c, start, ui=(2, 0), front=(2, 0), body=False)
    now = start
    for tick in range(1, 11):
      now = start + tick * 50_000_000
      c.context_time = now
      c.observe([(now, [channel_frame(UI)])], now)
    self.assertEqual(c.status, "cancelling:invalid_lamp_feedback")
    self.assertEqual(c.ready_request_id(now), 0)

  def test_transient_two_never_renews_physical_on_or_confirms_cancellation(self):
    c = opened()
    last_on = c.session.last_front_on
    feedback(c, N + 50_000_000, ui=(2, 0), front=(2, 0), body=False)
    self.assertEqual(c.session.last_front_on, last_on)
    self.assertFalse(c._off(N + 50_000_000))
    cancel = update(c, N + 50_000_001, direction=0)[0]
    echo(c, cancel, N + 50_000_002)
    for tick in range(2, 20):
      now = N + tick * 50_000_000
      feedback(c, now, front=(2, 0), body=False)
      self.assertIsNotNone(c.session)
      self.assertNotEqual(c.status, "cancelled")

  def test_opposite_front_two_is_not_ignored_and_cannot_extend_its_deadline(self):
    c = opened()
    for tick in range(12):
      now = N + 50_000_000 + tick * 50_000_000
      feedback(c, now, ui=(2, 0), front=(1, 2))
      sends = update(c, now)
      for sent in sends:
        echo(c, sent, now + 1)
      self.assertEqual(c.session.cancelling, tick >= 10)
    self.assertEqual(c.status, "cancelling:invalid_lamp_feedback")

  def test_confirmed_session_bridges_periodic_single_channel_gaps_with_continued_sends(self):
    for direction in (1, 2):
      for slow in (UI, FRONT):
        with self.subTest(direction=direction, slow=slow):
          c = opened(direction)
          phases = set()
          sent_count = 0
          for tick in range(1, 51):
            now = N + tick * 100_000_000
            frames = [channel_frame(FRONT if slow == UI else UI, direction, lit=tick % 8 < 4)]
            if tick % 10 == 1:
              frames.append(channel_frame(slow, direction, lit=tick % 8 < 4))
            frames.append((BODY, template(tick % 16), 1))
            c.observe([(now, frames)], now)
            sends = update(c, now, direction=direction)
            self.assertEqual(len(sends), 1)
            self.assertEqual(sends[0].dat[1] & 3, direction)
            echo(c, sends[0], now + 1)
            phases.add(c.diagnostics(now + 1)["feedback"])
            sent_count += 1
            self.assertEqual(c.status, "active")
            self.assertFalse(c.session.cancelling)
          self.assertEqual(sent_count, 50)
          self.assertEqual(phases, {"fresh", "degraded"})

  def test_total_or_extended_single_channel_failure_is_terminal_even_after_feedback_recovers(self):
    for remaining in (None, UI, FRONT):
      with self.subTest(remaining=remaining):
        c = opened()
        cancelled = False
        now = N
        for tick in range(1, 19):
          now = N + tick * 100_000_000
          frames = [(BODY, template(tick % 16), 1)]
          if remaining:
            frames.append(channel_frame(remaining))
          c.observe([(now, frames)], now)
          for sent in update(c, now):
            cancelled |= sent.dat[1] & 3 == 3
            if tick <= (5 if remaining is None else 15):
              self.assertEqual(sent.dat[1] & 3, 1)
            else:
              self.assertEqual(sent.dat[1] & 3, 3)
            echo(c, sent, now + 1)
        self.assertTrue(cancelled)
        self.assertEqual(c.status, "cancelling:feedback_stale")
        self.assertEqual(c.blocked_id, 1)
        self.assertEqual(FEEDBACK_DEGRADED_NS, 1_500_000_000)
        for tick in range(19, 40):
          now = N + tick * 100_000_000
          feedback(c, now)
          self.assertFalse(update(c, now))
        self.assertIsNone(c.session)
        self.assertFalse(update(c, now + 1))

  def test_sna_on_only_fresh_channel_cancels_immediately(self):
    for channel in (UI, FRONT):
      with self.subTest(channel=channel):
        c = opened()
        now = N + 600_000_000
        c.context_time = now
        frame = channel_frame(channel, fault=True) if channel == UI else CANPacker("tesla_model3_vehicle").make_can_msg(
          "ID3F5VCFRONT_lighting", 1, {"VCFRONT_turnSignalLeftStatus": 3})
        c.observe([(now, [frame])], now)
        self.assertEqual(c.status, "cancelling:invalid_lamp_feedback")
        self.assertEqual(c.take_sends(now)[0].dat[1] & 3, 3)

  def test_untrusted_or_out_of_order_feedback_cannot_renew_or_replace_latest_valid_state(self):
    for channel in (UI, FRONT):
      for invalid in ("old", "future", "source", "dlc"):
        with self.subTest(channel=channel, invalid=invalid):
          c = opened()
          now = N + 100_000_000
          feedback(c, now, ui=(2, 0), front=(1, 0))
          frame = channel_frame(channel, fault=True)
          timestamp = now - 1 if invalid == "old" else now + 1 if invalid == "future" else now
          if invalid == "source":
            frame = (frame[0], frame[1], 1 if channel == UI else 0)
          elif invalid == "dlc":
            frame = (frame[0], frame[1][:-1], frame[2])
          c.observe([(timestamp, [frame])], now)
          self.assertEqual(c.ui_time, now)
          self.assertEqual(c.front_time, now)
          self.assertEqual(c.ui, (2, 0))
          self.assertEqual(c.front, (1, 0))
          self.assertFalse(c.session.cancelling)

  def test_single_channel_tolerance_does_not_remove_echo_deadline(self):
    for slow in (UI, FRONT):
      with self.subTest(slow=slow):
        c = opened()
        first = c.take_sends(N + 3)[0]
        for tick in range(1, 14):
          now = N + tick * 100_000_000
          frames = [channel_frame(FRONT if slow == UI else UI), (BODY, template(tick % 16), 1)]
          if tick == 10:
            frames.append(channel_frame(slow))
          c.observe([(now, frames)], now)
          sends = update(c, now)
          self.assertTrue(all(sent.dat[1] & 3 == 3 for sent in sends))
        self.assertEqual(first.dat[1] & 3, 1)
        self.assertEqual(c.status, "cancelling:tx_echo_timeout")

  def test_feedback_startup_grace_still_bounds_a_missing_channel(self):
    for channel in (UI, FRONT):
      with self.subTest(channel=channel):
        c = TeslaTurnSignals(True)
        feedback(c, N)
        first = update(c)[0]
        echo(c, first, N + 1)
        for tick in range(1, 19):
          now = N + tick * 100_000_000
          c.observe([(now, [channel_frame(channel), (BODY, template(tick % 16), 1)])], now)
          for sent in update(c, now):
            echo(c, sent, now + 1)
        self.assertFalse(c.session.on_seen)
        self.assertEqual(c.status, "cancelling:feedback_stale")

  def test_initial_active_feedback_can_arrive_after_500ms_but_still_requires_confirmation(self):
    for direction in (1, 2):
      for slow in (UI, FRONT):
        with self.subTest(direction=direction, slow=slow):
          c = TeslaTurnSignals(True)
          feedback(c, N)
          first = update(c, direction=direction)[0]
          echo(c, first, N + 1)
          for tick in range(1, 31):
            now = N + tick * 100_000_000
            frames = [channel_frame(FRONT if slow == UI else UI, direction), (BODY, template(tick % 16), 1)]
            if tick % 10 == 0:
              frames.append(channel_frame(slow, direction))
            c.observe([(now, frames)], now)
            sends = update(c, now, direction=direction)
            self.assertEqual(len(sends), 1)
            self.assertEqual(sends[0].dat[1] & 3, direction)
            echo(c, sends[0], now + 1)
            self.assertFalse(c.session.cancelling)
            self.assertEqual(c.session.on_seen, tick >= 10)
          self.assertEqual(c.status, "active")

  def test_slow_fresh_feedback_cannot_skip_initial_physical_lamp_confirmation(self):
    for direction in (1, 2):
      with self.subTest(direction=direction):
        c = TeslaTurnSignals(True)
        feedback(c, N)
        first = update(c, direction=direction)[0]
        echo(c, first, N + 1)
        for tick in range(1, 27):
          now = N + tick * 100_000_000
          frames = [channel_frame(UI, direction), (BODY, template(tick % 16), 1)]
          if tick % 10 == 0:
            frames.append(channel_frame(FRONT, direction, lit=False))
          c.observe([(now, frames)], now)
          for sent in update(c, now, direction=direction):
            self.assertEqual(sent.dat[1] & 3, direction if tick < 25 else 3)
            echo(c, sent, now + 1)
        self.assertFalse(c.session.on_seen)
        self.assertEqual(c.status, "cancelling:lamp_not_confirmed")

  def test_ui_cannot_mask_a_periodically_reported_physical_lamp_stuck_off(self):
    for direction in (1, 2):
      with self.subTest(direction=direction):
        c = opened(direction)
        now = N
        for tick in range(1, 43):
          now = N + tick * 100_000_000
          frames = [channel_frame(UI, direction), (BODY, template(tick % 16), 1)]
          if tick % 10 == 0:
            frames.append(channel_frame(FRONT, direction, lit=False))
          c.observe([(now, frames)], now)
          for sent in update(c, now, direction=direction):
            self.assertEqual(sent.dat[1] & 3, direction if tick <= 40 else 3)
            echo(c, sent, now + 1)
        self.assertEqual(c.status, "cancelling:physical_lamp_feedback_lost")
        self.assertEqual(c.blocked_id, 1)
        self.assertGreaterEqual(c.diagnostics(now)["physical_on_age_ms"], 4000)

  def test_diagnostics_distinguish_submissions_echoes_and_rejections_without_side_effects(self):
    c = opened()
    self.assertEqual(c.diagnostics(N + 2)["active_submissions"], 1)
    self.assertEqual(c.diagnostics(N + 2)["active_tx_echoes"], 1)
    sent = c.take_sends(N + 3)[0]
    snapshot = c.diagnostics(N + 3)
    self.assertEqual(snapshot["active_submissions"], 2)
    self.assertEqual(snapshot["active_tx_echoes"], 1)
    self.assertTrue(snapshot["awaiting_echo"])
    self.assertTrue(snapshot["on_seen"])
    echo(c, sent, N + 4, source=0xC1)
    self.assertEqual(c.diagnostics(N + 4)["panda_rejections"], 1)
    self.assertEqual(c.status, "cancelling:panda_rejected")
    feedback(c, N + 5, ui=(2, 0), front=(1, 0))
    cancel = c.take_sends(N + 6)[0]
    self.assertEqual(cancel.dat[1] & 3, 3)
    echo(c, cancel, N + 7)
    echo(c, cancel, N + 8)  # Duplicate RX cannot inflate counters.
    snapshot = c.diagnostics(N + 8)
    self.assertEqual(snapshot["active_submissions"], 2)
    self.assertEqual(snapshot["active_tx_echoes"], 1)
    self.assertEqual(snapshot["cancel_submissions"], 1)
    self.assertEqual(snapshot["cancel_tx_echoes"], 1)
    self.assertFalse(snapshot["awaiting_echo"])

  def test_invalid_driver_input_does_not_masquerade_as_manual_takeover(self):
    c = opened()
    update(c, N + 3, cs=state(turnSignalDriverValid=False, rightBlinkerStalkCount=1))
    self.assertEqual(c.status, "cancelling:driver_input_unavailable")
    self.assertFalse(c.session.manual)

  def test_invalid_vehicle_sensors_cancel_active_lamp_session(self):
    for direction in (1, 2):
      with self.subTest(direction=direction):
        c = opened(direction)
        sends = update(c, N + 3, direction=direction, cs=state(vehicleSensorsInvalid=True))
        self.assertEqual(c.status, "cancelling:vehicle_sensors_invalid")
        self.assertFalse(c.session.manual)
        self.assertTrue(sends)
        self.assertTrue(all(frame.dat[1] & 3 == 3 for frame in sends))

  def test_full_lamp_cycle_requires_stable_ui_and_physical_off(self):
    for direction in (1, 2):
      with self.subTest(direction=direction):
        c = cancelling(direction)
        for dt in (10, 200_000_010, 400_000_010, 600_000_010):
          feedback(c, N + dt)
        self.assertIsNone(c.session)
        self.assertEqual(c.status, "cancelled")
        self.assertFalse(update(c, N + 600_000_011, direction=direction))  # consumed request
        self.assertTrue(update(c, N + 600_000_012, direction=direction, request=2))

  def test_flashing_dark_phase_fault_and_sna_never_confirm_cancellation(self):
    for front in (0, 2, 3):
      with self.subTest(front=front):
        c = cancelling()
        for dt in (10, 200_000_010, 400_000_010, 600_000_010):
          feedback(c, N + dt, ui=(1, 0), front=(front, 0))
        self.assertIsNotNone(c.session)
        self.assertNotEqual(c.status, "cancelled")
        c.advance(N + CANCEL_NS + 100)
        self.assertEqual(c.status, "fault:cancel_not_confirmed")
        self.assertEqual(c.owned_direction, 1)
        self.assertFalse(c.take_sends(N + CANCEL_NS + 101))

  def test_independent_receive_clock_cancels_when_controlsd_stops(self):
    c = opened()
    c.advance(N + CONTEXT_NS + 1)
    self.assertTrue(c.session.cancelling)
    self.assertEqual(c.take_sends(N + CONTEXT_NS + 2, cancel_only=True)[0].dat[1] & 3, 3)

  def test_start_gates(self):
    for gate in ["disabled", "model", "lateral", "can", "sensors", "gear", "driver", "stalk", "no_template"]:
      with self.subTest(gate=gate):
        c = TeslaTurnSignals(gate != "disabled")
        feedback(c, N, body=gate != "no_template")
        cs = state(canValid=gate != "can", vehicleSensorsInvalid=gate == "sensors",
                   gearShifter="park" if gate == "gear" else "drive",
                   turnSignalDriverValid=gate != "stalk", turnSignalDriverDirection=1 if gate == "driver" else 0)
        self.assertFalse(update(c, fresh=gate != "model", active=gate != "lateral", cs=cs))
        expected = {"disabled": "disabled", "model": "blocked:context_stale", "lateral": "blocked:lateral_inactive",
                    "can": "blocked:can_invalid", "sensors": "blocked:vehicle_sensors_invalid",
                    "gear": "blocked:not_in_drive", "driver": "blocked:driver",
                    "stalk": "blocked:driver_input_unavailable", "no_template": "waiting:body_template"}
        self.assertEqual(c.status, expected[gate])

  def test_body_only_changes_owned_fields(self):
    for direction in (1, 2, 3):
      with self.subTest(direction=direction):
        original = template(15)
        sent = body_frame(original, direction)
        self.assertEqual(sent[0], original[0])
        self.assertEqual(sent[3:6], original[3:6])
        self.assertEqual(sent[1] & 0xFC, original[1] & 0xFC)
        self.assertEqual(sent[2] & 0xE1, original[2] & 0xE1)
        self.assertEqual(sent[6], 7)
        self.assertEqual(sent[7], body_checksum(sent))

  def test_bad_template_and_reused_template_are_rejected(self):
    with self.assertRaises(ValueError):
      body_frame(bytes(8), 1)
    c = opened()
    self.assertTrue(c.take_sends(N + 3))
    self.assertFalse(c.take_sends(N + 4))

  def test_reverse_request_cancels_before_other_direction(self):
    c = opened()
    sends = update(c, N + 3, direction=2, request=2)
    self.assertEqual(len(sends), 1)
    self.assertEqual(sends[0].dat[1] & 3, 3)
    self.assertEqual(c.session.direction, 1)

  def test_session_limit_requests_cancel_even_with_fresh_controls(self):
    c = opened()
    now = N + SESSION_NS
    feedback(c, now, ui=(2, 0), front=(1, 0))
    self.assertTrue(c.session.cancelling)  # no control update can revive an expired lease
    self.assertEqual(update(c, now)[0].dat[1] & 3, 3)

  def test_ui_decoder_uses_real_dbc_and_does_not_accept_corrupt_checksum(self):
    c = TeslaTurnSignals(True)
    feedback(c, N, ui=(2, 1))
    self.assertEqual(c.ui, (2, 1))
    c.observe([(N + 1, [(UI, bytes(7), 0)])], N + 1)
    self.assertEqual(c.ui_time, N)
    self.assertNotEqual(FRONT, BODY)

  def test_loss_of_any_start_gate_requests_cancel_instead_of_relighting(self):
    for gate in ["model", "lateral", "can", "gear", "stalk"]:
      with self.subTest(gate=gate):
        c = opened()
        sends = update(c, N + 3, fresh=gate != "model", active=gate != "lateral",
                       cs=state(canValid=gate != "can", gearShifter="park" if gate == "gear" else "drive",
                                turnSignalDriverValid=gate != "stalk"))
        self.assertEqual(sends[0].dat[1] & 3, 3)
        self.assertEqual(c.owned_direction, 1)

  def test_lost_echo_allows_bounded_cancel_retries_then_latches_fault(self):
    c = opened()
    sends = update(c, N + 3, direction=0)
    self.assertEqual(sends[0].dat[1] & 3, 3)
    for attempt in (1, 2):
      now = N + 3 + attempt * 1_200_000_001
      feedback(c, now)
      self.assertEqual(c.take_sends(now)[0].dat[1] & 3, 3)
    feedback(c, N + 3_600_000_010)
    self.assertFalse(c.take_sends(N + 3_600_000_010))
    c.advance(N + CANCEL_NS + 4)
    self.assertTrue(c.failed)
    self.assertEqual(c.owned_direction, 1)
    for dt in (5_100_000_010, 5_300_000_010, 5_500_000_010, 5_700_000_010):
      feedback(c, N + dt)
    self.assertEqual(c.owned_direction, 0)
    self.assertTrue(c.failed)
    self.assertTrue(c.status.startswith("fault:"))
    self.assertFalse(update(c, N + 5_700_000_011, request=99))

  def test_rejected_cancel_is_never_reported_as_success(self):
    c = opened()
    sends = update(c, N + 3, direction=0)
    echo(c, sends[0], N + 4, source=0xC1)
    self.assertTrue(c.failed)
    self.assertEqual(c.status, "fault:panda_rejected_cancel")
    self.assertEqual(c.owned_direction, 1)

  def test_driver_handoff_cannot_hide_latched_cancel_failure(self):
    c = opened()
    cancel = update(c, N + 3, direction=0)[0]
    echo(c, cancel, N + 4, source=0xC1)
    self.assertFalse(update(c, N + 5, cs=state(turnSignalDriverDirection=2)))
    self.assertTrue(c.failed)
    self.assertEqual(c.status, "fault:panda_rejected_cancel")
    self.assertFalse(c.owned_direction)

  def test_hazards_and_fast_driver_tap_release_automatic_ownership(self):
    for hazards in (False, True):
      with self.subTest(hazards=hazards):
        c = opened()
        if hazards:
          feedback(c, N + 3, ui=(2, 2), front=(1, 1))
        sends = update(c, N + 4, cs=state(leftBlinkerStalkCount=1 if not hazards else 0))
        self.assertFalse(sends)
        self.assertFalse(c.owned_direction)
        self.assertEqual(c.status, "driver_takeover:waiting_off")

  def test_missing_template_waits_and_resumes_same_request_with_fresh_template(self):
    for direction in (1, 2):
      with self.subTest(direction=direction):
        c = opened(direction)
        c.template = None
        now = N
        for tick in range(1, 21):
          now = N + tick * 100_000_000
          feedback(c, now, ui=(2, 0) if direction == 1 else (0, 2),
                   front=(1, 0) if direction == 1 else (0, 1), body=False)
          self.assertFalse(update(c, now, direction=direction))
          self.assertFalse(c.session.cancelling)
          self.assertEqual(c.blocked_id, 0)
        c.observe([(now, [(BODY, template(7), 1)])], now)
        resumed = update(c, now, direction=direction)
        self.assertEqual(len(resumed), 1)
        self.assertEqual(resumed[0].dat, body_frame(template(7), direction))
        self.assertEqual(c.session.request_id, 1)

  def test_missing_template_wait_is_bounded_by_session_deadline(self):
    c = opened()
    c.template = None
    now = N
    for tick in range(1, 601):
      now = N + tick * 100_000_000
      feedback(c, now, ui=(2, 0), front=(1, 0), body=False)
      self.assertFalse(update(c, now))
      self.assertEqual(c.session.cancelling, tick == 600)
    self.assertEqual(c.status, "cancelling:session_timeout")
    self.assertEqual(c.blocked_id, 1)
    feedback(c, now + 1, ui=(2, 0), front=(1, 0))
    self.assertEqual(c.take_sends(now + 1)[0].dat[1] & 3, 3)
    c.advance(now + CANCEL_NS + 2)
    self.assertTrue(c.failed)

  def test_missing_template_does_not_hide_physical_lamp_loss(self):
    for direction in (1, 2):
      with self.subTest(direction=direction):
        c = opened(direction)
        c.template = None
        now = N
        for tick in range(1, 8):
          now = N + tick * 100_000_000
          feedback(c, now, body=False)
          self.assertFalse(update(c, now, direction=direction))
        self.assertEqual(c.status, "cancelling:lamps_lost")
        self.assertEqual(c.blocked_id, 1)
        feedback(c, now + 1)
        self.assertEqual(c.take_sends(now + 1)[0].dat[1] & 3, 3)

  def test_readiness_requires_both_physical_confirmation_and_exact_tx_echo(self):
    for direction in (1, 2):
      with self.subTest(direction=direction):
        c = TeslaTurnSignals(True)
        feedback(c, N)
        sent = update(c, direction=direction)[0]
        self.assertEqual(c.ready_request_id(N), 0)
        feedback(c, N + 1, ui=(2, 0) if direction == 1 else (0, 2),
                 front=(1, 0) if direction == 1 else (0, 1), body=False)
        self.assertTrue(c.session.on_seen)
        self.assertEqual(c.ready_request_id(N + 1), 0)
        echo(c, sent, N + 2)
        self.assertEqual(c.ready_request_id(N + 2), 1)
        # cp 追加 car.CarState capnp 序列化回读断言（本环境 capnp 不可用，未适配）。
        self.assertEqual(c.ready_request_id(N + CONTEXT_NS + 1), 0)
        self.assertEqual(c.ready_request_id(N - 1), 0)

  def test_readiness_drops_on_execution_failure_or_handoff(self):
    for gate in ["manual", "cancel", "fault", "context", "feedback", "session"]:
      with self.subTest(gate=gate):
        c = opened()
        now = N + 3
        self.assertEqual(c.ready_request_id(now), 1)
        if gate == "manual":
          c.observe_driver(state(turnSignalDriverDirection=1), now)
        elif gate == "cancel":
          update(c, now, direction=0)
        elif gate == "fault":
          cancel = update(c, now, direction=0)[0]
          echo(c, cancel, now, source=0xC1)
        elif gate == "context":
          c.context_time = 0
        elif gate == "feedback":
          c.front_time = 0
        else:
          now = N + SESSION_NS
          c.context_time = c.ui_time = c.front_time = now
        self.assertEqual(c.ready_request_id(now), 0)

  def test_consumed_or_out_of_order_template_cannot_be_reused_after_echo(self):
    c = TeslaTurnSignals(True)
    feedback(c, N)
    first = update(c)[0]
    echo(c, first, N + 1)
    for timestamp in (N - 1, N):
      c.observe([(timestamp, [(BODY, template(), 1)])], N + 2)
      self.assertFalse(c.take_sends(N + 2))
    c.observe([(N + 3, [(BODY, template(5), 1), (BODY, template(6), 1)])], N + 3)
    c.observe([(N + 2, [(BODY, template(4), 1)])], N + 3)
    self.assertEqual(c.take_sends(N + 3)[0].dat, body_frame(template(6), 1))
    self.assertFalse(c.take_sends(N + 4))

  def test_template_diagnostics_separate_filtered_rx_waiting_and_awaiting_echo(self):
    c = opened()
    c.template = None
    now = N + 3
    snapshot = c.diagnostics(now)
    self.assertEqual(snapshot["send_state"], "waiting:body_template")
    self.assertEqual(snapshot["ready_request_id"], 1)
    c.observe([(now, [(BODY, bytes(8), 1), (BODY, body_frame(template(), 1), 1)])], now)
    snapshot = c.diagnostics(now)
    self.assertEqual(snapshot["body_rx"], 4)
    self.assertEqual(snapshot["body_idle_rx"], 2)
    self.assertEqual(snapshot["body_invalid_rx"], 1)
    self.assertEqual(snapshot["body_non_idle_rx"], 1)
    self.assertFalse(c.take_sends(now))
    c.observe([(now + 1, [(BODY, template(6), 1)])], now + 1)
    self.assertEqual(c.diagnostics(now + 1)["send_state"], "ready")
    sent = c.take_sends(now + 1)[0]
    snapshot = c.diagnostics(now + 1)
    self.assertEqual(snapshot["send_state"], "waiting:tx_echo")
    self.assertEqual(snapshot["pending_counter"], 7)
    self.assertFalse(snapshot["template_ready"])
    echo(c, sent, now + 2)
    self.assertEqual(c.diagnostics(now + 2)["send_state"], "waiting:body_template")

  def test_unknown_opposite_lamp_yields_without_cancelling_it(self):
    for missing in (0, UI, FRONT):
      with self.subTest(missing=missing):
        c = opened()
        if missing == 0:
          feedback(c, N + 10, ui=(0, 2), front=(0, 1))
        else:
          if missing == UI:
            c.ui_time = 0
            frame = CANPacker("tesla_model3_vehicle").make_can_msg("ID3F5VCFRONT_lighting", 1, {"VCFRONT_turnSignalRightStatus": 1})
          else:
            c.front_time = 0
            frame = CANPacker("tesla_model3_party").make_can_msg("UI_warning", 0, {"rightBlinkerBlinking": 2})
          c.observe([(N + 10, [frame])], N + 10)
        self.assertTrue(c.session.manual)
        self.assertEqual(c.owned_direction, 0)
        self.assertFalse(c.take_sends(N + 10, cancel_only=True))
        self.assertFalse(update(c, N + 11))

  def test_manual_cleanup_cannot_send_until_fresh_idle_and_true_off(self):
    for gate in ["held", "stale", "dark", "hazards"]:
      with self.subTest(gate=gate):
        c = opened()
        update(c, N + 3, cs=state(turnSignalDriverDirection=1))
        for tick in range(1, 80):
          now = N + tick * 100_000_000
          c.observe_driver(state(turnSignalDriverDirection=1 if gate == "held" else 0,
                                 turnSignalDriverValid=gate != "stale"), now)
          feedback(c, now, ui=(1, 0) if gate == "dark" else (2, 2) if gate == "hazards" else (0, 0),
                   front=(1, 1) if gate == "hazards" else (0, 0))
          self.assertFalse(c.take_sends(now, cancel_only=True))
        self.assertTrue(c.session.manual)
        self.assertFalse(c.failed)

  def test_lamp_dark_phase_is_not_real_off_but_lost_lamps_cancel(self):
    for dark in (True, False):
      with self.subTest(dark=dark):
        c = opened()
        cancelled = False
        for tick in range(1, 13):
          now = N + tick * 100_000_000
          feedback(c, now, ui=(1, 0) if dark else (0, 0), front=(0, 0))
          sends = update(c, now)
          if sends:
            cancelled |= sends[0].dat[1] & 3 == 3
            echo(c, sends[0], now + 1)
        self.assertNotEqual(cancelled, dark)
        self.assertEqual(c.status, "active" if dark else "cancelled")

  def test_no_confirmed_lit_phase_after_initial_blink_is_bounded(self):
    c = opened()
    for tick in range(1, 28):
      now = N + tick * 100_000_000
      feedback(c, now, ui=(1, 0), front=(0, 0))
      for sent in update(c, now):
        echo(c, sent, now + 1)
    self.assertEqual(c.status, "cancelling:lamp_feedback_lost")

  def test_delayed_rejected_or_lost_active_echo_never_sends_unconfirmed_repeats(self):
    for source in (0x81, 0xC1, None):
      with self.subTest(source=source):
        c = TeslaTurnSignals(True)
        feedback(c, N)
        first = update(c)[0]
        for tick in range(1, 12):
          now = N + tick * 100_000_000
          feedback(c, now, ui=(2, 0), front=(1, 0))
          self.assertFalse(update(c, now))
        if source is not None:
          echo(c, first, now + 1, source=source)
          sends = update(c, now + 2)
          self.assertEqual(sends[0].dat[1] & 3, 1 if source == 0x81 else 3)
        else:
          now = N + 1_200_000_001
          feedback(c, now, ui=(2, 0), front=(1, 0))
          self.assertEqual(update(c, now)[0].dat[1] & 3, 3)
          self.assertEqual(c.status, "cancelling:tx_echo_timeout")

  def test_fault_or_unavailable_feedback_cancels_an_active_session(self):
    for ui, front in (((3, 0), (0, 0)), ((2, 3), (1, 0)), ((2, 0), (3, 0)), ((2, 0), (1, 3))):
      with self.subTest(ui=ui, front=front):
        c = opened()
        feedback(c, N + 3, ui=ui, front=front)
        self.assertTrue(c.session.cancelling)
        self.assertEqual(c.take_sends(N + 4)[0].dat[1] & 3, 3)

  def test_configuration_reports_why_extension_signals_are_not_enabled(self):
    cases = [
      ("ready", "idle", None),
      ("off", "disabled:setting_off", dict(enabled=False)),
      ("vehicle_bus", "blocked:vehicle_bus_unavailable", dict(flags=TeslaFlags.AUTO_TURN_SIGNALS)),
      ("restart", "blocked:restart_required", dict(flags=TeslaFlags.HAS_VEHICLE_BUS)),
      ("safety", "blocked:safety_configuration", dict(safety_param=0)),
      ("passive", "disabled:passive", dict(passive=True)),
      ("platform", "disabled:unsupported_platform", dict(carFingerprint="TESLA_MODEL_X")),
    ]
    for gate, expected, override in cases:
      with self.subTest(gate=gate):
        kwargs = override or {}
        enabled = kwargs.pop("enabled", True)
        cp = car_params(**kwargs)
        c = TeslaTurnSignals.from_car_params(cp, enabled=enabled)
        self.assertEqual(c.status, expected)
        self.assertEqual(c.configured, gate == "ready")
        self.assertEqual(bool(cp.flags & TeslaFlags.HAS_VEHICLE_BUS), gate != "vehicle_bus")

  def test_feedback_waits_report_specific_cause(self):
    for gate, expected in [("ui", "waiting:ui_feedback"), ("front", "waiting:front_feedback"),
                           ("lamp", "waiting:lamps_off"), ("invalid", "waiting:invalid_lamp_feedback")]:
      with self.subTest(gate=gate):
        c = TeslaTurnSignals(True)
        feedback(c, N, ui=(2, 0) if gate == "lamp" else (0, 0), front=(3, 0) if gate == "invalid" else (0, 0))
        if gate == "ui":
          c.ui_time = 0
        elif gate == "front":
          c.front_time = 0
        self.assertFalse(update(c))
        self.assertEqual(c.status, expected)
        feedback(c, N + 1)
        self.assertTrue(update(c, N + 1))


if __name__ == '__main__':
  unittest.main()
