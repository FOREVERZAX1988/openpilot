import pyray as rl
import time

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import gui_label


class PrimeWidget(Widget):
  """Widget for displaying Konn3kt pairing status"""

  PRIME_BG_COLOR = rl.Color(51, 51, 51, 255)
  KONN3KT_ONLINE_NS = 80_000_000_000  # 80 seconds in nanoseconds

  def _render(self, rect):
    if ui_state.prime_state.is_paired():
      self._render_for_paired_user(rect)
    else:
      self._render_for_unpaired_users(rect)

  def _is_konn3kt_online(self) -> bool:
    last_ping = ui_state.sm['deviceState'].lastAthenaPingTime
    return last_ping != 0 and (time.monotonic_ns() - last_ping) < self.KONN3KT_ONLINE_NS

  def _render_for_unpaired_users(self, rect: rl.Rectangle):
    """Renders the pairing prompt for unpaired users."""

    rl.draw_rectangle_rounded(rect, 0.025, 10, self.PRIME_BG_COLOR)

    # Layout
    x, y = rect.x + 80, rect.y + 90
    w = rect.width - 160

    # Title
    gui_label(rl.Rectangle(x, y, w, 90), tr("Pair Your Device"), 75, font_weight=FontWeight.BOLD)

    # Description with wrapping
    desc_y = y + 140
    font = gui_app.font(FontWeight.NORMAL)
    wrapped_text = "\n".join(wrap_text(font, tr("Pair your device in the Konn3kt app"), 56, int(w)))
    text_size = measure_text_cached(font, wrapped_text, 56)
    rl.draw_text_ex(font, wrapped_text, rl.Vector2(x, desc_y), 56, 0, rl.WHITE)

    # Features section
    features_y = desc_y + text_size.y + 50
    gui_label(rl.Rectangle(x, features_y, w, 50), tr("Konn3kt Features:"), 41, font_weight=FontWeight.BOLD)

    # Feature list
    features = [tr("Remote access"), tr("Live streaming"), tr("Unlimited route storage"), tr("And so much more")]
    for i, feature in enumerate(features):
      item_y = features_y + 80 + i * 65
      gui_label(rl.Rectangle(x, item_y, 100, 60), "✓", 50, color=rl.Color(70, 91, 234, 255))
      gui_label(rl.Rectangle(x + 60, item_y, w - 60, 60), feature, 50)

  def _render_for_paired_user(self, rect: rl.Rectangle):
    """Renders the paired status widget."""

    rl.draw_rectangle_rounded(rl.Rectangle(rect.x, rect.y, rect.width, 230), 0.1, 10, self.PRIME_BG_COLOR)

    x = rect.x + 56
    y = rect.y + 34

    font = gui_app.font(FontWeight.BOLD)
    rl.draw_text_ex(font, tr("Konn3kt"), rl.Vector2(x, y), 75, 0, rl.WHITE)

    status_label = tr("Konn3kt Status:")
    status_font = gui_app.font(FontWeight.NORMAL)
    status_font_size = 48
    status_pos = rl.Vector2(x, y + 95)
    rl.draw_text_ex(status_font, status_label, status_pos, status_font_size, 0, rl.WHITE)

    status_size = measure_text_cached(status_font, status_label, status_font_size)
    is_online = self._is_konn3kt_online()
    status_color = rl.Color(134, 255, 78, 255) if is_online else rl.Color(201, 34, 49, 255)

    dot_x = int(status_pos.x + status_size.x + 26)
    dot_y = int(status_pos.y + status_size.y / 2)
    rl.draw_circle(dot_x, dot_y, 14, status_color)
