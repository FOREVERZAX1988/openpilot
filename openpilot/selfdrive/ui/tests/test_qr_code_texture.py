"""QRCodeTexture lifecycle tests.

The pip `qrcode` + pyray-era implementation this widget used before could
never produce a texture under raylib_nb (no rl.ffi, and Image has no
writable `data` field), so every dialog fell back to its "Offline"
placeholder. These tests pin the fixed behavior: set_data delegates to the
vendored openpilot.common.qrcode.make_texture, textures are reused across
identical payloads, failures degrade to unavailable, and destroy() only
unloads GPU resources while a window exists. raylib_nb is stubbed, so no
OpenGL context is required.
"""
import sys
import unittest
from types import SimpleNamespace as NS

CALLS: list[tuple] = []
WINDOW_READY = [False]


def _fake_make_texture(data: str):
  if data == "boom":
    raise RuntimeError("renderer exploded")
  CALLS.append(("make_texture", data))
  return NS(id=len(CALLS), width=33, height=33)


class _StubRl:
  class Texture:  # identity only
    pass

  class Rectangle:
    def __init__(self, x, y, width, height):
      self.x, self.y, self.width, self.height = x, y, width, height

  class Vector2:
    def __init__(self, x, y):
      self.x, self.y = x, y

  class PixelFormat:
    PIXELFORMAT_UNCOMPRESSED_R8G8B8A8 = 1

  class TextureFilter:
    TEXTURE_FILTER_POINT = 1

  WHITE = NS(name="WHITE")

  @staticmethod
  def set_texture_filter(texture, _filter):
    CALLS.append(("set_texture_filter", texture.id))

  @staticmethod
  def draw_texture_pro(texture, _source, _dest, _origin, _rotation, _tint):
    CALLS.append(("draw_texture_pro", texture.id))

  @staticmethod
  def unload_texture(texture):
    CALLS.append(("unload_texture", texture.id))

  @staticmethod
  def is_window_ready():
    return WINDOW_READY[0]


STUB_MODULES = {
  "raylib_nb": _StubRl,
  "openpilot.system.ui.lib.raylib_compat": NS(),
  "openpilot.common.swaglog": NS(cloudlog=NS(exception=lambda *a, **k: CALLS.append(("cloudlog.exception", str(a))))),
  "openpilot.common.qrcode": NS(make_texture=_fake_make_texture),
}


class TestQRCodeTexture(unittest.TestCase):
  def setUp(self):
    CALLS.clear()
    WINDOW_READY[0] = False
    self._saved = {}
    for name, mod in STUB_MODULES.items():
      self._saved[name] = sys.modules.get(name)
      sys.modules[name] = mod

    import importlib
    import openpilot.selfdrive.ui.widgets.qr_code as module
    self.qr_module = importlib.reload(module)

  def tearDown(self):
    for name, mod in self._saved.items():
      if mod is None:
        sys.modules.pop(name, None)
      else:
        sys.modules[name] = mod

  def _texture(self):
    return self.qr_module.QRCodeTexture()

  def test_empty_data_never_builds_a_texture(self):
    for payload in (None, ""):
      texture = self._texture()
      self.assertFalse(texture.available)
      self.assertTrue(texture.set_data(payload))  # None and "" normalize identically
      self.assertFalse(texture.available)
      self.assertFalse(texture.render(_StubRl.Rectangle(0, 0, 10, 10)))
    self.assertEqual([], CALLS)

  def test_set_data_builds_and_filters_texture(self):
    texture = self._texture()
    self.assertTrue(texture.set_data("http://192.168.7.246:7000"))
    self.assertTrue(texture.available)
    self.assertEqual([("make_texture", "http://192.168.7.246:7000"),
                      ("set_texture_filter", 1)], CALLS)

  def test_render_draws_available_texture(self):
    texture = self._texture()
    texture.set_data("http://192.168.7.246:5080")
    self.assertTrue(texture.render(_StubRl.Rectangle(0, 0, 50, 50)))
    self.assertEqual(("draw_texture_pro", 1), CALLS[-1])

  def test_identical_payload_is_not_regenerated(self):
    texture = self._texture()
    self.assertTrue(texture.set_data("http://192.168.7.246:5090"))
    self.assertFalse(texture.set_data("http://192.168.7.246:5090"))
    self.assertEqual(1, sum(1 for call in CALLS if call[0] == "make_texture"))

  def test_payload_change_replaces_texture(self):
    texture = self._texture()
    texture.set_data("http://192.168.7.246:7000")
    WINDOW_READY[0] = True
    self.assertTrue(texture.set_data("http://192.168.7.246:5080"))
    self.assertEqual(2, sum(1 for call in CALLS if call[0] == "make_texture"))
    self.assertIn(("unload_texture", 1), CALLS)
    self.assertTrue(texture.available)

  def test_renderer_failure_degrades_to_unavailable(self):
    texture = self._texture()
    self.assertTrue(texture.set_data("boom"))
    self.assertFalse(texture.available)
    self.assertFalse(texture.render(_StubRl.Rectangle(0, 0, 10, 10)))
    self.assertEqual([("cloudlog.exception", "('Carrot Web QR code generation failed',)")], CALLS)

  def test_destroy_skips_gpu_when_no_window(self):
    texture = self._texture()
    texture.set_data("http://192.168.7.246:7000")
    texture.destroy()
    self.assertFalse(("unload_texture", 1) in CALLS)  # window never became ready
    self.assertFalse(texture.available)
    self.assertIsNone(texture._data)


if __name__ == "__main__":
  unittest.main()
