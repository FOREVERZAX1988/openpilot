"""The parked preview's stand-in signals, against what they have to serve.

Three contracts are pinned here, and every one of them is easy to break from a
distance:

  * jetlink is handed the drive only while nothing is in control. The adapter's
    in_control() is False exactly when carState, carControl and carControlSP are
    alive and valid and neither carControl nor carControlSP says it is engaged,
    so a shim frame is fed through a real SubMaster and the adapter is asked.
  * CalibrationParams is read, never written: the whole reason the preview gets a
    stand-in for calibrationd instead of calibrationd itself is that a reset or a
    spread write here would damage the calibration the car actually drives with.
  * the parked frame claims a live carState and not a healthy CAN. valid is what
    the preview's own readers need; canValid is what every writer in the tree
    gates on, so a frame that claimed both would look enough like a driving car
    to open carrot_bluetooth's command path offroad.
"""
import time
import warnings
from unittest import mock

import numpy as np

from openpilot.cereal import log, messaging
from openpilot.common.params import Params
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.locationd.calibrationd import HEIGHT_INIT, INPUTS_NEEDED, RPY_INIT
from openpilot.sunnypilot import jetlink_adapter
from openpilot.sunnypilot.onroad_preview_shim import (CALIBRATION_EVERY, PUBLISH_HZ, SERVICES,
                                                      calibration_message, parked_messages,
                                                      publish_frame, stored_calibration,
                                                      stored_calibration_bytes)

CALIBRATED_BLOCKS = 42


class RecordingPub:
  """A PubMaster that keeps what it was handed, in order."""

  def __init__(self):
    self.sent: list[tuple[str, object]] = []

  def send(self, service: str, msg) -> None:
    self.sent.append((service, msg))

  @property
  def services(self) -> list[str]:
    return [service for service, _ in self.sent]


def calibration_blob(rpy=(0.011, -0.022, 0.003), spread=(1e-4, 2e-4, 3e-4),
                     wide=(0.10, 0.20, 0.30), height=(1.234,), valid_blocks=CALIBRATED_BLOCKS) -> bytes:
  """The Event calibrationd leaves in CalibrationParams (its get_msg().to_bytes())."""
  msg = messaging.new_message('extrinsicsCalibration')
  msg.valid = True
  msg.extrinsicsCalibration.rpyCalib = list(rpy)
  msg.extrinsicsCalibration.rpyCalibSpread = list(spread)
  msg.extrinsicsCalibration.wideFromDeviceEuler = list(wide)
  msg.extrinsicsCalibration.height = list(height)
  msg.extrinsicsCalibration.validBlocks = valid_blocks
  return msg.to_bytes()


def calibration_msg():
  """What the shim publishes as extrinsicsCalibration, from this test's store."""
  return calibration_message(*stored_calibration(Params()))


class TestThePublishedFrame(OpenpilotTestCase):
  def test_the_declared_rates_are_the_services_own(self):
    self.assertEqual(PUBLISH_HZ, 100)
    self.assertEqual(CALIBRATION_EVERY, 25)  # extrinsicsCalibration is a 4 Hz service
    self.assertEqual(SERVICES, ('carState', 'carControl', 'carControlSP', 'extrinsicsCalibration'))

  def test_every_parked_frame_carries_the_three_control_path_services(self):
    pm = RecordingPub()
    publish_frame(pm, calibration_msg(), 1)
    self.assertEqual(pm.services, ['carState', 'carControl', 'carControlSP'])
    for service, msg in pm.sent:
      self.assertEqual(msg.which(), service, f"a {msg.which()} went to the {service} socket")

  def test_the_stored_calibration_goes_out_on_its_own_four_hz_service(self):
    pm = RecordingPub()
    publish_frame(pm, calibration_msg(), 0)
    self.assertEqual(pm.services, list(SERVICES))
    self.assertEqual(pm.sent[-1][1].which(), 'extrinsicsCalibration')

    pm = RecordingPub()
    publish_frame(pm, calibration_msg(), CALIBRATION_EVERY)
    self.assertEqual(pm.services, list(SERVICES))

  def test_the_parked_frame_opens_the_swap_window(self):
    # a real SubMaster, driven with one shim frame, as modeld's own would be
    pm = RecordingPub()
    publish_frame(pm, calibration_msg(), 0)
    frame = dict(pm.sent)
    sm = messaging.SubMaster(list(jetlink_adapter.IN_CONTROL))
    sm.update_msgs(time.monotonic(), [frame[s].as_reader() for s in jetlink_adapter.IN_CONTROL])

    self.assertTrue(sm.all_alive(jetlink_adapter.IN_CONTROL))
    self.assertTrue(sm.all_valid(jetlink_adapter.IN_CONTROL))
    self.assertFalse(jetlink_adapter.adapter().engaged(sm), "nothing is in control in a parked preview")

  def test_the_parked_frame_is_a_parked_car(self):
    msgs = parked_messages()
    self.assertTrue(msgs['carState'].valid)
    self.assertEqual(msgs['carState'].carState.vEgo, 0.0)
    self.assertTrue(msgs['carState'].carState.standstill)
    for service in ('carControl', 'carControlSP'):
      self.assertTrue(msgs[service].valid, f"{service} must be valid, in_control counts it invalid otherwise")

    control = msgs['carControl'].carControl
    self.assertFalse(control.enabled)
    self.assertFalse(control.latActive)
    self.assertFalse(control.longActive)

    # MADS counts as in control with its lateral paused, so it is off here too
    self.assertFalse(msgs['carControlSP'].carControlSP.mads.enabled)
    self.assertFalse(msgs['carControlSP'].carControlSP.mads.active)


class TestTheCalibrationItDrawsWith(OpenpilotTestCase):
  def test_it_is_the_calibration_calibrationd_stored(self):
    Params().put("CalibrationParams", calibration_blob(), block=True)

    rpy, spread, wide, height, valid_blocks = stored_calibration(Params())
    self.assertTrue(np.allclose(rpy, [0.011, -0.022, 0.003]))
    self.assertTrue(np.allclose(spread, [1e-4, 2e-4, 3e-4]))
    self.assertTrue(np.allclose(wide, [0.10, 0.20, 0.30]))
    self.assertTrue(np.allclose(height, [1.234]))
    self.assertEqual(valid_blocks, CALIBRATED_BLOCKS)

    msg = calibration_message(rpy, spread, wide, height, valid_blocks)
    cal = msg.extrinsicsCalibration
    self.assertTrue(msg.valid)
    self.assertEqual(cal.calStatus, log.ExtrinsicsCalibration.Status.calibrated)
    self.assertEqual(cal.calPerc, 100.0)
    self.assertTrue(np.allclose(cal.height, [1.234]))
    self.assertTrue(np.allclose(cal.rpyCalib, [0.011, -0.022, 0.003]))

  def test_reading_the_calibration_writes_nothing(self):
    # spec=['get']: any other call on the store -- a put, a put_bool -- raises
    params = mock.Mock(spec=['get'])
    params.get.return_value = calibration_blob()

    stored_calibration(params)

    self.assertEqual(params.mock_calls, [mock.call.get("CalibrationParams")])

  def test_no_stored_calibration_previews_uncalibrated(self):
    rpy, spread, wide, height, valid_blocks = stored_calibration(Params())
    self.assertEqual(valid_blocks, 0)
    self.assertTrue(np.allclose(rpy, RPY_INIT))
    self.assertTrue(np.allclose(height, HEIGHT_INIT))

    cal = calibration_message(rpy, spread, wide, height, valid_blocks).extrinsicsCalibration
    self.assertEqual(cal.calStatus, log.ExtrinsicsCalibration.Status.uncalibrated)
    self.assertEqual(cal.calPerc, 0.0)

  def test_an_unreadable_block_previews_uncalibrated_rather_than_dying(self):
    Params().put("CalibrationParams", b"not an event", block=True)
    rpy, spread, wide, height, valid_blocks = stored_calibration(Params())
    self.assertEqual(valid_blocks, 0)
    self.assertTrue(np.allclose(height, HEIGHT_INIT))
    self.assertFalse(np.isnan(rpy).any())

  def test_a_partly_built_calibration_says_how_far_it_got(self):
    _, spread, wide, _, _ = stored_calibration(Params())
    cal = calibration_message(RPY_INIT, spread, wide, HEIGHT_INIT, 2).extrinsicsCalibration
    self.assertEqual(cal.calStatus, log.ExtrinsicsCalibration.Status.uncalibrated)
    self.assertEqual(cal.calPerc, 2 * 100 // INPUTS_NEEDED)


class TestTheGate(OpenpilotTestCase):
  """Offroad and previewing, and never beside the real publishers."""

  class PreviewParams:
    def __init__(self, previewing: bool):
      self.previewing = previewing

    def get_bool(self, key: str) -> bool:
      assert key == "IsOnroadPreview"
      return self.previewing

  def test_the_truth_table(self):
    from openpilot.system.manager.process_config import onroad_preview_shim

    self.assertTrue(onroad_preview_shim(False, self.PreviewParams(True), None))
    self.assertFalse(onroad_preview_shim(True, self.PreviewParams(True), None), "the real card runs now")
    self.assertFalse(onroad_preview_shim(False, self.PreviewParams(False), None))

  def test_the_manager_starts_it_for_the_preview(self):
    from openpilot.system.manager.process_config import managed_processes

    shim = managed_processes["preview_shimd"]
    self.assertEqual(shim.module, "openpilot.sunnypilot.onroad_preview_shim")
    self.assertTrue(shim.should_run(False, self.PreviewParams(True), None))
    self.assertFalse(shim.should_run(True, self.PreviewParams(True), None))


class TestOnTheRealBus(OpenpilotTestCase):
  """One real send and receive, so the shim's PubMaster wiring is covered too and
  not only the shape of the messages."""

  def test_a_subscriber_gets_the_whole_parked_frame(self):
    pm = messaging.PubMaster(list(SERVICES))
    sm = messaging.SubMaster(list(SERVICES))
    publish_frame(pm, calibration_msg(), 0)

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not all(sm.seen.values()):
      sm.update(100)

    for service in SERVICES:
      self.assertTrue(sm.seen[service], f"{service} never arrived")
    self.assertEqual(sm['carState'].vEgo, 0.0)
    self.assertTrue(sm['carState'].standstill)
    self.assertFalse(sm['carControl'].enabled)
    self.assertFalse(sm['carControlSP'].mads.enabled)

  def test_the_four_hz_calibration_is_serialized_once_for_the_whole_preview(self):
    """This process re-sends one calibration for as long as the preview is up. A
    capnp message is write-once: feeding the builder there writes it again on every
    4 Hz frame, which capnp warns leaks (in memory and in the serialized data). So
    what goes on the bus is bytes, serialized once -- and the frame that draws the
    path keeps arriving."""
    Params().put("CalibrationParams", calibration_blob(), block=True)

    pm = messaging.PubMaster(list(SERVICES))
    sm = messaging.SubMaster(list(SERVICES))
    calibration = stored_calibration_bytes(Params())
    self.assertIsInstance(calibration, bytes, "serialized once, then sent as bytes")

    with warnings.catch_warnings(record=True) as caught:
      warnings.simplefilter("always")
      for frame in range(3 * CALIBRATION_EVERY):
        publish_frame(pm, calibration, frame)

      deadline = time.monotonic() + 5.0
      while time.monotonic() < deadline and not sm.seen["extrinsicsCalibration"]:
        sm.update(100)

    self.assertEqual([str(w.message) for w in caught if "written once" in str(w.message)], [],
                     "the calibration is serialized once, not written again every frame")
    self.assertTrue(sm.seen["extrinsicsCalibration"], "the 4 Hz calibration never arrived")
    self.assertTrue(sm.valid["extrinsicsCalibration"])
    self.assertTrue(np.allclose(sm["extrinsicsCalibration"].height, [1.234]))


class TestWhatTheParkedFrameDoesNotClaim(OpenpilotTestCase):
  """valid, and deliberately not canValid.

  carState.valid is what the preview needs -- a service a reader never heard from
  counts as dead, and the adapter's in_control() would never open. canValid is a
  different claim: it is the car's CAN health, and it is what every writer in the
  tree gates on. card, controlsd and selfdrived each check CS.canValid on their way to a
  sendcan or a CarParams write, and the one always-running consumer that does read
  carState offroad -- carrot_bluetooth's car_ok
  (sunnypilot/carrot/bluetooth/daemon.py:144) -- goes False on it, which is its
  hold_blocked branch. So the frame says "a car whose CAN is not there", which is
  the truth while parked offroad, and the preview's readers need nothing more.
  """

  def test_the_parked_car_is_valid_and_does_not_claim_can(self):
    car_state = parked_messages()['carState']
    self.assertTrue(car_state.valid)
    self.assertFalse(car_state.carState.canValid,
                     "a parked preview must not claim CAN health: every writer gates on it")

  def test_nothing_a_writer_publishes_is_in_the_frame(self):
    # the CAN writer, the engagement record, the fingerprint only card writes:
    # offroad each of them would be a lie, and none of them is published here
    for writer in ('sendcan', 'controlsState', 'selfdriveState', 'carParams', 'pandaStates'):
      self.assertNotIn(writer, SERVICES)

  def test_carrot_bluetooths_command_gate_stays_shut(self):
    """The daemon's own expression, over a real SubMaster fed one shim frame."""
    pm = RecordingPub()
    publish_frame(pm, calibration_msg(), 0)
    frame = dict(pm.sent)
    sm = messaging.SubMaster(['carState'])
    sm.update_msgs(time.monotonic(), [frame['carState'].as_reader()])

    # the gate is shut by the CAN claim, not by the service being absent: this is
    # exactly sunnypilot/carrot/bluetooth/daemon.py:144
    self.assertTrue(sm.alive['carState'] and sm.valid['carState'])
    self.assertFalse(sm['carState'].canValid)
    car_ok = sm.alive['carState'] and sm.valid['carState'] and sm['carState'].canValid
    self.assertFalse(car_ok, "a parked preview must not look like a car the bluetooth bridge may command")
