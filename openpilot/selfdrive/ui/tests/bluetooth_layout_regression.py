"""Regression tests for the Carrot Bluetooth settings layout.

Pins four defects reported on device (2026-09-28), all in the native
``CarrotBluetoothLayout``:

1. The device list was laid out from ``rect.y`` instead of below the header, so
   the first row rendered *under* the Scan / Advanced buttons. Its text was
   clipped away (only a sliver showed at the top) but its full-width row button
   stayed tappable -- so tapping "Advanced" also opened that device's mapping
   editor ("weird Carrot mapping screen").
2. Rows scroll under the header. Hit testing was not clipped to the visible
   band, so tapping the blank strip under the header activated the hidden row.
3. The editor's Back button clears ``self._draft`` while it renders; the rest of
   ``_render_editor`` then dereferenced it -> AttributeError -> ui exit 1 ->
   "Restarting ui" loop.
4. Device-row action captions were measured at a different font size than the
   Button renders at, so the Label wrapped them ("Disconnec" + "t"). The row
   Button also carried the device name as its caption, drawing a second,
   un-clipped copy over the hand-drawn name.

Run from the repo root:

    PYTHONPATH=. python openpilot/selfdrive/ui/tests/bluetooth_layout_regression.py
"""

import importlib.util
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

_smoke_spec = importlib.util.spec_from_file_location(
  "bluetooth_render_smoke", str(REPO_ROOT / "openpilot/selfdrive/ui/tests/bluetooth_render_smoke.py"))
smoke = importlib.util.module_from_spec(_smoke_spec)
_smoke_spec.loader.exec_module(smoke)
smoke.install_stubs()

import pyray as rl  # noqa: E402


# The render-smoke stub returns rec1 verbatim for get_collision_rec (and always
# True for check_collision_recs), which cannot exercise clipping at all. Use the
# real raylib semantics here: the intersection, or an all-zero rect when disjoint.
def _collision_rec(a, b):
  x1, x2 = max(a.x, b.x), min(a.x + a.width, b.x + b.width)
  y1, y2 = max(a.y, b.y), min(a.y + a.height, b.y + b.height)
  if x2 >= x1 and y2 >= y1:
    return smoke.Rect(x1, y1, x2 - x1, y2 - y1)
  return smoke.Rect(0, 0, 0, 0)


def _collision_recs(a, b):
  return _collision_rec(a, b).width > 0 and _collision_rec(a, b).height > 0


rl.get_collision_rec = _collision_rec
rl.check_collision_recs = _collision_recs

from openpilot.selfdrive.ui.sunnypilot.layouts.settings.bluetooth_settings import (  # noqa: E402
  CarrotBluetoothLayout, BTPanel, BTDevice, GESTURES, MAPPING_BUTTONS,
)

FAILURES = []


def check(name, cond, detail=""):
  status = "ok  " if cond else "FAIL"
  print(f"  [{status}] {name}{'' if cond else '  -> ' + detail}")
  if not cond:
    FAILURES.append(name)


# The stub application exposes MouseEvent as a non-callable placeholder, so build
# the same 6-field record the real NamedTuple has.
import collections  # noqa: E402

_MouseEvent = collections.namedtuple(
  "MouseEvent", ["pos", "slot", "left_pressed", "left_released", "left_down", "t"])


def _make_event(x, y, pressed, released, held):
  return _MouseEvent(smoke.Vec2(x, y), 0, pressed, released, held, 0.0)


def tap(layout, rect, x, y):
  """Press then release at (x, y), rendering a frame for each."""
  from openpilot.system.ui.lib.application import gui_app
  gui_app._mouse_events = [_make_event(x, y, True, False, True)]
  layout.render(rect)
  gui_app._mouse_events = [_make_event(x, y, False, True, False)]
  layout.render(rect)
  gui_app._mouse_events = []


def fresh_layout(rect, devices=None):
  layout = CarrotBluetoothLayout()
  layout.show_event()
  layout.render(rect)  # fetch state once
  if devices is not None:
    layout._state.devices = devices
  return layout


def center(r):
  return r.x + r.width / 2, r.y + r.height / 2


RECT = rl.Rectangle(50, 25, 1600, 950)


# ---------------------------------------------------------------------------
# 1. First row must not sit under the header, and tapping Advanced must not
#    fall through to the first device's editor.
# ---------------------------------------------------------------------------
def test_first_row_below_header():
  print("\n1. device list starts below the header")
  layout = fresh_layout(RECT)
  first = layout._state.devices[0]
  row_rect = layout._device_btns[first.address].rect
  adv_rect = layout._adv_btn.rect
  overlap = not (row_rect.x + row_rect.width <= adv_rect.x or adv_rect.x + adv_rect.width <= row_rect.x or
                 row_rect.y + row_rect.height <= adv_rect.y or adv_rect.y + adv_rect.height <= row_rect.y)
  check("first row does not overlap the Advanced button", not overlap,
        f"row={row_rect.y}..{row_rect.y + row_rect.height} adv={adv_rect.y}..{adv_rect.y + adv_rect.height}")
  check("first row starts below the header", row_rect.y >= adv_rect.y + adv_rect.height, f"row.y={row_rect.y}")


def test_advanced_tap_opens_advanced_only():
  print("\n2. tapping Advanced opens Advanced (not the mapping editor)")
  layout = fresh_layout(RECT)
  ax, ay = center(layout._adv_btn.rect)
  tap(layout, RECT, ax, ay)
  check("panel == ADVANCED", layout._panel == BTPanel.ADVANCED,
        f"got {BTPanel(layout._panel).name}")


# ---------------------------------------------------------------------------
# 3. Hit testing is clipped to the visible list band.
# ---------------------------------------------------------------------------
def test_hidden_row_is_not_tappable():
  print("\n3. taps in the band hidden behind the header do nothing")
  many = [BTDevice(address=f"AA:BB:CC:DD:EE:{i:02X}", name=f"Dev{i}", paired=(i < 2), rssi=-50 - i)
          for i in range(12)]
  layout = fresh_layout(RECT, devices=many)
  layout._scroll_panel.set_offset(-140)
  layout.render(RECT)

  first = layout._device_btns.get("AA:BB:CC:DD:EE:00")
  check("a scrolled row is still drawn", first is not None)
  if first is not None:
    hit = first._hit_rect
    check("scrolled row's hit rect is clipped to the list band", hit.y >= 205,
          f"hit.y={hit.y}")
    check("scrolled row's hit rect does not cover the header", hit.y >= layout._adv_btn.rect.y + layout._adv_btn.rect.height,
          f"hit.y={hit.y}")

  layout._panel = BTPanel.DEVICES
  layout._on_advanced_clicked()
  layout._panel = BTPanel.DEVICES
  layout._scroll_panel.set_offset(-140)
  # y=170 is the blank strip between the header and the list start.
  tap(layout, RECT, 300, 170)
  check("tapping the hidden strip stays on the device list", layout._panel == BTPanel.DEVICES,
        f"got {BTPanel(layout._panel).name}")


# ---------------------------------------------------------------------------
# 4. Back from the editor must not crash mid-render.
# ---------------------------------------------------------------------------
def test_back_from_editor_does_not_crash():
  print("\n4. Back from the mapping editor returns to the list without crashing")
  layout = fresh_layout(RECT)
  layout._on_edit_device(layout._state.devices[0])
  layout.render(RECT)
  check("editor is shown", layout._panel == BTPanel.EDITOR)
  bx, by = center(layout._back_btn.rect)
  try:
    tap(layout, RECT, bx, by)
    crashed = None
  except Exception as exc:  # noqa: BLE001
    crashed = exc
  check("no exception while rendering the Back tap", crashed is None, repr(crashed))
  check("panel == DEVICES after Back", layout._panel == BTPanel.DEVICES,
        f"got {BTPanel(layout._panel).name}")
  check("draft cleared after Back", layout._draft is None)


# ---------------------------------------------------------------------------
# 5. Action captions render on a single line, and the row name only once.
# ---------------------------------------------------------------------------
def test_action_captions_single_line():
  print("\n5. action captions are not wrapped, device name drawn once")
  layout = fresh_layout(RECT)
  drawn = []
  orig = rl.draw_text_ex
  rl.draw_text_ex = lambda f, t, p, s, sp, c: drawn.append(t)
  try:
    layout.render(RECT)
  finally:
    rl.draw_text_ex = orig

  for label in ("Disconnect", "Forget", "Pair"):
    check(f"'{label}' drawn exactly once", drawn.count(label) == 1, f"count={drawn.count(label)}")
  name = layout._state.devices[0].name
  check(f"device name '{name}' drawn exactly once", drawn.count(name) == 1, f"count={drawn.count(name)}")
  # A wrapped Label leaves orphan fragments behind.
  stray = [t for t in drawn if t in ("t", "r", "Disconnec", "Forge", "Pai")]
  check("no wrapped caption fragments", not stray, f"stray={stray}")


# ---------------------------------------------------------------------------
# 6. The reported missing translation now resolves.
# ---------------------------------------------------------------------------
def test_blind_spot_translation():
  print("\n6. 'Enable Carrot Blind Spot Data' is translated")
  po = REPO_ROOT / "openpilot/selfdrive/ui/translations/app_zh-CHS.po"
  text = po.read_text(encoding="utf-8")
  m = re.search(r'msgid "Enable Carrot Blind Spot Data"\nmsgstr "(.*)"', text)
  check("entry exists in app_zh-CHS.po", m is not None)
  if m:
    check("msgstr is non-empty", bool(m.group(1).strip()), f"msgstr={m.group(1)!r}")


# ---------------------------------------------------------------------------
# 7. The mapping editor must fit the panel: the Save row used to sit below the
#    screen (content ~1265px in a ~1030px panel) and could never be tapped.
# ---------------------------------------------------------------------------
def test_editor_fits_panel():
  print("\n7. mapping editor fits the panel, Save row is reachable")
  real = rl.Rectangle(50, 25, 2060, 1030)  # full 2160x1080 panel
  layout = fresh_layout(real)
  layout._on_edit_device(layout._state.devices[0])
  layout.render(real)
  check("editor is shown", layout._panel == BTPanel.EDITOR)

  bottom = real.y + real.height
  for name, btn in (("Save", layout._save_btn), ("Test / Learn", layout._test_btn)):
    r = btn.rect
    check(f"{name} button is inside the panel", r.y + r.height <= bottom, f"{r.y + r.height} > {bottom}")
    check(f"{name} button is fully hittable", btn._hit_rect.height >= r.height, f"hit={btn._hit_rect.height}")

  last = layout._gesture_btns[MAPPING_BUTTONS[-1]][GESTURES[-1]].rect
  check("last mapping row is inside the panel", last.y + last.height <= bottom,
        f"{last.y + last.height} > {bottom}")

  check("editor body fits without scrolling",
        layout._editor_body_height() <= bottom - (last.y - (layout._editor_body_height() - last.height)),
        f"body={layout._editor_body_height()}")

  # Captions must not need eliding in their cell.
  from openpilot.system.ui.lib.text_measure import measure_text_cached
  from openpilot.system.ui.lib.application import gui_app, FontWeight
  for caption in ("Cruise \u2212 Long", "CarrotCruise"):
    w = measure_text_cached(gui_app.font(FontWeight.MEDIUM), caption, 35).x
    check(f"'{caption}' fits a mapping cell", w <= last.width - 40, f"{w:.0f} > {last.width - 40:.0f}")


# ---------------------------------------------------------------------------
# 8. Advanced page: the "Reset Bluetooth" caption used to wrap ("Reset" /
#    "Bluetooth") because the button was a fixed 360px at font size 45.
# ---------------------------------------------------------------------------
def test_advanced_captions_fit():
  print("\n8. Advanced page captions fit their buttons")
  layout = fresh_layout(RECT)
  layout._on_advanced_clicked()
  drawn = []
  orig = rl.draw_text_ex
  rl.draw_text_ex = lambda f, t, pos, size, sp, c: drawn.append((t, size))
  try:
    layout.render(RECT)
  finally:
    rl.draw_text_ex = orig

  check("panel == ADVANCED", layout._panel == BTPanel.ADVANCED)
  texts = [t for t, _ in drawn]
  # Drawn as the section heading and as the button caption; never as fragments.
  check("'Reset Bluetooth' caption is present", texts.count("Reset Bluetooth") == 2,
        f"count={texts.count('Reset Bluetooth')}")
  check("no wrapped 'Reset' fragment", "Reset" not in texts, f"stray={[t for t in texts if t == 'Reset']}")

  from openpilot.system.ui.lib.text_measure import measure_text_cached
  from openpilot.system.ui.lib.application import gui_app, FontWeight
  need = measure_text_cached(gui_app.font(FontWeight.MEDIUM), "Reset Bluetooth", 45).x + 40
  check("Reset button is wide enough for its caption", layout._reset_btn.rect.width >= need,
        f"width={layout._reset_btn.rect.width} need={need:.0f}")


# ---------------------------------------------------------------------------
# 9. The Advanced page's "Device name" row must not draw its labels under the
#    name input box, and the page must still fit inside the panel.
# ---------------------------------------------------------------------------
def _overlap(a, b):
  return (min(a.x + a.width, b.x + b.width) - max(a.x, b.x) > 0 and
          min(a.y + a.height, b.y + b.height) - max(a.y, b.y) > 0)


def test_advanced_name_row_layout():
  print("\n9. Advanced page: name labels sit above the input box")
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import bluetooth_settings as bt

  layout = fresh_layout(RECT)
  layout._on_advanced_clicked()

  labels = []
  orig = bt.gui_label
  bt.gui_label = lambda rect, text, **kw: labels.append((text, rect))
  try:
    layout.render(RECT)
  finally:
    bt.gui_label = orig

  texts = [text for text, _ in labels]
  by_text = dict(labels)
  title = by_text.get("Device name")
  desc = by_text.get("Name shown to other Bluetooth devices.")
  check("name-row title is drawn once", texts.count("Device name") == 1, f"texts={texts}")
  check("name-row description is drawn once", texts.count("Name shown to other Bluetooth devices.") == 1,
        f"texts={texts}")
  if title is None or desc is None:
    return

  btn = layout._name_action_btn.rect
  check("title and description do not overlap each other", not _overlap(title, desc),
        f"title={title.y}..{title.y + title.height} desc={desc.y}..{desc.y + desc.height}")
  check("title ends above the name input box", title.y + title.height <= btn.y,
        f"title bottom={title.y + title.height} input.y={btn.y}")
  check("description ends above the name input box", desc.y + desc.height <= btn.y,
        f"desc bottom={desc.y + desc.height} input.y={btn.y}")
  check("name input box is 70 px tall (caption has room)", abs(btn.height - 70) < 1e-6,
        f"height={btn.height}")

  reset = layout._reset_btn.rect
  check("advanced page still fits inside the panel",
        reset.y + reset.height <= RECT.y + RECT.height,
        f"reset bottom={reset.y + reset.height} panel bottom={RECT.y + RECT.height}")


def main():
  test_first_row_below_header()
  test_advanced_tap_opens_advanced_only()
  test_hidden_row_is_not_tappable()
  test_back_from_editor_does_not_crash()
  test_action_captions_single_line()
  test_blind_spot_translation()
  test_editor_fits_panel()
  test_advanced_captions_fit()
  test_advanced_name_row_layout()

  print()
  if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    return 1
  print("all Bluetooth layout regression checks passed")
  return 0


if __name__ == "__main__":
  sys.exit(main())
