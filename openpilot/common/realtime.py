"""Utilities for reading real time clocks and keeping soft real time constraints."""
import gc
import os
import sys
import time
from pathlib import Path

from setproctitle import getproctitle

from openpilot.common.utils import MovingAverage
from openpilot.common.hardware import PC


# time step for each process
DT_CTRL = 0.01  # controlsd
DT_MDL = 0.05  # model
DT_HW = 0.5  # hardwared and manager
DT_DMON = 0.05  # driver monitoring


class Priority:
  # CORE 2
  # - modeld = 55
  # - camerad = 54
  CTRL_LOW = 51 # plannerd & radard

  # CORE 3
  # - pandad = 55
  CTRL_HIGH = 53


def drop_realtime() -> None:
  if sys.platform == 'linux' and not PC:
    os.sched_setscheduler(0, os.SCHED_OTHER, os.sched_param(0))


def drop_realtime_safe() -> bool:
  """Lower the calling thread to SCHED_OTHER without ever raising.

  Ported from carrotpilot's ``cluster/cluster_git_status.py``. Use this for a
  helper thread that must not preempt the control path (periodic git status,
  network or storage polling) and whose failure to change policy must not take
  the process down. Returns whether the demotion was applied.
  """
  try:
    os.sched_setscheduler(0, os.SCHED_OTHER, os.sched_param(0))
    return True
  except (AttributeError, OSError, ValueError):
    return False


def get_available_cores() -> set[int]:
  """CPUs this process is currently allowed to run on.

  On Comma hardware the big cluster (4-7) is taken offline by hardwared's power
  save mode whenever the device is offroad with the screen off. Calling
  os.sched_setaffinity() with an offline CPU raises EINVAL, which used to kill
  daemons (modeld boots straight into a hard-coded `config_realtime_process(7, 54)`).
  """
  if sys.platform == 'linux':
    try:
      return set(os.sched_getaffinity(0))
    except OSError:
      pass
  return set(range(os.cpu_count() or 1))


def _parse_cpu_list(spec: str) -> set[int]:
  """Parse a kernel cpu list ("0-3,6-7") into a set of cpus."""
  cores: set[int] = set()
  for group in spec.strip().split(','):
    if not group:
      continue
    bounds = group.split('-', maxsplit=1)
    first = int(bounds[0])
    last = int(bounds[-1])
    if last < first:
      raise ValueError(f"bad cpu range: {group!r}")
    cores.update(range(first, last + 1))
  return cores


def get_online_cores() -> set[int]:
  """CPUs the kernel currently reports as online.

  Deliberately different from get_available_cores(), which reports this process's
  affinity mask. A process that pinned itself to one core (the UI bootstraps with
  config_realtime_process(0, ...)) keeps that narrow mask forever, so using the
  mask as the definition of "available" makes every later re-pin a silent no-op:
  the mask never mentions the big cluster again, even after power save brings it
  back online. The UI stayed on core 0 for its whole lifetime because of this.
  """
  if sys.platform == 'linux':
    try:
      cores = _parse_cpu_list(Path("/sys/devices/system/cpu/online").read_text(encoding="utf-8"))
      if cores:
        return cores
    except (OSError, ValueError):
      pass
  return set(range(os.cpu_count() or 1))


def pick_online_core(preference: tuple[int, ...] | list[int], online: set[int] | None = None) -> list[int]:
  """Return the first CPU in `preference` that is online, or [] when none is.

  Kept separate from the callers so the preference order is testable without
  importing the UI. `online` defaults to the kernel's online set, never this
  process's affinity mask (see get_online_cores).
  """
  if online is None:
    online = get_online_cores()
  for core in preference:
    if core in online:
      return [core]
  return []


def set_core_affinity(cores: list[int]) -> set[int]:
  """Pin the current process to `cores`, skipping any CPU that is not online.

  Returns the set of CPUs actually pinned. An empty set means no pinning was
  applied, either because `cores` were all unavailable (power save offlined the
  big cluster) or because this is not a Linux Comma device. Never raises on an
  offline core: a daemon degraded to the wrong core is recoverable, a daemon
  that fails to start is not.
  """
  if not (sys.platform == 'linux' and not PC):
    return set()

  # online, not this process's mask: a mask narrowed by an earlier pin must not
  # veto widening back onto the big cluster once power save has re-onlined it.
  online = get_online_cores()
  usable = [c for c in cores if c in online]
  if not usable:
    return set()

  try:
    os.sched_setaffinity(0, usable)
  except OSError:
    return set()
  return set(usable)


def config_realtime_process(cores: int | list[int], priority: int) -> None:
  gc.disable()
  if sys.platform == 'linux' and not PC:
    os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(priority))
  c = cores if isinstance(cores, list) else [cores, ]
  set_core_affinity(c)


class Ratekeeper:
  def __init__(self, rate: float, print_delay_threshold: float | None = 0.0) -> None:
    """Rate in Hz for ratekeeping. print_delay_threshold must be nonnegative."""
    self._interval = 1. / rate
    self._print_delay_threshold = print_delay_threshold
    self._frame = 0
    self._remaining = 0.0
    self._process_name = getproctitle()
    self._last_monitor_time = -1.
    self._next_frame_time = -1.

    self.avg_dt = MovingAverage(100)
    self.avg_dt.add_value(self._interval)

  @property
  def frame(self) -> int:
    return self._frame

  @property
  def remaining(self) -> float:
    return self._remaining

  @property
  def lagging(self) -> bool:
    expected_dt = self._interval * (1 / 0.9)
    return self.avg_dt.get_average() > expected_dt

  # Maintain loop rate by calling this at the end of each loop
  def keep_time(self) -> bool:
    lagged = self.monitor_time()
    if self._remaining > 0:
      time.sleep(self._remaining)
    return lagged

  # Monitors the cumulative lag, but does not enforce a rate
  def monitor_time(self) -> bool:
    if self._last_monitor_time < 0:
      self._next_frame_time = time.monotonic() + self._interval
      self._last_monitor_time = time.monotonic()

    prev = self._last_monitor_time
    self._last_monitor_time = time.monotonic()
    self.avg_dt.add_value(self._last_monitor_time - prev)

    lagged = False
    now = time.monotonic()
    remaining = self._next_frame_time - now
    if remaining < -self._interval:
      # more than a frame behind (e.g. a stall): resync instead of running catch-up frames back-to-back
      self._next_frame_time = now + self._interval
    else:
      self._next_frame_time += self._interval
    if self._print_delay_threshold is not None and remaining < -self._print_delay_threshold:
      print(f"{self._process_name} lagging by {-remaining * 1000:.2f} ms")
      lagged = True
    self._frame += 1
    self._remaining = remaining
    return lagged
