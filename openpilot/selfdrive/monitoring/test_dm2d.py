import bisect
from types import SimpleNamespace


import unittest
try:
  import openpilot.cereal.messaging  # noqa: F401
except ImportError as exc:  # PC without the msgq native module
  raise unittest.SkipTest('msgq native module unavailable on this host') from exc
from opendbc.car.structs import car
from openpilot.cereal import log
from openpilot.selfdrive.monitoring import dm2d
from openpilot.selfdrive.monitoring.dm2_test_settings import pin_carrot_vision_settings
from openpilot.selfdrive.monitoring.test_monitoring import make_msg
from openpilot.common.test import OpenpilotTestCase
from openpilot.common.parameterized import parameterized


def checked_submaster(state, replay=False):
  def create(services, *, poll=None, frequency=None):
    # Preserve the real IPC API contract even in the simulated daemon loop.
    assert frequency is None or poll is None
    expected_poll = 'modelV2' if replay else 'driverStateV2'
    assert poll == expected_poll and poll in services
    return state
  return create



class TestDm2DTests(OpenpilotTestCase):
  def setUp(self):
    super().setUp()
    # live-camera cases assume carrotpilot's VISION (5, 8, 13) timeouts;
    # see dm2_test_settings.py for why the shipped policy must not be edited.
    pin_carrot_vision_settings(self)

  @parameterized.expand([False, True], names=('experimental',))
  def test_live_reenable_cadence_and_camera_recovery(self, monkeypatch, experimental):
    from openpilot.cereal.messaging import FrequencyTracker
    from openpilot.selfdrive.monitoring import dm2_cadence
    from openpilot.selfdrive.monitoring.test_dm2_cadence import Clock

    clock = Clock()
    enable_time = clock.now + 780
    end_time = enable_time + 70
    # Model startup, irregular inference, a camera outage and recovery.
    arrivals = [enable_time + 2 + i * .05 + (.028 if i % 2 else 0)
                for i in range(1500) if not 600 <= i < 800]
    packets = []
    input_trackers = {s: FrequencyTracker(100, 20, False) for s in ('carState', 'selfdriveState')}
    output_tracker = FrequencyTracker(20, 100, False)

    class Done(Exception):
      pass

    class State(dict):
      updated = {'carParams': False, 'radarState': True, 'driverStateV2': False}
      logMonoTime = {'driverStateV2': 0}
      received = 0

      def update(self, timeout):
        assert timeout == 50
        if clock.now >= end_time:
          raise Done
        if self.received < len(arrivals) and arrivals[self.received] <= clock.now:
          new_received = bisect.bisect_right(arrivals, clock.now)
        elif self.received < len(arrivals) and arrivals[self.received] <= clock.now + .05:
          clock.now = arrivals[self.received]
          new_received = self.received + 1
        else:
          clock.now += .05
          new_received = self.received
        self.updated['driverStateV2'] = new_received != self.received
        if new_received:
          self.logMonoTime['driverStateV2'] = int(arrivals[new_received - 1] * 1e9)
        self.received = new_received
        for service, tracker in input_trackers.items():
          tracker.record_recv_time(clock.now)
          self.logMonoTime[service] = int(clock.now * 1e9)
        clock.now += .003  # processing beyond the blocking camera poll

      def all_checks(self, services):
        return all((input_trackers[s].valid if s in input_trackers else
                    self.received > 0 and clock.now - self.logMonoTime['driverStateV2'] / 1e9 < .5
                    if s == 'driverStateV2' else True) for s in services)

    model = log.ModelDataV2.new_message()
    model.meta.disengagePredictions.brakeDisengageProbs = [0.0]
    model.orientationRate.z = [0.] * 33
    model.laneLineProbs = [0., 1., 1., 0.]
    state = State(carState=car.CarState.new_message(vEgo=20, canValid=True, gearShifter='drive'),
                  selfdriveState=log.SelfdriveState.new_message(enabled=True), modelV2=model.as_reader(),
                  radarState=log.RadarState.new_message(), extrinsicsCalibration=log.ExtrinsicsCalibration.new_message(rpyCalib=[0., 0., 0.]),
                  driverStateV2=make_msg(True))

    class Params:
      def get_bool(self, name):
        return name == 'DriverMonitoringEnabled' and clock.now >= enable_time

      def get_int(self, _):
        return int(experimental)

      def put_bool(self, *_args):
        pass

    class Publisher:
      def send(self, service, packet):
        assert service == 'driverMonitoringState'
        output_tracker.record_recv_time(clock.now)
        if clock.now >= enable_time:
          packets.append((clock.now, packet.to_dict(), output_tracker.valid))

    monkeypatch.delenv('REPLAY', raising=False)
    monkeypatch.setattr(dm2d.messaging, 'SubMaster', checked_submaster(state))
    monkeypatch.setattr(dm2d.messaging, 'PubMaster', lambda *a: Publisher(), raising=False)
    monkeypatch.setattr(dm2d.messaging, 'sub_sock', lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(dm2d.messaging, 'drain_sock', lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(dm2d, 'CommandReader', lambda *a: SimpleNamespace(read=lambda **kw: None))
    monkeypatch.setattr(dm2d, 'time', clock)
    monkeypatch.setattr(dm2_cadence, 'time', clock)
    # Keep the real production ratekeeper and dispatcher; earlier policy tests
    # mocked the timer and could not expose accumulated timing debt.
    with self.assertRaises(Done):
      dm2d.run_dm2(Params(), experimental)
    assert packets and all(p['valid'] and freq_ok for _, p, freq_ok in packets)
    for start, end, unavailable in ((5, 30, False), (33, 41, True), (45, 69, False)):
      window = [p['driverMonitoringState'] for t, p, _ in packets if enable_time + start < t < enable_time + end]
      assert window and all(not p['dm2Disabled'] and p['cameraUnavailable'] == unavailable for p in window)


  def test_replay_dm_clock_uses_route_timeline(self, monkeypatch):
    state = SimpleNamespace(logMonoTime={
      'driverStateV2': int(12.05e9), 'modelV2': int(12.0e9),
      'carState': int(12.04e9), 'selfdriveState': int(11.99e9),
    })
    monkeypatch.setattr(dm2d.time, 'monotonic', lambda: 100.0)

    assert dm2d.dm_clock(state, replay=True) == 12.05
    assert dm2d.input_packet_fresh(dm2d.dm_clock(state, replay=True), 11.9)

    assert dm2d.dm_clock(state, replay=False) == 100.0
    assert dm2d.input_packet_fresh(100.0, 99.9)
    assert not dm2d.input_packet_fresh(100.0, 12.0)
    assert not dm2d.input_packet_fresh(100.0, float('nan'))


  @parameterized.expand([(False, 'none', False, False), (True, 'none', False, False), (False, 'held', False, False), (True, 'held', False, False), (False, 'stale', False, False), (True, 'stale', False, False), (False, 'none', True, False), (True, 'none', True, False), (False, 'held', True, False), (True, 'held', True, False), (False, 'stale', True, False), (True, 'stale', True, False), (False, 'none', False, True), (True, 'none', False, True), (False, 'held', False, True), (True, 'held', False, True), (False, 'stale', False, True), (True, 'stale', False, True), (False, 'none', True, True), (True, 'none', True, True), (False, 'held', True, True), (True, 'held', True, True), (False, 'stale', True, True), (True, 'stale', True, True)], names=('experimental', 'touch_signal', 'model_ready', 'live_mode'))  # noqa: E501
  def test_missing_or_failed_camera_still_publishes_valid_interaction_monitoring(self, monkeypatch, experimental, touch_signal, model_ready, live_mode):
    clock = [100.0]
    packets = []

    class Params:
      def get_bool(self, name):
        return name == "DriverMonitoringEnabled"

      def get_int(self, _):
        return int(not experimental if live_mode and clock[0] >= 108 else experimental)

    class State(dict):
      updated = {'carParams': False, 'radarState': True, 'driverStateV2': False}
      logMonoTime = {'driverStateV2': 0}

      def update(self, timeout):
        assert timeout == 50
        clock[0] += .05
        if touch_signal == 'held':
          self['carState'].steeringTouch.sampleMonoTime = int(clock[0] * 1e9)

      def all_checks(self, services):
        return 'driverStateV2' not in services

    cs = car.CarState.new_message(vEgo=20, canValid=True, gearShifter='drive')
    if touch_signal != 'none':
      cs.steeringTouch = {'available': True, 'valid': True, 'touched': True, 'sampleMonoTime': int(100e9)}
    model = log.ModelDataV2.new_message()
    if model_ready:
      model.orientationRate.z = [0.] * 33
      model.laneLineProbs = [0., 1., 1., 0.]
    state = State(carState=cs, selfdriveState=log.SelfdriveState.new_message(enabled=True),
                  radarState=log.RadarState.new_message(), modelV2=model.as_reader())

    class Done(Exception):
      pass

    class Rate:
      frame = 0

      def keep_time(self):
        self.frame += 1
        if self.frame >= 310:
          raise Done

    class Publisher:
      def send(self, service, packet):
        assert service == 'driverMonitoringState'
        packets.append(packet.to_dict())

    monkeypatch.setattr(dm2d.messaging, 'SubMaster', checked_submaster(state), raising=False)
    monkeypatch.setattr(dm2d.messaging, 'PubMaster', lambda *a: Publisher(), raising=False)
    monkeypatch.setattr(dm2d.messaging, 'sub_sock', lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(dm2d.messaging, 'drain_sock', lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(dm2d, 'DmRatekeeper', lambda *a, **kw: Rate())
    monkeypatch.setattr(dm2d.time, 'monotonic', lambda: clock[0])
    with self.assertRaises(Done):
      dm2d.run_dm2(Params(), experimental)
    assert len(packets) == 310 and all(p['valid'] for p in packets)
    assert all(p['driverMonitoringState']['cameraUnavailable'] for p in packets)
    state = packets[-1]['driverMonitoringState']
    assert state['alertLevel'] == ('none' if touch_signal == 'held' else 'one')
    assert state['dm2WheelTimeoutFactor'] == 1  # no verified empty-road coverage
    assert packets[0]['driverMonitoringState']['dm2Experimental'] == experimental
    assert state['dm2Experimental'] == (not experimental if live_mode else experimental)
    if live_mode:
      changed = next(i for i, p in enumerate(packets) if p['driverMonitoringState']['dm2Experimental'] != experimental)
      assert 159 <= changed <= 171  # Next half-second check plus one 20 Hz update.


  def test_malformed_camera_outputs_cannot_reuse_previous_attention(self):
    model = log.ModelDataV2.new_message()
    model.meta.disengagePredictions.brakeDisengageProbs = [0.0]
    calibration = log.ExtrinsicsCalibration.new_message(rpyCalib=[0., 0., 0.])

    class State(dict):
      def all_checks(self, _):
        return True

    state = State(driverStateV2=make_msg(True), extrinsicsCalibration=calibration, modelV2=model)
    assert dm2d.camera_sample_usable(state, False)
    state['driverStateV2'].leftDriverData.faceOrientation = []
    assert not dm2d.camera_sample_usable(state, False)
    state['driverStateV2'] = make_msg(True)
    state['driverStateV2'].leftDriverData.faceOrientation = [float('nan'), 0]
    assert not dm2d.camera_sample_usable(state, False)
    state['driverStateV2'] = make_msg(True)
    state['driverStateV2'].leftDriverData.sleepProb = float('nan')
    assert not dm2d.camera_sample_usable(state, False)


  def test_replay_camera_dependencies_expire_on_route_timeline(self):
    model = log.ModelDataV2.new_message()
    model.meta.disengagePredictions.brakeDisengageProbs = [0.0]
    calibration = log.ExtrinsicsCalibration.new_message(rpyCalib=[0., 0., 0.])

    class State(dict):
      logMonoTime = {
        'driverStateV2': int(100e9),
        'modelV2': int(100e9),
        'extrinsicsCalibration': int(100e9),
      }

      def all_checks(self, _):
        return True

    state = State(driverStateV2=make_msg(True), extrinsicsCalibration=calibration, modelV2=model)
    assert dm2d.camera_sample_usable(state, False, replay_now=100.0)

    state.logMonoTime['modelV2'] = int(99.49e9)
    assert not dm2d.camera_sample_usable(state, False, replay_now=100.0)
    assert dm2d.camera_sample_usable(state, False, demo=True, replay_now=100.0)

    state.logMonoTime['modelV2'] = int(100e9)
    state.logMonoTime['extrinsicsCalibration'] = int(97.49e9)
    assert not dm2d.camera_sample_usable(state, False, replay_now=100.0)

    state.logMonoTime['extrinsicsCalibration'] = int(100e9)
    state.logMonoTime['driverStateV2'] = int(99.49e9)
    assert not dm2d.camera_sample_usable(state, False, replay_now=100.0)


  def test_disabled_state_packet_is_valid_and_neutral(self):
    state = dm2d.disabled_state_packet(rhd=True, experimental=True).to_dict()
    assert state['valid']
    dm_state = state['driverMonitoringState']
    assert dm_state['dm2Disabled'] and dm_state['dm2Experimental'] and dm_state['isRHD']
    assert dm_state['alertLevel'] == 'none' and dm_state['activePolicy'] == 'wheeltouch'
    assert not dm_state['lockout'] and not dm_state['alwaysOnLockout'] and not dm_state['noResponseForceDecel']
    assert not dm_state['cameraUnavailable']
    assert dm_state['visionPolicyState']['awarenessPercent'] == 100
    assert dm_state['wheeltouchPolicyState']['awarenessPercent'] == 100


  def test_disabled_driver_view_keeps_face_preview_without_enforcement(self, monkeypatch):
    clock, packets = [100.0], []

    class Params:
      def get_bool(self, name):
        return name in ("IsDriverViewEnabled", "DriverMonitoringEnabled", "DriverMonitoringSessionDisabled")

      def get_int(self, _):
        return 0

    class State(dict):
      updated = {'carParams': False, 'radarState': False, 'driverStateV2': True}
      logMonoTime = {'driverStateV2': int(clock[0] * 1e9)}

      def update(self, _):
        clock[0] += .05
        self.logMonoTime['driverStateV2'] = int(clock[0] * 1e9)

      def all_checks(self, _services):
        return True

    state = State(carState=car.CarState.new_message(vEgo=0, canValid=True, gearShifter='park'),
                  selfdriveState=log.SelfdriveState.new_message(enabled=False),
                  driverStateV2=make_msg(True, distracted=True))

    class Bluetooth:
      def read(self, **_kwargs):
        return None

    class Done(Exception):
      pass

    class Rate:
      frame = 0

      def keep_time(self):
        self.frame += 1
        if self.frame >= 45:
          raise Done

    class Publisher:
      def send(self, _, packet):
        packets.append(packet.to_dict())

    monkeypatch.setattr(dm2d.messaging, 'SubMaster', checked_submaster(state))
    monkeypatch.setattr(dm2d.messaging, 'PubMaster', lambda *a: Publisher(), raising=False)
    monkeypatch.setattr(dm2d.messaging, 'sub_sock', lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(dm2d.messaging, 'drain_sock', lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(dm2d, 'CommandReader', lambda *a: Bluetooth())
    monkeypatch.setattr(dm2d, 'DmRatekeeper', lambda *a, **kw: Rate())
    monkeypatch.setattr(dm2d.time, 'monotonic', lambda: clock[0])
    with self.assertRaises(Done):
      dm2d.run_dm2(Params(), experimental=False)

    preview = packets[-1]['driverMonitoringState']
    assert preview['dm2Disabled'] and preview['visionPolicyState']['faceDetected']
    assert preview['activePolicy'] == 'vision' and preview['alertLevel'] == 'none'
    assert not preview['lockout'] and not preview['noResponseForceDecel']
    assert preview['visionPolicyState']['awarenessPercent'] == 100
    assert not preview['visionPolicyState']['isDistracted']
    assert not any(preview['visionPolicyState']['distractedTypes'].values())


  GEAR_CASES = ([(str(gear), (gear,) * 6) for gear in car.CarState.GearShifter.schema.enumerants]
                + [('gear_changes', ('drive', 'drive', 'neutral', 'neutral', 'reverse', 'reverse'))])

  @parameterized.expand([((10.0,) * 6,), ((0.0,) * 6,), ((10.0, 10.0, 0.0, 0.0, 0.0, 0.0),)], names=('speeds',))
  def test_three_physical_cancel_presses_disable_for_current_session_at_any_gear_or_speed(self, monkeypatch, speeds):
    for gears_id, gears in self.GEAR_CASES:
      with self.subTest(gears=gears_id):
        self._three_press_scenario(monkeypatch, gears, speeds)

  def _three_press_scenario(self, monkeypatch, gears, speeds):
    # one fixture instance per scenario: fresh clock and packet ledger each time
    clock, packets = [100.0], []

    class Params:
      def __init__(self):
        self.values = {"DriverMonitoringEnabled": True}
        self.writes = []

      def get_bool(self, name):
        return self.values.get(name, False)

      def get_int(self, _):
        return 0

      def put_bool_nonblocking(self, name, value):
        self.writes.append((name, value))
        # Model an asynchronous first write that is not yet observable. The
        # daemon must keep DM locally disabled and retry at its settings cadence.
        if len(self.writes) == 2:
          self.values[name] = value

    params = Params()

    class State(dict):
      updated = {'carParams': False, 'radarState': True, 'driverStateV2': False}
      logMonoTime = {'driverStateV2': 0}

      def update(self, _):
        clock[0] += .05

      def all_checks(self, services):
        return 'driverStateV2' not in services

    state = State(carState=car.CarState.new_message(vEgo=speeds[0], canValid=True, gearShifter=gears[0]),
                  selfdriveState=log.SelfdriveState.new_message(enabled=True),
                  radarState=log.RadarState.new_message(), modelV2=log.ModelDataV2.new_message())
    edges = iter(zip(gears, speeds, (True, False, True, False, True, False), strict=True))

    def drain_sock(sock, **_kwargs):
      if sock != 'carState':
        return []
      try:
        gear, speed, pressed = next(edges)
      except StopIteration:
        return []
      sample = car.CarState.new_message(vEgo=speed, canValid=True, gearShifter=gear)
      sample.buttonEvents = [{'type': 'cancel', 'pressed': pressed}]
      state['carState'] = sample
      return [SimpleNamespace(valid=True, logMonoTime=int(clock[0] * 1e9), carState=sample)]

    class Bluetooth:
      def read(self, **_kwargs):
        return None

    class Done(Exception):
      pass

    class Rate:
      frame = 0

      def keep_time(self):
        self.frame += 1
        if self.frame >= 43:
          raise Done

    class Publisher:
      def send(self, _, packet):
        packets.append(packet.to_dict())

    monkeypatch.setattr(dm2d.messaging, 'SubMaster', lambda *a, **kw: state)
    monkeypatch.setattr(dm2d.messaging, 'PubMaster', lambda *a: Publisher(), raising=False)
    monkeypatch.setattr(dm2d.messaging, 'sub_sock', lambda service, **kw: service, raising=False)
    monkeypatch.setattr(dm2d.messaging, 'drain_sock', drain_sock, raising=False)
    monkeypatch.setattr(dm2d, 'CommandReader', lambda *a: Bluetooth())
    monkeypatch.setattr(dm2d, 'DmRatekeeper', lambda *a, **kw: Rate())
    monkeypatch.setattr(dm2d.time, 'monotonic', lambda: clock[0])
    with self.assertRaises(Done):
      dm2d.run_dm2(params, experimental=False)

    assert params.writes == [("DriverMonitoringSessionDisabled", True)] * 2
    assert params.values["DriverMonitoringSessionDisabled"] is True
    assert all(not packet['driverMonitoringState']['dm2Disabled'] for packet in packets[:4])
    assert all(packet['valid'] and packet['driverMonitoringState']['dm2Disabled'] for packet in packets[4:])


  def test_automatic_cancel_echo_racing_between_socket_drains_is_not_counted(self, monkeypatch):
    clock, packets = [100.0], []

    class Params:
      writes = []

      def get_bool(self, name):
        return name == "DriverMonitoringEnabled"

      def get_int(self, _):
        return 0

      def put_bool_nonblocking(self, name, value):
        self.writes.append((name, value))

    params = Params()

    class State(dict):
      updated = {'carParams': False, 'radarState': True, 'driverStateV2': False}
      logMonoTime = {'driverStateV2': 0}

      def update(self, _):
        clock[0] += .05

      def all_checks(self, services):
        return 'driverStateV2' not in services

    state = State(carState=car.CarState.new_message(vEgo=10, canValid=True, gearShifter='drive'),
                  selfdriveState=log.SelfdriveState.new_message(enabled=True),
                  radarState=log.RadarState.new_message(), modelV2=log.ModelDataV2.new_message())
    edges = iter((True, False, True, False, True, False))
    pending_request = [False]

    def drain_sock(sock, **_kwargs):
      if sock == 'carControl':
        if not pending_request[0]:
          return []
        pending_request[0] = False
        control = SimpleNamespace(cruiseControl=SimpleNamespace(cancel=True))
        # card actuates alive packets regardless of this validity bit.
        return [SimpleNamespace(valid=False, logMonoTime=int((clock[0] - .01) * 1e9), carControl=control)]

      try:
        pressed = next(edges)
      except StopIteration:
        return []
      sample = car.CarState.new_message(vEgo=10, canValid=True, gearShifter='drive')
      sample.buttonEvents = [{'type': 'cancel', 'pressed': pressed}]
      pending_request[0] = pressed
      return [SimpleNamespace(valid=True, logMonoTime=int(clock[0] * 1e9), carState=sample)]

    class Bluetooth:
      def read(self, **_kwargs):
        return None

    class Done(Exception):
      pass

    class Rate:
      frame = 0

      def keep_time(self):
        self.frame += 1
        if self.frame >= 8:
          raise Done

    class Publisher:
      def send(self, _, packet):
        packets.append(packet.to_dict())

    monkeypatch.setattr(dm2d.messaging, 'SubMaster', lambda *a, **kw: state)
    monkeypatch.setattr(dm2d.messaging, 'PubMaster', lambda *a: Publisher(), raising=False)
    monkeypatch.setattr(dm2d.messaging, 'sub_sock', lambda service, **kw: service, raising=False)
    monkeypatch.setattr(dm2d.messaging, 'drain_sock', drain_sock, raising=False)
    monkeypatch.setattr(dm2d, 'CommandReader', lambda *a: Bluetooth())
    monkeypatch.setattr(dm2d, 'DmRatekeeper', lambda *a, **kw: Rate())
    monkeypatch.setattr(dm2d.time, 'monotonic', lambda: clock[0])
    with self.assertRaises(Done):
      dm2d.run_dm2(params, experimental=False)

    assert params.writes == []
    assert all(not packet['driverMonitoringState']['dm2Disabled'] for packet in packets)
    assert all(not packet['driverMonitoringState']['wheeltouchPolicyState']['driverInteracting'] for packet in packets)


  def test_hyundai_openpilot_long_cancel_level_does_not_mask_physical_gesture(self, monkeypatch):
    clock = [100.0]

    class Params:
      def __init__(self):
        self.values = {"DriverMonitoringEnabled": True}
        self.writes = []

      def get_bool(self, name):
        return self.values.get(name, False)

      def get_int(self, _):
        return 0

      def put_bool_nonblocking(self, name, value):
        self.values[name] = value
        self.writes.append((name, value))

    params = Params()

    class State(dict):
      updated = {'carParams': False, 'radarState': True, 'driverStateV2': False}
      logMonoTime = {'driverStateV2': 0}

      def update(self, _):
        clock[0] += .2

      def all_checks(self, services):
        return 'driverStateV2' not in services

    state = State(carState=car.CarState.new_message(vEgo=10, canValid=True, gearShifter='drive'),
                  selfdriveState=log.SelfdriveState.new_message(enabled=True),
                  radarState=log.RadarState.new_message(), modelV2=log.ModelDataV2.new_message())
    edges = iter((True, False, True, False, True, False))
    controls_enabled = [True]

    def drain_sock(sock, **_kwargs):
      if sock == 'carControl':
        control = car.CarControl.new_message(enabled=controls_enabled[0])
        control.cruiseControl.cancel = True
        return [SimpleNamespace(valid=True, logMonoTime=int((clock[0] - .01) * 1e9), carControl=control)]

      try:
        pressed = next(edges)
      except StopIteration:
        return []
      sample = car.CarState.new_message(vEgo=10, canValid=True, gearShifter='drive')
      sample.buttonEvents = [{'type': 'cancel', 'pressed': pressed}]
      state['carState'] = sample
      if pressed and controls_enabled[0]:
        controls_enabled[0] = False
        state['selfdriveState'] = log.SelfdriveState.new_message(enabled=False)
      return [SimpleNamespace(valid=True, logMonoTime=int(clock[0] * 1e9), carState=sample)]

    class Bluetooth:
      def read(self, **_kwargs):
        return None

    class Done(Exception):
      pass

    class Rate:
      frame = 0

      def keep_time(self):
        self.frame += 1
        if self.frame >= 8:
          raise Done

    class Publisher:
      def send(self, *_):
        pass

    cp = car.CarParams.new_message(brand='hyundai', openpilotLongitudinalControl=True)
    assert not dm2d.cancel_echo_filter_required(cp)

    monkeypatch.setattr(dm2d.messaging, 'SubMaster', lambda *a, **kw: state)
    monkeypatch.setattr(dm2d.messaging, 'PubMaster', lambda *a: Publisher(), raising=False)
    monkeypatch.setattr(dm2d.messaging, 'sub_sock', lambda service, **kw: service, raising=False)
    monkeypatch.setattr(dm2d.messaging, 'drain_sock', drain_sock, raising=False)
    monkeypatch.setattr(dm2d, 'CommandReader', lambda *a: Bluetooth())
    monkeypatch.setattr(dm2d, 'DmRatekeeper', lambda *a, **kw: Rate())
    monkeypatch.setattr(dm2d.time, 'monotonic', lambda: clock[0])
    with self.assertRaises(Done):
      dm2d.run_dm2(params, experimental=False, initial_car_params=cp)

    assert params.writes == [("DriverMonitoringSessionDisabled", True)]
    assert params.values["DriverMonitoringSessionDisabled"] is True


  @parameterized.expand([
    ('hyundai', True, False),
    ('hyundai', False, True),
    ('gm', True, True),
  ], names=('brand', 'openpilot_longitudinal', 'required'))
  def test_cancel_echo_filter_scope(self, brand, openpilot_longitudinal, required):
    cp = car.CarParams.new_message(brand=brand, openpilotLongitudinalControl=openpilot_longitudinal)
    assert dm2d.cancel_echo_filter_required(cp) is required
    assert dm2d.cancel_echo_filter_required(None)


  def test_replay_route_time_gap_resets_cancel_sequence(self, monkeypatch):
    route_times = iter((10.0, 10.05, 10.40, 10.45, 10.50, 10.55, 10.60))
    current_time = [0.0]

    class Params:
      writes = []

      def get_bool(self, name):
        return name == "DriverMonitoringEnabled"

      def get_int(self, _):
        return 0

      def put_bool_nonblocking(self, name, value):
        self.writes.append((name, value))

    params = Params()

    class State(dict):
      updated = {'carParams': False, 'radarState': True, 'driverStateV2': False}
      logMonoTime = {'driverStateV2': 0, 'modelV2': 0}

      def update(self, _):
        current_time[0] = next(route_times)
        self.logMonoTime['modelV2'] = int(current_time[0] * 1e9)

      def all_checks(self, services):
        return 'driverStateV2' not in services

    state = State(carState=car.CarState.new_message(vEgo=10, canValid=True, gearShifter='drive'),
                  selfdriveState=log.SelfdriveState.new_message(enabled=True),
                  radarState=log.RadarState.new_message(), modelV2=log.ModelDataV2.new_message())
    edges = iter((True, False, True, False, True, False))

    def drain_sock(sock, **_kwargs):
      if sock != 'carState':
        return []
      try:
        pressed = next(edges)
      except StopIteration:
        return []
      sample = car.CarState.new_message(vEgo=10, canValid=True, gearShifter='drive')
      sample.buttonEvents = [{'type': 'cancel', 'pressed': pressed}]
      return [SimpleNamespace(valid=True, logMonoTime=int(current_time[0] * 1e9), carState=sample)]

    class Bluetooth:
      def read(self, **_kwargs):
        return None

    class Done(Exception):
      pass

    class Rate:
      frame = 0

      def keep_time(self):
        self.frame += 1
        if self.frame >= 7:
          raise Done

    class Publisher:
      def send(self, *_args):
        pass

    monkeypatch.setenv('REPLAY', '1')
    monkeypatch.setattr(dm2d.messaging, 'SubMaster', checked_submaster(state, replay=True))
    monkeypatch.setattr(dm2d.messaging, 'PubMaster', lambda *a: Publisher(), raising=False)
    monkeypatch.setattr(dm2d.messaging, 'sub_sock', lambda service, **kw: service, raising=False)
    monkeypatch.setattr(dm2d.messaging, 'drain_sock', drain_sock, raising=False)
    monkeypatch.setattr(dm2d, 'CommandReader', lambda *a: Bluetooth())
    monkeypatch.setattr(dm2d, 'Ratekeeper', lambda *a, **kw: Rate())
    with self.assertRaises(Done):
      dm2d.run_dm2(params, experimental=False)

    assert params.writes == []


  @parameterized.expand([
    ({"DriverMonitoringEnabled": True, "DriverMonitoringSessionDisabled": True},
     "DriverMonitoringSessionDisabled", None),
    ({"DriverMonitoringEnabled": False}, "DriverMonitoringEnabled", True),
  ], names=('initial_values', 'changed_key', 'changed_value'))
  def test_monitoring_enable_change_reenables_with_fresh_state(self, monkeypatch, initial_values, changed_key, changed_value):
    clock, packets = [100.0], []

    class Params:
      def __init__(self):
        self.values = dict(initial_values)

      def get_bool(self, name):
        return self.values.get(name, False)

      def get_int(self, _):
        return 0

    params = Params()

    class State(dict):
      updated = {'carParams': False, 'radarState': True, 'driverStateV2': False}
      logMonoTime = {'driverStateV2': 0}
      frames = 0

      def update(self, _):
        self.frames += 1
        clock[0] += .05
        if self.frames == 41:
          if changed_value is None:
            # Model manager clearing the session key on the next ignition-on edge.
            params.values.pop(changed_key)
          else:
            # Model the persistent search-only Web setting being enabled.
            params.values[changed_key] = changed_value

      def all_checks(self, services):
        return 'driverStateV2' not in services

    state = State(carState=car.CarState.new_message(vEgo=10, canValid=True, gearShifter='drive'),
                  selfdriveState=log.SelfdriveState.new_message(enabled=True),
                  radarState=log.RadarState.new_message(), modelV2=log.ModelDataV2.new_message())

    class Bluetooth:
      def read(self, **_kwargs):
        return None

    class Done(Exception):
      pass

    class Rate:
      frame = 0

      def keep_time(self):
        self.frame += 1
        if self.frame >= 43:
          raise Done

    class Publisher:
      def send(self, _, packet):
        packets.append(packet.to_dict())

    created = []
    original_factory = dm2d.new_driver_monitor

    def factory(*args):
      monitor = original_factory(*args)
      created.append(monitor)
      return monitor

    monkeypatch.setattr(dm2d.messaging, 'SubMaster', lambda *a, **kw: state)
    monkeypatch.setattr(dm2d.messaging, 'PubMaster', lambda *a: Publisher(), raising=False)
    monkeypatch.setattr(dm2d.messaging, 'sub_sock', lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(dm2d.messaging, 'drain_sock', lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(dm2d, 'CommandReader', lambda *a: Bluetooth())
    monkeypatch.setattr(dm2d, 'new_driver_monitor', factory)
    monkeypatch.setattr(dm2d, 'DmRatekeeper', lambda *a, **kw: Rate())
    monkeypatch.setattr(dm2d.time, 'monotonic', lambda: clock[0])
    with self.assertRaises(Done):
      dm2d.run_dm2(params, experimental=False)

    assert len(created) == 2
    assert all(packet['driverMonitoringState']['dm2Disabled'] for packet in packets[:40])
    assert all(not packet['driverMonitoringState']['dm2Disabled'] for packet in packets[40:])


  @parameterized.expand([(False, 'bt'), (True, 'bt'), (False, 'touch'), (True, 'touch')], names=('experimental', 'source'))
  def test_live_camera_response_defers_only_experimental_monitoring(self, monkeypatch, experimental, source):
    clock, packets = [100.0], []

    class Params:
      def get_bool(self, name):
        return name == "DriverMonitoringEnabled"

      def get_int(self, _):
        return int(experimental)

    class State(dict):
      updated = {'carParams': False, 'radarState': True, 'driverStateV2': True}
      logMonoTime = {'driverStateV2': 0}

      def update(self, _):
        clock[0] += .05
        self.logMonoTime['driverStateV2'] = int(clock[0] * 1e9)
        if source == 'touch':
          self['carState'].steeringTouch = {'available': True, 'valid': True, 'touched': clock[0] >= 103,
                                           'sampleMonoTime': int(clock[0] * 1e9)}

      def all_checks(self, _):
        return True

    model = log.ModelDataV2.new_message()
    model.meta.disengagePredictions.brakeDisengageProbs = [0.0]
    # Production SubMaster exposes read-only Cap'n Proto arrays, not Python
    # lists. Populate the road fields so short-circuiting cannot hide API errors.
    model.orientationRate.z = [0.] * 33
    model.laneLineProbs = [0., 1., 1., 0.]
    state = State(carState=car.CarState.new_message(vEgo=20, canValid=True, gearShifter='drive'),
                  selfdriveState=log.SelfdriveState.new_message(enabled=True), modelV2=model.as_reader(),
                  radarState=log.RadarState.new_message(), extrinsicsCalibration=log.ExtrinsicsCalibration.new_message(rpyCalib=[0., 0., 0.]),
                  driverStateV2=make_msg(True, distracted=True))

    class Bluetooth:
      sent = False

      def read(self, allowed, now):
        if source == 'bt' and allowed and not self.sent and now >= 103:
          self.sent = True
          return 'none'  # an unmapped real BT button still counts
        return None

    class Done(Exception):
      pass

    class Rate:
      frame = 0

      def keep_time(self):
        self.frame += 1
        if self.frame >= 1220:
          raise Done

    class Publisher:
      def send(self, _, packet):
        packets.append((clock[0], packet.to_dict()))

    monkeypatch.setattr(dm2d.messaging, 'SubMaster', checked_submaster(state))
    monkeypatch.setattr(dm2d.messaging, 'PubMaster', lambda *a: Publisher(), raising=False)
    monkeypatch.setattr(dm2d.messaging, 'sub_sock', lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(dm2d.messaging, 'drain_sock', lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(dm2d, 'CommandReader', lambda *a: Bluetooth())
    monkeypatch.setattr(dm2d, 'DmRatekeeper', lambda *a, **kw: Rate())
    monkeypatch.setattr(dm2d.time, 'monotonic', lambda: clock[0])
    with self.assertRaises(Done):
      dm2d.run_dm2(Params(), experimental)
    steady = [p['driverMonitoringState'] for t, p in packets if 104 < t < 147]
    if experimental:
      assert all(p['alertLevel'] == 'none' and p['dm2InteractionGraceRemaining'] > 0 for p in steady)
      assert packets[-1][1]['driverMonitoringState']['alertLevel'] == 'one'
    else:
      assert all(p['dm2InteractionGraceRemaining'] == 0 for p in steady)
      assert packets[-1][1]['driverMonitoringState']['alertLevel'] == 'three'
