import time

import raylib_nb as rl

from openpilot.common.params import Params
from openpilot.common.qrcode import make_texture
from openpilot.common.swaglog import cloudlog
from openpilot.sunnypilot.agent.tailscale import parse_tailscale_state
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.widgets.button import IconButton


JOINED_POP_SECONDS = 6.0


class TailscaleDialog(Widget):
  """Full-screen pairing dialog for the Remote SSH (Tailscale) toggle.

  Renders the auth URL from the TailscaleState param (written by AGNOS's
  tailscale_manager.py) as a QR code, and follows the join until it completes.
  Pops itself once the device shows as joined.
  """

  POLL_INTERVAL = 1.0

  def __init__(self, params: Params | None = None):
    super().__init__()
    self._params = params or Params()
    self._raw_state: str | None = None
    self._state = parse_tailscale_state(None)
    self._qr_texture: rl.Texture | None = None
    self._next_poll = 0.0
    self._joined_at: float | None = None
    self._close_btn = IconButton(gui_app.texture("icons/close.png", 80, 80))
    self._close_btn.set_click_callback(gui_app.pop_widget)

  def _poll_state(self) -> None:
    now = time.monotonic()
    if now < self._next_poll:
      return
    self._next_poll = now + self.POLL_INTERVAL

    raw = self._params.get("TailscaleState")
    if raw == self._raw_state:
      return
    self._raw_state = raw
    self._state = parse_tailscale_state(raw)

    if self._state.status == "pairing" and self._state.url:
      try:
        if self._qr_texture and self._qr_texture.id != 0:
          rl.unload_texture(self._qr_texture)
        self._qr_texture = make_texture(self._state.url)
      except Exception:
        cloudlog.exception("Tailscale QR generation failed")
        self._qr_texture = None
    elif self._state.status == "joined" and self._joined_at is None:
      self._joined_at = now

  def _update_state(self):
    self._poll_state()
    if self._joined_at is not None and time.monotonic() - self._joined_at >= JOINED_POP_SECONDS:
      gui_app.pop_widget()

  def _render(self, rect: rl.Rectangle) -> int:
    rl.clear_background(rl.Color(224, 224, 224, 255))

    margin = 70
    content = rl.Rectangle(rect.x + margin, rect.y + margin, rect.width - 2 * margin, rect.height - 2 * margin)

    close_size = 80
    self._close_btn.render(rl.Rectangle(content.x - 20, content.y - 20, close_size + 40, close_size + 40))

    bold_font = gui_app.font(FontWeight.BOLD)
    normal_font = gui_app.font(FontWeight.NORMAL)

    y = content.y + close_size + 30

    # Status headline
    if self._state.status == "pairing":
      headline = tr("Scan to join your Tailscale network")
    elif self._state.status == "joined":
      headline = tr("Remote SSH is ready")
    elif self._state.status == "error":
      headline = tr("Tailscale error")
    else:
      headline = tr("Waiting for Tailscale state...")
    rl.draw_text_ex(bold_font, headline, rl.Vector2(content.x, y), 64, 0.0, rl.BLACK)
    y += 90

    if self._state.status == "pairing":
      steps = [
        tr("1. Install the Tailscale app on your phone and sign in"),
        tr("2. Scan this QR code and tap Connect in the browser"),
        tr("3. Once joined, SSH to the address shown here"),
      ]
      for step in steps:
        rl.draw_text_ex(normal_font, step, rl.Vector2(content.x, y), 40, 0.0, rl.BLACK)
        y += 55

      qr_size = max(0, min(content.width // 2 - 40, content.height - (y - content.y) - 40))
      if self._qr_texture:
        source = rl.Rectangle(0, 0, self._qr_texture.width, self._qr_texture.height)
        rl.draw_texture_pro(self._qr_texture, source,
                            rl.Rectangle(content.x + content.width // 2 + 20, y, qr_size, qr_size),
                            rl.Vector2(0, 0), 0.0, rl.WHITE)
      else:
        rl.draw_text_ex(normal_font, tr("Generating QR..."), rl.Vector2(content.x + content.width // 2 + 20, y), 40, 0.0, rl.BLACK)
    elif self._state.status == "joined":
      lines = [tr("SSH to your device from any device in your Tailscale network:"), f"ssh comma@{self._state.ip}"]
      for line in lines:
        rl.draw_text_ex(normal_font, line, rl.Vector2(content.x, y), 44, 0.0, rl.BLACK)
        y += 60
    elif self._state.status == "error":
      wrapped = wrap_text(normal_font, self._state.message or tr("Unknown error"), 60, int(content.width))
      rl.draw_text_ex(normal_font, "\n".join(wrapped), rl.Vector2(content.x, y), 40, 0.0, rl.BLACK)

    return -1

  def __del__(self):
    if self._qr_texture and self._qr_texture.id != 0:
      rl.unload_texture(self._qr_texture)


if __name__ == "__main__":
  gui_app.init_window("tailscale pairing")
  gui_app.push_widget(TailscaleDialog())
  try:
    for _ in gui_app.render():
      pass
  finally:
    pass
