"""Device-side tests for the curve-speed learning persistence (StarPilot
curve_speed/preferences.py port): strict decode, size limit, versioned
document with legacy migration, atomic async writes with read-back
verification, and external-edit conflict suspension."""
import json
import os
import tempfile
import time
import unittest

from openpilot.selfdrive.controls.lib.curve_speed_persistence import (
  DOCUMENT_KEY,
  DOCUMENT_VERSION,
  EXTERNAL_EDIT,
  LearningPersistence,
  SAVED,
  WRITE_FAILED,
  decode,
  load_document,
  read_saved,
)


class FakeParams:
  """Contract-faithful stand-in backed by a real tempdir (params-contract:
  exact signatures; get_param_path points into <root>/d/<KEY>)."""

  def __init__(self, root):
    self.root = root

  def get_param_path(self, key=""):
    return os.path.join(self.root, "d", key)


class TestDecodeAndLoad(unittest.TestCase):
  def test_decode_rejects_duplicate_keys(self):
    raw = b'{"a": 1, "a": 2}'  # json.dumps cannot emit dup keys; craft raw bytes
    with self.assertRaises(ValueError):
      decode(raw)

  def test_load_versioned_document(self):
    with tempfile.TemporaryDirectory() as root:
      params = FakeParams(root)
      path = params.get_param_path(DOCUMENT_KEY)
      os.makedirs(os.path.dirname(path), exist_ok=True)
      with open(path, "wb") as f:
        f.write(json.dumps({"version": DOCUMENT_VERSION, "buckets": {"0.01": {"average": 2.5, "count": 10}}}).encode())
      data, valid, reason = load_document(params)
      self.assertTrue(valid)
      self.assertEqual(data, {"0.01": {"average": 2.5, "count": 10}})

  def test_load_legacy_document(self):
    with tempfile.TemporaryDirectory() as root:
      params = FakeParams(root)
      path = params.get_param_path(DOCUMENT_KEY)
      os.makedirs(os.path.dirname(path), exist_ok=True)
      with open(path, "wb") as f:
        f.write(json.dumps({"0.01": {"average": 2.5, "count": 10}}).encode())
      data, valid, _ = load_document(params)
      self.assertTrue(valid)
      self.assertEqual(data, {"0.01": {"average": 2.5, "count": 10}})

  def test_load_invalid_document(self):
    with tempfile.TemporaryDirectory() as root:
      params = FakeParams(root)
      path = params.get_param_path(DOCUMENT_KEY)
      os.makedirs(os.path.dirname(path), exist_ok=True)
      with open(path, "wb") as f:
        f.write(b"not json at all")
      data, valid, reason = load_document(params)
      self.assertFalse(valid)
      self.assertIsNone(data)
      self.assertEqual(reason, "invalid_learning")

  def test_load_versioned_missing_buckets(self):
    with tempfile.TemporaryDirectory() as root:
      params = FakeParams(root)
      path = params.get_param_path(DOCUMENT_KEY)
      os.makedirs(os.path.dirname(path), exist_ok=True)
      with open(path, "wb") as f:
        f.write(json.dumps({"version": DOCUMENT_VERSION}).encode())
      _, valid, reason = load_document(params)
      self.assertFalse(valid)
      self.assertEqual(reason, "invalid_learning")

  def test_read_saved_over_limit_unreadable(self):
    with tempfile.TemporaryDirectory() as root:
      params = FakeParams(root)
      path = params.get_param_path(DOCUMENT_KEY)
      os.makedirs(os.path.dirname(path), exist_ok=True)
      with open(path, "wb") as f:
        f.write(b"x" * 40960)  # > DOCUMENT_LIMIT
      raw, readable = read_saved(params, DOCUMENT_KEY, 32768)
      self.assertFalse(readable)


class TestLearningPersistence(unittest.TestCase):
  def _params(self):
    root = tempfile.mkdtemp(prefix="curvepersist_")
    self.addCleanup(lambda: None)  # keep tmpdir for post-mortem; tests are tiny
    return FakeParams(root), root

  def _wait_for_status(self, persistence, status, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
      events = persistence.poll()
      if any(s == status for _, s in events):
        return events
      time.sleep(0.01)
    raise AssertionError(f"status {status} not reached in {timeout}s")

  def test_write_roundtrip_and_readback(self):
    params, root = self._params()
    persistence = LearningPersistence(params)
    buckets = {"0.01": {"average": 2.5, "count": 42}}
    revision = persistence.submit(buckets)
    self.assertIsNotNone(revision)
    self._wait_for_status(persistence, SAVED)

    # document on disk: versioned, verified
    data, valid, _ = load_document(params)
    self.assertTrue(valid)
    self.assertEqual(data, buckets)

    # a fresh owner reads the same data
    second = LearningPersistence(params)
    self.assertEqual(second.load_data(), buckets)

  def test_external_edit_suspends_persistence(self):
    params, root = self._params()
    persistence = LearningPersistence(params)
    persistence.submit({"0.01": {"average": 2.0, "count": 1}})
    self._wait_for_status(persistence, SAVED)

    # an external editor replaces the document out-of-band
    path = params.get_param_path(DOCUMENT_KEY)
    with open(path, "wb") as f:
      f.write(json.dumps({"version": DOCUMENT_VERSION, "buckets": {}}).encode())

    revision = persistence.submit({"0.01": {"average": 3.0, "count": 2}})
    self.assertIsNotNone(revision)
    self._wait_for_status(persistence, EXTERNAL_EDIT)
    self.assertTrue(persistence.conflicted)

    # further writes are refused; the on-disk document keeps the external edit
    self.assertIsNone(persistence.submit({"0.01": {"average": 4.0, "count": 3}}))
    data, valid, _ = load_document(params)
    self.assertTrue(valid)
    self.assertEqual(data, {})

  def test_document_limit_enforced(self):
    params, root = self._params()
    persistence = LearningPersistence(params)
    # 24 buckets is small; blow the limit with a huge fake bucket count
    big = {str(i / 10000): {"average": 2.0, "count": 10 ** 9} for i in range(4000)}
    revision = persistence.submit(big)
    self.assertIsNotNone(revision)
    self._wait_for_status(persistence, WRITE_FAILED)
    self.assertFalse(persistence.conflicted)  # size failure is not an external edit
    self.assertFalse(os.path.exists(params.get_param_path(DOCUMENT_KEY)))

  def test_closed_persistence_refuses_writes(self):
    params, root = self._params()
    persistence = LearningPersistence(params)
    persistence.close()
    self.assertIsNone(persistence.submit({"0.01": {"average": 2.0, "count": 1}}))


if __name__ == "__main__":
  unittest.main()
