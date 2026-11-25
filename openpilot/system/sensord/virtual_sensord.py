#!/usr/bin/env python3
"""Virtual sensord for comma devices with no physical IMU (e.g. C3XL).

Publishes the same accelerometer/gyroscope services as the real sensord so
locationd's sensor_all_checks() stays alive, but synthesizes the samples from
independent vehicle signals instead of an I2C IMU:

  - yaw rate: CAN carState.yawRate (ESC), with CHASSIS_YAW_INVALID sentinel
    filtered out. Falls back to cameraOdometry for roll/pitch axes only.
  - longitudinal accel: carState.aEgo from the CAN wheel-speed KF.
  - lateral accel: vEgo * yawRate from CAN (not cameraOdometry -> no self-proof).
  - gravity: fixed 9.81 on the sensor x axis (device z), giving the EKF the
    absolute roll/pitch reference it needs (cameraOdometry cannot provide it).

Safety contract (see .workbuddy/reports/车友无IMU-virtual-sensord补丁规格-20261125.md):
  - DEFAULT OFF: manager gate requires VirtualSensordEnabled=1 AND no physical
    IMU detected. Mutually exclusive with the real sensord.
  - source=velodyne: accepted by locationd (only bmx055 rejected) but NOT in
    the impact-dashcam whitelist, so synthetic data can never trigger impact
    detection. This also means impact detection is unavailable on such cars.
  - timestamp=logMonoTime (monotonic): wall-clock time.time_ns() would be off
    by the uptime and fail _validate_sensor_time -> inputsOK false -> no engage.
  - ImuCalibrationEnabled must be 0 (legacy calibrationd); a stale IMU matrix
    would corrupt the pose. Module exits if it is 1.

TODO(device-verify): vehicle->device axis signs for a_lat, and the sysfs IMU
detection node, are statically inferred and need a real-car route to confirm.
No part of this module has been built or run on a device.
"""
import time

import numpy as np

from opendbc.car.hyundai.values import HyundaiExtFlags
from openpilot.cereal import log
import openpilot.cereal.messaging as messaging
from openpilot.common.realtime import config_realtime_process, Ratekeeper
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.common.transformations.orientation import rot_from_euler
from openpilot.system.sensord.sensor_synth import build_gyro, build_accel, can_yaw_ok

SERVICES = ['accelerometer', 'gyroscope']
SOURCE = log.SensorEventData.SensorSource.velodyne
ROTATION_SANITY_CHECK = 10.0       # locationd.py:37
WARMUP_S = 0.5                     # cover manager's async stop() double-publish window


def send_pair(pm, accel: np.ndarray, gyro: np.ndarray) -> None:
  """Publish one acc/gyro pair using the exact capnp contract of the real sensord."""
  for service, union_name, values in (
    ('accelerometer', 'acceleration', accel),
    ('gyroscope', 'gyroUncalibrated', gyro),
  ):
    msg = messaging.new_message(service, valid=True)
    payload = getattr(msg, service)
    payload.timestamp = msg.logMonoTime        # monotonic, NOT time.time_ns()
    payload.source = SOURCE                    # velodyne: locationd accepts, impact ignores
    payload.init(union_name)                   # union must be explicitly initialized
    getattr(payload, union_name).v = np.asarray(values, dtype=float).tolist()
    pm.send(service, msg)


def main() -> None:
  config_realtime_process([2, ], 10)
  params = Params()
  if params.get_bool("ImuCalibrationEnabled"):
    cloudlog.warning("virtualsensord requires ImuCalibrationEnabled=0; exiting")
    return

  pm = messaging.PubMaster(SERVICES)
  sm = messaging.SubMaster(['carState', 'cameraOdometry', 'extrinsicsCalibration', 'carParams'],
                           poll='cameraOdometry')
  rk = Ratekeeper(104., print_delay_threshold=None)   # services.py:24-25
  warmup_until = time.monotonic() + WARMUP_S

  while True:
    sm.update()
    if not sm.all_checks() or time.monotonic() < warmup_until:
      rk.keep_time()
      continue

    ext = sm['extrinsicsCalibration']
    if len(ext.rpyCalib) != 3:
      rk.keep_time()
      continue
    device_from_calib = rot_from_euler(np.asarray(ext.rpyCalib, dtype=float))

    cs, CP = sm['carState'], sm['carParams']
    ok = can_yaw_ok(cs, CP, int(HyundaiExtFlags.CHASSIS_YAW_RATE), ROTATION_SANITY_CHECK)
    yaw_rate = float(cs.yawRate) if ok else 0.0
    accel = build_accel(abs(float(cs.vEgo)), yaw_rate, float(cs.aEgo), device_from_calib, ok)
    gyro = build_gyro(yaw_rate, sm['cameraOdometry'].rot, device_from_calib, ok)
    send_pair(pm, accel, gyro)
    rk.keep_time()


if __name__ == '__main__':
  main()
