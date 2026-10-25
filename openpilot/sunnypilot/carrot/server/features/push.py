"""Web Push + PWA endpoints (Galaxy-inspired, StarPilot MIT).

The phone installs the panel as a PWA and subscribes to push; the server keeps
the VAPID keypair and the browser subscriptions in a JSON state file and can
notify on events (offroad errors, updates). The payload encryption lives in
services/web_push.py; this feature only wires the HTTP surface.

Note: browsers only register service workers on a secure origin, so `npm`-free
LAN installs work over http for the manifest, while push needs the https tunnel
(the /push page says so explicitly).
"""
from __future__ import annotations

import asyncio
import json
import os

import aiohttp
from aiohttp import web

from ..config import WEB_DIR
from ..services.web_push import ensure_vapid_keys, load_state, save_state, send_push

_MAX_SUBSCRIPTIONS = 8


def _load_subscriptions() -> list[dict]:
  return [s for s in load_state()["subscriptions"] if isinstance(s, dict)]


def _save_subscriptions(subscriptions: list[dict]) -> None:
  state = load_state()
  state["subscriptions"] = subscriptions
  save_state(state)


async def handle_status(request: web.Request) -> web.Response:
  state = load_state()
  return web.json_response({
    "vapidPublicKey": ensure_vapid_keys(state)["public_key"],
    "subscriptions": len(state["subscriptions"]),
  })


async def handle_subscribe(request: web.Request) -> web.Response:
  try:
    body = await request.json()
  except ValueError:
    return web.json_response({"error": "invalid json"}, status=400)
  endpoint = str(body.get("endpoint", ""))
  keys = body.get("keys") or {}
  if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
    return web.json_response({"error": "endpoint and keys.p256dh/keys.auth required"}, status=400)

  subscriptions = [s for s in _load_subscriptions() if s.get("endpoint") != endpoint]
  subscriptions.append({"endpoint": endpoint, "keys": keys})
  if len(subscriptions) > _MAX_SUBSCRIPTIONS:
    subscriptions = subscriptions[-_MAX_SUBSCRIPTIONS:]
  _save_subscriptions(subscriptions)
  return web.json_response({"ok": True, "subscriptions": len(subscriptions)})


async def handle_unsubscribe(request: web.Request) -> web.Response:
  try:
    body = await request.json()
  except ValueError:
    return web.json_response({"error": "invalid json"}, status=400)
  endpoint = str(body.get("endpoint", ""))
  remaining = [s for s in _load_subscriptions() if s.get("endpoint") != endpoint]
  _save_subscriptions(remaining)
  return web.json_response({"ok": True, "subscriptions": len(remaining)})


async def handle_test(request: web.Request) -> web.Response:
  try:
    body = await request.json()
  except ValueError:
    body = {}
  title = str(body.get("title", "carrot"))[:64]
  text = str(body.get("body", "push test"))[:200]
  payload = json.dumps({"title": title, "body": text})

  vapid_keys = ensure_vapid_keys()
  subscriptions = _load_subscriptions()
  if not subscriptions:
    return web.json_response({"error": "no subscriptions"}, status=404)
  results = []
  async with aiohttp.ClientSession() as session:
    for sub in subscriptions:
      try:
        status, text_out = await send_push(sub, payload, vapid_keys, session)
        results.append({"endpoint": sub.get("endpoint", "")[:80], "status": status})
      except Exception as exc:  # network/encryption failures are per-subscriber
        results.append({"endpoint": sub.get("endpoint", "")[:80], "error": type(exc).__name__})
        await asyncio.sleep(0)
  return web.json_response({"ok": True, "results": results})


async def handle_page(request: web.Request) -> web.Response:
  # The panel itself cannot host the subscribe flow: the SW/Push permission prompt
  # must come from a user gesture on a secure origin, so this page is standalone
  # (reachable over the same LAN address, or over the cloudflared https tunnel).
  page_path = os.path.join(WEB_DIR, "push.html")
  text = await asyncio.to_thread(_read_file_text, page_path)
  return web.Response(text=text, content_type="text/html",
                      headers={"Cache-Control": "no-store"})


async def handle_service_worker(request: web.Request) -> web.Response:
  sw_path = os.path.join(WEB_DIR, "sw.js")
  text = await asyncio.to_thread(_read_file_text, sw_path)
  return web.Response(text=text, content_type="application/javascript",
                      headers={"Cache-Control": "no-cache"})


async def handle_manifest(request: web.Request) -> web.Response:
  manifest_path = os.path.join(WEB_DIR, "manifest.webmanifest")
  text = await asyncio.to_thread(_read_file_text, manifest_path)
  return web.Response(text=text, content_type="application/manifest+json",
                      headers={"Cache-Control": "no-cache"})


def _read_file_text(path: str) -> str:
  with open(path, encoding="utf-8") as f:
    return f.read()


def register(app: web.Application) -> None:
  app.router.add_get("/sw.js", handle_service_worker)
  app.router.add_get("/manifest.webmanifest", handle_manifest)
  app.router.add_get("/push", handle_page)
  app.router.add_get("/api/push/status", handle_status)
  app.router.add_post("/api/push/subscribe", handle_subscribe)
  app.router.add_post("/api/push/unsubscribe", handle_unsubscribe)
  app.router.add_post("/api/push/test", handle_test)
