#!/usr/bin/env python3
"""Bounded asynchronous persistence for the curve-speed learner.

StarPilot curve_speed/preferences.py port, adapted to this fork's hook
architecture: the learner (curve_speed_learning.py) is pure logic with
injected load/put hooks; this module owns the device side of those hooks.

- strict JSON decode (duplicate keys rejected), 32 KB document limit, a
  version field ({'version': 1, 'buckets': {...}}) while still reading the
  legacy raw bucket dict;
- writes run off the planner thread: staging file -> fsync -> params-root
  lock -> external-edit check -> atomic replace -> directory fsync ->
  read-back verification;
- a conflicting external edit suspends persistence for the session - the
  learner keeps its in-memory state but nothing more is written;
- a non-POSIX host (no fcntl) degrades to the same flow without the
  learning lease and params lock; conflict detection still applies.
"""
import json
import os
import tempfile
import threading
from queue import SimpleQueue

try:
  import fcntl
  _HAVE_FCNTL = True
except ImportError:  # non-POSIX host: lease/lock hardening unavailable
  _HAVE_FCNTL = False

DOCUMENT_KEY = 'CurvatureLearningData'
DOCUMENT_VERSION = 1
DOCUMENT_LIMIT = 32768

# statuses surfaced by poll()
SAVED = 'saved'
EXTERNAL_EDIT = 'external_edit'
WRITE_FAILED = 'write_failed'
CANCELLED = 'cancelled'


def _unique_object(items):
  result = {}
  for key, value in items:
    if key in result:
      raise ValueError('duplicate JSON key')
    result[key] = value
  return result


def decode(raw: bytes | None):
  return None if raw is None else json.loads(raw, object_pairs_hook=_unique_object)


def read_saved(params, key: str, limit: int):
  """Read the raw document bytes; returns (raw, readable).

  readable=False means the stored document exists but exceeds the limit -
  treated as corrupt rather than truncated into something plausible.
  """
  try:
    path = params.get_param_path(key)
    if not path or not os.path.exists(path):
      return None, True
    with open(path, 'rb') as f:
      raw = f.read(limit + 1)
    if len(raw) > limit:
      return raw, False
    return raw, True
  except OSError:
    return None, False


def load_document(params, key=DOCUMENT_KEY):
  """Decode the saved document into bucket data for CurvatureLearning.load().

  Accepts the versioned format ({'version': 1, 'buckets': {...}}) and the
  legacy format (the raw bucket dict). Returns (data, valid, reason): data
  is the bucket dict or None, reason is '' when valid.
  """
  raw, readable = read_saved(params, key, DOCUMENT_LIMIT)
  if not readable:
    return None, False, 'unreadable_learning'
  if raw is None:
    return None, True, 'empty'
  try:
    document = decode(raw)
    if not isinstance(document, dict):
      raise ValueError('invalid saved document')
    if document.get('version') == DOCUMENT_VERSION:
      buckets = document.get('buckets')
      if not isinstance(buckets, dict):
        raise ValueError('missing buckets')
      return buckets, True, ''
    # legacy: the document is the bucket dict itself
    return document, True, ''
  except (ValueError, UnicodeDecodeError, RecursionError, OverflowError, TypeError):
    return None, False, 'invalid_learning'


class LearningPersistence:
  """One drive owns the document; writes execute off the planner thread.

  submit() hands a bucket dict to a writer thread and returns the pending
  revision; poll() drains completions and surfaces (revision, status)
  events. The learner stays dirty until its revision is acknowledged, so a
  failed or superseded write is retried on the next flush cadence instead
  of being lost.
  """

  def __init__(self, params, key=DOCUMENT_KEY):
    self.params = params
    self.key = key
    self.completed = SimpleQueue()
    self.worker = None
    self.status = 'idle'
    self.conflicted = False
    self.closed = False
    self.cancel_write = threading.Event()
    self.commit_lock = threading.Lock()
    self._revision = 0

    data, valid, reason = load_document(params, key)
    self.saved_valid = valid
    self.saved_reason = reason
    self.initial_data = data if valid else None
    # expected bytes for the external-edit check: what we read at start, or
    # the bytes of the last write this owner completed
    self.expected_raw, readable = read_saved(params, key, DOCUMENT_LIMIT)
    if not readable:
      self.expected_raw = None

  # -- reading --

  def load_data(self):
    """The initial bucket data for CurvatureLearning.load()."""
    return self.initial_data

  # -- writing --

  def submit(self, buckets: dict) -> int | None:
    """Queue one async write of the bucket dict.

    Returns the pending revision for the caller to acknowledge once poll()
    reports SAVED, or None when persistence is suspended/closed or a write
    is already in flight (the learner re-flushes on its next cadence).
    """
    if self.closed or self.conflicted:
      return None
    if self.worker is not None:
      return None
    self._revision += 1
    document = {'version': DOCUMENT_VERSION, 'buckets': dict(buckets)}
    self.worker = threading.Thread(target=self._write,
                                   args=(document, self._revision, self.expected_raw),
                                   daemon=True, name='curve-learning')
    self.status = 'writing'
    self.worker.start()
    return self._revision

  def poll(self) -> list[tuple[int, str]]:
    """Drain completed writes; returns [(revision, status), ...]."""
    events = []
    while not self.completed.empty():
      revision, status = self.completed.get()
      self.worker = None
      self.status = status
      if status == SAVED:
        pass  # expected_raw updated inside the writer
      elif status == EXTERNAL_EDIT:
        # one-shot flag for the caller's logging; persistence itself is suspended
        self.conflicted = True
      events.append((revision, status))
    return events

  def close(self) -> None:
    with self.commit_lock:
      self.closed = True
      self.cancel_write.set()
    if self.worker is not None:
      self.worker.join(timeout=0.25)

  # -- writer thread --

  def _lock_params_root(self, root: str):
    if not _HAVE_FCNTL:
      return None
    fd = os.open(os.path.join(root, '.lock'), os.O_CREAT | os.O_RDONLY, 0o775)
    while not self.cancel_write.is_set():
      try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
      except BlockingIOError:
        self.cancel_write.wait(0.01)
    os.close(fd)
    return None

  def _write(self, document: dict, revision: int, expected: bytes | None) -> None:
    temporary = None
    try:
      raw = json.dumps(document, allow_nan=False, separators=(',', ':')).encode()
      if len(raw) > DOCUMENT_LIMIT:
        raise ValueError('learning document too large')
      destination = self.params.get_param_path(self.key)
      root = os.path.dirname(os.path.dirname(destination))  # the params root
      os.makedirs(os.path.dirname(destination), exist_ok=True)

      with tempfile.NamedTemporaryFile(prefix='.tmp_curve_', dir=root, delete=False) as staging:
        temporary = staging.name
        staging.write(raw)
        staging.flush()
        os.fsync(staging.fileno())

      lock_fd = self._lock_params_root(root)
      try:
        current, readable = read_saved(self.params, self.key, DOCUMENT_LIMIT)
        if not readable or current != expected:
          self.completed.put((revision, EXTERNAL_EDIT))
          return
        with self.commit_lock:
          if self.cancel_write.is_set():
            self.completed.put((revision, CANCELLED))
            return
          os.replace(temporary, destination)
          temporary = None
        if _HAVE_FCNTL:
          directory_fd = os.open(os.path.dirname(destination), os.O_RDONLY)
          try:
            os.fsync(directory_fd)
          finally:
            os.close(directory_fd)
        # read-back verification: only acknowledge a verified saved revision
        actual, readable = read_saved(self.params, self.key, DOCUMENT_LIMIT)
        if not readable or actual != raw:
          raise OSError('learning write not verified')
        self.expected_raw = raw
        self.completed.put((revision, SAVED))
      finally:
        if lock_fd is not None:
          os.close(lock_fd)
    except (OSError, RuntimeError, ValueError, TypeError, RecursionError, OverflowError):
      self.completed.put((revision, WRITE_FAILED))
    finally:
      if temporary is not None:
        try:
          os.unlink(temporary)
        except FileNotFoundError:
          pass
