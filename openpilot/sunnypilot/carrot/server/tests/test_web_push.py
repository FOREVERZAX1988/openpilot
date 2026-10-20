#!/usr/bin/env python3
import base64
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from openpilot.sunnypilot.carrot.server import config
from openpilot.sunnypilot.carrot.server.services.web_push import (
  build_vapid_authorization,
  encrypt_payload,
  ensure_vapid_keys,
  generate_vapid_keys,
)


def _b64url(data: bytes) -> bytes:
  return base64.urlsafe_b64encode(data).rstrip(b"=")


class TestWebPush(unittest.TestCase):
  def test_generated_keys_are_loadable(self):
    keys = generate_vapid_keys()
    private_key = serialization.load_der_private_key(
      base64.urlsafe_b64decode(keys["private_key"] + "=" * (-len(keys["private_key"]) % 4)), password=None)
    self.assertEqual(private_key.curve.name, "secp256r1")
    self.assertEqual(len(base64.urlsafe_b64decode(keys["public_key"] + "=" * (-len(keys["public_key"]) % 4))), 65)

  def test_encrypt_payload_round_trips_with_client_private_key(self):
    # Simulate the browser side: the client keypair whose public half was
    # subscribed; the server ciphertext must decrypt under the shared secret.
    client_private = ec.generate_private_key(ec.SECP256R1())
    client_public = client_private.public_key().public_bytes(
      serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    p256dh = _b64url(client_public).decode()
    auth_secret = _b64url(b"\x11" * 16).decode()

    payload = b'{"title":"carrot","body":"hello"}'
    body = encrypt_payload(payload, p256dh, auth_secret)

    # aes128gcm header: salt(16) + rs(4) + idlen(1) + server ephemeral point(65)
    self.assertEqual(body[16:20], (4096).to_bytes(4, "big"))
    self.assertEqual(body[20], 65)
    server_public = body[21:86]

    shared = client_private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(
      ec.SECP256R1(), server_public))
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    prk = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"\x11" * 16,
               info=b"WebPush: info\x00" + client_public + server_public).derive(shared)
    salt = body[:16]
    cek = HKDF(algorithm=hashes.SHA256(), length=16, salt=salt,
               info=b"Content-Encoding: aes128gcm\x00").derive(prk)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt,
                 info=b"Content-Encoding: nonce\x00").derive(prk)

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    decrypted = AESGCM(cek).decrypt(nonce, body[86:], None)
    self.assertTrue(decrypted.endswith(b"\x02"))
    self.assertEqual(decrypted[:-1], payload)

  def test_encrypt_rejects_oversized_payload(self):
    client_public = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
      serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    with self.assertRaises(ValueError):
      encrypt_payload(b"x" * 5000, _b64url(client_public).decode(), _b64url(b"0" * 16).decode())

  def test_vapid_authorization_shape(self):
    keys = generate_vapid_keys()
    auth = build_vapid_authorization("https://fcm.googleapis.com/fcm/send/abc", keys)
    self.assertTrue(auth.startswith("vapid t="))
    self.assertIn(f"k={keys['public_key']}", auth)
    token = auth.split("t=", 1)[1].split(",", 1)[0]
    header, claims, signature = token.split(".")
    import base64
    pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
    self.assertEqual(json.loads(base64.urlsafe_b64decode(pad(header)))["alg"], "ES256")
    self.assertEqual(json.loads(base64.urlsafe_b64decode(pad(claims)))["aud"], "https://fcm.googleapis.com")
    # Signature must verify against the published public key.
    from cryptography.hazmat.primitives.asymmetric import utils as asym_utils
    pub = ec.EllipticCurvePublicKey.from_encoded_point(
      ec.SECP256R1(), base64.urlsafe_b64decode(pad(keys["public_key"])))
    raw_sig = base64.urlsafe_b64decode(pad(signature))
    der_sig = asym_utils.encode_dss_signature(int.from_bytes(raw_sig[:32], "big"),
                                              int.from_bytes(raw_sig[32:], "big"))
    pub.verify(der_sig, f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))

  def test_ensure_vapid_keys_persist_across_calls(self):
    with tempfile.TemporaryDirectory() as tmp:
      path = os.path.join(tmp, "state", "web_push.json")
      with mock.patch.object(config, "CARROT_WEB_PUSH_PATH", path):
        keys = ensure_vapid_keys()
        self.assertIn("private_key", keys)
        self.assertEqual(ensure_vapid_keys(), keys)  # second call reuses the stored keypair
        with open(path, encoding="utf-8") as f:
          self.assertEqual(json.load(f)["vapid"], keys)


def _push_app():
  from aiohttp import web
  from openpilot.sunnypilot.carrot.server.features import push as push_feature

  app = web.Application()
  push_feature.register(app)
  return app


def _state(tmp_path):
  return os.path.join(str(tmp_path), "web_push.json")


def test_manifest_icon_size_matches_the_file_we_serve():
  """Chrome refuses the install prompt when the declared icon size is wrong."""
  from openpilot.sunnypilot.carrot.server.config import SELFDRIVE_ASSETS_DIR

  icon = os.path.join(SELFDRIVE_ASSETS_DIR, "img_spinner_comma.png")
  if not os.path.exists(icon):
    raise unittest.SkipTest("icon asset not present in this checkout")
  head = pathlib.Path(icon).read_bytes()[:26]
  assert (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")) == (800, 800)


def test_pwa_assets_are_served_and_the_panel_links_them(tmp_path, monkeypatch):
  import asyncio
  from aiohttp.test_utils import TestClient, TestServer

  monkeypatch.setattr(config, "CARROT_WEB_PUSH_PATH", _state(tmp_path))

  async def check():
    async with TestClient(TestServer(_push_app())) as client:
      manifest = await client.get("/manifest.webmanifest")
      assert manifest.status == 200
      assert manifest.headers["Content-Type"].startswith("application/manifest+json")
      text = await manifest.text()
      assert '"sizes": "800x800"' in text
      assert "/shared-assets/img_spinner_comma.png" in text

      sw = await client.get("/sw.js")
      assert sw.status == 200
      assert sw.headers["Content-Type"].startswith("application/javascript")
      sw_text = await sw.text()
      assert "self.addEventListener('push'" in sw_text
      assert "/api/" in sw_text  # network-first API path in the SW fetch handler

      page = await client.get("/push")
      assert page.status == 200
      page_text = await page.text()
      for needle in ("/api/push/status", "/api/push/subscribe", "/api/push/unsubscribe",
                     "/api/push/test", "pushManager.subscribe", "isSecureContext"):
        assert needle in page_text

  asyncio.run(check())


def test_status_hands_out_a_stable_vapid_key_and_subscriptions_round_trip(tmp_path, monkeypatch):
  import asyncio
  from aiohttp.test_utils import TestClient, TestServer

  state_path = _state(tmp_path)
  monkeypatch.setattr(config, "CARROT_WEB_PUSH_PATH", state_path)

  async def check():
    async with TestClient(TestServer(_push_app())) as client:
      first = await (await client.get("/api/push/status")).json()
      second = await (await client.get("/api/push/status")).json()
      assert first["vapidPublicKey"] == second["vapidPublicKey"], "VAPID keys must be stable across requests"
      assert len(base64.urlsafe_b64decode(first["vapidPublicKey"] + "==")) == 65
      assert first["subscriptions"] == 0

      bad = await client.post("/api/push/subscribe", json={"endpoint": "http://insecure"})
      assert bad.status == 400

      sub = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "BPk", "auth": "a"}}
      ok = await (await client.post("/api/push/subscribe", json=sub)).json()
      assert ok == {"ok": True, "subscriptions": 1}

      again = await (await client.post("/api/push/subscribe", json=sub)).json()
      assert again["subscriptions"] == 1, "re-subscribing the same endpoint must not duplicate"

      gone = await (await client.post("/api/push/unsubscribe", json={"endpoint": sub["endpoint"]})).json()
      assert gone == {"ok": True, "subscriptions": 0}

  asyncio.run(check())
  assert pathlib.Path(state_path).exists(), "the keypair must be persisted on first use"
