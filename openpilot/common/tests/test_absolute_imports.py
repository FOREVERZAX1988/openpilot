"""No file may import a package root this checkout does not publish.

`openpilot/cereal`, `openpilot/selfdrive`, `openpilot/sunnypilot` ... live one level
down, so the import roots are `openpilot.cereal`, `openpilot.selfdrive`, and so on.
Writing the old flat spelling (`from cereal import car`) does not raise at review time
and it does not raise in the file that matters either: it sits inside a `try/except`
that answers "unknown platform", so the feature gate it feeds never fires and the
feature it was supposed to grey out stays clickable. That is exactly how
`feature_support.current_fingerprint()` came back `None` for every car, Macan included,
while the NNFF row stayed live.

Static on purpose: `openpilot.cereal` builds its capnp schemas at import time, so half
of these modules cannot be imported off-device at all.

Sibling guard: `sunnypilot/carrot/tests/test_relative_imports_resolve.py` covers `from .x
import y`; this file covers the absolute spelling.
"""
import ast
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Top-level names that only resolve when the *inside* of `openpilot/` is on sys.path.
#: `msgq`, `opendbc`, `panda` and `tinygrad` are real installed roots and not listed.
LEGACY_ROOTS = ("cereal", "selfdrive", "common", "system", "sunnypilot", "tools")


def legacy_imports_in_source(source: str) -> list[tuple[int, str]]:
  """(lineno, what) for every absolute import whose root this checkout does not publish."""
  # The translation scripts re-root sys.path onto `openpilot/` themselves and then import
  # `selfdrive.*` on purpose; that is the one spelling that is legal here.
  if "sys.path.insert" in source:
    return []
  try:
    tree = ast.parse(source)
  except SyntaxError:
    return []
  found: list[tuple[int, str]] = []
  for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom) and node.level == 0:
      root = (node.module or "").split(".")[0]
      if root in LEGACY_ROOTS:
        found.append((node.lineno, f"from {node.module} import ..."))
    elif isinstance(node, ast.Import):
      for alias in node.names:
        if alias.name.split(".")[0] in LEGACY_ROOTS:
          found.append((node.lineno, f"import {alias.name}"))
  return found


def legacy_imports(root: str) -> list[str]:
  problems: list[str] = []
  for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if d != "__pycache__"]
    for filename in filenames:
      if not filename.endswith(".py"):
        continue
      path = os.path.join(dirpath, filename)
      try:
        with open(path, encoding="utf-8", errors="replace") as f:
          source = f.read()
      except OSError:
        continue
      for lineno, what in legacy_imports_in_source(source):
        problems.append(f"{os.path.relpath(path, root)}:{lineno} -> {what}")
  return problems


class AbsoluteImportRootTests(unittest.TestCase):

  def test_every_absolute_import_has_a_published_root(self):
    problems = legacy_imports(REPO_ROOT)
    self.assertFalse(problems, "imports a root this checkout does not publish:\n  " + "\n  ".join(problems))

  def test_the_check_can_actually_fail(self):
    """Guard the guard: the bug this file exists for must be visible to it."""
    self.assertEqual(legacy_imports_in_source("from cereal import car\n"), [(1, "from cereal import ...")])
    self.assertEqual(legacy_imports_in_source("import msgq.visionipc\n"), [])
    self.assertEqual(legacy_imports_in_source("from openpilot.cereal import log\n"), [])
    self.assertEqual(legacy_imports_in_source("sys.path.insert(0, x)\nfrom selfdrive import y\n"), [])


if __name__ == "__main__":
  unittest.main()
