#!/usr/bin/env python3
# Copyright (c) 2026, firestar5683 and StarPilot contributors
# SPDX-License-Identifier: MIT
"""Sentry notification delivery over the carrot web push ecosystem.

Ported from StarPilot's sentry_mode/notifications.py delivery semantics,
bound to this fork's existing carrot push channel instead of the Galaxy
phone relay (which this fork does not have):

- Carrot web push: subscriptions live in the WebPushSubscriptions param
  and VAPID keys in WebPushVapidKeys (params_keys.h:541-542); encryption
  and RFC 8292 auth are reused verbatim from
  sunnypilot/carrot/server/services/web_push.py (send_push /
  build_vapid_authorization), the same path the carrot PWA server uses.
- Discord / ntfy: optional webhook endpoints from params, default empty
  means disabled (same opt-in style as CwebPushReportUrl,
  cweb_push.py:49-63).

Dedup and throttle follow StarPilot semantics:
- warning is edge-triggered by the policy itself: it fires exactly once
  per motion episode when trigger_count == warning_trigger_count
  (starpilot sentry_mode/policy.py:164-165, mirrored in
  sunnypilot/sentry/policy.py:158-159); alarm fires once per window via
  the alarm_triggered latch (starpilot policy.py:166-168 /
  sp policy.py:160-162). A per-kind cooldown is kept here as a
  belt-and-braces guard against duplicate deliveries.
- battery maps the low_voltage transition (starpilot message semantics,
  notifications.py:44 "Car battery is low"); repeats are held back for a
  cooldown of RETRY_SECONDS[2] (starpilot notifications.py:35).
- retries: MAX_ATTEMPTS=4 with RETRY_SECONDS=(30,120,600,600) backoff and
  jobs dropped after MAX_AGE=86400 (starpilot notifications.py:33-35);
  at most one HTTP attempt at a time in a background worker thread
  (starpilot notifications.py:652-667).

Honesty note: on the C3 the motion kinds cannot fire today - sensord is
only_onroad (system/manager/process_config.py:353) and sentryd passes no
motion sample (sentryd.py sample=None), so the policy stays in the
sensor_unavailable path while parked. The low_voltage/battery event IS
producible on device. The motion wiring exists so a future qualified
motion source lights it up without another port.
"""
import asyncio
import json
import threading
import time
import urllib.error
import urllib.request

from openpilot.common.swaglog import cloudlog
from openpilot.sunnypilot.sentry.policy import Decision, RESET_TIME_SECONDS
from openpilot.common.params import Params

# Retry constants mirror StarPilot's durable queue (sentry_mode/notifications.py:33-35).
MAX_JOB_AGE_S = 86400.0
MAX_ATTEMPTS = 4
RETRY_SECONDS = (30.0, 120.0, 600.0, 600.0)
SEND_TIMEOUT_S = (3.0, 10.0)  # starpilot notifications.py:617

# Alarm window length in StarPilot (policy.py:11) reused as the motion cooldown.
MOTION_COOLDOWN_S = RESET_TIME_SECONDS
BATTERY_COOLDOWN_S = RETRY_SECONDS[2]

DISCORD_WEBHOOK_PARAM = "SentryDiscordWebhookUrl"
NTFY_URL_PARAM = "SentryNtfyUrl"
USER_AGENT = "openpilot-sentry-notifications/1"

_COOLDOWNS = {"warning": MOTION_COOLDOWN_S, "alarm": MOTION_COOLDOWN_S, "battery": BATTERY_COOLDOWN_S}


def message_text(kind: str) -> str:
  # Wording follows StarPilot (sentry_mode/notifications.py:40-45).
  if kind == "battery":
    return "Car battery is low. The parked watch is disarmed until voltage recovers."
  return f"Parked motion detected ({kind})."


def load_subscriptions(params) -> list[dict]:
  # Same Params-backed subscription store the carrot PWA server writes
  # (sunnypilot/carrot/server/features/push.py:28-36).
  raw = params.get("WebPushSubscriptions")
  if isinstance(raw, bytes):
    raw = raw.decode("utf-8", errors="replace")
  if not raw:
    return []
  try:
    subs = json.loads(raw)
    return subs if isinstance(subs, list) else []
  except ValueError:
    return []


def _param_text(params, key: str) -> str:
  try:
    value = params.get(key)
    if isinstance(value, bytes):
      value = value.decode("utf-8", errors="replace")
    return str(value or "").strip()
  except Exception:
    return ""


class SentryNotifier:
  """Consumes decisions, dedupes, and delivers notifications off-thread."""

  def __init__(self, params=None, transport=None):
    self.params = params if params is not None else Params()
    # Transport injection mirrors StarPilot (notifications.py:77-81) so
    # tests never touch the network.
    self._transport = transport if transport is not None else self._deliver
    self._lock = threading.Lock()
    self._jobs: list[dict] = []
    self._last_state: str | None = None
    self._last_sent: dict[str, float] = {}
    self._stop = threading.Event()
    self._thread: threading.Thread | None = None

  def update(self, now: float, decision: Decision) -> None:
    kind = self._kind_for(decision)
    self._last_state = decision.state
    if kind is None:
      return
    cooldown = _COOLDOWNS[kind]
    last = self._last_sent.get(kind)
    if last is not None and now - last < cooldown:
      return
    self._last_sent[kind] = now
    if not self._any_channel_configured():
      # Nothing is subscribed/configured; do not queue work that can only
      # retry to a dead end.
      return
    self._enqueue(kind, now)

  def _any_channel_configured(self) -> bool:
    # webPush is configured by the PWA subscribe endpoint writing the
    # WebPushSubscriptions param (features/push.py:62-66); the webhook
    # channels follow the CwebPushReportUrl opt-in style (cweb_push.py:49-63).
    return bool(load_subscriptions(self.params) or
                _param_text(self.params, DISCORD_WEBHOOK_PARAM) or
                _param_text(self.params, NTFY_URL_PARAM))

  def _kind_for(self, decision: Decision) -> str | None:
    if decision.event in ("warning", "alarm"):
      return decision.event
    # Battery maps the low_voltage state transition (starpilot
    # notifications.py:44); only the entry edge notifies.
    if decision.state == "low_voltage" and self._last_state != "low_voltage":
      return "battery"
    return None

  def _enqueue(self, kind: str, now: float) -> None:
    with self._lock:
      self._jobs.append({"kind": kind, "created": now, "next": now, "attempts": 0})
    self._start_worker()

  def _start_worker(self) -> None:
    if self._thread is not None and self._thread.is_alive():
      return
    self._stop.clear()
    self._thread = threading.Thread(target=self._run, name="sentry-notifications", daemon=True)
    self._thread.start()

  def _run(self) -> None:
    # At most one HTTP attempt in flight, like StarPilot's tick loop
    # (notifications.py:575 "At most one HTTP attempt per tick").
    while not self._stop.is_set():
      job = self._due_job()
      if job is None:
        self._stop.wait(1.0)
        continue
      try:
        ok = bool(self._transport(job["kind"]))
      except Exception:
        cloudlog.event("sentry_notification_error", kind=job["kind"])
        ok = False
      now = time.monotonic()
      with self._lock:
        job["attempts"] += 1
        if ok:
          self._jobs.remove(job)
          continue
        # Backoff/drop per StarPilot constants (notifications.py:33-35).
        if job["attempts"] >= MAX_ATTEMPTS or now - job["created"] > MAX_JOB_AGE_S:
          self._jobs.remove(job)
          continue
        job["next"] = now + RETRY_SECONDS[min(job["attempts"], MAX_ATTEMPTS) - 1]

  def _due_job(self) -> dict | None:
    now = time.monotonic()
    with self._lock:
      due = [job for job in self._jobs if job["next"] <= now]
      return min(due, key=lambda job: job["next"]) if due else None

  def close(self) -> None:
    self._stop.set()

  def _deliver(self, kind: str) -> bool:
    text = message_text(kind)
    title = "Sentry parked watch"
    results = []
    results.append(self._send_web_push(kind, title, text))
    results.append(self._send_discord(kind, text))
    results.append(self._send_ntfy(title, text))
    return any(results)

  def _send_web_push(self, kind: str, title: str, text: str) -> bool | None:
    subscriptions = load_subscriptions(self.params)
    if not subscriptions:
      return None  # Channel unconfigured, not a failure.
    # Import is lazy: services/web_push.py pulls in cryptography, which the
    # notifier must not require just to idle.
    from openpilot.sunnypilot.carrot.server.services.web_push import ensure_vapid_keys, send_push

    vapid_keys = ensure_vapid_keys(self.params)
    payload = json.dumps({"title": title, "body": text, "kind": kind}, separators=(",", ":"))

    async def _run() -> list[bool]:
      import aiohttp

      results = []
      async with aiohttp.ClientSession() as session:
        for sub in subscriptions:
          try:
            status, _ = await send_push(sub, payload, vapid_keys, session)
            results.append(200 <= status < 300)
          except Exception:
            # Per-subscriber failure never blocks the others (push.py:102-104).
            results.append(False)
      return results

    results = asyncio.run(_run())
    return any(results)

  def _send_discord(self, kind: str, text: str) -> bool | None:
    url = _param_text(self.params, DISCORD_WEBHOOK_PARAM)
    if not url:
      return None  # Default empty = disabled (starpilot channel config style).
    # Discord POSTs JSON content (starpilot notifications.py:631-637).
    return _post_json(url, {"content": f"Sentry parked watch: {text}"})

  def _send_ntfy(self, title: str, text: str) -> bool | None:
    url = _param_text(self.params, NTFY_URL_PARAM)
    if not url:
      return None
    # ntfy takes the message as the body with Title/Priority/Tags headers
    # (starpilot notifications.py:643-646).
    return _post_text(url, text.encode("utf-8"), headers={
      "Title": title,
      "Priority": "default",
      "Tags": "warning,car",
    })


def _post_json(url: str, payload: dict) -> bool:
  return _post_text(url, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"})


def _post_text(url: str, body: bytes, headers: dict) -> bool:
  request = urllib.request.Request(url=url, data=body, method="POST", headers={
    "User-Agent": USER_AGENT,
    **headers,
  })
  try:
    with urllib.request.urlopen(request, timeout=SEND_TIMEOUT_S[1]) as response:
      return 200 <= response.status < 300
  except urllib.error.HTTPError:
    return False
  except Exception:
    return False
