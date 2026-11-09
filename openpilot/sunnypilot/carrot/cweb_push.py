#!/usr/bin/env python3
"""CWeb push reporter: keep a Carrot Web Push (CWP) endpoint informed of this
device's {deviceId, ip, port} so the device web UI stays reachable remotely.

Ported from CarrotPilot's cweb_push.py with one deliberate change (privacy
contract, see recovery/server.py): the fork ships NO baked-in third-party
endpoint. cp XOR-obfuscated the author's own relay into the binary; here the
byte table is empty and the report URL must come from either the
CWEB_PUSH_REPORT_URL environment variable or the CwebPushReportUrl param.
Unconfigured means idle polling at a low rate - the loop stays alive so a URL
supplied later (recovery registration, web settings) takes effect without a
manager restart.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import socket
import time
import urllib.error
import urllib.request
from ipaddress import ip_address
from typing import Any

from openpilot.common.params import Params

# XOR frame kept from cp so a URL embedded the same way stays possible; the
# table is intentionally EMPTY in this fork (privacy-first decision, see
# sunnypilot/carrot/recovery/server.py CWP_REPORT_URL_BYTES).
_REPORT_URL_KEY = 23
_REPORT_URL_BYTES: tuple[int, ...] = ()
DEFAULT_WEB_PORT = 7000
DEFAULT_IFACE = "wlan0"
DEFAULT_POLL_INTERVAL_S = 5.0
DEFAULT_HEARTBEAT_INTERVAL_S = 10.0
DEFAULT_DEBOUNCE_S = 1.0
DEFAULT_TIMEOUT_S = 4.0
DEFAULT_BACKOFF_S = 5.0
MAX_BACKOFF_S = 180.0
UNCONFIGURED_POLL_INTERVAL_S = 30.0


def _decode_default_report_url() -> str:
  return "".join(chr(value ^ _REPORT_URL_KEY) for value in _REPORT_URL_BYTES)


def resolve_report_url(params: Params) -> str:
  """env first, then the CwebPushReportUrl param, then the (empty) baked table."""
  env = os.environ.get("CWEB_PUSH_REPORT_URL", "").strip()
  if env:
    return env
  try:
    value = params.get("CwebPushReportUrl")
    if isinstance(value, bytes):
      value = value.decode("utf-8", errors="replace")
    text = str(value or "").strip()
    if text:
      return text
  except Exception:
    pass
  return _decode_default_report_url()


def _default_heartbeat_url(report_url: str) -> str:
  if report_url.endswith("/report"):
    return report_url[:-len("/report")] + "/heartbeat"
  return report_url.rstrip("/") + "/heartbeat"


def _param_text(params: Params, key: str, default: str = "") -> str:
  try:
    value = params.get(key)
    if isinstance(value, bytes):
      value = value.decode("utf-8", errors="replace")
    value = str(value or "").strip()
    return value or default
  except Exception:
    return default


def _usable_ip(value: str | None) -> str:
  try:
    text = str(value or "").strip()
    addr = ip_address(text)
    if addr.version != 4:
      return ""
    if addr.is_unspecified or addr.is_loopback or addr.is_multicast:
      return ""
    if addr.is_link_local:
      return ""
    return text
  except Exception:
    return ""


def _iface_ipv4(iface: str) -> str:
  try:
    import fcntl
    import struct

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
      raw = fcntl.ioctl(
        sock.fileno(),
        0x8915,
        struct.pack("256s", iface[:15].encode("utf-8")),
      )[20:24]
    return _usable_ip(socket.inet_ntoa(raw))
  except Exception:
    return ""


def _route_ipv4() -> str:
  try:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
      sock.settimeout(0.5)
      sock.connect(("8.8.8.8", 80))
      return _usable_ip(sock.getsockname()[0])
  except Exception:
    return ""


def get_local_ip(iface: str = DEFAULT_IFACE) -> str:
  return _iface_ipv4(iface) or _route_ipv4()


def _meaningful_device_id(value: str) -> str:
  text = str(value or "").strip()
  if not text:
    return ""
  if text.lower() in {"unknown", "none", "null", "unregistereddevice"}:
    return ""
  return text


def device_id(params: Params) -> str:
  for value in (
    _param_text(params, "DongleId"),
    _param_text(params, "HardwareSerial"),
  ):
    value = _meaningful_device_id(value)
    if value:
      return value
  return socket.gethostname() or "comma"


def build_payload(params: Params, local_ip: str, port: int) -> dict[str, Any]:
  return {
    "deviceId": device_id(params),
    "ip": local_ip,
    "port": int(port),
  }


def post_json(url: str, payload: dict[str, Any], timeout_s: float) -> tuple[bool, int, str]:
  data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
  req = urllib.request.Request(
    url=url,
    data=data,
    headers={
      "Content-Type": "application/json",
      "User-Agent": "openpilot-cweb-push/1",
    },
    method="POST",
  )
  try:
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
      body = resp.read().decode("utf-8", errors="replace")
      return 200 <= resp.status < 300, int(resp.status), body
  except urllib.error.HTTPError as exc:
    try:
      body = exc.read().decode("utf-8", errors="replace")
    except Exception:
      body = ""
    return False, int(exc.code), body
  except Exception as exc:
    return False, 0, str(exc)


class CwebPushReporter:
  def __init__(
    self,
    params: Params,
    report_url: str,
    heartbeat_url: str,
    iface: str,
    port: int,
    timeout_s: float,
    heartbeat_interval_s: float,
    debounce_s: float,
    dry_run: bool = False,
  ) -> None:
    self.params = params
    self.report_url = report_url
    self.heartbeat_url = heartbeat_url
    self.iface = iface
    self.port = port
    self.timeout_s = timeout_s
    self.heartbeat_interval_s = max(heartbeat_interval_s, 5.0)
    self.debounce_s = debounce_s
    self.dry_run = dry_run
    self.last_success_ip = ""
    self.current_candidate_ip = ""
    self.current_candidate_since = 0.0
    self.was_down = True
    self.first_report = True
    self.next_retry_at = 0.0
    self.backoff_s = DEFAULT_BACKOFF_S
    self.next_heartbeat_at = time.monotonic() + random.uniform(0.0, self.heartbeat_interval_s)

  def _status(self, state: str, **extra: Any) -> None:
    data = {
      "state": state,
      "ts": int(time.time()),  # noqa: TID251 wall clock on purpose: this rides in remote logs
      "last_success_ip": self.last_success_ip,
      **extra,
    }
    line = "[cweb_push] " + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    print(line, flush=True)

  def poll_once(self) -> bool:
    now = time.monotonic()
    local_ip = get_local_ip(self.iface)
    if not local_ip:
      self.was_down = True
      self.current_candidate_ip = ""
      self.current_candidate_since = 0.0
      self._status("no_ip")
      return False

    if local_ip != self.current_candidate_ip:
      self.current_candidate_ip = local_ip
      self.current_candidate_since = now
      self._status("ip_candidate", ip=local_ip)
      return False

    if now - self.current_candidate_since < self.debounce_s:
      return False

    should_report = self.first_report or local_ip != self.last_success_ip
    if not should_report:
      if now >= self.next_heartbeat_at:
        payload = build_payload(self.params, local_ip, self.port)
        self.next_heartbeat_at = now + self.heartbeat_interval_s + random.uniform(0.0, min(3.0, self.heartbeat_interval_s * 0.15))
        if self.dry_run:
          self._status("heartbeat_dry_run", ip=local_ip, payload=payload)
          return True
        ok, status, body = post_json(self.heartbeat_url, payload, self.timeout_s)
        self._status(
          "heartbeat" if ok else "heartbeat_failed",
          ip=local_ip,
          http_status=status,
          response=body[:240],
        )
        return ok
      self._status("idle", ip=local_ip)
      return False

    if now < self.next_retry_at:
      return False

    payload = build_payload(self.params, local_ip, self.port)

    if self.dry_run:
      self.last_success_ip = local_ip
      self.was_down = False
      self.first_report = False
      self._status("dry_run", ip=local_ip, payload=payload)
      return True

    ok, status, body = post_json(self.report_url, payload, self.timeout_s)
    if ok:
      self.last_success_ip = local_ip
      self.was_down = False
      self.first_report = False
      self.backoff_s = DEFAULT_BACKOFF_S
      self.next_retry_at = 0.0
      self.next_heartbeat_at = now + self.heartbeat_interval_s
      self._status("reported", ip=local_ip, http_status=status, response=body[:240])
      return True

    self.next_retry_at = now + self.backoff_s
    self.backoff_s = min(self.backoff_s * 2.0, MAX_BACKOFF_S)
    self._status("report_failed", ip=local_ip, http_status=status, error=body[:240], retry_in_s=round(self.backoff_s, 1))
    return False


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--once", action="store_true", help="run one stable-IP report check and exit")
  parser.add_argument("--dry-run", action="store_true", help="print payload without POSTing")
  parser.add_argument("--url", default="")
  parser.add_argument("--heartbeat-url", default=os.environ.get("CWEB_PUSH_HEARTBEAT_URL"))
  parser.add_argument("--iface", default=os.environ.get("CWEB_PUSH_IFACE", DEFAULT_IFACE))
  parser.add_argument("--port", type=int, default=int(os.environ.get("CWEB_PUSH_PORT", DEFAULT_WEB_PORT)))
  parser.add_argument("--interval", type=float, default=float(os.environ.get("CWEB_PUSH_INTERVAL_S", DEFAULT_POLL_INTERVAL_S)))
  parser.add_argument("--heartbeat-interval", type=float, default=float(os.environ.get("CWEB_PUSH_HEARTBEAT_INTERVAL_S", DEFAULT_HEARTBEAT_INTERVAL_S)))
  parser.add_argument("--debounce", type=float, default=float(os.environ.get("CWEB_PUSH_DEBOUNCE_S", DEFAULT_DEBOUNCE_S)))
  parser.add_argument("--timeout", type=float, default=float(os.environ.get("CWEB_PUSH_TIMEOUT_S", DEFAULT_TIMEOUT_S)))
  args = parser.parse_args()

  params = Params()

  # The report URL is resolved once per loop iteration so a param written by
  # the recovery server or web settings takes effect without a restart. With
  # no URL anywhere this loop idles at a low rate and posts nothing.
  print(f"[cweb_push] starting iface={args.iface} port={args.port} heartbeat_interval={args.heartbeat_interval:g}s", flush=True)

  reporter: CwebPushReporter | None = None
  reporter_url = ""
  next_url_check = 0.0

  while True:
    now = time.monotonic()
    url = args.url or resolve_report_url(params)
    if url != reporter_url:
      if url:
        reporter = CwebPushReporter(
          params=params,
          report_url=url,
          heartbeat_url=args.heartbeat_url or _default_heartbeat_url(url),
          iface=args.iface,
          port=args.port,
          timeout_s=args.timeout,
          heartbeat_interval_s=args.heartbeat_interval,
          debounce_s=args.debounce,
          dry_run=args.dry_run,
        )
        reporter_url = url
        print(f"[cweb_push] endpoint configured ({url.rsplit('/', 1)[0]})", flush=True)
      else:
        reporter = None
        reporter_url = ""

    if reporter is None:
      if now >= next_url_check:
        next_url_check = now + UNCONFIGURED_POLL_INTERVAL_S
        print("[cweb_push] no CWEB_PUSH_REPORT_URL / CwebPushReportUrl configured; idling", flush=True)
      time.sleep(min(max(args.interval, 1.0), 5.0))
      continue

    if args.once:
      deadline = now + max(args.debounce + 2.0, 3.0)
      while time.monotonic() < deadline:
        if reporter.poll_once():
          return
        time.sleep(min(args.interval, 0.5))
      reporter._status("once_no_report")
      return

    reporter.poll_once()
    time.sleep(max(args.interval, 1.0))


if __name__ == "__main__":
  main()
