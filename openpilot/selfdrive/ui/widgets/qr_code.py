import raylib_nb as rl
import openpilot.system.ui.lib.raylib_compat  # noqa: F401  (pyray-era API shims on raylib_nb)

from openpilot.common.swaglog import cloudlog
from openpilot.common.qrcode import make_texture


class QRCodeTexture:
  def __init__(self):
    self._data: str | None = None
    self._texture: rl.Texture | None = None

  @property
  def available(self) -> bool:
    return self._texture is not None and self._texture.id != 0

  def set_data(self, data: str | None) -> bool:
    normalized = str(data or "")
    if normalized == self._data:
      return False

    self.destroy()
    self._data = normalized
    if not normalized:
      return True

    try:
      # Vendored, dependency-free QR renderer (see openpilot/common/qrcode.py).
      # The previous implementation here drove the pip `qrcode` package with
      # pyray-era rl.ffi / Image.data field assignment, neither of which exists
      # in raylib_nb: the empty rl.Image() fields assignment is invisible to the
      # C struct, so load_texture_from_image always failed and the dialog only
      # ever showed its "Offline" placeholder.
      self._texture = make_texture(normalized)
      rl.set_texture_filter(self._texture, rl.TextureFilter.TEXTURE_FILTER_POINT)
    except Exception:
      cloudlog.exception("Carrot Web QR code generation failed")
      self._texture = None
    return True

  def render(self, rect: rl.Rectangle) -> bool:
    if not self.available:
      return False

    source = rl.Rectangle(0, 0, self._texture.width, self._texture.height)
    rl.draw_texture_pro(self._texture, source, rect, rl.Vector2(0, 0), 0.0, rl.WHITE)
    return True

  def destroy(self) -> None:
    if self.available and rl.is_window_ready():
      rl.unload_texture(self._texture)
    self._texture = None
    self._data = None

  def __del__(self):
    self.destroy()
