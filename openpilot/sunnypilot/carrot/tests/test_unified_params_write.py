"""Unit tests for UnifiedParams' write path into the system Params store.

Regression guard: ``_write_to_system`` used to call ``Params.put_int``/``put_float``. This
binding only exposes ``put``/``put_bool``, so every integer tuning raised AttributeError,
was swallowed by the blanket ``except`` and silently landed in ``nav_params.json`` instead
of the Params store. The setting never took effect (``get()`` prefers the store) and the
repo-tracked JSON got dirtied.
"""
import json
import os
import tempfile
import unittest

from openpilot.common.params import UnknownKeyName
from openpilot.sunnypilot.carrot.config import UnifiedParams


class FakeParamStore:
  """Mimics openpilot.common.params.Params as it exists on device.

  Exposes only ``put``/``put_bool`` (no ``put_int``/``put_float``) and type-checks the value
  against the registered key type, like ``Params.python2cpp`` does.
  """

  BOOL = "BOOL"
  INT = "INT"
  STRING = "STRING"

  def __init__(self, types: dict[str, str]):
    self.types = dict(types)
    self.values: dict[str, object] = {}
    self.put_calls: list[tuple[str, object]] = []

  def check_key(self, key):
    if key not in self.types:
      raise UnknownKeyName(key)
    return key

  def get_type(self, key):
    return self.types[self.check_key(key)]

  def get(self, key, block=False, return_default=False):
    key = self.check_key(key)
    if key in self.values:
      return self.values[key]
    return {self.INT: 0, self.BOOL: False, self.STRING: ""}[self.types[key]]

  def put(self, key, dat, block=False):
    key = self.check_key(key)
    kind = self.types[key]
    if kind == self.BOOL and not isinstance(dat, bool):
      raise TypeError(f"Type mismatch while writing param {key}: {dat!r}")
    if kind == self.INT and not isinstance(dat, int):
      raise TypeError(f"Type mismatch while writing param {key}: {dat!r}")
    if kind == self.STRING and not isinstance(dat, str):
      raise TypeError(f"Type mismatch while writing param {key}: {dat!r}")
    self.values[key] = dat
    self.put_calls.append((key, dat))

  def put_bool(self, key, val, block=False):
    self.values[self.check_key(key)] = bool(val)
    self.put_calls.append((key, bool(val)))


class FailingParamStore(FakeParamStore):
  """Store that knows the key but cannot persist it (e.g. /data full)."""

  def put(self, key, dat, block=False):
    self.check_key(key)
    raise OSError("no space left on device")

  def put_bool(self, key, val, block=False):
    self.check_key(key)
    raise OSError("no space left on device")


class TestUnifiedParamsWriteToSystem(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.nav_json = os.path.join(self.tmpdir, "nav_params.json")
    with open(self.nav_json, "w", encoding="utf-8") as fh:
      json.dump({}, fh)

    UnifiedParams._instance = None
    UnifiedParams._initialized = False
    self.params = UnifiedParams(nav_json_file=self.nav_json)
    self.store = FakeParamStore({
      "MacanStartStopDistance": FakeParamStore.INT,
      "Brightness": FakeParamStore.INT,
      "CarrotEnabled": FakeParamStore.BOOL,
    })
    self.params._system_params = self.store

  def _nav_cache(self) -> dict:
    with open(self.nav_json, encoding="utf-8") as fh:
      return json.load(fh)

  def test_store_has_no_put_int_like_the_device_binding(self):
    # documents the constraint that broke registered integer writes
    self.assertFalse(hasattr(self.store, "put_int"))
    self.assertFalse(hasattr(self.store, "put_float"))

  def test_registered_int_write_reaches_the_store(self):
    self.params.put("MacanStartStopDistance", 3)
    self.assertEqual(self.store.values["MacanStartStopDistance"], 3)
    self.assertNotIn("MacanStartStopDistance", self._nav_cache())

  def test_registered_int_write_accepts_on_off_values(self):
    for value in (0, 1):
      with self.subTest(value=value):
        UnifiedParams._instance = None
        UnifiedParams._initialized = False
        self.params = UnifiedParams(nav_json_file=self.nav_json)
        self.params._system_params = self.store
        self.params.put("MacanStartStopDistance", value)
        self.assertEqual(self.store.values["MacanStartStopDistance"], value)
        self.assertNotIn("MacanStartStopDistance", self._nav_cache())

  def test_registered_float_is_coerced_to_the_int_key(self):
    self.params.put("Brightness", 42.0)
    self.assertEqual(self.store.values["Brightness"], 42)
    self.assertNotIn("Brightness", self._nav_cache())

  def test_bool_registered_key_accepts_int_0_and_1(self):
    self.params.put("CarrotEnabled", 1)
    self.assertTrue(self.store.values["CarrotEnabled"])
    self.assertNotIn("CarrotEnabled", self._nav_cache())

  def test_bool_registered_key_falls_back_when_given_a_big_int(self):
    # put() rejects an int for a BOOL key -> put_bool path must still be tried
    self.params.put("CarrotEnabled", 3)
    self.assertTrue(self.store.values["CarrotEnabled"])
    self.assertNotIn("CarrotEnabled", self._nav_cache())

  def test_unregistered_key_is_still_cached_in_nav_params_json(self):
    self.params.put("CarrotNotARegisteredParam", 7)
    self.assertEqual(self._nav_cache()["CarrotNotARegisteredParam"], 7)

  def test_nav_params_json_is_written_with_a_trailing_newline(self):
    self.params.put("CarrotNotARegisteredParam", 7)
    with open(self.nav_json, encoding="utf-8") as fh:
      self.assertTrue(fh.read().endswith("\n"))

  def test_registered_key_is_not_cached_when_the_store_write_fails(self):
    self.params._system_params = FailingParamStore({"MacanStartStopDistance": FakeParamStore.INT})
    self.params.put("MacanStartStopDistance", 3)
    # get() prefers the store value (or the schema default), so a cached copy would be
    # ignored and would only dirty the repo-tracked file
    self.assertNotIn("MacanStartStopDistance", self._nav_cache())

  def test_write_survives_a_non_exception_UnknownKeyName_binding(self):
    # The carrot test shims leave a non-exception object where UnknownKeyName used to be;
    # `except (..., UnknownKeyName, ...)` then raised
    # "catching classes that do not inherit from BaseException" and took down the write path.
    import openpilot.sunnypilot.carrot.config as cfg
    original = cfg.UnknownKeyName
    try:
      cfg.UnknownKeyName = None
      self.params.put("CarrotNotARegisteredParam", 7)
      self.assertEqual(self._nav_cache()["CarrotNotARegisteredParam"], 7)

      UnifiedParams._instance = None
      UnifiedParams._initialized = False
      self.params = UnifiedParams(nav_json_file=self.nav_json)
      self.params._system_params = self.store
      self.params.put("MacanStartStopDistance", 3)
      self.assertEqual(self.store.values["MacanStartStopDistance"], 3)
      self.assertNotIn("MacanStartStopDistance", self._nav_cache())
    finally:
      cfg.UnknownKeyName = original


if __name__ == "__main__":
  unittest.main()
