"""When the gyro<->cameraOdometry yaw-rate cross-check is allowed to lie.

The cross-check compares the IMU yaw rate against the model's yaw rate with a
tolerance of YAWRATE_CROSS_ERR_CHECK_FACTOR times the model's own std. While
driving that catches genuine divergence between IMU and vision. While the car
is parked (or crawling) it does not: the model legitimately reports yaw=0 with
a tiny std, but cranking the steering twists the body and the IMU honestly
reports it. Every such frame then counts as INPUT_INVALID, the gyro sensor
budget (limit 10, ~10 s decay) latches, and inputsOK goes false long enough
for selfdrived to raise locationdTemporaryError -- repeatedly, during
parking-lot driving.

Route 00000003--37ada6fd6a--0 (2026-11-26): 12 cross-check trips in 2.2 s,
all at vEgo=0.00 with ~60 deg of steering (err 0.033 vs threshold 0.030 rad/s);
deviceMotion.inputsOK went false exactly over that window. Below this speed the
cross-check is skipped and the ROTATION_SANITY_CHECK (10 rad/s) magnitude gate
still applies, so a genuinely broken gyro cannot sneak through. Same low-speed
reasoning as the posenetOK `car_speed <= 5.0` gate in locationd.get_msg.
"""
YAWRATE_CROSS_ERR_CHECK_FACTOR = 30  # tolerance = factor * model yaw-rate std
YAWRATE_CROSSCHECK_MIN_SPEED = 1.0  # m/s; below this the cross-check is skipped


def gyro_yawrate_crosscheck_valid(gyro_yawrate: float, gyro_bias_z: float,
                                  camodo_yawrate_mean: float, camodo_yawrate_std: float,
                                  car_speed: float) -> bool:
  """Would this gyro yaw rate pass the cameraOdometry cross-check?

  Standstill steering (vEgo below YAWRATE_CROSSCHECK_MIN_SPEED) is exempt: the
  camera's yaw-rate ground truth is meaningless there -- the model sees a
  stationary car (yaw=0, high confidence) while the IMU picks up body twist
  from steering drag. While moving, a divergence beyond
  YAWRATE_CROSS_ERR_CHECK_FACTOR * camodo_yawrate_std still trips.
  """
  if car_speed < YAWRATE_CROSSCHECK_MIN_SPEED:
    return True
  err = abs((gyro_yawrate - gyro_bias_z) - camodo_yawrate_mean)
  return err < YAWRATE_CROSS_ERR_CHECK_FACTOR * camodo_yawrate_std
