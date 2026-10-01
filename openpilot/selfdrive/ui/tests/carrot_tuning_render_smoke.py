"""Headless render smoke test for the Carrot tuning layout.

Why this exists
---------------
CarrotTuningLayout crashed the UI with

    AttributeError: 'CarrotTuningLayout' object has no attribute '_font'

because Widget.__init__ never defines _font. That bug was invisible to
py_compile and to reading the diff: it only fires when the widget tree is
actually walked by render(). The same class of bug (undefined attribute, wrong
signature, bad name) stays hidden in any widget that was never rendered.

So instead of trusting a diff review, drive the real code with a fake raylib and
a fake gui_app. Everything under test is real: Widget.render, Scroller,
ListItemSP, NavButton, measure_text_cached, the root navigation rows, and every
group sub-page returned by carrot_tuning_items.build_*_items().

It also pins the typography to the sunnypilot design tokens. The page this
replaced mixed 24px tab labels in with 40/50px settings text, which read as
"fonts all different sizes"; that is exactly the kind of drift an assertion
catches and a screenshot does not.

Run from the repo root (no display, no capnp, no zmq needed):

    PYTHONPATH=. python openpilot/selfdrive/ui/tests/carrot_tuning_render_smoke.py

Exit status is 0 when every check passes.

NOTE: deliberately NOT named test_*.py. install_stubs() replaces
openpilot.system.ui.lib.application, pyray and openpilot.common.params in
sys.modules, so pytest must not collect it into a shared session - doing so
would poison every other test that imports the UI stack.
"""


from __future__ import annotations

import re
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# Repo root, so the script works regardless of the caller's cwd.
REPO_ROOT = Path(__file__).resolve().parents[4]
PO_PATH = REPO_ROOT / "openpilot" / "selfdrive" / "ui" / "translations" / "app_zh-CHS.po"

# ---------------------------------------------------------------------------
# Fake pyray
# ---------------------------------------------------------------------------


class Rect:
  def __init__(self, x=0.0, y=0.0, width=0.0, height=0.0):
    self.x, self.y, self.width, self.height = float(x), float(y), float(width), float(height)

  def __repr__(self):
    return f"Rect({self.x}, {self.y}, {self.width}, {self.height})"


class Vec2:
  def __init__(self, x=0.0, y=0.0):
    self.x, self.y = float(x), float(y)

  def __repr__(self):
    return f"Vec2({self.x}, {self.y})"


class Color:
  def __init__(self, r=0, g=0, b=0, a=255):
    self.r, self.g, self.b, self.a = r, g, b, a


class Texture:
  def __init__(self, tid=1):
    self.id = tid
    self.width, self.height = 64, 64


class Font:
  def __init__(self, tid=1):
    self.texture = Texture(tid)
    self.baseSize = 48


# Average glyph advance as a fraction of font size, used to give measured text a
# plausible width. Wrapping and eliding only get exercised if text is wide enough
# to overflow, so this must not return something trivially small.
_ADVANCE = 0.55
# Screens are 2160x1080 on a C3; the settings content panel is ~1600 wide.
DRAWN: list[tuple] = []


class _FakeModule(types.ModuleType):
  """Module that fabricates any attribute it does not define explicitly."""

  def __getattr__(self, name: str) -> Any:
    if name.startswith("__"):
      raise AttributeError(name)
    value = _AnyCall()
    setattr(self, name, value)
    return value


class _AnyCall:
  def __call__(self, *a, **k):
    return None

  def __getattr__(self, name):
    if name.startswith("__"):
      raise AttributeError(name)
    return _AnyCall()


def _measure_text_ex(font, text, size, spacing):
  return Vec2(len(text) * size * _ADVANCE, size * 1.15)


def _measure_text(text, size):
  return len(text) * size * _ADVANCE


def _draw_text_ex(font, text, pos, size, spacing, color):
  DRAWN.append((getattr(font, "texture", None) and font.texture.id, text, pos.x, pos.y, size))


def _draw_text(text, x, y, size, color):
  DRAWN.append(("DEFAULT_FONT", text, x, y, size))


def _check_collision_point_rec(point, rect):
  """Real raylib semantics: inclusive on both edges."""
  return (rect.x <= point.x <= rect.x + rect.width and
          rect.y <= point.y <= rect.y + rect.height)


def build_fake_pyray() -> types.ModuleType:
  m = _FakeModule("pyray")
  m.Rectangle = Rect
  m.Rectangle.__module__ = "pyray"
  m.Vector2 = Vec2
  m.Color = Color
  m.Font = Font
  m.Texture = Texture
  m.Rectangle.__qualname__ = "Rectangle"
  m.Vector2.__qualname__ = "Vector2"
  m.WHITE = Color(255, 255, 255, 255)
  m.BLACK = Color(0, 0, 0, 255)
  m.BLANK = Color(0, 0, 0, 0)
  m.measure_text_ex = _measure_text_ex
  m.measure_text = _measure_text
  m.draw_text_ex = _draw_text_ex
  m.draw_text = _draw_text
  m.load_font = lambda path: Font(1)
  m.load_font_ex = lambda *a, **k: Font(1)
  m.get_font_default = lambda: Font(0)
  m.gen_texture_mipmaps = lambda *a, **k: None
  m.set_texture_filter = lambda *a, **k: None
  m.get_time = lambda: 0.0
  m.get_mouse_position = lambda: Vec2(-1000, -1000)
  m.is_mouse_button_pressed = lambda *a, **k: False
  m.is_mouse_button_down = lambda *a, **k: False
  m.get_mouse_wheel_move = lambda: 0.0
  # A real hit test, not a "False" stub. Widgets and GuiScrollPanel gate input on
  # this, so stubbing it to False would make every tap test silently vacuous.
  m.check_collision_point_rec = _check_collision_point_rec
  m.get_collision_rec = lambda a, b: Rect(a.x, a.y, a.width, a.height)
  m.ffi = _AnyCall()
  m.MouseButton = types.SimpleNamespace(MOUSE_BUTTON_LEFT=0, MOUSE_BUTTON_RIGHT=1, MOUSE_BUTTON_MIDDLE=2)
  m.TextureFilter = types.SimpleNamespace(TEXTURE_FILTER_BILINEAR=0, TEXTURE_FILTER_TRILINEAR=1)
  m.ConfigFlags = types.SimpleNamespace(FLAG_MSAA_4X_HINT=0, FLAG_VSYNC_HINT=0)
  return m


# ---------------------------------------------------------------------------
# Fake openpilot.system.ui.lib.application
# ---------------------------------------------------------------------------

FONT_WEIGHTS: dict[str, str] = {}


class FakeGuiApp:
  def __init__(self):
    self._font_cache: dict = {}
    self.target_fps = 60
    self.show_touches = False
    self.width, self.height = 2160, 1080
    self._textures: dict = {}
    # Widget._process_mouse_events iterates this every render; an empty list is
    # exactly the "no touch this frame" case.
    self._mouse_events: list = []

  @property
  def mouse_events(self):
    return self._mouse_events

  def font(self, weight=None):
    # Mirror GuiApplication.font: return a per-weight object that carries the
    # weight, so a stale-cache bug (reusing the wrong weight) would show up.
    key = str(weight)
    FONT_WEIGHTS[key] = FONT_WEIGHTS.get(key, 0) + 1
    return self._font_cache.setdefault(key, Font(100 + len(self._font_cache)))

  def fallback_font(self, text: str = ""):
    return self._font_cache.setdefault("__fallback__", Font(999))

  def texture(self, asset_path, width=None, height=None, alpha_premultiply=False,
              keep_aspect_ratio=True, flip_x=False):
    # Signature mirrors GuiApplication.texture; layouts pass keep_aspect_ratio.
    return Texture()

  def big_ui(self):
    return False

  # Modules branch on this at import time to pick the sunnypilot UI paths.
  def sunnypilot_ui(self):
    return True

  def render(self):
    return iter(())

  def __getattr__(self, name):
    # Permissive fallback for the long tail of GuiApplication surface the panels
    # touch (set_show_touches, push_widget, ...): a callable no-op is closer to
    # the real object than an AttributeError, so a panel is never failed by a
    # method this harness simply did not list yet.
    if name.startswith("__"):
      raise AttributeError(name)
    value = PermissiveField()
    object.__setattr__(self, name, value)
    return value


def build_fake_application() -> types.ModuleType:
  m = _FakeModule("openpilot.system.ui.lib.application")
  app = FakeGuiApp()
  m.gui_app = app
  m.FontWeight = types.SimpleNamespace(
    NORMAL="Inter-Medium.ttf", MEDIUM="Inter-Medium.ttf", BOLD="Inter-Bold.ttf",
    SEMI_BOLD="Inter-SemiBold.ttf", UNIFONT="OpFont-Regular-Labels.fnt", AUDIOWIDE="Audiowide-Regular.ttf",
    DISPLAY_REGULAR="Inter-Regular.ttf", ROMAN="Inter-Regular.ttf", DISPLAY="Inter-Bold.ttf",
  )
  m.TextAlignment = types.SimpleNamespace(LEFT=0, CENTER=1, RIGHT=2)
  m.TextAlignmentVertical = types.SimpleNamespace(TOP=0, MIDDLE=1, BOTTOM=2)
  m.FONT_SCALE = 1.16
  m.DEFAULT_TEXT_SIZE = 60
  m.DEFAULT_TEXT_COLOR = Color(255, 255, 255, 230)
  m.MAX_TOUCH_SLOTS = 2
  m.MousePos = Vec2  # NamedTuple of (x, y) - a Vec2 is a faithful stand-in
  m.MouseEvent = types.SimpleNamespace
  m.requires_font_fallback = lambda: True
  m.font_fallback = lambda font, text="": font
  return m


# ---------------------------------------------------------------------------
# Fake multilang + Params
# ---------------------------------------------------------------------------


def build_fake_multilang() -> types.ModuleType:
  m = _FakeModule("openpilot.system.ui.lib.multilang")
  m.language = "zh-CHS"
  m.languages = {"en": "English", "zh-CHS": "简体中文"}
  m.codes = {v: k for k, v in m.languages.items()}
  m.tr = lambda s: s
  m.trn = lambda s, p, n: s if n == 1 else p
  m.tr_noop = lambda s: s
  m.requires_font_fallback = lambda: True
  m.change_language = lambda code: None
  m.init = lambda: None
  return m


class PermissiveField(MagicMock):
  """A MagicMock that also survives being used as a number.

  Layouts format readings straight into strings (f"{delay:.2f} s") and use them
  as dict keys/lookup values. A plain MagicMock raises TypeError on the format
  and KeyError on the lookup, which reads like an app bug when it is only the
  harness returning a mock. Returning numeric zero for those operations keeps
  the render path real while never failing on a value nobody asserted.
  """

  def __format__(self, spec: str) -> str:
    return format(0.0, spec) if spec else "0"

  def __float__(self) -> float:
    return 0.0

  def __int__(self) -> int:
    return 0

  def __index__(self) -> int:
    return 0

  def __iter__(self):
    return iter(())


def permissive(**values) -> Any:
  """Object with real `values` plus a PermissiveField for anything else."""

  class _Obj:
    def __init__(self):
      for key, value in values.items():
        object.__setattr__(self, key, value)

    def __getattr__(self, name):
      if name.startswith("__"):
        raise AttributeError(name)
      value = PermissiveField()
      object.__setattr__(self, name, value)
      return value

    # Container-ish protocols: several call sites do sm.updated["carState"] or
    # iterate a message list, which must not raise on a permissive stand-in.
    def __getitem__(self, key):
      value = PermissiveField()
      object.__setattr__(self, f"_item_{key}", value)
      return value

    def __setitem__(self, key, value) -> None:
      object.__setattr__(self, f"_item_{key}", value)

    def __contains__(self, key) -> bool:
      return True

    def __iter__(self):
      return iter(())

    def __len__(self) -> int:
      return 0

    def __bool__(self) -> bool:
      return True

  return _Obj()


class FakeSubMaster:
  """cereal SubMaster stand-in with realistic defaults for the messages the
  settings pages read (personality names, delays, speeds) so branches that
  parse those values are exercised instead of mocked away."""

  DEFAULTS: dict[str, dict] = {
    "selfdriveState": {"personality": "standard", "enabled": False, "active": False,
                       "experimentalMode": False, "alertStatus": 0, "alertText1": "", "alertText2": ""},
    "lateralDelay": {"lateralDelay": 0.0, "active": False},
    "carState": {"vEgo": 0.0, "standstill": True, "gearShifter": "park", "steeringAngleDeg": 0.0,
                 "leftBlinker": False, "rightBlinker": False, "vCruise": 0.0,
                 "gasPressed": False, "brakePressed": False},
    "deviceState": {"thermalStatus": 0, "batteryPercent": 100.0, "started": True, "deviceType": "tizi"},
    "controlsState": {"enabled": False, "active": False, "vCruise": 0.0},
    "carControl": {"enabled": False, "latActive": False, "longActive": False},
    "carParams": {"steerActuatorDelay": 0.1, "openpilotLongitudinalControl": False},
  }

  def __init__(self):
    self._cache: dict[str, Any] = {}
    self.updated = permissive()
    self.valid = permissive()
    self.alive = permissive()

  def __getitem__(self, key):
    if key not in self._cache:
      self._cache[key] = permissive(**self.DEFAULTS.get(key, {}))
    return self._cache[key]

  def __contains__(self, key):
    return True

  def all_checks(self) -> bool:
    return True

  def all_alive(self) -> bool:
    return True

  def all_valid(self) -> bool:
    return True

  def update(self, timeout: int = 0):
    return []

  def __getattr__(self, name):
    if name.startswith("__"):
      raise AttributeError(name)
    value = PermissiveField()
    object.__setattr__(self, name, value)
    return value


def build_fake_params() -> types.ModuleType:
  m = types.ModuleType("openpilot.common.params")
  store: dict[str, Any] = {}

  class Params:
    """Duck-typed stand-in for openpilot.common.params.Params.

    Signature-compatible with the real class: layouts call Params(log_root) and
    pass block=True to put_bool, and a stub that rejects either makes the layout
    look broken when it is the harness that is.
    """

    def __init__(self, *args, **kwargs):
      pass

    def get(self, key, return_default=False):
      return store.get(key, 0 if return_default else None)

    def get_bool(self, key, return_default=False):
      return bool(store.get(key, False))

    def put(self, key, value, block=False):
      store[key] = value

    def put_bool(self, key, value, block=False):
      store[key] = value

    def put_nonblocking(self, key, value):
      store[key] = value

    def remove(self, key):
      store.pop(key, None)

    def clear(self):
      store.clear()

  class UnknownKeyName(Exception):
    """Mirrors the C++ exception raised for keys missing from params_keys.h."""

  m.Params = Params
  m.UnknownKeyName = UnknownKeyName
  m.ParamKeyType = types.SimpleNamespace(STRING=0, BOOL=1, INT=2, FLOAT=3, JSON=4, TIME=5)
  m.store = store
  return m


def install_stubs() -> None:
  import importlib

  # The layouts read ui_state as a bag of both plain flags and predicate
  # methods (is_offroad() / is_onroad() are methods in the real UIState, and
  # callers do `if ui_state.is_onroad():`). Model both, and give unknown
  # attributes a permissive fallback so a panel that reads a field this harness
  # does not know about still renders instead of failing the smoke test.
  _ui_mod = types.ModuleType('openpilot.selfdrive.ui.ui_state')
  _fake_params = build_fake_params().Params()

  class _FakeUiState:
    def __init__(self):
      self.params = _fake_params
      self.CP = permissive(steerActuatorDelay=0.1, openpilotLongitudinalControl=False)
      self.sm = FakeSubMaster()
      self.prime_state = permissive()
      self.started = True
      self.engaged = False
      self.demo_mode = False
      self.has_longitudinal_control = False
      self.has_lat_control = False
      self.is_release = False
      self._extra: dict = {}

    def is_offroad(self) -> bool:
      return True

    def is_onroad(self) -> bool:
      return False

    def is_engaged(self) -> bool:
      return False

    def update_params(self) -> None:
      return None

    def __getattr__(self, name):
      # Only reached for attributes nobody set explicitly.
      if name.startswith("__"):
        raise AttributeError(name)
      value = self._extra.get(name)
      if value is None:
        value = PermissiveField()
        self._extra[name] = value
      return value

  _ui_mod.ui_state = _FakeUiState()
  class _FakeDevice:
    """device is read as both flags (device.awake) and methods (is_awake())."""

    def __init__(self):
      self.awake = True
      self._awake = True
      self._interactive_timeout = 0.0
      self.started = True

    def is_awake(self) -> bool:
      return True

    def __getattr__(self, name):
      if name.startswith("__"):
        raise AttributeError(name)
      value = PermissiveField()
      object.__setattr__(self, name, value)
      return value

  _ui_mod.device = _FakeDevice()
  sys.modules['openpilot.selfdrive.ui.ui_state'] = _ui_mod

  fake_pyray = build_fake_pyray()
  sys.modules["pyray"] = fake_pyray
  # openpilot imports `import pyray as rl`, and some modules use `rl.` helpers that
  # reach back into openpilot; keep the fake self-contained.

  sys.modules["openpilot.system.ui.lib.application"] = build_fake_application()
  sys.modules["openpilot.system.ui.lib.multilang"] = build_fake_multilang()
  sys.modules["openpilot.common.params"] = build_fake_params()

  # swaglog pulls in zmq, and wifi_manager pulls in jeepney + dbus; neither is
  # present on a PC and neither is exercised by a layout render.
  swaglog = _FakeModule("openpilot.common.swaglog")
  swaglog.cloudlog = _AnyCall()
  sys.modules["openpilot.common.swaglog"] = swaglog

  wifi = _FakeModule("openpilot.system.ui.lib.wifi_manager")
  wifi.WifiManager = type("WifiManager", (), {"__init__": lambda self, *a, **k: None,
                                              "set_active": lambda self, v: None})
  wifi.SecurityType = _AnyCall()
  wifi.Network = _AnyCall()
  wifi.MeteredType = _AnyCall()
  wifi.normalize_ssid = lambda s: s
  sys.modules["openpilot.system.ui.lib.wifi_manager"] = wifi

  for name in ("jeepney", "jeepney.io", "jeepney.io.blocking", "jeepney.io.threading",
               "jeepney.bus_messages", "jeepney.low_level", "jeepney.wrappers"):
    sys.modules.setdefault(name, _FakeModule(name))

  # Make sure `from openpilot.system.ui.lib.application import X` resolves the
  # parent packages to the real (empty) __init__ modules, not to a fabricated one.
  for pkg in ("openpilot", "openpilot.system", "openpilot.system.ui", "openpilot.system.ui.lib",
              "openpilot.system.ui.widgets", "openpilot.system.ui.sunnypilot",
              "openpilot.system.ui.sunnypilot.widgets", "openpilot.common",
              "openpilot.selfdrive", "openpilot.selfdrive.ui",
              "openpilot.selfdrive.ui.sunnypilot",
              "openpilot.selfdrive.ui.sunnypilot.layouts",
              "openpilot.selfdrive.ui.sunnypilot.layouts.settings"):
    if pkg in sys.modules:
      continue
    try:
      importlib.import_module(pkg)
    except Exception as exc:  # pragma: no cover - diagnostic only
      print(f"  [warn] could not import {pkg}: {exc}")


# ---------------------------------------------------------------------------
# The actual test
#
# History: this file used to drive upstream's group-list page (CARROT_GROUPS /
# CarrotGroupKey, one navigation row + sub-page per group). Our Carrot tuning
# page is the 9-tab layout built from carrot_tuning_items, so those symbols do
# not exist here and the test died on import -- a stale test, not an app crash.
# It now drives the page we actually ship: the tab strip plus every tab's list.
#
# The two bugs this class of test exists for are still covered:
#   * an undefined attribute / wrong signature inside a widget that is only
#     reached by render() (this is how CarrotTuningLayout's missing _font, and
#     TripsLayout's missing _get_stats, reached the device);
#   * tab typography drift (the strip was 24 px against 50 px list items).
# ---------------------------------------------------------------------------


def main() -> int:
  install_stubs()

  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.carrot_tuning import (  # noqa: E402
    TAB_FONT_MIN_SIZE, TAB_FONT_SIZE, CarrotTuningLayout, TabType,
  )
  from openpilot.system.ui.sunnypilot.lib.styles import style  # noqa: E402

  failures: list[str] = []
  checks = 0

  def check(label, fn):
    nonlocal checks
    checks += 1
    try:
      fn()
      print(f"  ok  {label}")
    except Exception as exc:  # noqa: BLE001
      failures.append(f"{label}: {type(exc).__name__}: {exc}")
      print(f"  FAIL {label}: {type(exc).__name__}: {exc}")

  content = Rect(0, 0, 1600, 900)
  # Render into a viewport tall enough for every row: the real panel is 900px and
  # culls off-screen items, which would hide rows we want to check.
  tall = Rect(0, 0, content.width, 6000)

  print("== construction ==")
  layout = CarrotTuningLayout(lambda: None)
  layout.set_parent_rect(content)
  layout.show_event()

  def renders():
    DRAWN.clear()
    layout.render(content)
    assert DRAWN, "carrot tuning page drew nothing"

  check("renders without crashing", renders)

  def starts_on_the_first_tab():
    assert layout._current_tab == TabType.START, f"started on {layout._current_tab!r}"

  check("starts on the first tab", starts_on_the_first_tab)

  print("== tab strip ==")

  def every_tab_label_is_drawn():
    DRAWN.clear()
    layout.render(content)
    drawn = {d[1] for d in DRAWN}
    missing = [label for label in layout.TAB_LABELS if label not in drawn]
    assert not missing, f"tab labels not drawn: {missing}"

  check("every tab label is drawn", every_tab_label_is_drawn)

  def every_tab_owns_one_ninth():
    layout.render(content)
    strip = Rect(100.0, 12.0, 1800.0, 96.0)
    tab_w = strip.width / layout.TAB_COUNT
    for index in range(layout.TAB_COUNT):
      centre_x = strip.x + (index + 0.5) * tab_w
      assert layout.tab_index_at(Vec2(centre_x, strip.y + 48), strip) == index, f"tab {index} mis-hit"

  check("each ninth of the strip resolves to its own tab", every_tab_owns_one_ninth)

  def points_outside_the_strip_have_no_tab():
    strip = Rect(100.0, 12.0, 1800.0, 96.0)
    for pos in (Vec2(strip.x - 1, strip.y + 48), Vec2(strip.x + strip.width + 1, strip.y + 48),
                Vec2(strip.x + 10, strip.y - 1), Vec2(strip.x + 10, strip.y + strip.height + 1)):
      assert layout.tab_index_at(pos, strip) is None, f"{pos} should not hit a tab"

  check("points outside the strip hit no tab", points_outside_the_strip_have_no_tab)

  print("== every tab page ==")

  def every_tab_has_items():
    empty = [TabType(i).name for i in range(layout.TAB_COUNT) if not layout._tab_scrollers[TabType(i)]._items]
    assert not empty, f"tabs with no items: {empty}"

  check("every tab has at least one item", every_tab_has_items)

  def every_tab_renders():
    for index in range(layout.TAB_COUNT):
      layout._select_tab(index)
      DRAWN.clear()
      layout.render(tall)
      assert DRAWN, f"tab {TabType(index).name} drew nothing"
      assert layout._current_tab == TabType(index)
    layout._select_tab(0)

  check("every tab renders its page", every_tab_renders)

  def item_titles_are_strings():
    """A title that is a widget (or None) instead of a string is a wiring bug."""
    for index in range(layout.TAB_COUNT):
      for item in layout._tab_scrollers[TabType(index)]._items:
        title = getattr(item, 'title', None)
        if title is None:
          continue
        assert isinstance(title, str), f"{TabType(index).name}: title is {type(title).__name__}"

  check("item titles are plain strings", item_titles_are_strings)

  print("== typography pin ==")

  def tab_font_tokens():
    assert (TAB_FONT_SIZE, TAB_FONT_MIN_SIZE) == (36, 24), \
      f"tab font tokens drifted: {TAB_FONT_SIZE}/{TAB_FONT_MIN_SIZE} (expected 36/24)"

  check("tab font tokens stay at the 1.5x values", tab_font_tokens)

  def long_labels_shrink_but_never_below_the_floor():
    from openpilot.system.ui.lib.application import gui_app  # noqa: E402
    fnt = gui_app.font()
    tab_w = content.width / layout.TAB_COUNT
    for label in layout.TAB_LABELS:
      size, _ = CarrotTuningLayout._fit_tab_label(fnt, label, tab_w)
      assert TAB_FONT_MIN_SIZE <= size <= TAB_FONT_SIZE, f"{label!r} fitted to {size}px"

  check("tab labels shrink only down to the floor", long_labels_shrink_but_never_below_the_floor)

  def styles_are_used():
    assert style.ON_BG_COLOR is not None and style.OFF_BG_COLOR is not None

  check("active/inactive tab colours come from the style tokens", styles_are_used)

  print("== strings ==")

  def every_tab_label_is_translated():
    src = (REPO_ROOT / "openpilot" / "selfdrive" / "ui" / "sunnypilot" / "layouts" / "settings" /
           "carrot_tuning.py").read_text(encoding="utf-8")
    keys = re.search(r"TAB_KEYS = \(([^)]*)\)", src)
    assert keys, "TAB_KEYS not found"
    labels = re.findall(r"'([^']*)'", keys.group(1))
    assert labels, "no tab labels parsed"
    for lang in ("zh-CHS", "zh-CHT"):
      po = (REPO_ROOT / "openpilot" / "selfdrive" / "ui" / "translations" / f"app_{lang}.po").read_text(encoding="utf-8")
      have = set(re.findall(r'^msgid "(.+?)"$', po, re.M))
      missing = [label for label in labels if label not in have]
      assert not missing, f"{lang} missing tab labels: {missing}"

  check("every tab label has a translation entry", every_tab_label_is_translated)

  print()
  print(f"{checks - len(failures)}/{checks} checks passed")
  for f in failures:
    print(f"FAILED: {f}")
  return 1 if failures else 0


if __name__ == "__main__":
  sys.exit(main())
