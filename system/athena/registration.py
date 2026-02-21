#!/usr/bin/env python3
import os
import re
import secrets
from pathlib import Path

from openpilot.common.params import Params
from openpilot.common.spinner import Spinner
from openpilot.system.hardware.hw import Paths
from openpilot.common.swaglog import cloudlog


UNREGISTERED_DONGLE_ID = "UnregisteredDevice"
_DONGLE_ID_RE = re.compile(r"^[a-fA-F0-9]{16}$")

def get_cached_dongle_id(params: Params | None = None, prefer_readonly: bool = True) -> str | None:
  p = Params() if params is None else params
  param_id = p.get("DongleId")
  if param_id in ("", UNREGISTERED_DONGLE_ID):
    param_id = None

  file_id = None
  dongle_path = Path(Paths.persist_root() + "/comma/dongle_id")
  if dongle_path.is_file():
    try:
      file_id = dongle_path.read_text().strip() or None
    except Exception:
      cloudlog.exception("failed to read cached dongle_id from persist")

  return file_id if (prefer_readonly and file_id) else (param_id or file_id)

def is_valid_dongle_id(dongle_id: str | None) -> bool:
  return bool(dongle_id and _DONGLE_ID_RE.fullmatch(dongle_id))

def ensure_dev_pairing_identity(params: Params | None = None, force_reset: bool = False) -> dict[str, str]:
  p = Params() if params is None else params

  persist_dir = Path(Paths.persist_root()) / "comma"
  dongle_path = persist_dir / "dongle_id"
  persist_writable = True
  try:
    persist_dir.mkdir(parents=True, exist_ok=True)
  except OSError:
    persist_writable = False
    cloudlog.warning("persist storage is not writable, using params-only device identity")

  forced_dongle = os.getenv("KONN3KT_DEV_DONGLE_ID")
  dongle_id = forced_dongle.strip().lower() if forced_dongle else None
  if dongle_id and not is_valid_dongle_id(dongle_id):
    cloudlog.error("KONN3KT_DEV_DONGLE_ID must be 16 hex chars")
    dongle_id = None

  if force_reset:
    dongle_id = None

  if dongle_id is None:
    existing = None
    if persist_writable:
      try:
        existing = dongle_path.read_text().strip().lower() if dongle_path.is_file() else None
      except Exception:
        cloudlog.exception("failed reading existing dev dongle_id")
    if not is_valid_dongle_id(existing):
      existing = p.get("DongleId")
      if isinstance(existing, str):
        existing = existing.strip().lower()
    dongle_id = existing if is_valid_dongle_id(existing) else secrets.token_hex(8)

  if persist_writable:
    try:
      dongle_path.write_text(dongle_id)
    except OSError:
      cloudlog.warning("failed to write persist dongle_id, using params-only device identity")
      persist_writable = False

  p.put("DongleId", dongle_id)
  p.put("HardwareSerial", p.get("HardwareSerial") or f"DEV-{dongle_id}")

  return {
    "dongle_id": dongle_id,
    "serial": p.get("HardwareSerial") or f"DEV-{dongle_id}",
    "persist_dir": str(persist_dir),
  }

def is_registered_device() -> bool:
  dongle = Params().get("DongleId")
  return dongle not in (None, UNREGISTERED_DONGLE_ID)


def register(show_spinner=False) -> str | None:
  # IQ Pilot local identity mode:
  # never perform backend registration/network identity calls.
  params = Params()
  spinner = Spinner() if show_spinner else None
  if spinner is not None:
    spinner.update("initializing local device identity")

  identity = ensure_dev_pairing_identity(params=params, force_reset=False)
  dongle_id = identity["dongle_id"]

  if spinner is not None:
    spinner.close()

  if not dongle_id:
    cloudlog.error("failed to initialize local device identity")
    return UNREGISTERED_DONGLE_ID
  return dongle_id


if __name__ == "__main__":
  print(register())
