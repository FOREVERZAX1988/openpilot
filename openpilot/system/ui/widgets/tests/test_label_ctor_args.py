"""Guard: every keyword a caller passes to ``Label(...)`` must be a real
``Label.__init__`` parameter, and ``no_fallback`` must actually be honoured.

Regression this pins (device UI boot loop, 2026-09-28).  The *flattened* commit
91caae2181 kept the caller side of the "force UNIFONT, skip the CJK fallback"
feature but dropped the callee side::

    # system/ui/widgets/button.py
    self._label = Label(text, ..., elide_right=elide_right,
                        no_fallback=no_fallback)         # <-- passed
    # system/ui/widgets/label.py
    def __init__(self, text, ..., elide_right=False,
                 line_scale=1.0):                        # <-- never accepted

so the very first dialog built at startup (SetupWidget -> Pair-device Button)
died with::

    File ".../system/ui/widgets/button.py", line 102, in __init__
      self._label = Label(..., no_fallback=no_fallback)
    TypeError: Label.__init__() got an unexpected keyword argument 'no_fallback'

``ui.py`` constructs ``MainLayout()`` before it ever paints, so the UI exited 1
on every boot and the manager logged "Restarting ui (exitcode 1)" forever.

Pure ast -- importing the widgets would pull in pyray/gui_app and need a window.
"""

import ast
import unittest
from pathlib import Path

WIDGETS = Path(__file__).resolve().parents[1]
LABEL = WIDGETS / "label.py"
# Every module that constructs a Label(...) directly.
CALLERS = [WIDGETS / "button.py", WIDGETS / "option_dialog.py"]


def _init_params(path: Path, cls_name: str) -> set[str]:
  tree = ast.parse(path.read_text(encoding="utf-8"))
  cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name)
  init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
  return {a.arg for a in [*init.args.args, *init.args.kwonlyargs]} - {"self"}


def _label_calls(path: Path) -> list[ast.Call]:
  tree = ast.parse(path.read_text(encoding="utf-8"))
  return [n for n in ast.walk(tree)
          if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Label"]


class TestLabelCtorArgs(unittest.TestCase):
  def test_no_fallback_is_accepted(self):
    self.assertIn("no_fallback", _init_params(LABEL, "Label"),
                  "Label.__init__ must accept no_fallback (Button/option_dialog pass it)")

  def test_caller_kwargs_all_valid(self):
    accepted = _init_params(LABEL, "Label")
    for caller in CALLERS:
      for call in _label_calls(caller):
        for kw in call.keywords:
          if kw.arg is None:  # **kwargs splat, cannot check statically
            continue
          self.assertIn(kw.arg, accepted,
                        f"{caller.name}:{call.lineno} passes unknown kwarg {kw.arg!r} to Label")

  def test_no_fallback_is_honoured(self):
    """The draw path must branch on self._no_fallback instead of always
    calling font_fallback()."""
    src = LABEL.read_text(encoding="utf-8")
    tree = ast.parse(src)
    label = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Label")
    store = [n for n in ast.walk(label)
             if isinstance(n, ast.Attribute) and n.attr == "_no_fallback"
             and isinstance(n.ctx, ast.Store)]
    self.assertTrue(store, "Label.__init__ must store self._no_fallback")
    # a draw_text_ex call whose 1st arg is an IfExp referring to _no_fallback
    ok = False
    for call in [n for n in ast.walk(label) if isinstance(n, ast.Call)]:
      fname = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
      if fname == "draw_text_ex" and call.args and isinstance(call.args[0], ast.IfExp):
        names = {n.attr for n in ast.walk(call.args[0]) if isinstance(n, ast.Attribute)}
        if "_no_fallback" in names:
          ok = True
    self.assertTrue(ok, "Label.draw must use `self._font if self._no_fallback else font_fallback(...)`")


if __name__ == "__main__":
  unittest.main()
