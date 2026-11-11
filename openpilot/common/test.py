import contextlib
import gc
import importlib
import inspect
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpilot.common.hardware import HARDWARE, COMMA_HARDWARE
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.system.manager import manager


@contextlib.contextmanager
def clean_env():
  starting_env = dict(os.environ)
  try:
    yield
  finally:
    os.environ.clear()
    os.environ.update(starting_env)


# approx lives at the bottom of this module (class _Approx): pytest tolerance
# semantics with a bool-context guard; it is defined after the helpers below
# because it needs no imports from here.

class OpenpilotTestCase(unittest.TestCase):
  """TestCase with openpilot's per-test isolation."""

  COMMA_HARDWARE_TEST = False
  SHARED_DOWNLOAD_CACHE = False
  SHARED_FIXTURE_MODULES = ()

  def __init_subclass__(cls, **kwargs):
    super().__init_subclass__(**kwargs)
    # Preserve legacy xunit hooks and invoke them inside the prefix below.
    for name in ("setup_method", "teardown_method"):
      hook = cls.__dict__.get(name)
      if hook is not None:
        setattr(cls, f"openpilot_{name}", hook)
        setattr(cls, name, None)

  def _fixture(self, name):
    # pytest caches a fixture for the duration of one test, so a fixture used
    # by several tests of the same class sees the same object within a test.
    cache = getattr(self, "_fixture_cache", None)
    if cache is None:
      cache = self._fixture_cache = {}
    if name in cache:
      return cache[name]
    value = self._make_fixture(name)
    cache[name] = value
    return value

  def _make_fixture(self, name):
    if name == "mocker":
      return Mocker(self.addCleanup)
    if name == "monkeypatch":
      return MonkeyPatch(self.addCleanup)
    if name == "subtests":
      return SubTests(self)
    if name == "tmp_path":
      return self._tmp_path()
    if name == "capsys":
      return self._capsys()

    fixture = getattr(inspect.getmodule(type(self)), name, None)
    if fixture is None:
      # ported conftest fixtures: a test module may declare SHARED_FIXTURE_MODULES
      # naming the helper modules that carry fixtures it uses across files.
      # Upstream declares it at module scope but only looks it up on the class,
      # so fixtures such as `params` (ui/sunnypilot/tests/helpers.py) never
      # resolved and the ported UI suites errored out. Accept both spellings.
      modules = (getattr(type(self), 'SHARED_FIXTURE_MODULES', ()) or
                 getattr(inspect.getmodule(type(self)), 'SHARED_FIXTURE_MODULES', ()))
      for mod_name in modules:
        import importlib
        fixture = getattr(importlib.import_module(mod_name), name, None)
        if fixture is not None:
          break
    if fixture is None:
      raise AttributeError(f'unknown fixture {name!r} for {type(self).__module__}')
    kwargs = {p: self._fixture(p) for p in inspect.signature(fixture).parameters}
    value = fixture(**kwargs)
    if inspect.isgenerator(value):
      generator = value
      value = next(generator)
      self.addCleanup(lambda: next(generator, None))
    return value

  def _autouse_fixtures(self):
    """Module-level fixtures marked ``autouse`` run for every test.

    A ported pytest module keeps its fixtures as plain functions; the
    ``AUTOUSE_FIXTURES`` tuple lists the ones that were autouse.
    """
    return getattr(inspect.getmodule(type(self)), "AUTOUSE_FIXTURES", ())

  def _apply_autouse(self):
    for name in self._autouse_fixtures():
      self._fixture(name)

  def use_fixture(self, name):
    """Resolve a module-level fixture by name, as ``@pytest.mark.usefixtures`` does."""
    return self._fixture(name)

  def _tmp_path(self):
    """pytest's ``tmp_path``: a fresh, empty directory per test."""
    path = Path(tempfile.mkdtemp(prefix="openpilot-test-"))
    self.addCleanup(shutil.rmtree, path, True)
    return path

  def _capsys(self):
    """pytest's ``capsys``: capture stdout/stderr for the duration of the test."""
    fixture = _CaptureFixture(self)
    fixture.start()
    return fixture

  def _callTestMethod(self, method):
    # inspect.signature on a bound method raises ValueError when the underlying
    # function has no parameters at all; those need no fixture injection.
    try:
      params = [name for name, param in inspect.signature(method).parameters.items()
                if param.default is inspect.Parameter.empty]
    except ValueError:
      params = []
    return method(**{name: self._fixture(name) for name in params})

  def run(self, result=None):
    # This boundary cannot live in setUp/tearDown: existing unittest classes
    # are allowed to override those hooks without calling super().
    if (self.COMMA_HARDWARE_TEST and not COMMA_HARDWARE) or getattr(type(self), "__unittest_skip__", False):
      return super().run(result)
    test_env = clean_env()
    test_env.__enter__()
    prefix = OpenpilotPrefix(shared_download_cache=self.SHARED_DOWNLOAD_CACHE)
    prefix.__enter__()
    try:
      return super().run(result)
    finally:
      prefix.__exit__(None, None, None)
      manager.manager_cleanup()
      if not gc.isenabled():
        gc.enable()
        gc.collect()
      test_env.__exit__(None, None, None)

  @classmethod
  def setUpClass(cls):
    super().setUpClass()
    if cls.COMMA_HARDWARE_TEST and not COMMA_HARDWARE:
      raise unittest.SkipTest("Skipping comma hardware test on PC")
    cls._class_env = clean_env()
    cls._class_env.__enter__()
    setup_class = getattr(cls, "setup_class", None)
    if setup_class is not None:
      setup_class()

  @classmethod
  def tearDownClass(cls):
    try:
      teardown_class = getattr(cls, "teardown_class", None)
      if teardown_class is not None:
        teardown_class()
    finally:
      cls._class_env.__exit__(None, None, None)
      super().tearDownClass()

  def setUp(self):
    super().setUp()
    self._fixture_cache = {}
    self._apply_autouse()
    if self.COMMA_HARDWARE_TEST and not COMMA_HARDWARE:
      self.skipTest("Skipping comma hardware test on PC")

    if self.COMMA_HARDWARE_TEST:
      HARDWARE.initialize_hardware()
      HARDWARE.set_power_save(False)
      subprocess.run(["pkill", "-9", "-f", "athena"], check=False)

    setup_method = getattr(self, "openpilot_setup_method", None)
    if setup_method is not None:
      setup_method()

  def tearDown(self):
    try:
      teardown_method = getattr(self, "openpilot_teardown_method", None)
      if teardown_method is not None:
        teardown_method()
    finally:
      super().tearDown()


class _Missing:
  def __repr__(self):
    return "<missing>"


_MISSING = _Missing()


class Mocker:
  Mock = mock.Mock
  MagicMock = mock.MagicMock
  call = mock.call
  ANY = mock.ANY
  sentinel = mock.sentinel

  def __init__(self, add_cleanup):
    self._add_cleanup = add_cleanup
    self.patch = Patch(self._start)
    self._patchers = []

  def _start(self, patcher):
    value = patcher.start()
    self._patchers.append(patcher)
    self._add_cleanup(patcher.stop)
    return value

  def stopall(self):
    """Undo every patch started through this mocker."""
    while self._patchers:
      self._patchers.pop().stop()


class Patch:
  def __init__(self, start):
    self._start = start

  def __call__(self, *args, **kwargs):
    return self._start(mock.patch(*args, **kwargs))

  def object(self, *args, **kwargs):
    return self._start(mock.patch.object(*args, **kwargs))

  def dict(self, *args, **kwargs):
    return self._start(mock.patch.dict(*args, **kwargs))


class MonkeyPatch:
  """The subset of pytest's monkeypatch fixture that this repo's tests use.

  Every mutation is undone when the test finishes, matching pytest's
  function-scoped fixture teardown.
  """

  def __init__(self, add_cleanup):
    self._add_cleanup = add_cleanup
    self._undo_stack = []

  def setattr(self, target, name, value=_MISSING, raising=True):
    if value is _MISSING:
      # pytest's two-argument form: setattr("pkg.mod.attr", value)
      if not isinstance(target, str):
        raise TypeError("use setattr(target, name, value) or setattr(target, value) with target being a dotted import string")
      value = name
      name, target = self._derive_importpath(target, raising)
    elif not isinstance(name, str):
      raise TypeError("use setattr(target, name, value) with name being a string")

    original = getattr(target, name, _MISSING)
    if original is _MISSING and raising:
      raise AttributeError(f"{target!r} has no attribute {name!r}")
    setattr(target, name, value)
    self._undo_stack.append(lambda: _restore_attr(target, name, original))
    self._add_cleanup(self.undo)

  @staticmethod
  def _derive_importpath(import_path, raising):
    if "." not in import_path:
      raise TypeError(f"must be absolute import path string, not {import_path!r}")
    module, attr = import_path.rsplit(".", 1)
    target = importlib.import_module(module)
    if raising and not hasattr(target, attr):
      raise AttributeError(f"{module!r} has no attribute {attr!r}")
    return attr, target

  def delattr(self, target, name, raising=True):
    original = getattr(target, name, _MISSING)
    if original is _MISSING:
      if raising:
        raise AttributeError(f"{target!r} has no attribute {name!r}")
      return
    delattr(target, name)
    self._undo_stack.append(lambda: _restore_attr(target, name, original))
    self._add_cleanup(self.undo)

  def setitem(self, dic, name, value):
    missing = name not in dic
    original = dic.get(name, _MISSING)
    dic[name] = value
    if missing:
      self._undo_stack.append(lambda: dic.pop(name, None))
    else:
      self._undo_stack.append(lambda: dic.__setitem__(name, original))
    self._add_cleanup(self.undo)

  def setenv(self, name, value, prepend=None):
    original = os.environ.get(name, _MISSING)
    os.environ[name] = str(value)
    if original is _MISSING:
      self._undo_stack.append(lambda: os.environ.pop(name, None))
    else:
      self._undo_stack.append(lambda: os.environ.__setitem__(name, original))
    self._add_cleanup(self.undo)

  def delenv(self, name, raising=True):
    original = os.environ.get(name, _MISSING)
    if original is _MISSING:
      if raising:
        raise KeyError(name)
      return
    del os.environ[name]
    self._undo_stack.append(lambda: os.environ.__setitem__(name, original))
    self._add_cleanup(self.undo)

  def chdir(self, path):
    original = os.getcwd()
    os.chdir(path)
    self._undo_stack.append(lambda: os.chdir(original))
    self._add_cleanup(self.undo)

  def undo(self):
    """Revert every change this monkeypatch made, most recent first."""
    while self._undo_stack:
      self._undo_stack.pop()()


class SubTests:
  def __init__(self, test_case):
    self._test_case = test_case

  def test(self, label=None, **kwargs):
    return self._test_case.subTest(**kwargs) if label is None else self._test_case.subTest(label, **kwargs)


def _restore_attr(obj, name, original):
  if original is _MISSING:
    with contextlib.suppress(AttributeError):
      delattr(obj, name)
  else:
    setattr(obj, name, original)


class _CapturedResult:
  def __init__(self, out, err):
    self.out = out
    self.err = err


class _CaptureFixture:
  """pytest's ``capsys``: redirect stdout/stderr for the duration of a test."""

  def __init__(self, test_case):
    self._test_case = test_case
    self._out = io.StringIO()
    self._err = io.StringIO()
    self._saved = None

  def start(self):
    self._saved = (sys.stdout, sys.stderr)
    sys.stdout, sys.stderr = self._out, self._err
    self._test_case.addCleanup(self.stop)

  def stop(self):
    if self._saved is not None:
      sys.stdout, sys.stderr = self._saved
      self._saved = None

  def readouterr(self):
    out, err = self._out.getvalue(), self._err.getvalue()
    self._out.truncate(0)
    self._out.seek(0)
    self._err.truncate(0)
    self._err.seek(0)
    return _CapturedResult(out, err)


class _Approx:
  """pytest's ``approx``: an expected value compared within a tolerance.
  Mirrors pytest's tolerance rule: ``abs`` and ``rel`` default to 1e-12 and
  1e-6, and the comparison passes when the actual value is within the larger
  of the two tolerances.
  """

  DEFAULT_ABSOLUTE_TOLERANCE = 1e-12
  DEFAULT_RELATIVE_TOLERANCE = 1e-6

  def __init__(self, expected, rel=None, abs=None):  # noqa: A002 - mirrors pytest's keyword
    self.expected = expected
    self.rel = rel
    self.abs = abs

  def __repr__(self):
    return f"approx({self.expected!r})"

  def __bool__(self):
    raise AssertionError("approx() is not supported in a boolean context. Did you mean: `assert a == approx(b)`?")

  def __eq__(self, actual):
    if isinstance(self.expected, (list, tuple)):
      try:
        if len(actual) != len(self.expected):
          return False
      except TypeError:
        return False
      return all(self._scalar_eq(a, e) for a, e in zip(actual, self.expected, strict=False))
    return self._scalar_eq(actual, self.expected)

  def __ne__(self, other):
    return not (self == other)

  def _scalar_eq(self, actual, expected):
    if isinstance(expected, bool) or not isinstance(expected, (int, float, complex)):
      return actual == expected
    if actual == expected:
      return True
    try:
      return abs(expected - actual) <= self._tolerance(expected)
    except TypeError:
      return False

  def _tolerance(self, expected):
    absolute = self.abs if self.abs is not None else self.DEFAULT_ABSOLUTE_TOLERANCE
    if absolute < 0:
      raise ValueError(f"absolute tolerance can't be negative: {absolute}")
    if self.rel is None and self.abs is not None:
      return absolute
    relative = (self.rel if self.rel is not None else self.DEFAULT_RELATIVE_TOLERANCE) * abs(expected)
    if relative < 0:
      raise ValueError(f"relative tolerance can't be negative: {relative}")
    return max(relative, absolute)


def approx(expected, rel=None, abs=None):  # noqa: A002 - mirrors pytest's keyword
  """pytest-compatible ``approx`` for tests ported to unittest (pytest tolerance
  semantics: the comparison passes when |actual - expected| is within the larger
  of rel * |expected| and abs, defaulting to 1e-6 / 1e-12)."""
  return _Approx(expected, rel=rel, abs=abs)
