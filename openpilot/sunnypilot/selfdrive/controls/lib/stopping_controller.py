"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

import numpy as np

from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState


class StoppingController:
  """Optional terminal-stop policy applied after stock LongControl.update()."""

  STOPPING_DECEL_RATE = 0.3  # m/s^2/s
  # once the wheels really stand (wheel pulse) and the hold delay has passed, press on firmly to stopAccel: the driver
  # presses to 1000-2400 N within 1-2 s of stopping (owner 2026-10-02: the car must not be able to move again, also on
  # a slope). 1.0 m/s^2/s reaches the default -2.0 (~2900 N) in ~1.9 s; the old 0.5 took ~3.7 s.
  STANDSTILL_HOLD_RATE = 1.0  # m/s^2/s
  # The standstill flag is the real wheel stop (wheel pulse counter). Driver 2026-10-05, after a slope stop at 15:53
  # where "at the last moment the hold locked early with a jerk": "let the car sit at -0.25 a while longer, then add the
  # parking force" -> 1.0 s at the end value before the ramp to stopAccel (was 0.2 s; the 10-03 "never more than 0.2 s"
  # was about the auto hold under a pedal, not this ramp). If the car creeps on a slope during that second the creep
  # path below raises the request on its own (CREEP_RATE_GROWTH), so the wait costs nothing on the flat and is bounded
  # on a hill.
  STANDSTILL_HOLD_DELAY_LEAD = 1.0  # s
  STANDSTILL_HOLD_DELAY_NO_LEAD = 1.0  # s
  STOPPING_FREEZE_MAX = 2.0  # s
  STOPPING_EXIT_DEBOUNCE = 0.2  # s
  STOPPING_FOLLOW_MIN = -0.10  # m/s^2
  STOPPING_FOLLOW_RATE = 2.0  # m/s^3
  CREEP_V_MIN = 0.03  # m/s
  CREEP_RATE_GROWTH = 1.5  # m/s^2/s per second of creep
  CREEP_RATE_MAX = 1.0  # m/s^2/s

  # The end of the stop. First road test of the template rule (route 000000ec, 2026-10-03, four op stops): holding
  # END_REQUEST -0.15 (~660 N) from 3 km/h was a STEP - the plan was at -0.63..-0.78 (1160-1560 N) when the car crossed
  # 3 km/h and the request fell to -0.15 within 0.3 s; the force dropped to 280-520 N, the car sped UP again (+0.1..+0.3
  # m/s^2, 1.7 -> 2.5 km/h) on its creep torque and then needed 3.4-4.3 s and 760-1000 N (-0.2..-0.25 m/s^2) to stop.
  # The driver felt exactly that: "at 3 km/h the brake suddenly lightens - wrong - there must be a smooth hand-over".
  # The driver's own hard stop that night (23:45:04, 36 km/h, 4880 N peak) still ended smoothly because the pedal came
  # off CONTINUOUSLY: -aEgo ~ 1.6 + 0.25 v (r 0.86), -3.4 m/s^2 at 27 km/h, -2.6 at 10, -1.4 at 3, -1.0 at 1 km/h -
  # the decel falls roughly linearly with speed to the wheel stop, never a step, and does not go light at the end.
  # So below BLEND_V the request follows a line in speed from the request it had at BLEND_V (a_entry) down to
  # END_REQUEST at 0 km/h: blend(v) = END_REQUEST + (a_entry - END_REQUEST) * (v / BLEND_V) ** BLEND_POW. It is a FLOOR
  # on the plan: the firmer of the plan and the line is sent, so the planner's own curve still wins while it is braking
  # harder (a late-seen lead), and the line takes over only where the planner eases off. A plan that wants to go
  # (a_target > 0, the lead moved off) releases it; after standstill the hold ramp to stopAccel applies unchanged.
  # END_REQUEST -0.50 (~1080 N by BF ~ 480 + 1200 * |req|) is the lightest request that still decelerates under ACC:
  # on this route 760-1000 N gave only -0.2..-0.25 m/s^2 (the pedal is not pressed, so the hybrid keeps its creep
  # torque), while -0.63..-0.78 gave -0.6..-1.07 at 3 km/h. The driver's template ends at 0.5-0.7 m/s^2.
  # Driver 2026-10-03 afternoon, after the -0.50 / -0.40 / -0.35 flat ends: "from 5 km/h to 0 use a formula: -0.5 at
  # 5 km/h, -0.3 at 0 km/h, interpolated - firmer at 5 km/h, then easing as the car comes to rest". So the line is
  # now piecewise linear through (BLEND_V, a_entry) -> (END_V_HI, END_HI) -> (0, END_LO); a_entry is at least END_HI.
  BLEND_V = 10.0 / 3.6  # m/s: the line starts here, at the request the car had at that moment
  END_V_HI = 5.0 / 3.6  # m/s
  END_HI = -0.50  # m/s^2 at END_V_HI (~1080 N)
  END_LO = -0.25  # m/s^2 at 0 km/h (~780 N); driver 2026-10-04: -0.30 "closer to perfect", -0.25 = the threshold
  # Driver 2026-10-04 (route 000000f2): "between 5 and 0 km/h not linear but parabolic: steeper from 5 to 2, flat from
  # 2 to 0" -> x^2 parabola -0.50/-0.41/-0.34/-0.29/-0.26/-0.25 ("closer to perfect"). An S-shaped table
  # (-0.50/-0.47/-0.40/-0.29/-0.25/-0.24) was "not better" and reverted. Then the driver gave his own points, close to
  # the parabola but a touch lighter in the middle: 4 km/h -0.40, 3 -0.33, 2 -0.27, 1 -0.25, 0 -0.25. Held as a table,
  # linearly interpolated at the actual speed every 10 ms (continuous curve).
  END_CURVE_V = [0.0, 1.0 / 3.6, 2.0 / 3.6, 3.0 / 3.6, 4.0 / 3.6, 5.0 / 3.6]  # m/s
  END_CURVE_A = [END_LO, -0.25, -0.27, -0.33, -0.40, END_HI]  # m/s^2
  END_PLAN_MIN = -0.25  # m/s^2: the plan must be braking this much at BLEND_V to count as stopping (a crawl-follow hovers near 0)
  END_RATE = 2.0  # m/s^3: how fast the request may move toward the line

  # Leaving the standstill hold (driver 2026-10-04, route 000000fa 14:43:32: "the brake release at launch is a jerk, as
  # if let go suddenly; make it linear and slow"). There the request went from the -2.0 hold (3960 N) to +0.7 in 0.5 s
  # at the Toyota windup limit: the PCM bled 3960 -> 0 N in 0.6 s while the gas request was already +0.6, and the car
  # lurched at +1.7 m/s^2 for the first 0.1 s. The brake pressure cannot move the car while the request is well below
  # zero, so the release keeps the fast rate down there and goes LINEAR AND SLOW only through the hand-over band where
  # the clamp falls off and the creep torque takes over: RELEASE_FAST up to RELEASE_BAND_LO, RELEASE_SLOW from there
  # up to RELEASE_BAND_HI, then the plan again. The first motion comes ~0.1 s later than before, the lurch is gone.
  RELEASE_FAST = 4.0  # m/s^3 (the stock windup limit)
  RELEASE_SLOW = 1.5  # m/s^3
  RELEASE_BAND_LO = -0.6  # m/s^2
  RELEASE_BAND_HI = 0.4  # m/s^2

  def __init__(self, stop_accel):
    self.stop_accel = stop_accel
    self.standstill_t = 0.0
    self.stopping_t = 0.0
    self.go_t = 0.0
    self.stopped_once = False
    self.creep_t = 0.0
    self.end_active = False
    self.a_entry = self.END_HI
    self.releasing = False

  def _blend(self, v_ego):
    if v_ego < self.END_V_HI:
      return float(np.interp(max(v_ego, 0.0), self.END_CURVE_V, self.END_CURVE_A))
    return float(np.interp(v_ego, [self.END_V_HI, self.BLEND_V], [self.END_HI, self.a_entry]))

  def _end_request(self, a_target, prev_accel, v_ego):
    target = min(a_target, self._blend(v_ego))  # the firmer of the plan and the line
    step = self.END_RATE * DT_CTRL
    return float(np.clip(target, prev_accel - step, prev_accel + step))

  def update(self, prev_state, state, CS, a_target, prev_accel, stock_accel, accel_limits, has_lead=False):
    if prev_state == LongCtrlState.stopping and state == LongCtrlState.pid and CS.standstill:
      self.go_t += DT_CTRL
      if self.go_t < self.STOPPING_EXIT_DEBOUNCE:
        state = LongCtrlState.stopping
    else:
      self.go_t = 0.0

    self.standstill_t = self.standstill_t + DT_CTRL if CS.standstill else 0.0
    self.stopping_t = self.stopping_t + DT_CTRL if state == LongCtrlState.stopping else 0.0
    if state != LongCtrlState.stopping:
      self.stopped_once = False
    elif CS.standstill:
      self.stopped_once = True

    creeping = self.stopped_once and not CS.standstill and CS.vEgo > self.CREEP_V_MIN
    self.creep_t = self.creep_t + DT_CTRL if creeping else 0.0

    # end-of-stop window: rolling below BLEND_V with a plan that is braking to a stop
    rolling = not CS.standstill and not self.stopped_once
    if state == LongCtrlState.off or not rolling or CS.vEgo >= self.BLEND_V or a_target > 0.0:
      self.end_active = False
    elif not self.end_active and a_target <= self.END_PLAN_MIN:
      self.end_active = True
      self.a_entry = min(prev_accel, self.END_HI)  # the line starts where the request is now, at least END_HI

    if state != LongCtrlState.stopping:
      if self.end_active:
        return state, float(np.clip(self._end_request(a_target, prev_accel, CS.vEgo), accel_limits[0], accel_limits[1]))
      # coming off the hold: linear, slow through the hand-over band (see RELEASE_*)
      if prev_state == LongCtrlState.stopping and state == LongCtrlState.pid and prev_accel < self.RELEASE_BAND_HI:
        self.releasing = True
      if self.releasing:
        if stock_accel <= prev_accel or prev_accel >= self.RELEASE_BAND_HI or state == LongCtrlState.off:
          self.releasing = False
          return state, stock_accel
        rate = self.RELEASE_FAST if prev_accel < self.RELEASE_BAND_LO else self.RELEASE_SLOW
        return state, float(min(stock_accel, prev_accel + rate * DT_CTRL))
      return state, stock_accel

    output_accel = prev_accel
    if output_accel > self.stop_accel:
      output_accel = min(output_accel, 0.0)
      if not CS.standstill and not self.stopped_once and a_target < self.STOPPING_FOLLOW_MIN and a_target > output_accel:
        output_accel = min(a_target, output_accel + self.STOPPING_FOLLOW_RATE * DT_CTRL)
      if self.end_active:
        # still rolling inside the end window: the line (or the plan where it is firmer), never the eased-off curve
        output_accel = self._end_request(a_target, prev_accel, CS.vEgo)

      hold_delay = self.STANDSTILL_HOLD_DELAY_LEAD if has_lead else self.STANDSTILL_HOLD_DELAY_NO_LEAD
      if self.standstill_t >= hold_delay:
        rate = self.STANDSTILL_HOLD_RATE
      elif creeping:
        rate = min(self.STOPPING_DECEL_RATE + self.CREEP_RATE_GROWTH * self.creep_t, self.CREEP_RATE_MAX)
      elif self.stopping_t >= self.STOPPING_FREEZE_MAX:
        rate = self.STOPPING_DECEL_RATE
      else:
        rate = 0.0
      output_accel -= rate * DT_CTRL

    return state, float(np.clip(output_accel, accel_limits[0], accel_limits[1]))