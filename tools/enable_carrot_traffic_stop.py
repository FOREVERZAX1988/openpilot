#!/usr/bin/env python3
"""Batch-enable the carrot traffic-light stop&go gates on a fleet of devices.

Sets two params over the device webui API (port 7000):
  CarrotEnabled                  = 1  (carrot_man publishes carrotManSP)
  CarrotLongitudinalSourceEnabled = 1 (planner runs the carrot 6-state machine)

Both default to 1 since the 2026-11 fix, so this script is only needed for
devices whose params predate the fix (or were reset by a reflash).

Usage:
  python tools/enable_carrot_traffic_stop.py 192.168.1.23 192.168.1.24
  python tools/enable_carrot_traffic_stop.py --file devices.txt
  python tools/enable_carrot_traffic_stop.py --port 7000 192.168.1.23

Each device must be reachable on its webui port from the machine running this.
"""
import argparse
import json
import sys
import urllib.request

PARAMS = {
  "CarrotEnabled": "1",
  "CarrotLongitudinalSourceEnabled": "1",
}
DEFAULT_PORT = 7000
TIMEOUT_S = 8


def _request(base: str, path: str, payload: dict | None = None, method: str = "GET") -> tuple[bool, dict | None]:
  url = f"http://{base}{path}"
  data = json.dumps(payload).encode() if payload is not None else None
  req = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
  try:
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
      return True, json.loads(resp.read().decode())
  except Exception as e:
    print(f"    ! {method} {path} failed: {e}")
    return False, None


def enable_device(host: str, port: int) -> bool:
  base = f"{host}:{port}"
  print(f"[{base}]")
  ok, _ = _request(base, "/api/opui/params/CarrotEnabled")
  if not ok:
    print("    unreachable or API down, skipping")
    return False
  all_ok = True
  for key, value in PARAMS.items():
    wrote, result = _request(base, f"/api/opui/params/{key}",
                             payload={"value": value}, method="PUT")
    ok = bool(wrote and result and result.get("ok"))
    print(f"    {key} = {value}: {'OK' if ok else 'FAILED'}")
    all_ok &= ok
  # Verify by reading back
  for key in PARAMS:
    _, result = _request(base, f"/api/opui/params/{key}")
    read = result.get("value") if result and result.get("ok") else "?"
    print(f"    verify {key} = {read}")
  return all_ok


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("hosts", nargs="*", help="device IPs / hostnames")
  parser.add_argument("--file", help="text file with one host per line")
  parser.add_argument("--port", type=int, default=DEFAULT_PORT)
  args = parser.parse_args()

  hosts = list(args.hosts)
  if args.file:
    with open(args.file) as f:
      hosts += [line.strip() for line in f if line.strip() and not line.startswith("#")]
  if not hosts:
    parser.print_usage()
    return 1

  failed = [h for h in hosts if not enable_device(h, args.port)]
  if failed:
    print(f"\nFAILED: {', '.join(failed)}")
    return 1
  print("\nall devices updated")
  return 0


if __name__ == "__main__":
  sys.exit(main())
