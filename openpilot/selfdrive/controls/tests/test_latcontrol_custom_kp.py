import math

from openpilot.common.test import OpenpilotTestCase
from opendbc.car.toyota.values import CAR as TOYOTA

from openpilot.selfdrive.controls.lib.latcontrol_torque import (
  CUSTOM_KP_REFRESH_FRAMES,
  CUSTOM_KP_SCALE_LIMITS,
  KP_INTERP,
)
from openpilot.selfdrive.controls.tests.test_latcontrol_torque_buffer import get_controller


class ParamsStub:
  """Mirrors common.params.Params.get(key, return_default=False) exactly."""

  def __init__(self, value=None, raises=False):
    self._value = value
    self._raises = raises
    self.reads = 0

  def get(self, key, return_default=False):
    self.reads += 1
    if self._raises:
      # What a device raises while libparams_c.so predates params_keys.h.
      raise RuntimeError(f"UnknownKeyName {key!r}")
    return self._value


class TestLatControlCustomKp(OpenpilotTestCase):

  def setUp(self):
    self.controller, _ = get_controller(TOYOTA.TOYOTA_COROLLA_TSS2)

  def _pid_gains(self):
    return list(self.controller.pid._k_p[1])

  def _stock_gains(self):
    return [float(k) for k in KP_INTERP]

  def test_unregistered_key_falls_back_to_stock(self):
    # A device whose shared library does not know CustomKp yet must not die here.
    self.controller.params = ParamsStub(raises=True)
    self.assertEqual(self.controller._read_custom_kp_scale(), 1.0)

    self.controller.refresh_custom_kp_scale()
    self.assertEqual(self.controller._custom_kp_scale, 1.0)
    self.assertEqual(self._pid_gains(), self._stock_gains())

  def test_default_value_is_identity(self):
    pid_before = self.controller.pid
    self.controller.params = ParamsStub(1.0)
    self.controller.refresh_custom_kp_scale()
    self.assertIs(self.controller.pid, pid_before)
    self.assertEqual(self._pid_gains(), self._stock_gains())

  def test_scale_multiplies_the_curve(self):
    self.controller.params = ParamsStub(1.5)
    self.controller.refresh_custom_kp_scale()
    self.assertAlmostEqual(self.controller._custom_kp_scale, 1.5)
    self.assertEqual(self._pid_gains(), [k * 1.5 for k in self._stock_gains()])

  def test_scale_is_clamped(self):
    self.controller.params = ParamsStub(5.0)
    self.controller.refresh_custom_kp_scale()
    self.assertAlmostEqual(self.controller._custom_kp_scale, CUSTOM_KP_SCALE_LIMITS[1])
    self.assertEqual(self._pid_gains(), [k * CUSTOM_KP_SCALE_LIMITS[1] for k in self._stock_gains()])

    self.controller.params = ParamsStub(0.1)
    for _ in range(CUSTOM_KP_REFRESH_FRAMES):
      self.controller.refresh_custom_kp_scale()
    self.assertAlmostEqual(self.controller._custom_kp_scale, CUSTOM_KP_SCALE_LIMITS[0])
    self.assertEqual(self._pid_gains(), [k * CUSTOM_KP_SCALE_LIMITS[0] for k in self._stock_gains()])

  def test_non_finite_falls_back_to_stock(self):
    self.controller.params = ParamsStub(math.nan)
    self.assertEqual(self.controller._read_custom_kp_scale(), 1.0)
    self.controller.params = ParamsStub(math.inf)
    self.assertEqual(self.controller._read_custom_kp_scale(), 1.0)

  def test_unchanged_value_keeps_the_integrator(self):
    self.controller.params = ParamsStub(1.2)
    self.controller.refresh_custom_kp_scale()
    pid_after_first = self.controller.pid
    for _ in range(CUSTOM_KP_REFRESH_FRAMES * 2):
      self.controller.refresh_custom_kp_scale()
    self.assertIs(self.controller.pid, pid_after_first)
    self.assertEqual(self._pid_gains(), [k * 1.2 for k in self._stock_gains()])

  def test_refresh_cadence_matches_the_torque_override_extension(self):
    self.controller.params = ParamsStub(1.0)
    self.controller._kp_frame = -1
    self.controller.refresh_custom_kp_scale()
    self.assertEqual(self.controller.params.reads, 1)
    for _ in range(CUSTOM_KP_REFRESH_FRAMES - 1):
      self.controller.refresh_custom_kp_scale()
    self.assertEqual(self.controller.params.reads, 1)
    self.controller.refresh_custom_kp_scale()
    self.assertEqual(self.controller.params.reads, 2)
