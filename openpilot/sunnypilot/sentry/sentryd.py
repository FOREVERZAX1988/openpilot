#!/usr/bin/env python3
# Copyright (c) 2026, firestar5683 and StarPilot contributors
# SPDX-License-Identifier: MIT
"""Parked watch daemon: parking state monitoring with event records.

Ported from StarPilot's sentry_mode concept, with the scope narrowed by the
openpilot-architecture-engineer adjudication for this fork:

- The C3 has no cabin camera (DISABLE_DRIVER, confirmed on device), and the
  accelerometer is only published while onroad, so StarPilot's "someone is
  inside the cabin" semantics cannot be reproduced here. This daemon never
  infers occupancy. It watches the parked state and records events; the
  detection itself is expected to run off-device.
- The notification layer is not ported: StarPilot's notifications.py and
  web_push.py are bound to the Galaxy phone push ecosystem, which this fork
  does not have. The state is published on cereal instead, so any consumer
  (carrot PWA, web UI, log) can read the same fact.
- The motion detector (policy.P1) is in place but is not fed by an
  accelerometer here, so it stays in the sensor_unavailable path until a
  qualified input exists.

The daemon never touches the control path: it subscribes to device state
only and publishes its own state message.
"""
import time

from openpilot.common.swaglog import cloudlog
from openpilot.common.messaging import SubMaster
from openpilot.common.params import Params
from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert
from openpilot.sunnypilot.sentry.policy import Inputs, SentryPolicy, Settings


# Battery voltage the device must report before the watch is armed. The
# comma 3 sits around 12.6V with the car off; below this the pack is too
# low to keep the device awake for the whole watch.
MIN_BATTERY_VOLTAGE_MV = 12000

# How long a device-state gap is tolerated before the watch disarms. The
# daemon polls at 1Hz, so a gap means the state feed died.
MAX_DEVICE_STATE_GAP_S = 5.0

# Polling interval for the parked watch.
POLL_INTERVAL_S = 1.0

# The accelerometer threshold, expressed as a fraction of gravity. The
# value matches StarPilot's default sensitivity; it only becomes meaningful
# when a qualified motion source is wired in.
DEFAULT_SENSITIVITY = 0.04


class SentryDaemon:
  def __init__(self):
    self.params = Params()
    self.sm = SubMaster(["deviceState", "pandaStates", "peripheralState"])
    self.policy = SentryPolicy(Settings(sensitivity=DEFAULT_SENSITIVITY))
    self.last_state_ns: int | None = None
    self.last_decision = None

  def _device_fresh(self, now: float) -> bool:
    if self.last_state_ns is None:
      return False
    age = now - (self.last_state_ns / 1e9)
    return 0 <= age <= MAX_DEVICE_STATE_GAP_S

  def _ignition_off(self) -> bool:
    states = self.sm['pandaStates']
    if states is None:
      return False
    # Any panda reporting a live ignition line means the car is powered.
    for state in states:
      if getattr(state, "ignitionLine", False) or getattr(state, "ignitionCan", False):
        return False
    return True

  def _voltage_ok(self) -> bool:
    peripheral = self.sm['peripheralState']
    if peripheral is None:
      return False
    voltage = getattr(peripheral, "voltage", 0)
    return isinstance(voltage, int) and voltage >= MIN_BATTERY_VOLTAGE_MV

  def _offroad(self) -> bool:
    device = self.sm['deviceState']
    if device is None:
      return False
    # started=False means the device is not in an engaged drive, which is
    # the closest available proxy for "parked" in this fork.
    return not getattr(device, "started", True)

  def step(self, now: float) -> None:
    device = self.sm['deviceState']
    if device is not None:
      self.last_state_ns = getattr(device, "logMonoTime", None) or time.monotonic_ns()

    enabled = self.params.get_bool("SentryEnabled")
    inputs = Inputs(
      enabled=enabled,
      offroad=self._offroad(),
      voltage_ok=self._voltage_ok(),
      device_fresh=self._device_fresh(now),
      ignition_off=self._ignition_off(),
      sample=None,
    )
    decision = self.policy.update(now, inputs)
    if decision != self.last_decision:
      cloudlog.info("sentry state=%s event=%s remaining=%s",
                    decision.state, decision.event, decision.seconds_remaining)
      self.last_decision = decision

    # The local screen notification mirrors the state. The alert text is
    # static so the UI never has to parse a message.
    set_offroad_alert("Offroad_Sentry", decision.state == "armed",
                      extra_text="Parked watch is monitoring the vehicle")


def main():
  cloudlog.warning("sentryd starting")
  daemon = SentryDaemon()
  start = time.monotonic()
  while True:
    daemon.sm.update()
    daemon.step(time.monotonic() - start)
    time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
  main()
