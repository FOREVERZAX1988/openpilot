import pyray as rl
from openpilot.system.ui.lib.application import FontWeight
from openpilot.system.ui.lib.multilang import tr, multilang  # # 解决语言选择菜单字符问题修改1：导入全局实例multilang
# 解决语言选择菜单字符问题修改2：添加以下导入
from openpilot.system.ui.lib.multilang import CHINA_LANGUAGES, UNIFONT_LANGUAGES
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.widgets.scroller_tici import Scroller

# Constants
MARGIN = 50
TITLE_FONT_SIZE = 70
ITEM_HEIGHT = 135
BUTTON_SPACING = 50
BUTTON_HEIGHT = 160
ITEM_SPACING = 50
LIST_ITEM_SPACING = 25


class MultiOptionDialog(Widget):
  def __init__(self, title, options, current="", option_font_weight=FontWeight.MEDIUM):
    super().__init__()
    self.title = title
    self.options = options
    self.current = current
    self.selection = current
    self._result: DialogResult = DialogResult.NO_ACTION

        # 解决语言选择菜单字符问题修改3：新增：根据当前语言动态调整字体权重
    self.option_buttons = []
    lang = multilang.language
    try:
      if lang in CHINA_LANGUAGES:
          # 中文使用中文字体
          option_font_weight = FontWeight.CHINA  # 需确保该权重对应china.ttf
      elif lang in UNIFONT_LANGUAGES:
          # 其他特殊语言使用unifont
          option_font_weight = FontWeight.CHINA  # 需确保该权重对应unifont.otf
    except AttributeError:
      # 若FontWeight无对应枚举，降级为默认，避免崩溃
      option_font_weight = FontWeight.MEDIUM

        # 解决语言选择菜单字符问题修改4：创建选项按钮（修复闭包问题+明确参数）
    for option in self.options:
        print(f"选项: {option}, 当前语言: {lang}, 字体权重: {option_font_weight}")  # 新增调试输出
        def on_click(opt=option): 
          self._on_option_clicked(opt)
        btn = Button(
          text=option,
          click_callback=on_click,
          font_weight=option_font_weight,
          text_alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
          button_style=ButtonStyle.NORMAL,
          text_padding=50,
          elide_right=True
          )
        self.option_buttons.append(btn)
    
    self.scroller = Scroller(self.option_buttons, spacing=LIST_ITEM_SPACING)

    #解决语言选择菜单字符问题修改5：修复取消/确认按钮文本参数（原lambda传参错误）
    self.cancel_button = Button(
      text=tr("Cancel"), 
      click_callback=lambda: self._set_result(DialogResult.CANCEL),
      button_style=ButtonStyle.NORMAL
      )
    self.select_button = Button(
      text=tr("Select"), 
      click_callback=lambda: self._set_result(DialogResult.CONFIRM), 
      button_style=ButtonStyle.PRIMARY
      )

  def _set_result(self, result: DialogResult):
    self._result = result

  def _on_option_clicked(self, option):
    self.selection = option

  def _render(self, rect):
    dialog_rect = rl.Rectangle(rect.x + MARGIN, rect.y + MARGIN, rect.width - 2 * MARGIN, rect.height - 2 * MARGIN)
    rl.draw_rectangle_rounded(dialog_rect, 0.02, 20, rl.Color(30, 30, 30, 255))

    content_rect = rl.Rectangle(dialog_rect.x + MARGIN, dialog_rect.y + MARGIN,
                                dialog_rect.width - 2 * MARGIN, dialog_rect.height - 2 * MARGIN)

    gui_label(rl.Rectangle(content_rect.x, content_rect.y, content_rect.width, TITLE_FONT_SIZE), self.title, 70, font_weight=FontWeight.BOLD)

    # Options area
    options_y = content_rect.y + TITLE_FONT_SIZE + ITEM_SPACING
    options_h = content_rect.height - TITLE_FONT_SIZE - BUTTON_HEIGHT - 2 * ITEM_SPACING
    options_rect = rl.Rectangle(content_rect.x, options_y, content_rect.width, options_h)

    # Update button styles and set width based on selection
    for i, option in enumerate(self.options):
      selected = option == self.selection
      button = self.option_buttons[i]
      button.set_button_style(ButtonStyle.PRIMARY if selected else ButtonStyle.NORMAL)
      button.set_rect(rl.Rectangle(0, 0, options_rect.width, ITEM_HEIGHT))

    self.scroller.render(options_rect)

    # Buttons
    button_y = content_rect.y + content_rect.height - BUTTON_HEIGHT
    button_w = (content_rect.width - BUTTON_SPACING) / 2

    cancel_rect = rl.Rectangle(content_rect.x, button_y, button_w, BUTTON_HEIGHT)
    self.cancel_button.render(cancel_rect)

    select_rect = rl.Rectangle(content_rect.x + button_w + BUTTON_SPACING, button_y, button_w, BUTTON_HEIGHT)
    self.select_button.set_enabled(self.selection != self.current)
    self.select_button.render(select_rect)

    return self._result
