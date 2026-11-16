"""Shared parsing for the TailscaleState param written by AGNOS tailscale_manager.py.

Pure stdlib so both the UI (widgets/tailscale_dialog.py) and tests can use it
without pulling in device-only dependencies.
"""
from dataclasses import dataclass

# Protocol (AGNOS userspace/root/usr/comma/tailscale_manager.py):
#   ""                    disabled / not joined
#   "pairing|<url>"       show QR for <url>
#   "joined|<name>|<ip>"  member of the tailnet
#   "error|<msg>"         last operation failed


@dataclass(frozen=True)
class TailscaleState:
  status: str = ""    # "", "pairing", "joined", "error", or raw unknown payloads
  url: str = ""
  name: str = ""
  ip: str = ""
  message: str = ""


def parse_tailscale_state(raw: str | None) -> TailscaleState:
  value = str(raw or "").strip()
  if not value:
    return TailscaleState(status="")

  parts = value.split("|")
  head = parts[0]

  if head == "pairing" and len(parts) >= 2:
    return TailscaleState(status="pairing", url=parts[1])
  if head == "joined" and len(parts) >= 3:
    return TailscaleState(status="joined", name=parts[1], ip=parts[2])
  if head == "error":
    return TailscaleState(status="error", message="|".join(parts[1:]))
  return TailscaleState(status=head, message=value)
