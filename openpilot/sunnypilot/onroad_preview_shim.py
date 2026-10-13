#!/usr/bin/env python3
"""The parked preview, given the onroad signals it is missing, and nothing more.

Device settings -> Onroad Preview renders the driving view while parked. camerad
and the stock modeld run for it, but every publisher of what that view draws is
gated on the device being started, so offroad the preview shows the camera and
nothing else:

  * selfdrive/ui/onroad/model_renderer.py draws the path, the lane lines and the
    leads only once an extrinsicsCalibration has arrived since the view was
    entered. calibrationd never runs offroad, so none does: the renderer returns
    before it draws anything, and the preview is a plain camera feed.
  * jetlink is handed the drive only while nothing else is in control -- the
    adapter's in_control(), read over carState, carControl and carControlSP.
    card, selfdrived and controlsd are all offroad too, so that check reads a
    carControl that never arrived and reports "in control" forever. The large
    model never gets a window to swap in, so even a preview that drew a path
    would only ever draw the comma's own model.

So this process stands in for those four messages while the preview is on and
the device is not started:

  * extrinsicsCalibration, built from the persisted CalibrationParams. A read:
    that file is never written here, so previewing cannot reset, spread or
    overwrite a calibration -- which a calibrationd started into the preview
    would risk, it param_put's every few seconds and resets a spread that looks
    like a remount.
  * carState, parked: standstill, vEgo 0.
  * carControl and carControlSP, disengaged.

It publishes nothing else and touches no hardware. controlsd, selfdrived and
card stay offroad exactly as before, so no control output exists for anything to
mistake for a drive, and the moment the device is actually started this process
is stopped and the real publishers take over. What it publishes is only what the
preview already assumes: a parked car.

The gate is onroad_preview_shim() in system/manager/process_config.py, over
`IsOnroadPreview` and `started`. The contract this serves is pinned by
sunnypilot/tests/test_onroad_preview_shim.py.
"""
from __future__ import annotations

from typing import NoReturn

import numpy as np

import openpilot.cereal.messaging as messaging
from openpilot.cereal import log
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.locationd.calibrationd import HEIGHT_INIT, INPUTS_NEEDED, RPY_INIT

# what this publishes, and how often. The three control-path services are 100 Hz
# services and a reader treats one as dead after 10/frequency seconds
# (cereal/messaging's SubMaster), so they go out on every loop;
# extrinsicsCalibration is a 4 Hz service and only its latest value is wanted,
# so it goes out every CALIBRATION_EVERY frames
SERVICES = ('carState', 'carControl', 'carControlSP', 'extrinsicsCalibration')
PUBLISH_HZ = 100
CALIBRATION_EVERY = PUBLISH_HZ // 4


def stored_calibration(params: Params) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
  """The persisted CalibrationParams, restored exactly as calibrationd restores
  itself in its own __init__, as (rpyCalib, rpyCalibSpread, wideFromDeviceEuler,
  height, validBlocks). Defaults while nothing is stored, which is what the
  renderer and modeld fall back to anyway. Read-only."""
  rpy = RPY_INIT
  spread = np.zeros(3, dtype=np.float64)
  wide_from_device_euler = np.zeros(3, dtype=np.float64)
  height = HEIGHT_INIT
  valid_blocks = 0

  stored = params.get("CalibrationParams")
  if stored:
    try:
      # the store keeps calibrationd's own Event, so the whole block comes back,
      # the spread included: it is not a Params key of its own
      with log.Event.from_bytes(stored) as msg:
        cal = msg.extrinsicsCalibration
        rpy = np.array(cal.rpyCalib)
        spread = np.array(cal.rpyCalibSpread)
        wide_from_device_euler = np.array(cal.wideFromDeviceEuler)
        height = np.array(cal.height)
        valid_blocks = cal.validBlocks
    except Exception:
      # an unreadable block must not take the preview down with it
      cloudlog.exception("onroad preview: unreadable CalibrationParams, previewing uncalibrated")

  return rpy, spread, wide_from_device_euler, height, valid_blocks


def calibration_message(rpy: np.ndarray, spread: np.ndarray, wide_from_device_euler: np.ndarray,
                        height: np.ndarray, valid_blocks: int):
  """One extrinsicsCalibration for a calibration already on disk: the same fields
  calibrationd.get_msg() fills, from the same values it restored itself from. The
  renderer reads only height off it; modeld reads rpyCalib and height."""
  msg = messaging.new_message('extrinsicsCalibration')
  msg.valid = True

  cal = msg.extrinsicsCalibration
  calibrated = valid_blocks >= INPUTS_NEEDED
  cal.validBlocks = valid_blocks
  cal.calStatus = (log.ExtrinsicsCalibration.Status.calibrated if calibrated
                   else log.ExtrinsicsCalibration.Status.uncalibrated)
  cal.calPerc = 100.0 if calibrated else min(100 * valid_blocks // INPUTS_NEEDED, 100)
  cal.rpyCalib = rpy.tolist()
  cal.rpyCalibSpread = spread.tolist()
  cal.wideFromDeviceEuler = wide_from_device_euler.tolist()
  cal.height = height.tolist()
  return msg


def parked_messages() -> dict:
  """One parked frame's control-path services, as {service: message}:

  * carState, standstill at vEgo 0. Every reader in the preview (the adapter's
    in_control, the speed on the HUD) got the never-updated default struct for
    this before; the values are the same, the service is simply alive now.
  * carControl and carControlSP, disengaged. This is the whole point: in_control()
    is False once these are alive and valid, which is the window jetlink's large
    model swaps in on. MADS counts as in control too, so it is disengaged with
    the rest.
  """
  car_state = messaging.new_message('carState')
  car_state.valid = True
  car_state.carState.vEgo = 0.0
  car_state.carState.standstill = True

  control = messaging.new_message('carControl')
  control.valid = True
  control.carControl.enabled = False
  control.carControl.latActive = False
  control.carControl.longActive = False

  control_sp = messaging.new_message('carControlSP')
  control_sp.valid = True
  control_sp.carControlSP.mads.enabled = False
  control_sp.carControlSP.mads.active = False

  return {'carState': car_state, 'carControl': control, 'carControlSP': control_sp}


def stored_calibration_bytes(params: Params) -> bytes:
  """The calibration this process publishes, read and serialized exactly once, as
  the bytes the 4 Hz service is fed. A capnp message is write-once, and this one is
  re-sent on every CALIBRATION_EVERY-th frame for as long as the preview is up: a
  builder here would be written again on every send, which capnp warns leaks (in
  memory and in the serialized data). Built from what calibrationd left on disk and
  never written back, as above."""
  return calibration_message(*stored_calibration(params)).to_bytes()


def publish_frame(pm, calibration, frame: int) -> None:
  """One loop: the parked services every frame, the stored calibration on every
  CALIBRATION_EVERY-th. `calibration` is the bytes from stored_calibration_bytes,
  so re-sending it writes nothing twice. Split out so a test can drive a real
  SubMaster with it and show the swap window actually opens."""
  for service, msg in parked_messages().items():
    pm.send(service, msg)
  if frame % CALIBRATION_EVERY == 0:
    pm.send('extrinsicsCalibration', calibration)


def main() -> NoReturn:
  pm = messaging.PubMaster(list(SERVICES))
  # read once -- nothing that writes CalibrationParams runs while the preview is up
  # (calibrationd is offroad), and the preview is entered deliberately -- and
  # serialized once: see stored_calibration_bytes.
  calibration = stored_calibration_bytes(Params())

  rk = Ratekeeper(PUBLISH_HZ, None)
  frame = 0
  while True:
    publish_frame(pm, calibration, frame)
    frame += 1
    rk.keep_time()


if __name__ == '__main__':
  main()
