#!/usr/bin/env python3
import os
import time

from openpilot.cereal import messaging
from openpilot.common.hardware import COMMA_HARDWARE
from openpilot.common.realtime import Priority, config_realtime_process, pick_online_core, set_core_affinity
from openpilot.common.watchdog import kick_watchdog
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.layouts.main import MainLayout
from openpilot.selfdrive.ui.mici.layouts.main import MiciMainLayout
from openpilot.selfdrive.ui.ui_state import ui_state

if gui_app.sunnypilot_ui():
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.main import MiciMainLayoutSP as MiciMainLayout

BIG_UI = gui_app.big_ui()

# UI wants a big core to itself. The carrot layout owns the rest of the big
# cluster: card/plannerd/radard on 5, controlsd/selfdrived on 6, modeld on 7.
# Core 4 only hosts radarcan (CTRL_LOW), which this process outranks. Power
# save offlines the big cluster when offroad with the screen off, so the
# render loop re-affines once it is back online.
UI_CORES = (4, 5)


def resolve_ui_cores() -> list[int]:
  """Pick a CPU for the UI, skipping any core power save has taken offline.

  Must consult the kernel's online set, not this process's affinity mask: the UI
  bootstraps pinned to core 0, so its own mask never lists the big cluster and
  every later re-pin degraded to a no-op (UI stuck on core 0 -> dropped frames).
  """
  return pick_online_core(UI_CORES)


def main():
  # above plannerd and radard; core 0 only when power save has the big cluster offline
  config_realtime_process(resolve_ui_cores() or 0, Priority.CTRL_HIGH)

  gui_app.init_window("UI")
  if BIG_UI:
    MainLayout()
  else:
    MiciMainLayout()

  next_affinity_check = 0.0
  pm = messaging.PubMaster(['uiDebug'])
  for should_render, frame_time, cpu_time in gui_app.render():
    # Tell the manager this process is still making progress. A render loop
    # that stops ticking is exactly the failure restart_if_crash cannot see.
    kick_watchdog()
    extra_start = time.monotonic()
    ui_state.update()

    if should_render:
      # reaffine after power save offlines/onlines our core; rate limited so a
      # pending re-pin cannot turn into a per-frame syscall storm
      now = time.monotonic()
      if COMMA_HARDWARE and now >= next_affinity_check:
        next_affinity_check = now + 1.0
        target = resolve_ui_cores()
        if target and os.sched_getaffinity(0) != set(target):
          set_core_affinity(target)

      extra_cpu = time.monotonic() - extra_start
      msg = messaging.new_message('uiDebug')
      msg.uiDebug.cpuTimeMillis = (cpu_time + extra_cpu) * 1000
      msg.uiDebug.frameTimeMillis = frame_time * 1000
      pm.send('uiDebug', msg)


if __name__ == "__main__":
  main()
