import numpy as np

from openpilot.cereal import log
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.locationd.locationd import (
  DEAD_POSE_MIN_SPEED, HandleLogResult, LocationEstimator, ObservationKind,
)


class FakeParams:
  """LocationEstimator only asks for the two IMU-calibration keys at init."""

  def get_bool(self, key, *args, **kwargs):
    return False

  def get(self, key, *args, **kwargs):
    return None


def camodo(rot, trans, rot_std, trans_std, timestamp_eof_ns):
  msg = log.Event.new_message()
  msg.logMonoTime = timestamp_eof_ns
  msg.valid = True
  c = msg.init('cameraOdometry')
  c.frameId = 0
  c.timestampEof = timestamp_eof_ns
  c.rot = list(rot)
  c.trans = list(trans)
  c.rotStd = list(rot_std)
  c.transStd = list(trans_std)
  return msg


class TestDeadPoseGate(OpenpilotTestCase):
  """The dead-pose gate decides on translation, not rotation.

  A dead pose is a model that reports zeros where the car moved. Rotation alone
  cannot say that: a straight road at 40 km/h has rot ~ 0 and a live camera, and
  the old rot-only gate threw those frames away. Measured on route 00000043/44
  (2026-11-21) the chestnut model's translation was 0.01 of vEgo on every moving
  frame while the small model on the same drive read 1.01, so translation is the
  evidence, at the one speed where it cannot be faked.
  """

  def setUp(self):
    super().setUp()
    self.est = LocationEstimator(False, params=FakeParams())
    self.est.device_from_calib = np.eye(3)
    self.t = 1_000_000_000_000

  def feed(self, rot, trans, rot_std, trans_std):
    msg = camodo(rot, trans, rot_std, trans_std, self.t)
    self.t += 50_000_000
    res = self.est.handle_log(None, 'cameraOdometry', msg.cameraOdometry)
    self.assertEqual(res, HandleLogResult.SUCCESS)
    return self.est.observations[ObservationKind.CAMERA_ODO_TRANSLATION]

  def assert_dropped(self):
    self.assertEqual(self.est.observations[ObservationKind.CAMERA_ODO_TRANSLATION].tolist(), [0.0, 0.0, 0.0])

  def assert_fed(self, trans):
    np.testing.assert_allclose(self.est.observations[ObservationKind.CAMERA_ODO_TRANSLATION], trans, atol=1e-5)

  def test_straight_road_at_speed_is_kept(self):
    # 40 km/h, dead ahead: rot is legitimately ~0, translation is not
    self.est.car_speed = 10.9
    self.feed([0.0, 0.0, 1e-5], [10.9, 0.0, 0.02], [0.001] * 3, [0.05] * 3)
    self.assert_fed([10.9, 0.0, 0.02])
    self.assertEqual(self.est._dead_pose_moving, 0)
    self.assertEqual(self.est._dead_pose_still, 0)

  def test_curving_at_speed_is_kept(self):
    self.est.car_speed = 8.0
    self.feed([0.01, 0.002, 0.09], [8.0, 0.1, 0.3], [0.01] * 3, [0.05] * 3)
    self.assert_fed([8.0, 0.1, 0.3])

  def test_dead_model_while_moving_is_dropped(self):
    # route 00000043: v 10 m/s, |trans| 0.07, transStd 0.037, rot 2e-4
    self.est.car_speed = 10.0
    self.feed([1e-4, 1e-5, 2e-4], [-0.07, 0.01, 0.02], [0.001] * 3, [0.037] * 3)
    self.assert_dropped()
    self.assertEqual(self.est._dead_pose_moving, 1)
    self.assertEqual(self.est._dead_pose_still, 0)

  def test_zeros_at_standstill_are_dropped(self):
    self.est.car_speed = 0.0
    self.feed([1e-4, 1e-5, 2e-4], [-0.03, 0.01, 0.01], [0.001] * 3, [0.037] * 3)
    self.assert_dropped()
    self.assertEqual(self.est._dead_pose_still, 1)
    self.assertEqual(self.est._dead_pose_moving, 0)

  def test_creeping_is_kept(self):
    # just over the moving threshold, a live pose still reports its speed
    self.est.car_speed = DEAD_POSE_MIN_SPEED + 0.2
    trans = [DEAD_POSE_MIN_SPEED + 0.2, 0.0, 0.0]
    self.feed([0.0, 0.0, 0.002], trans, [0.02] * 3, [0.05] * 3)
    self.assert_fed(trans)

  def test_recovering_model_is_fed_again(self):
    self.est.car_speed = 10.0
    self.feed([1e-4, 1e-5, 2e-4], [-0.07, 0.01, 0.02], [0.001] * 3, [0.037] * 3)
    self.assert_dropped()
    self.feed([0.0, 0.0, 1e-5], [10.0, 0.0, 0.0], [0.001] * 3, [0.05] * 3)
    self.assert_fed([10.0, 0.0, 0.0])
    self.assertEqual(self.est._dead_pose_moving, 1)
