"""Applies and restores Safe Mode against the real parameter store.

The rules live in safe_mode.py, which is plain logic. This file is the thin
layer that reads and writes Params, and it keeps every read defensive: a key
that the device's parameter library does not know about yet must leave the
feature alone, not take the caller down.
"""
import datetime
import json
from typing import Any

from openpilot.common.params import ParamKeyType
from openpilot.sunnypilot.common.param_read import read_bool
from openpilot.sunnypilot.common.safe_mode import (
  SAFE_MODE_BACKUP_PARAM,
  SAFE_MODE_MANAGED_KEYS,
  SAFE_MODE_PARAM,
  backup_entry,
  can_restore,
  load_backup,
  missing_backup_keys,
  restore_plan,
  safe_value,
  serialize_backup,
)


def _get(params, key: str) -> Any:
  """The raw value of a key, or None when it is not set.

  Returns None for a key the store does not know about, which is the same
  answer as "not set": Safe Mode must not act on it.

  A JSON key keeps its structure: load_backup needs the document itself, and
  str()-ing a dict yields Python repr, which is not JSON, parses to "no backup",
  and made every restore a silent no-op.
  """
  try:
    value = params.get(key)
  except Exception:
    return None
  if value is None:
    return None
  if isinstance(value, (dict, list)):
    return value
  if isinstance(value, bool):
    # The store writes a BOOL as "1"/"0"; str(False) is "False" and never equals a
    # target, which made every enforce cycle rewrite all the BOOL keys.
    return "1" if value else "0"
  if isinstance(value, bytes):
    return value.decode("utf-8", errors="ignore")
  return str(value)


def _stock(params, key: str) -> str | None:
  """The registered stock value of a key, or None when it is not known."""
  try:
    value = params.get_stock_value(key)
  except Exception:
    return None
  if value is None:
    return None
  if isinstance(value, bytes):
    value = value.decode("utf-8", errors="ignore")
  text = str(value)
  return text if text else None


def _default(params, key: str) -> str | None:
  """The registered default of a key, or None when it has none.

  Deliberately not ``get(key, return_default=True)``: that returns the *stored* value
  once the key is set, so the "fall back to the registered default" branch of
  safe_value received the very value it was supposed to replace and the reset was a
  no-op. The registered default is a property of the key, not of the store.
  """
  try:
    value = params.get_default_value(key)
  except Exception:
    return None
  if value is None:
    return None
  if isinstance(value, bool):
    return "1" if value else "0"
  if isinstance(value, bytes):
    return value.decode("utf-8", errors="ignore")
  return str(value)


def _coerce(params, key: str, value: str):
  """Turn a backup string into the type the key is registered with.

  Safe Mode works in strings, because that is what a backup document holds and what
  the rules in safe_mode.py compare. ``Params.put`` is strictly typed: it raises
  TypeError for a str written to a BOOL/INT/FLOAT/JSON key, so writing the string
  straight through fails for every managed key and _put swallows it. The coercion
  belongs here, at the store boundary, and nowhere above it.

  Returns None when the string does not fit the type, which _put reports as "not
  written" rather than writing something nobody asked for.
  """
  try:
    key_type = params.get_type(key)
  except Exception:
    return value
  try:
    if key_type == ParamKeyType.BOOL:
      return value.strip().lower() not in ("", "0", "false", "no")
    if key_type == ParamKeyType.INT:
      return int(float(value))
    if key_type == ParamKeyType.FLOAT:
      return float(value)
    if key_type == ParamKeyType.JSON:
      return json.loads(value)
    if key_type == ParamKeyType.TIME:
      return datetime.datetime.fromisoformat(value)
    if key_type == ParamKeyType.BYTES:
      return value.encode()
  except (TypeError, ValueError):
    return None
  return value


def _put(params, key: str, value: str) -> bool:
  """Write a key, tolerating a store that does not know it.

  Returns whether anything was written, so the caller can tell whether the
  car has to cycle for the change to take effect.
  """
  typed = _coerce(params, key, value)
  if typed is None:
    return False
  try:
    params.put(key, typed, block=True)
    return True
  except Exception:
    return False


def is_safe_mode(params) -> bool:
  """Whether Safe Mode is switched on."""
  return read_bool(params, SAFE_MODE_PARAM, False)


def _write_backup(params, backup: dict) -> None:
  # Goes through _put so the JSON key gets a dict, not the serialized string.
  _put(params, SAFE_MODE_BACKUP_PARAM, serialize_backup(backup))


def apply_safe_mode(params, *, ensure_backup: bool = True) -> bool:
  """Force the managed knobs to their safe values. Returns whether to cycle.

  ``ensure_backup`` is False on the periodic re-apply: once the original
  values are recorded they must not be overwritten with the forced ones.
  """
  changed = False

  if ensure_backup:
    backup = load_backup(_get(params, SAFE_MODE_BACKUP_PARAM))
    missing = missing_backup_keys(backup)
    if missing:
      for key in missing:
        current = _get(params, key)
        backup[key] = backup_entry(current is not None, current)
      _write_backup(params, backup)
      changed = True

  backup = load_backup(_get(params, SAFE_MODE_BACKUP_PARAM))
  for key in SAFE_MODE_MANAGED_KEYS:
    target = safe_value(key,
                        current=_get(params, key),
                        stock=_stock(params, key),
                        default=_default(params, key))
    if target is None:
      # Nothing sane to write for this key. Leaving it alone is the only
      # honest option: writing a placeholder would change it to a value
      # nobody chose.
      continue
    if _get(params, key) == target:
      continue
    if _put(params, key, target):
      changed = True

  return changed


def restore_safe_mode(params) -> bool:
  """Undo Safe Mode from the backup. Returns whether anything changed.

  Refused while the car is moving: restoring rewrites the steering
  parameters, which must not happen mid-drive.
  """
  is_onroad = read_bool(params, "IsOnroad", False)
  is_offroad = read_bool(params, "IsOffroad", False)
  if not can_restore(is_onroad, is_offroad):
    return False

  backup = load_backup(_get(params, SAFE_MODE_BACKUP_PARAM))
  changed = False

  for key, value in restore_plan(backup):
    if not backup:
      # Nothing recorded: the keys were never forced, so there is nothing to
      # put back. This happens when Safe Mode was toggled before the backup
      # was ever written.
      break
    if value is None:
      try:
        params.remove(key)
        changed = True
      except Exception:
        pass
    elif _get(params, key) != value:
      if _put(params, key, value):
        changed = True

  try:
    params.remove(SAFE_MODE_BACKUP_PARAM)
  except Exception:
    pass

  return changed


def enforce_safe_mode(params, frame: int) -> bool:
  """Re-apply the forced values on a slow cadence while Safe Mode is on.

  Returns whether anything changed. Returns False when Safe Mode is off, so
  the caller can use it unconditionally.
  """
  if not is_safe_mode(params):
    return False
  from openpilot.sunnypilot.common.safe_mode import SAFE_MODE_ENFORCE_FRAMES
  if frame % SAFE_MODE_ENFORCE_FRAMES != 0:
    return False
  return apply_safe_mode(params, ensure_backup=False)


def backup_document(params) -> dict[str, Any]:
  """The current backup document, for display and tests."""
  return load_backup(_get(params, SAFE_MODE_BACKUP_PARAM))
