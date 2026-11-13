import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openpilot.sunnypilot.flm.shadow_producer import FlmShadowProducer


class ParamsStub:
  def __init__(self):
    self.enabled = True

  def get_bool(self, key):
    assert key == 'FlmShadowEnabled'
    return self.enabled


class TestFlmShadowProducer(unittest.TestCase):
  def fixture(self):
    cp = SimpleNamespace(carFingerprint='fixture',
                         lateralTuning=SimpleNamespace(torque=SimpleNamespace(latAccelFactor=3.0), which=lambda: 'torque'))
    params = ParamsStub()
    producer = FlmShadowProducer(cp, params)
    self.params = params
    lc = SimpleNamespace(saturated=False, actualLateralAccel=.4, desiredLateralAccel=.4,
                         desiredLateralJerk=0., error=0., errorRate=0., p=0., i=0., d=0., f=0., output=.1)
    lateral = SimpleNamespace(which=lambda: 'torqueState', torqueState=lc)
    self.now = 10_000_000_000
    values = {
      'carState': SimpleNamespace(vEgo=20., steeringPressed=False, brakePressed=False, gasPressed=False,
                                 canValid=True, canTimeout=False, steeringAngleDeg=1., steeringTorque=0.),
      'carControl': SimpleNamespace(latActive=True, actuators=SimpleNamespace(torque=-.1)),
      'carOutput': SimpleNamespace(actuatorsOutput=SimpleNamespace(torque=-.1)),
      'controlsState': SimpleNamespace(lateralControlState=lateral),
      'deviceMotion': SimpleNamespace(timestamp=self.now, angularVelocityDevice=SimpleNamespace(valid=True),
                                     orientationNED=SimpleNamespace(valid=True), inputsOK=True, sensorsOK=True, posenetOK=True),
      'extrinsicsCalibration': SimpleNamespace(calStatus='calibrated'),
      'lateralDelay': SimpleNamespace(lateralDelay=0.),
    }

    class SM(dict):
      def all_checks(self, services=None):
        return True
    sm = SM(values)
    sm.seen = dict.fromkeys(sm, True)
    sm.updated = dict(sm.seen)
    sm.logMonoTime = dict.fromkeys(sm, self.now)
    producer.calibrator = Mock(feed_extrinsics_calibration=lambda msg: None,
      build_calibrated_pose=lambda pose: SimpleNamespace(angular_velocity=SimpleNamespace(yaw=.02)))
    return producer, sm

  def ticks(self, producer, sm, count):
    pose = SimpleNamespace(orientation=SimpleNamespace(roll=0.))
    with patch('openpilot.sunnypilot.flm.shadow_producer.Pose.from_device_motion', return_value=pose), \
         patch('openpilot.sunnypilot.flm.shadow_producer.time.monotonic_ns', side_effect=lambda: self.now), \
         patch('time.clock_gettime_ns', side_effect=lambda clock: self.now, create=True):  # POSIX-only builtin; absent on Windows
      for _ in range(count):
        self.now += 50_000_000
        sm.logMonoTime = dict.fromkeys(sm, self.now)
        sm['deviceMotion'].timestamp = self.now
        producer.update(sm, None)

  def test_disabled_producer_is_unavailable_telemetry_only(self):
    producer, sm = self.fixture()
    self.params.enabled = False
    self.ticks(producer, sm, 10)
    self.assertIsNone(producer.identity)
    self.assertEqual(producer.verdict()['status'], 'unavailable')
    self.assertEqual(producer.verdict()['reason'], 'disabled')
    self.assertEqual(producer.verdict()['totalPoints'], 0)

  def test_param_flip_hard_resets_collected_windows(self):
    producer, sm = self.fixture()
    self.ticks(producer, sm, 400)
    self.assertGreater(len(producer.windows), 0)
    self.params.enabled = False
    self.ticks(producer, sm, 1)
    self.assertEqual(len(producer.windows), 0)
    self.assertIsNone(producer.identity)
    self.params.enabled = True
    self.ticks(producer, sm, 400)
    self.assertEqual(len(producer.windows), 1)

  def test_one_block_per_continuous_maneuver_and_genuine_boundary(self):
    producer, sm = self.fixture()
    self.ticks(producer, sm, 800)
    self.assertEqual(producer.optional_errors, 0)
    self.assertEqual(len(producer.windows), 1)
    first = producer.windows[0]
    self.assertEqual(len(first.response), 240)
    self.assertLessEqual(first.active_since_ns + 2_000_000_000, first.response[0].mono_ns)
    self.ticks(producer, sm, 500)
    self.assertEqual(len(producer.windows), 1)
    sm['controlsState'].lateralControlState.torqueState.desiredLateralAccel = -.4
    sm['carOutput'].actuatorsOutput.torque = .1
    self.ticks(producer, sm, 300)
    self.assertEqual(len(producer.windows), 2)
    self.assertNotEqual(first.block_id, producer.windows[1].block_id)
    self.assertLess(first.response[-1].mono_ns, producer.windows[1].response[0].mono_ns)

  def test_override_discards_prebuffer_and_preserves_alignment_history(self):
    producer, sm = self.fixture()
    self.ticks(producer, sm, 140)
    self.assertGreater(len(producer.pending), 0)
    sm['carState'].steeringPressed = True
    self.ticks(producer, sm, 1)
    self.assertEqual(len(producer.pending), 0)
    self.assertEqual(len(producer.points), 0)
    self.assertIsNone(producer.active_since_ns)
    self.assertGreater(len(producer.torques), 100)
    sm['carState'].steeringPressed = False
    self.ticks(producer, sm, 19)
    self.assertIsNone(producer.active_since_ns)
    self.assertEqual(len(producer.points), 0)
    self.ticks(producer, sm, 300)
    self.assertEqual(producer.optional_errors, 0)
    self.assertEqual(len(producer.windows), 1)

  def test_optional_source_errors_invalidate_without_raising(self):
    producer, sm = self.fixture()
    self.ticks(producer, sm, 400)
    self.assertEqual(len(producer.windows), 1)
    with patch.object(producer, '_update', side_effect=ValueError('malformed optional Params')):
      producer.update(sm, None)
    self.assertIsNone(producer.identity)
    self.assertEqual(len(producer.windows), 0)
    self.assertEqual(len(producer.torques), 0)
    self.assertEqual(producer.optional_errors, 1)

  def test_verdict_payload_without_result_carries_collection_counters(self):
    producer, sm = self.fixture()
    self.ticks(producer, sm, 800)
    v = producer.verdict()
    self.assertEqual(v['status'], 'collecting')
    self.assertEqual(v['latAccelFactor'], 0.0)
    self.assertEqual(v['trainWindows'], 0)
    self.assertEqual(v['heldoutWindows'], 0)
    self.assertEqual(v['totalPoints'], sum(len(w.response) for w in producer.windows))
    self.assertEqual(v['totalPoints'], 240)


if __name__ == '__main__':
  unittest.main()
