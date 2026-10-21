"""Applies and restores Safe Mode against the real parameter store.

The rules live in safe_mode.py, which is plain logic. This file is the thin
layer that reads and writes Params, and it keeps every read defensive: a key
that the device's parameter library does not know about yet must leave the
feature alone, not take the caller down.
"""
from typing import Any

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


def _get(params, key: str) -> str | None:
  """The raw string value of a key, or None when it is not set.

  Returns None for a key the store does not know about, which is the same
  answer as "not set": Safe Mode must not act on it.
  """
  try:
    value = params.get(key)
  except Exception:
    return None
  if value is None:
    return None
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
  try:
    value = params.get(key, return_default=True)
  except Exception:
    return None
  if value is None or isinstance(value, bool):
    return None if value is None else ("1" if value else "0")
  if isinstance(value, bytes):
    return value.decode("utf-8", errors="ignore")
  return str(value)


def _put(params, key: str, value: str) -> bool:
  """Write a key, tolerating a store that does not know it.

  Returns whether anything was written, so the caller can tell whether the
  car has to cycle for the change to take effect.
  """
  try:
    params.put(key, value, block=True)
    return True
  except Exception:
    return False


def is_safe_mode(params) -> bool:
  """Whether Safe Mode is switched on."""
  return read_bool(params, SAFE_MODE_PARAM, False)


def _write_backup(params, backup: dict) -> None:
  try:
    params.put(SAFE_MODE_BACKUP_PARAM, serialize_backup(backup), block=True)
  except Exception:
    pass


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
