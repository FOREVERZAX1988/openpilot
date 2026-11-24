"""StarPilot-style screen brightness preferences for sunnypilot.

Two independent brightness levels (onroad / offroad) with adjustable offsets,
adapted from StarPilot's common/screen_settings.py:

- Offroad level replaces the stock ``Brightness``/BACKLIGHT_OFFROAD value when
  the param is set; unset keeps the stock handling untouched.
- Onroad level (unset = auto) overrides the light-sensor automatic path when
  set. The offset scales the *automatic* path multiplicatively and is ignored
  in manual mode, mirroring StarPilot semantics.

The hardware write path (Device -> HARDWARE.set_screen_brightness) is
unchanged; only the value computation lives here. All functions are pure so
they can be unit-tested without hardware or the UI import chain.

The four keys are deliberately NOT registered in params_keys.h yet; unknown
keys read as unset and code defaults keep stock behavior. A settings-page
entry will be added separately.

TspKeepAliveBrightness is likewise unregistered and device-local: it opts a
unit into a nonzero sleep backlight duty so touch-wake survives on clone
panels whose Samsung TSP gates itself off at zero duty. Default (unset) is
true dark sleep, matching stock behavior.
"""
import math

BRIGHTNESS_MIN = 0
BRIGHTNESS_MAX = 100
OFFSET_MIN = -30.0
OFFSET_MAX = 30.0

KEY_SCREEN_BRIGHTNESS_ONROAD = "ScreenBrightnessOnroad"
KEY_SCREEN_BRIGHTNESS_ONROAD_OFFSET = "ScreenBrightnessOnroadOffset"
KEY_SCREEN_BRIGHTNESS_OFFROAD = "ScreenBrightnessOffroad"
KEY_SCREEN_BRIGHTNESS_OFFROAD_OFFSET = "ScreenBrightnessOffroadOffset"
KEY_TSP_KEEPALIVE = "TspKeepAliveBrightness"
TSP_KEEPALIVE_MAX = 10


def parse_level(raw, default=None) -> int | None:
  """Parse a brightness level (0-100) from a raw params value.

  Unparseable / non-finite / out-of-range values fall back to ``default``
  (None means unset, i.e. keep the automatic behavior).
  """
  try:
    value = float(raw)
  except (TypeError, ValueError):
    return default
  if not math.isfinite(value):
    return default
  value = round(value)
  if not (BRIGHTNESS_MIN <= value <= BRIGHTNESS_MAX):
    return default
  return int(value)


def parse_offset(raw, default: float = 0.0) -> float:
  """Parse a brightness offset, clamped to [OFFSET_MIN, OFFSET_MAX]."""
  try:
    value = float(raw)
  except (TypeError, ValueError):
    return default
  if not math.isfinite(value):
    return default
  return min(OFFSET_MAX, max(OFFSET_MIN, value))


def parse_keepalive(raw, default: int = 0) -> int:
  """Parse the TSP touch keep-alive duty (0-10, percent).

  Unset/0 = true dark sleep (default; normal panels wake by touch at 0).
  A small positive value (measured alive at >=2) keeps the Samsung TSP on
  C3 clone panels powered at zero backlight writes. Out-of-range or
  unparseable values fall back to ``default``.
  """
  try:
    value = float(raw)
  except (TypeError, ValueError):
    return default
  if not math.isfinite(value):
    return default
  value = round(value)
  if not (0 <= value <= TSP_KEEPALIVE_MAX):
    return default
  return int(value)


def apply_offset(value: float, offset: float) -> float:
  """Scale an automatic brightness by the user offset (StarPilot semantics)."""
  offset = min(OFFSET_MAX, max(OFFSET_MIN, offset))
  return min(float(BRIGHTNESS_MAX), max(float(BRIGHTNESS_MIN), value * (1.0 + offset / 100.0)))


def calculate_screen_brightness(auto_brightness: float, manual: int | None = None,
                                offset: float = 0.0, awake: bool = True) -> int:
  """Compute the final brightness target from the automatic value and prefs.

  - Not awake -> 0 (screen off).
  - Manual level set -> the level itself, offset ignored (StarPilot behavior).
  - Otherwise -> automatic value scaled by the offset, rounded and clamped
    to 0-100. With no prefs set this is the identity of ``auto_brightness``.
  """
  if not awake:
    return 0
  if manual is not None:
    target = float(manual)
  else:
    target = apply_offset(float(auto_brightness), offset)
  return int(min(BRIGHTNESS_MAX, max(BRIGHTNESS_MIN, round(target))))


def read_screen_brightness(params) -> tuple[int | None, float, int | None, float]:
  """Read the four screen-brightness params.

  Keys are intentionally unregistered (defaults live in code), so unknown-key
  errors surface as unset values. Returns
  ``(onroad, onroad_offset, offroad, offroad_offset)`` where levels are None
  when unset (automatic/stock behavior) and offsets default to 0.0.
  """
  def _raw(key):
    try:
      return params.get(key)
    except Exception:
      return None

  onroad = parse_level(_raw(KEY_SCREEN_BRIGHTNESS_ONROAD), None)
  onroad_offset = parse_offset(_raw(KEY_SCREEN_BRIGHTNESS_ONROAD_OFFSET), 0.0)
  offroad = parse_level(_raw(KEY_SCREEN_BRIGHTNESS_OFFROAD), None)
  offroad_offset = parse_offset(_raw(KEY_SCREEN_BRIGHTNESS_OFFROAD_OFFSET), 0.0)
  return onroad, onroad_offset, offroad, offroad_offset
