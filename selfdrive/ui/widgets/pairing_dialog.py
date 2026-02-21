import pyray as rl
import qrcode
import numpy as np
import time
import jwt
from datetime import datetime, timedelta, UTC

from openpilot.common.api.base import BaseApi
from openpilot.common.swaglog import cloudlog
from openpilot.common.params import Params
from openpilot.system.athena.registration import UNREGISTERED_DONGLE_ID
from openpilot.system.hardware import HARDWARE
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets.button import IconButton
from openpilot.selfdrive.ui.ui_state import ui_state


class PairingDialog(Widget):
  """Dialog for device pairing with QR code."""

  QR_REFRESH_INTERVAL = 300  # 5 minutes in seconds

  def __init__(self):
    super().__init__()
    self.params = Params()
    self.qr_texture: rl.Texture | None = None
    self.last_qr_generation = float('-inf')
    self._close_btn = IconButton(gui_app.texture("icons/close.png", 80, 80))
    self._close_btn.set_click_callback(lambda: gui_app.set_modal_overlay(None))

  def _get_pairing_url(self) -> str:
    try:
      serial = HARDWARE.get_serial() or "unknown"
    except Exception as e:
      cloudlog.warning(f"Failed to get serial: {e}")
      serial = "unknown"

    try:
      imei1 = HARDWARE.get_imei(0) or ""
    except Exception as e:
      cloudlog.warning(f"Failed to get imei1: {e}")
      imei1 = ""

    try:
      imei2 = HARDWARE.get_imei(1) or ""
    except Exception as e:
      cloudlog.warning(f"Failed to get imei2: {e}")
      imei2 = ""

    try:
      algorithm, private_key, public_key = BaseApi.get_key_pair()
      if not private_key:
        cloudlog.error("No device keys found")
        return "error://keys_not_found"

      dongle_id = self.params.get("DongleId")

      now = datetime.now(UTC).replace(tzinfo=None)
      payload = {
        'imei': imei1,
        'imei2': imei2,
        'serial': serial,
        'public_key': public_key,
        'register': True,
        'exp': now + timedelta(hours=1),
      }
      if dongle_id and dongle_id != UNREGISTERED_DONGLE_ID:
        payload['identity'] = dongle_id

      token = jwt.encode(payload, private_key, algorithm=algorithm)
      if isinstance(token, bytes):
        token = token.decode('utf8')
      return f"https://konn3kt.com/?pair={token}"
    except FileNotFoundError as e:
      cloudlog.error(f"Key files not found: {e}")
      return "error://keys_not_found"
    except Exception as e:
      cloudlog.error(f"Failed to generate pairing token: {e}")
      return "error://token_generation_failed"

  def _generate_qr_code(self) -> None:
    try:
      url = self._get_pairing_url()
      if url.startswith("error://"):
        cloudlog.warning(f"Cannot generate QR code: {url}")
        self.qr_texture = None
        return

      qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
      qr.add_data(url)
      qr.make(fit=True)

      pil_img = qr.make_image(fill_color="black", back_color="white").convert('RGBA')
      img_array = np.array(pil_img, dtype=np.uint8)

      if self.qr_texture and self.qr_texture.id != 0:
        rl.unload_texture(self.qr_texture)

      rl_image = rl.Image()
      rl_image.data = rl.ffi.cast("void *", img_array.ctypes.data)
      rl_image.width = pil_img.width
      rl_image.height = pil_img.height
      rl_image.mipmaps = 1
      rl_image.format = rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8

      self.qr_texture = rl.load_texture_from_image(rl_image)
    except Exception:
      cloudlog.exception("QR code generation failed")
      self.qr_texture = None

  def _check_qr_refresh(self) -> None:
    current_time = time.monotonic()
    if current_time - self.last_qr_generation >= self.QR_REFRESH_INTERVAL:
      self._generate_qr_code()
      self.last_qr_generation = current_time

  def _update_state(self):
    if ui_state.prime_state.is_paired():
      gui_app.set_modal_overlay(None)

  def _render(self, rect: rl.Rectangle) -> int:
    rl.clear_background(rl.Color(224, 224, 224, 255))

    self._check_qr_refresh()

    margin = 70
    content_rect = rl.Rectangle(rect.x + margin, rect.y + margin, rect.width - 2 * margin, rect.height - 2 * margin)
    y = content_rect.y

    # Close button
    close_size = 80
    pad = 20
    close_rect = rl.Rectangle(content_rect.x - pad, y - pad, close_size + pad * 2, close_size + pad * 2)
    self._close_btn.render(close_rect)

    y += close_size + 40

    # Title
    title = tr("Pair your device to your Konn3kt account")
    title_font = gui_app.font(FontWeight.NORMAL)
    left_width = int(content_rect.width * 0.5 - 15)

    title_wrapped = wrap_text(title_font, title, 75, left_width)
    rl.draw_text_ex(title_font, "\n".join(title_wrapped), rl.Vector2(content_rect.x, y), 75, 0.0, rl.BLACK)
    y += len(title_wrapped) * 75 + 60

    # Two columns: instructions and QR code
    remaining_height = content_rect.height - (y - content_rect.y)
    right_width = content_rect.width // 2 - 20

    # Instructions
    self._render_instructions(rl.Rectangle(content_rect.x, y, left_width, remaining_height))

    # QR code
    qr_size = min(right_width, content_rect.height) - 40
    qr_x = content_rect.x + left_width + 40 + (right_width - qr_size) // 2
    qr_y = content_rect.y
    self._render_qr_code(rl.Rectangle(qr_x, qr_y, qr_size, qr_size))

    return -1

  def _render_instructions(self, rect: rl.Rectangle) -> None:
    instructions = [
      tr("Go to https://konn3kt.com on your phone"),
      tr("Click \"add new device\" and scan the QR code on the right"),
      tr("Bookmark konn3kt.com to your home screen to use it like an app"),
    ]

    font = gui_app.font(FontWeight.BOLD)
    y = rect.y

    for i, text in enumerate(instructions):
      circle_radius = 25
      circle_x = rect.x + circle_radius + 15
      text_x = rect.x + circle_radius * 2 + 40
      text_width = rect.width - (circle_radius * 2 + 40)

      wrapped = wrap_text(font, text, 47, int(text_width))
      text_height = len(wrapped) * 47
      circle_y = y + text_height // 2

      # Circle and number
      rl.draw_circle(int(circle_x), int(circle_y), circle_radius, rl.Color(70, 70, 70, 255))
      number = str(i + 1)
      number_size = measure_text_cached(font, number, 30)
      rl.draw_text_ex(font, number, (int(circle_x - number_size.x // 2), int(circle_y - number_size.y // 2)), 30, 0, rl.WHITE)

      # Text
      rl.draw_text_ex(font, "\n".join(wrapped), rl.Vector2(text_x, y), 47, 0.0, rl.BLACK)
      y += text_height + 50

  def _render_qr_code(self, rect: rl.Rectangle) -> None:
    if not self.qr_texture:
      rl.draw_rectangle_rounded(rect, 0.1, 20, rl.Color(240, 240, 240, 255))
      error_font = gui_app.font(FontWeight.BOLD)
      rl.draw_text_ex(
        error_font, tr("QR Code Error"), rl.Vector2(rect.x + 20, rect.y + rect.height // 2 - 15), 30, 0.0, rl.RED
      )
      return

    source = rl.Rectangle(0, 0, self.qr_texture.width, self.qr_texture.height)
    rl.draw_texture_pro(self.qr_texture, source, rect, rl.Vector2(0, 0), 0, rl.WHITE)

  def __del__(self):
    if self.qr_texture and self.qr_texture.id != 0:
      rl.unload_texture(self.qr_texture)


if __name__ == "__main__":
  gui_app.init_window("pairing device")
  pairing = PairingDialog()
  try:
    for _ in gui_app.render():
      result = pairing.render(rl.Rectangle(0, 0, gui_app.width, gui_app.height))
      if result != -1:
        break
  finally:
    del pairing
