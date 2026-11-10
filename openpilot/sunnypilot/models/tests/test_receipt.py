"""modeld load receipt contract tests.

Ported subset of the StarPilot receipt discipline: the JSON decode contract
(strict field set, positive-int identity, digest shape, known model id), the
rlog event roundtrip, and the pure helpers. The fd-based shm paths (dir_fd +
O_NOFOLLOW + O_DIRECTORY) are POSIX-only and verified on device; they are
skipped rather than stubbed so the tests never lie about coverage.
"""

import json
import os
import sys
import types
import unittest
from pathlib import Path

if 'fcntl' not in sys.modules:  # openpilot.common.hardware imports fcntl; POSIX-only, stub for import
  sys.modules['fcntl'] = types.ModuleType('fcntl')

from openpilot.sunnypilot.models import catalog, receipt
from openpilot.sunnypilot.models.receipt import ReceiptUnavailable, logged_model_load, recorded_model_message, _decode
from openpilot.sunnypilot.models.status import ModelLoad, ModelVariant

LOAD = ModelLoad(4321, 987654321, 1234567890, catalog.BUNDLED_CURRENT, ModelVariant.SMALL, 'a' * 64, None)

FD_PATHS_AVAILABLE = hasattr(os, 'O_DIRECTORY') and hasattr(os, 'O_NOFOLLOW')


class TestReceiptDecodeContract(unittest.TestCase):
  def test_decode_accepts_the_canonical_record(self):
    raw = json.dumps({"version": 1, "pid": 1, "processStartTicks": 2, "loadedMonoNs": 3,
                      "modelId": catalog.BUNDLED_CURRENT, "variant": ModelVariant.SMALL.value,
                      "artifactSha256": 'a' * 64, "fallbackReason": None}).encode()
    self.assertEqual(_decode(raw), ModelLoad(1, 2, 3, catalog.BUNDLED_CURRENT, ModelVariant.SMALL, 'a' * 64, None))

  def test_decode_rejects_malformed_and_unknown(self):
    raw = json.dumps({"version": 1, "pid": 1, "processStartTicks": 2, "loadedMonoNs": 3,
                      "modelId": catalog.BUNDLED_CURRENT, "variant": ModelVariant.SMALL.value,
                      "artifactSha256": 'a' * 64, "fallbackReason": None}).encode()
    cases = (
      b'not json',
      raw.replace(b'"version": 1', b'"version": 2'),
      raw.replace(b'"pid": 1', b'"pid": 0'),
      raw.replace(b'"pid": 1', b'"pid": true'),
      raw + b'{"extra": 1}',  # duplicate keys via object_pairs hook path
      raw.replace(b'"artifactSha256": "a' + b'a' * 63, b'"artifactSha256": "b'),
      raw.replace(b'"fallbackReason": null', b'"fallbackReason": "made-up-reason"'),
      raw.replace(catalog.BUNDLED_CURRENT.encode(), b'unknown-model'),
    )
    for case in cases:
      with self.subTest(case=case[:40]):
        with self.assertRaises(ReceiptUnavailable):
          _decode(case)


class TestReceiptLogEvent(unittest.TestCase):
  def test_logged_model_load_roundtrip(self):
    raw = recorded_model_message(LOAD)
    self.assertEqual(logged_model_load(raw), LOAD)

  def test_logged_model_load_rejects_foreign_events(self):
    self.assertIsNone(logged_model_load('{"msg": {"event": "something-else"}}'))
    self.assertIsNone(logged_model_load('garbage'))
    tampered = recorded_model_message(LOAD).replace('"process":4321', '"process":9999')
    self.assertIsNone(logged_model_load(tampered))


class TestReceiptHelpers(unittest.TestCase):
  def test_process_start_ticks_unavailable_returns_zero(self):
    self.assertEqual(receipt.process_start_ticks(999999, proc_root=Path(os.devnull).parent), 0)
    self.assertEqual(receipt.process_start_ticks(0), 0)
    self.assertEqual(receipt.process_start_ticks(-1), 0)


@unittest.skipUnless(FD_PATHS_AVAILABLE, 'POSIX dir_fd receipt paths verified on device')
class TestReceiptFdRoundtrip(unittest.TestCase):
  def test_write_read_clear_roundtrip(self):
    import tempfile
    from openpilot.sunnypilot.models.receipt import write_receipt, read_receipt, clear_receipt
    with tempfile.TemporaryDirectory() as d:
      p = Path(d) / 'load-v1.json'
      write_receipt(LOAD, p)
      self.assertEqual(read_receipt(p), LOAD)
      clear_receipt(p)
      self.assertIsNone(read_receipt(p))


if __name__ == '__main__':
  unittest.main()
