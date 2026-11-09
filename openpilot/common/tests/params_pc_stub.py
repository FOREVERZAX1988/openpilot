"""Shared PC stub for the native Params backend.

The real openpilot.common.params loads a C extension (libparams) that is not
built on PC test hosts. Several test suites stub it independently; divergent
stubs used to poison each other through sys.modules (the first import wins for
the whole run). Every suite must import THIS stub instead of defining its own,
so behavior is identical regardless of module load order.

Behavior mirrors the real backend closely enough for the suites that use it:
missing keys read as None (0/"" for the typed getters with return_default),
BOOL values round-trip as "1"/"0", and get() returns ints when the stored
value parses as one (real Params casts INT-typed keys the same way).
"""


class Params:
  _store: dict[str, str] = {}

  def __init__(self, *args, **kwargs):
    pass

  @classmethod
  def _reset(cls):
    cls._store = {}

  def get(self, key, encoding=None, return_default=False, **kwargs):
    value = self._store.get(key)
    if value is None:
      return 0 if return_default else None
    try:
      return int(value)
    except (TypeError, ValueError):
      return value

  def get_bool(self, key, return_default=False, **kwargs):
    return self._store.get(key, "0") == "1"

  def get_int(self, key, return_default=False, default=0, **kwargs):
    try:
      return int(self._store.get(key, "0"))
    except (TypeError, ValueError):
      return default

  def get_float(self, key, return_default=False, **kwargs):
    try:
      return float(self._store.get(key, "nan"))
    except (TypeError, ValueError):
      return float("nan")

  def put(self, key, value, **kwargs):
    if value is True or value == "1":
      value = "1"
    elif value is False or value == "0":
      value = "0"
    else:
      value = str(value)
    self._store[key] = value

  def put_bool(self, key, value, **kwargs):
    self._store[key] = "1" if value else "0"

  def put_bool_nonblocking(self, key, value, **kwargs):
    self.put_bool(key, value)

  def put_int(self, key, value, **kwargs):
    self._store[key] = str(int(value))

  def put_int_nonblocking(self, key, value, **kwargs):
    self.put_int(key, value)

  def remove(self, key, *args, **kwargs):
    self._store.pop(key, None)


def register():
  """Install this stub as openpilot.common.params for the whole process.

  Import-time side effect lives behind an explicit call so merely importing
  the stub module never mutates sys.modules.
  """
  import sys
  import types
  if 'openpilot.common.params' not in sys.modules:
    module = types.ModuleType('openpilot.common.params')
    module.Params = Params
    sys.modules['openpilot.common.params'] = module
