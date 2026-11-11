"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import numpy as np

from opendbc.car.structs import car

from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL
from openpilot.sunnypilot import PARAMS_UPDATE_PERIOD
from openpilot.sunnypilot.flm.shadow_producer import FlmShadowProducer
from openpilot.sunnypilot.selfdrive.locationd.speed_bin_learner import SpeedBinLearner

RELAXED_MIN_BUCKET_POINTS = np.array([1, 200, 300, 500, 500, 300, 200, 1])

ALLOWED_CARS = ['toyota', 'hyundai', 'rivian', 'honda']


class TorqueEstimatorExt(SpeedBinLearner):
  def __init__(self, CP: car.CarParams):
    self.CP = CP
    self._params = Params()
    self.frame = -1
    # Seam A shadow (telemetry only, self-gates on FlmShadowEnabled): verdicts
    # ride the CustomReserved19 append fields; nothing in the learn path reads
    # them. update_flm_shadow is the only thing driving it.
    self.flm_shadow = FlmShadowProducer(CP, self._params)

    self.enforce_torque_control_toggle = self._params.get_bool("EnforceTorqueControl")  # only during init
    self.use_params = self.CP.brand in ALLOWED_CARS and self.CP.lateralTuning.which() == 'torque'
    self.use_live_torque_params = self._params.get_bool("LiveTorqueParamsToggle")
    self.custom_torque_params = self._params.get_bool("CustomTorqueParams")
    self.torque_override_enabled = self._params.get_bool("TorqueParamsOverrideEnabled")
    self.min_bucket_points = RELAXED_MIN_BUCKET_POINTS
    self.factor_sanity = 0.0
    self.friction_sanity = 0.0
    self.offline_latAccelFactor = 0.0
    self.offline_friction = 0.0

  def initialize_custom_params(self, decimated=False):
    # Self-tune runs on upstream's brands (use_params, set by torqued), or wherever the toggle is
    # on once torque control is enforced. Taken before update_use_params folds in the manual
    # override, which only pauses the learner's output.
    self_tune = self.use_live_torque_params if self.enforce_torque_control_toggle else self.use_params
    self.speed_binned = self.CP.lateralTuning.which() == 'torque' and self_tune
    self.update_use_params()

    if self.enforce_torque_control_toggle:
      if self._params.get_bool("LiveTorqueParamsRelaxedToggle"):
        self.min_bucket_points = RELAXED_MIN_BUCKET_POINTS / (10 if decimated else 1)
        self.factor_sanity = 0.5 if decimated else 1.0
        self.friction_sanity = 0.8 if decimated else 1.0

      if self._params.get_bool("CustomTorqueParams"):
        # typed on upstream's tune scale, like the manual override they share with
        from opendbc.sunnypilot.car.lateral_tune import get_tune_scale
        scale = get_tune_scale(self.CP)
        self.offline_latAccelFactor = float(self._params.get("TorqueParamsOverrideLatAccelFactor", return_default=True)) * scale
        self.offline_friction = float(self._params.get("TorqueParamsOverrideFriction", return_default=True)) / scale

    # bins and their cache must exist before the first get_msg
    self._init_speed_bins()

  def _update_params(self):
    if self.frame % int(PARAMS_UPDATE_PERIOD / DT_MDL) == 0:
      self.use_live_torque_params = self._params.get_bool("LiveTorqueParamsToggle")
      self.custom_torque_params = self._params.get_bool("CustomTorqueParams")
      self.torque_override_enabled = self._params.get_bool("TorqueParamsOverrideEnabled")

  def update_use_params(self):
    self._update_params()

    if self.enforce_torque_control_toggle:
      if self.custom_torque_params and self.torque_override_enabled:
        self.use_params = False
      else:
        self.use_params = self.use_live_torque_params

    self.frame += 1

  @staticmethod
  def update_flm_shadow(estimator, sm):
    """torqued main's per-loop hook: drive the Seam A shadow producer. Never
    raises into the TLS publication path (update() fails closed internally)."""
    shadow = getattr(estimator, 'flm_shadow', None)
    if shadow is not None:
      shadow.update(sm, estimator)
