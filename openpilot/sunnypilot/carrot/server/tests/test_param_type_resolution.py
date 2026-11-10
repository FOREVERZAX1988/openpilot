"""resolve_param_type: profile preview/apply must type a parameter the same way
a single write does, so a not-yet-registered key is not flagged as an error.

This was the cause of the "오류 3" that appeared on every profile apply.
"""
import unittest
from unittest import mock

from openpilot.sunnypilot.carrot.server.services import params as params_service


class FakeParamKeyType:
  BOOL = "BOOL"
  INT = "INT"
  FLOAT = "FLOAT"
  STRING = "STRING"
  JSON = "JSON"
  TIME = "TIME"
  BYTES = "BYTES"


class FakeParams:
  """Knows a fixed set of registered keys; everything else raises, like the
  native Params does for a key missing from its table."""

  def __init__(self, known):
    self._known = dict(known)

  def get_type(self, key):
    if key in self._known:
      return self._known[key]
    raise KeyError(key)


class TestParamTypeResolution(unittest.TestCase):

  def setUp(self):
    patcher = mock.patch.object(params_service, "ParamKeyType", FakeParamKeyType)
    patcher.start()
    self.addCleanup(patcher.stop)

  def test_a_registered_key_uses_its_native_type(self):
    params = FakeParams({"Known": FakeParamKeyType.INT})
    self.assertEqual(params_service.resolve_param_type(params, "Known", self.int_definition()), FakeParamKeyType.INT)

  def test_the_native_type_wins_over_the_definition(self):
    # A registered key is trusted even if the catalog would infer something else.
    params = FakeParams({"Known": FakeParamKeyType.STRING})
    self.assertEqual(params_service.resolve_param_type(params, "Known", self.int_definition()), FakeParamKeyType.STRING)

  def test_an_unregistered_key_is_typed_from_its_definition(self):
    params = FakeParams({})
    self.assertEqual(params_service.resolve_param_type(params, "New", self.int_definition()), FakeParamKeyType.INT)
    self.assertEqual(params_service.resolve_param_type(params, "New", self.bool_definition()), FakeParamKeyType.BOOL)
    self.assertEqual(params_service.resolve_param_type(params, "New", self.float_definition()), FakeParamKeyType.FLOAT)

  def test_an_unregistered_key_with_no_definition_stays_unknown(self):
    params = FakeParams({})
    self.assertIsNone(params_service.resolve_param_type(params, "New", None))

  def test_inference_is_disabled_without_a_runtime_type_system(self):
    patcher = mock.patch.object(params_service, "ParamKeyType", None)
    patcher.start()
    self.addCleanup(patcher.stop)
    params = FakeParams({})
    self.assertIsNone(params_service.resolve_param_type(params, "New", self.int_definition()))

  def test_inference_matches_the_catalog_type_heuristic(self):
    # A parameter whose bounds are all integers infers int, so a hair-under
    # value would not be dropped by the resolved type.
    params = FakeParams({})
    resolved = params_service.resolve_param_type(params, "New", {"min": -120, "max": 120, "default": 0})
    self.assertEqual(resolved, FakeParamKeyType.INT)

  @staticmethod
  def int_definition():
    return {"min": 0, "max": 100, "default": 5}

  @staticmethod
  def bool_definition():
    return {"min": 0, "max": 1, "default": 0}

  @staticmethod
  def float_definition():
    return {"min": 0.0, "max": 1.0, "default": 0.5}


if __name__ == "__main__":
  unittest.main()
