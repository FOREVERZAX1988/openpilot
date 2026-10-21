"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
"""Which upstream features are pulled in but cannot work on this car.

Policy (driver's call, 2026-10-21): upstream is taken as-is. We do not delete a
feature just because our car (Porsche Macan, MLB evo) cannot use it -- deleting is
what makes the next upstream pull expensive, because every deletion comes back as a
conflict. Instead the switch stays on screen, renders greyed out, keeps its off
default and cannot be turned on. "Ported but not usable here" is then visible on the
device instead of buried in a doc.

One table drives both halves:

  * UI   -- `ui_enabled(param)` is passed to `toggle_item_sp` / `option_item_sp` as
            `enabled=`; the widget greys the row and drops clicks
            (system/ui/sunnypilot/widgets/option_control.py, toggle.py).
  * Data -- `enforce(params)` runs once when carrot_server starts and forces the key
            back to off, so a value left in /data/params by an earlier build -- or
            restored from a backup made on another car -- cannot silently drive the
            feature.

Adding the next pull: one row in UNSUPPORTED. `tests/test_feature_support.py` fails if
the key is not in common/params_keys.h, so an upstream rename shows up as a red test
instead of a dead switch.
"""

import threading
from dataclasses import dataclass
from typing import Any, Callable

#: Platforms this fork actually drives. Only these are checked: an unknown fingerprint
#: means someone is running a car we never validated, and guessing there is worse than
#: leaving the switch live.
OUR_CARS = frozenset({"PORSCHE_MACAN_MK1"})


@dataclass(frozen=True)
class Unsupported:
  """A param that is ported, has a UI face, and is inert on `cars`."""

  #: Param key written by the UI switch.
  param: str
  #: Fingerprints where the feature cannot work.
  cars: frozenset[str]
  #: Shown appended to the row's description so the grey-out has a reason on screen.
  reason: str
  #: Value written by `enforce()` -- the "off" for this key's param type.
  off: Any = False
  #: False for keys with no settings-page switch (headless coefficients). The UI wiring
  #: test only requires `enabled=` on the rows that actually appear on a page.
  on_screen: bool = True


UNSUPPORTED: tuple[Unsupported, ...] = (
  Unsupported(
    param="AutoGasSyncSpeed",
    cars=OUR_CARS,
    reason="Tesla / BYD only: nothing on the Macan gateway re-synchronizes the ACC set speed.",
    off=False,
  ),
  Unsupported(
    param="EnableRadarTracks",
    cars=OUR_CARS,
    reason="BYD corner radar only: the Macan ACC module keeps its target list internal, "
           "so there are no tracks to feed in.",
    off=False,
  ),
  Unsupported(
    param="NNFFMode",
    cars=OUR_CARS,
    reason="No torque model for a Macan: none of the 121 models is a PORSCHE and opendbc has no substitute, so this falls back to stock torque math.",
    off=0,
  ),
  Unsupported(
    param="CarrotFastRadarEnabled",
    cars=OUR_CARS,
    reason="Hyundai only: plannerd keeps liveTracks switched on whenever this key is set and "
           "then requires CarParams.brand == hyundai before using them, so on the Macan the "
           "switch can be set but never act.",
    off=False,
  ),
)

_BY_PARAM: dict[str, Unsupported] = {row.param: row for row in UNSUPPORTED}

_fp_lock = threading.Lock()
_fp_cached = False
_fp_value: str | None = None


def reset_cache() -> None:
  """Drop the cached fingerprint (tests; a car change needs a reboot anyway)."""
  global _fp_cached, _fp_value
  with _fp_lock:
    _fp_cached = False
    _fp_value = None


def current_fingerprint() -> str | None:
  """CarParams.carFingerprint from /data/params, or None when it is not there yet."""
  global _fp_cached, _fp_value
  with _fp_lock:
    if _fp_cached:
      return _fp_value
  fp: str | None = None
  try:
    from openpilot.common.params import Params

    raw = Params().get("CarParams")
    if raw is not None:
      from opendbc.car.structs import car

      with car.CarParams.from_bytes(raw) as cp:
        fp = str(cp.carFingerprint) or None
  except Exception:
    # No CarParams yet (fresh install / offroad before card runs) or an unreadable blob:
    # "unknown platform" is the safe answer, and a stale value is never cached.
    return None
  with _fp_lock:
    _fp_value = fp
    _fp_cached = True
  return fp


def row(param: str) -> Unsupported | None:
  """The table row for `param`, regardless of platform."""
  return _BY_PARAM.get(param)


def unsupported_row(param: str, fingerprint: str | None = None) -> Unsupported | None:
  """The row for `param` if it is inert on `fingerprint` (default: this car)."""
  r = _BY_PARAM.get(param)
  if r is None:
    return None
  fp = current_fingerprint() if fingerprint is None else fingerprint
  return r if fp in r.cars else None


def is_supported(param: str, fingerprint: str | None = None) -> bool:
  """True when the switch for `param` should be live."""
  return unsupported_row(param, fingerprint) is None


def ui_enabled(param: str, fingerprint: str | None = None) -> Callable[[], bool]:
  """`enabled=` callable for toggle_item_sp / option_item_sp (re-evaluated per frame)."""
  return lambda: is_supported(param, fingerprint)


def describe(param: str, base: str | None, fingerprint: str | None = None) -> str | None:
  """Append the reason to a row description when the switch is inert on this car."""
  r = unsupported_row(param, fingerprint)
  if r is None:
    return base
  return f"{base} — {r.reason}" if base else r.reason


def enforce(params: Any = None, fingerprint: str | None = None) -> list[str]:
  """Force every inert-on-this-car key back to off. Returns the keys that were changed.

  Idempotent and cheap: one Params read per table row, writes only on a mismatch.
  """
  rows = UNSUPPORTED
  if not rows:
    return []
  fp = current_fingerprint() if fingerprint is None else fingerprint
  if fp not in OUR_CARS:
    return []
  if params is None:
    from openpilot.common.params import Params

    params = Params()

  changed: list[str] = []
  for r in rows:
    if fp not in r.cars:
      continue
    try:
      current = params.get(r.param)
    except Exception:
      continue
    if current in (None, b"", ""):
      # Absent means "registered default", which is already off for these keys.
      continue
    if _is_off(current, r.off):
      continue
    try:
      params.put(r.param, r.off)
    except Exception:
      continue
    changed.append(r.param)
  return changed


def _is_off(current: Any, off: Any) -> bool:
  if isinstance(current, bytes):
    current = current.decode("utf-8", "replace")
  if isinstance(current, str):
    current = current.strip()
    if current.lower() in ("false", "0", ""):
      return True
    try:
      return float(current) == float(bool(off) if isinstance(off, bool) else off)
    except ValueError:
      return False
  if isinstance(off, bool):
    return bool(current) is off
  return current == off
