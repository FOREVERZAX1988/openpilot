import raylib_nb as rl
from collections.abc import Callable
from openpilot.system.ui.lib.application import gui_app, FontWeight, TextAlignment
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.widgets.scroller_tici import Scroller

# Constants (Big GUI 2160x1080 baseline; mici 536x240 uses the COMPACT set below)
MARGIN = 50
TITLE_FONT_SIZE = 70
ITEM_HEIGHT = 135
BUTTON_SPACING = 50
BUTTON_HEIGHT = 160
ITEM_SPACING = 50
LIST_ITEM_SPACING = 25

# mici-sized set: the Big GUI constants alone need ~500px height, which does not
# fit the 536x240 mici screen (title clipped, cancel/select stacked over content)
COMPACT_HEIGHT_THRESHOLD = 500
MARGIN_COMPACT = 10
TITLE_FONT_SIZE_COMPACT = 34
ITEM_HEIGHT_COMPACT = 60
BUTTON_SPACING_COMPACT = 16
BUTTON_HEIGHT_COMPACT = 68
ITEM_SPACING_COMPACT = 12
LIST_ITEM_SPACING_COMPACT = 10


class MultiOptionDialog(Widget):
  def __init__(self, title, options, current="", option_font_weight=FontWeight.MEDIUM, callback: Callable[[DialogResult], None] | None = None):
    super().__init__()
    self.title = title
    self.options = options
    self.current = current
    self.selection = current
    self._callback = callback

    # mici 536x240 and other small panels get the compact metrics; Big GUI keeps
    # the baseline ones
    self._compact = gui_app.height < COMPACT_HEIGHT_THRESHOLD
    margin = MARGIN_COMPACT if self._compact else MARGIN
    title_font_size = TITLE_FONT_SIZE_COMPACT if self._compact else TITLE_FONT_SIZE
    item_height = ITEM_HEIGHT_COMPACT if self._compact else ITEM_HEIGHT
    button_height = BUTTON_HEIGHT_COMPACT if self._compact else BUTTON_HEIGHT
    item_spacing = ITEM_SPACING_COMPACT if self._compact else ITEM_SPACING
    button_spacing = BUTTON_SPACING_COMPACT if self._compact else BUTTON_SPACING
    list_item_spacing = LIST_ITEM_SPACING_COMPACT if self._compact else LIST_ITEM_SPACING

    # Create scroller with option buttons
    self.option_buttons = [Button(option, click_callback=lambda opt=option: self._on_option_clicked(opt),
                                  font_weight=option_font_weight,
                                  text_alignment=TextAlignment.LEFT, button_style=ButtonStyle.NORMAL,
                                  text_padding=50, elide_right=True) for option in options]
    self.scroller = Scroller(self.option_buttons, spacing=list_item_spacing)

    self.cancel_button = Button(lambda: tr("Cancel"), click_callback=lambda: self._set_result(DialogResult.CANCEL))
    self.select_button = Button(lambda: tr("Select"), click_callback=lambda: self._set_result(DialogResult.CONFIRM), button_style=ButtonStyle.PRIMARY)

    self._metrics = (margin, title_font_size, item_height, button_height, item_spacing, button_spacing)

  def _set_result(self, result: DialogResult):
    gui_app.pop_widget()
    if self._callback:
      self._callback(result)

  def _on_option_clicked(self, option):
    self.selection = option

  def _render(self, rect):
    margin, title_font_size, item_height, button_height, item_spacing, button_spacing = self._metrics
    dialog_rect = rl.Rectangle(rect.x + margin, rect.y + margin, rect.width - 2 * margin, rect.height - 2 * margin)
    rl.draw_rectangle_rounded(dialog_rect, 0.02, 20, rl.Color(30, 30, 30, 255))

    content_rect = rl.Rectangle(dialog_rect.x + margin, dialog_rect.y + margin,
                                dialog_rect.width - 2 * margin, dialog_rect.height - 2 * margin)

    gui_label(rl.Rectangle(content_rect.x, content_rect.y, content_rect.width, title_font_size), self.title, title_font_size, font_weight=FontWeight.BOLD)

    # Options area
    options_y = content_rect.y + title_font_size + item_spacing
    options_h = content_rect.height - title_font_size - button_height - 2 * item_spacing
    options_rect = rl.Rectangle(content_rect.x, options_y, content_rect.width, max(options_h, 0))

    # Update button styles and set width based on selection
    for i, option in enumerate(self.options):
      selected = option == self.selection
      button = self.option_buttons[i]
      button.set_button_style(ButtonStyle.PRIMARY if selected else ButtonStyle.NORMAL)
      button.set_rect(rl.Rectangle(0, 0, options_rect.width, item_height))

    self.scroller.render(options_rect)

    # Buttons
    button_y = content_rect.y + content_rect.height - button_height
    button_w = (content_rect.width - button_spacing) / 2

    cancel_rect = rl.Rectangle(content_rect.x, button_y, button_w, button_height)
    self.cancel_button.render(cancel_rect)

    select_rect = rl.Rectangle(content_rect.x + button_w + button_spacing, button_y, button_w, button_height)
    self.select_button.set_enabled(self.selection != self.current)
    self.select_button.render(select_rect)
