import pyray as rl
from collections.abc import Callable
from openpilot.sunnypilot.carrot.config import unified_params
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.sunnypilot.lib.styles import style
from openpilot.system.ui.widgets.list_view import ItemAction

# Dimensions and styling constants
BUTTON_WIDTH = 150
BUTTON_HEIGHT = 150
LABEL_WIDTH = 350
BUTTON_SPACING = 25
VALUE_FONT_SIZE = 50
BUTTON_FONT_SIZE = 60
CONTAINER_PADDING = 20


class OptionControlSP(ItemAction):
  def __init__(self, param: str, min_value: int, max_value: int,
               value_change_step: int = 1, enabled: bool | Callable[[], bool] = True,
               on_value_changed: Callable[[int], None] | None = None,
               value_map: dict[int, int] | None = None,
               label_width: int = LABEL_WIDTH,
               use_float_scaling: bool = False, label_callback: Callable[[int], str] | None = None,
               input_title: str | Callable[[], str] | None = None):

    super().__init__(enabled=enabled)
    self.params = unified_params
    self.param_key = param
    self.min_value = min_value
    self.max_value = max_value
    self.value_change_step = value_change_step
    self._minus_enabled = enabled
    self._plus_enabled = enabled
    self.on_value_changed = on_value_changed
    self.value_map = value_map
    self.label_width = label_width
    self.use_float_scaling = use_float_scaling
    self.current_value = min_value
    self.label_callback = label_callback
    self.input_title = input_title
    if self.value_map:
      for key in self.value_map:
        if self.value_map[key] == self.params.get(self.param_key):
          self.current_value = int(key)
          break
    else:
      value = self.params.get(self.param_key)
      if value is None:
        # unset/unregistered key: show the minimum instead of raising TypeError and
        # killing the whole settings layout during construction.
        value = min_value
      self.current_value = int(float(value) * 100.0) if self.use_float_scaling else int(value)

    # Initialize font and button styles
    self._font = gui_app.font(FontWeight.MEDIUM)

    # Layout rectangles for components
    self.minus_btn_rect = rl.Rectangle(0, 0, 0, 0)
    self.plus_btn_rect = rl.Rectangle(0, 0, 0, 0)
    self.label_rect = rl.Rectangle(0, 0, 0, 0)

  def get_value(self) -> int:
    """Get the current value of the control"""
    return self.current_value

  def set_value(self, value: int):
    """Set the control to a specific value"""
    if not (self.min_value <= value <= self.max_value):
      return
    if value == self.current_value:
      return
    self.current_value = value
    if self.value_map:
      self.params.put(self.param_key, self.value_map[value])
    elif self.use_float_scaling:
      self.params.put(self.param_key, value / 100.0)
    else:
      self.params.put(self.param_key, value)
    if self.on_value_changed:
      self.on_value_changed(value)

  def get_displayed_value(self) -> str:
    """Get the displayed value, handling value mapping if present"""
    value = self.current_value

    if callable(self.label_callback):
      if self.value_map:
        return self.label_callback(self.value_map[value])
      else:
        return self.label_callback(value)

    if self.value_map:
      # Use the value map to get the display string
      if value in self.value_map:
        return str(self.value_map[value])  # Return the display string

    # If using float scaling, format as float
    if self.use_float_scaling:
      return f"{value / 100.0:.2f}"

    return str(value)

  def _input_title_text(self) -> str:
    title = self.input_title() if callable(self.input_title) else self.input_title
    return title or tr("Enter value")

  def _editable_text(self) -> str:
    """Prefill for the keypad: the number the +/- buttons act on (mapped value kept as-is)."""
    if self.value_map and self.current_value in self.value_map:
      return str(self.value_map[self.current_value])
    if self.use_float_scaling:
      return f"{self.current_value / 100.0:g}"
    return str(self.current_value)

  def _open_input_dialog(self):
    # Direct numeric entry (user request 2026-09-19): tapping the value box opens the
    # on-screen keypad so a value that +/- stepping reaches only slowly (or an enum index)
    # can be typed.  Imported lazily to avoid a circular import (input_dialog -> keyboard).
    from openpilot.system.ui.sunnypilot.widgets.input_dialog import InputDialogSP
    if self.value_map:
      sub_title = None
    elif self.use_float_scaling:
      sub_title = f"{self.min_value / 100.0:g} - {self.max_value / 100.0:g}"
    else:
      sub_title = f"{self.min_value} - {self.max_value}"
    InputDialogSP(
      self._input_title_text(),
      sub_title=sub_title,
      current_text=self._editable_text(),
      callback=self._on_input_result,
    ).show()

  def _on_input_result(self, result, text: str):
    from openpilot.system.ui.widgets import DialogResult
    if result != DialogResult.CONFIRM:
      return
    text = (text or "").strip().replace(" ", "")
    if not text:
      return
    try:
      typed = float(text)
    except ValueError:
      return  # non-numeric entry: leave the value untouched (do not crash the layout)

    if self.value_map:
      # The box shows the mapped value; find the key that yields it and set that key.
      for key, mapped in self.value_map.items():
        try:
          if abs(float(mapped) - typed) < 1e-6:
            self.set_value(int(key))
            return
        except (TypeError, ValueError):
          continue
      return

    value = int(round(typed * 100.0)) if self.use_float_scaling else int(round(typed))
    value = max(self.min_value, min(self.max_value, value))
    self.set_value(value)

  def _render(self, rect: rl.Rectangle):
    if self._rect.width == 0 or self._rect.height == 0 or not self.is_visible:
      return

    control_width = (BUTTON_WIDTH * 2) + self.label_width + (BUTTON_SPACING * 2)
    total_width = control_width + (CONTAINER_PADDING * 2)
    self._rect.width = total_width

    start_x = self._rect.x + self._rect.width - control_width - (CONTAINER_PADDING * 2)
    component_y = rect.y + (rect.height - BUTTON_HEIGHT) / 2
    self.container_rect = rl.Rectangle(start_x, component_y, total_width, BUTTON_HEIGHT)

    # background
    rl.draw_rectangle_rounded(self.container_rect, 0.2, 20, style.OPTION_CONTROL_CONTAINER_BG)

    # minus button
    self.minus_btn_rect = rl.Rectangle(self.container_rect.x, component_y, BUTTON_WIDTH + CONTAINER_PADDING,
                                       BUTTON_HEIGHT)

    # label
    label_x = self.container_rect.x + CONTAINER_PADDING + BUTTON_WIDTH + BUTTON_SPACING
    self.label_rect = rl.Rectangle(label_x, component_y, self.label_width, BUTTON_HEIGHT)

    # plus button
    plus_x = label_x + self.label_width + BUTTON_SPACING
    self.plus_btn_rect = rl.Rectangle(plus_x, component_y, BUTTON_WIDTH + CONTAINER_PADDING, BUTTON_HEIGHT)

    self._minus_enabled = self.enabled and self.current_value > self.min_value
    self._plus_enabled = self.enabled and self.current_value < self.max_value

    self._render_button(self.minus_btn_rect, "-", self._minus_enabled)
    self._render_value_label()
    self._render_button(self.plus_btn_rect, "+", self._plus_enabled)

  def _render_button(self, rect: rl.Rectangle, text: str, enabled: bool):
    mouse_pos = rl.get_mouse_position()
    is_pressed = (rl.check_collision_point_rec(mouse_pos, rect) and
                  self._touch_valid() and rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT))

    text_color = style.ITEM_TEXT_COLOR if enabled else style.ITEM_DISABLED_TEXT_COLOR

    # highlight
    if enabled and is_pressed:
      rl.draw_rectangle_rounded(rect, 0.2, 20, style.OPTION_CONTROL_BTN_PRESSED)

    # button text
    text_size = measure_text_cached(self._font, text, BUTTON_FONT_SIZE)
    text_x = rect.x + (rect.width - text_size.x) / 2
    text_y = rect.y + (rect.height - text_size.y) / 2
    rl.draw_text_ex(self._font, text, rl.Vector2(text_x, text_y), BUTTON_FONT_SIZE, 0, text_color)

  def _render_value_label(self):
    """Render the current value label"""
    text = self.get_displayed_value()
    text_color = style.ITEM_TEXT_COLOR if self.enabled else style.ITEM_DISABLED_TEXT_COLOR

    # Make it obvious the value box is tappable: tap it to type a value directly.
    if self.enabled:
      rl.draw_rectangle_rounded(self.label_rect, 0.2, 12, style.OPTION_CONTROL_BTN_ENABLED)

    text_size = measure_text_cached(self._font, text, VALUE_FONT_SIZE)
    text_x = self.label_rect.x + (self.label_rect.width - text_size.x) / 2
    text_y = self.label_rect.y + (self.label_rect.height - text_size.y) / 2

    rl.draw_text_ex(self._font, text, rl.Vector2(text_x, text_y), VALUE_FONT_SIZE, 0, text_color)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if self._minus_enabled and rl.check_collision_point_rec(mouse_pos, self.minus_btn_rect):
      new_value = self.current_value - self.value_change_step
      new_value = max(self.min_value, new_value)
      self.set_value(new_value)
    elif self._plus_enabled and rl.check_collision_point_rec(mouse_pos, self.plus_btn_rect):
      new_value = self.current_value + self.value_change_step
      new_value = min(self.max_value, new_value)
      self.set_value(new_value)
    elif self.enabled and self.label_rect.width > 0 and rl.check_collision_point_rec(mouse_pos, self.label_rect):
      self._open_input_dialog()
