"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Carrot tuning settings for mici, data-driven.

Port of the Big GUI ``carrot_tuning.py`` / ``carrot_tuning_items.py`` pair: the
root page is a scroller of group entries (plus the Carrot Web toggle) and each
entry opens a sub-page built from the data table in ``carrot_items.py``.

mici has no +/- stepper or slider widget, so numeric params use the same
degradation the OSM region picker uses: a BigButton showing the current value
that opens a scrollable list picker page (``ParamPickerPage``). Toggles map to
BigParamControl; where the Big GUI value map is small, zero-based and fully
labeled, the cycling BigMultiParamToggle is used instead of a picker.
"""
from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigMultiParamToggle, BigParamControl, GreyBigButton
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import carrot_items
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings.carrot_egpu import EgpuPageMici

# BigMultiParamToggle draws one pill per option inside the button, so it is only
# used for small, fully-labeled, zero-based value maps; everything else gets the
# picker page (which also covers negative bases like EnableSpeedTF).
MAX_MULTI_TOGGLE_OPTIONS = 3


def _default_value(param: str, mn: int) -> int:
  raw = Params().get(param, return_default=True)
  return raw if isinstance(raw, int) else mn


class ParamValueButton(BigButton):
  """BigButton bound to an int param: shows the formatted current value and
  opens a picker page on click."""

  def __init__(self, title: str, param: str, mn: int, mx: int, step: int,
               fmt=None, labels: dict[int, str] | None = None, desc: str = ""):
    super().__init__(title, "", description=desc)
    self._title = title
    self._param = param
    self._mn = mn
    self._mx = mx
    self._step = step
    self._fmt = fmt
    self._labels = labels or {}
    self.params = Params()
    self.set_click_callback(self._open_picker)
    self.refresh()

  def _format(self, value: int) -> str:
    label = self._labels.get(value)
    if label is not None:
      return tr(label)
    if self._fmt is not None:
      return self._fmt(value)
    return str(value)

  def refresh(self):
    self.set_value(self._format(_default_value(self._param, self._mn)))

  def _open_picker(self):
    values = list(range(self._mn, self._mx + 1, self._step))
    current = _default_value(self._param, self._mn)

    def on_select(value: int):
      self.params.put(self._param, value)
      self.refresh()

    gui_app.push_widget(ParamPickerPage(self._title, values, current, self._format, on_select))


class ParamPickerPage(NavScroller):
  """Scrollable value list for one numeric param; same degradation the Big GUI
  TreeOptionDialog gets in mici (see the OSM region picker)."""

  def __init__(self, title: str, values: list[int], current: int, fmt, on_select):
    super().__init__()
    self._scroller.add_widget(GreyBigButton(title, tr("scroll to continue")))
    for value in values:
      btn = BigButton(fmt(value), tr("selected") if value == current else "")
      btn.set_click_callback(lambda v=value: self.dismiss(lambda: on_select(v)))
      self._scroller.add_widget(btn)


def _multi_toggle_item(item: dict) -> BigMultiParamToggle | None:
  """Use the cycling toggle only for small, fully-labeled, zero-based maps."""
  labels = item["labels"]
  if not labels or item["min"] != 0:
    return None
  if set(labels) != set(range(item["min"], item["max"] + 1, item["step"])):
    return None
  if item["max"] + 1 > MAX_MULTI_TOGGLE_OPTIONS:
    return None
  options = [tr(labels[i]) for i in range(item["max"] + 1)]
  return BigMultiParamToggle(tr(item["title"]), item["param"], options, description=item["desc"] or "")


class CarrotGroupPageMici(NavScroller):
  """One Carrot tuning group: heading + rows built from the data table."""

  def __init__(self, title: str, items: list[dict]):
    super().__init__()
    self._scroller.add_widget(GreyBigButton(title, tr("scroll to continue")))

    self._toggles: list[BigParamControl] = []
    self._value_buttons: list[BigButton] = []
    self._status_rows: list[tuple[BigButton, callable]] = []

    widgets: list = []
    for item in items:
      kind = item["kind"]
      if kind == "heading":
        widgets.append(GreyBigButton(tr(item["title"]), ""))
      elif kind == "toggle":
        toggle = BigParamControl(tr(item["title"]), item["param"], description=item["desc"] or "")
        self._toggles.append(toggle)
        widgets.append(toggle)
      elif kind == "value":
        multi = _multi_toggle_item(item)
        if multi is not None:
          self._value_buttons.append(multi)  # refresh() exists there too
          widgets.append(multi)
        else:
          value_btn = ParamValueButton(tr(item["title"]), item["param"], item["min"], item["max"],
                                       item["step"], fmt=item["fmt"], labels=item["labels"],
                                       desc=item["desc"] or "")
          self._value_buttons.append(value_btn)
          widgets.append(value_btn)
      elif kind == "action":
        action_btn = BigButton(tr(item["title"]), tr(item["btn_text"]), description=item["desc"] or "")
        action_btn.set_click_callback(item["callback"])
        widgets.append(action_btn)
      elif kind == "status":
        status_btn = BigButton(tr(item["title"]), "", description=item["desc"] or "")
        status_btn.set_enabled(False)
        self._status_rows.append((status_btn, item["value_callback"]))
        widgets.append(status_btn)
      else:
        raise ValueError(f"unknown carrot item kind: {kind}")

    self._scroller.add_widgets(widgets)

  def show_event(self):
    super().show_event()
    # Mirror external param changes into the rows (navigation.py pattern).
    for toggle in self._toggles:
      toggle.refresh()
    for btn in self._value_buttons:
      btn.refresh()

  def _update_state(self):
    super()._update_state()
    for btn, value_callback in self._status_rows:
      btn.set_value(value_callback())


class CarrotLayoutMici(NavScroller):
  """Carrot tuning root page: Carrot Web toggle + one entry per group.

  Sub-pages are built on first open: the groups hold ~160 items in total and
  there is no reason to allocate them all when the page is only passed through
  (same lazy layout as Big GUI CarrotTuningLayout)."""

  def __init__(self):
    super().__init__()
    self._params = Params()

    self._carrot_web_toggle = BigParamControl(tr("Carrot Web Panel"), "CarrotWebEnabled",
                                              description=tr("Serve the carrot tuning page (/nav_params) and four-corner radar " +
                                                             "visualisation (/radar) on port 8088."))

    self._group_buttons: dict[str, BigButton] = {}
    self._group_pages: dict[str, NavScroller] = {}
    for key, group_title, group_desc in carrot_items.CARROT_GROUPS:
      btn = BigButton(tr(group_title), "", description=tr(group_desc))
      btn.set_click_callback(lambda k=key: self._open_group(k))
      self._group_buttons[key] = btn

    self._scroller.add_widgets([
      self._carrot_web_toggle,
      *[self._group_buttons[key] for key, _, _ in carrot_items.CARROT_GROUPS],
    ])

    # The Carrot Web toggle only makes sense offroad, matching Big GUI
    # CarrotTuningLayout._update_state.
    self._carrot_web_toggle.set_enabled(lambda: not ui_state.started)

  def _open_group(self, key: str):
    if key == 'egpu':
      gui_app.push_widget(EgpuPageMici())
      return
    if key not in self._group_pages:
      group_title = next(t for k, t, _ in carrot_items.CARROT_GROUPS if k == key)
      items = carrot_items.CARROT_ITEM_BUILDERS[key]()
      self._group_pages[key] = CarrotGroupPageMici(tr(group_title), items)
    gui_app.push_widget(self._group_pages[key])

  def show_event(self):
    super().show_event()
    self._carrot_web_toggle.refresh()
