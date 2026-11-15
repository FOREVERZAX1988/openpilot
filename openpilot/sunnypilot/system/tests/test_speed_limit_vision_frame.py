"""
Regression guard for speed_limit_vision's onroad camera frame path.

VisionBuf.data (msgq.visionipc) is a memoryview, not a NumPy array. The ported
daemon used to call ``data.any()`` on it, which raised AttributeError on the
first real camera frame. manager restarted the daemon ~2x/s for the whole
drive, starving camerad/modeld and producing the cameraFrameRate / commIssue /
modeldLagging / processNotRunning soft-disable chain.

Static on purpose: the daemon pulls in cv2 and the compiled messaging stack, so
this runs on a PC as well as on device.
"""

import ast
import unittest
from pathlib import Path

_DAEMON = Path(__file__).resolve().parents[2] / "system" / "speed_limit_vision.py"


def _receive_frame_bgr_node():
  tree = ast.parse(_DAEMON.read_text(encoding="utf-8"))
  for cls in tree.body:
    if isinstance(cls, ast.ClassDef):
      for fn in cls.body:
        if isinstance(fn, ast.FunctionDef) and fn.name == "_receive_frame_bgr":
          return fn
  raise AssertionError("_receive_frame_bgr not found in speed_limit_vision.py")


class TestReceiveFrameBGR(unittest.TestCase):
  def setUp(self):
    self.fn = _receive_frame_bgr_node()

  def _calls(self):
    return [n for n in ast.walk(self.fn) if isinstance(n, ast.Call)]

  def test_no_numpy_method_on_raw_memoryview(self):
    """data.any() is invalid on a memoryview - that was the onroad crash."""
    bad = [c for c in self._calls()
           if isinstance(c.func, ast.Attribute) and c.func.attr == "any"
           and isinstance(c.func.value, ast.Name) and c.func.value.id == "data"]
    assert not bad, "raw VisionBuf.data must not be treated as a NumPy array"

  def test_empty_frame_guard(self):
    src = ast.unparse(self.fn)
    assert "len(data) == 0" in src, "empty camera buffer must be dropped"

  def test_numpy_view_used_for_zero_check_and_decode(self):
    src = ast.unparse(self.fn)
    assert "np.frombuffer(data" in src
    assert "image.any()" in src, "all-zero frame guard must run on the NumPy view"
    assert "image.reshape(" in src
    assert "cv2.cvtColor(" in src


if __name__ == "__main__":
  unittest.main()
