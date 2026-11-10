from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpilot.sunnypilot.carrot.server.services.asset_manifest import (
  AssetManifestError,
  AssetManifestLoader,
)


def _content_hash(payload: bytes) -> str:
  return hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest()


def _write_manifest(web_dir: Path, payload: bytes) -> None:
  generated = web_dir / "generated"
  generated.mkdir(exist_ok=True)
  manifest = {
    "schemaVersion": 1,
    "assets": [{
      "id": "app.runtime",
      "kind": "bundle",
      "source": "src/entries/app.js",
      "path": "js/generated/app.js",
      "hash": _content_hash(payload),
    }],
  }
  (generated / "asset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class TestAssetManifest(unittest.TestCase):

  def setUp(self):
    tmp = tempfile.mkdtemp(prefix="asset_manifest_test_")
    self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    self.tmp_path = Path(tmp)

  def test_runtime_loader_repairs_stale_hash_and_strict_validation_reports_it(self):
    web_dir = self.tmp_path / "web"
    asset_dir = web_dir / "js" / "generated"
    asset_dir.mkdir(parents=True)
    asset_path = asset_dir / "app.js"
    original = b"original asset\n"
    asset_path.write_bytes(original)
    _write_manifest(web_dir, original)

    loader = AssetManifestLoader()
    self.assertEqual(loader.load(web_dir)["assets"][0]["hash"], _content_hash(original))

    updated = b"updated asset with a different size\n"
    asset_path.write_bytes(updated)
    self.assertEqual(loader.load(web_dir)["assets"][0]["hash"], _content_hash(updated))
    with self.assertRaisesRegex(AssetManifestError, "content hash"):
      loader.validate(web_dir)

  def test_loader_recovers_after_manifest_and_asset_finish_updating(self):
    web_dir = self.tmp_path / "web"
    asset_dir = web_dir / "js" / "generated"
    asset_dir.mkdir(parents=True)
    asset_path = asset_dir / "app.js"
    original = b"original asset\n"
    updated = b"updated asset\n"
    asset_path.write_bytes(original)
    _write_manifest(web_dir, original)

    loader = AssetManifestLoader()
    loader.load(web_dir)

    asset_path.write_bytes(updated)
    self.assertEqual(loader.load(web_dir)["assets"][0]["hash"], _content_hash(updated))
    with self.assertRaises(AssetManifestError):
      loader.validate(web_dir)

    _write_manifest(web_dir, updated)
    manifest = loader.validate(web_dir)
    self.assertEqual(manifest["assets"][0]["hash"], _content_hash(updated))

  def test_index_falls_back_to_empty_manifest_when_manifest_is_unavailable(self):
    from openpilot.sunnypilot.carrot.server.features import static

    web_dir = self.tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text(
      '<!doctype html><script id="carrotAssetManifest" type="application/json"></script>',
      encoding="utf-8",
    )
    for patch in (
      mock.patch.object(static, "WEB_DIR", str(web_dir)),
      mock.patch.object(static, "_INDEX_RETRY_DELAYS", (0.0,)),
      mock.patch.object(static, "_ASSET_MANIFEST_LOADER", AssetManifestLoader()),
    ):
      patch.start()
      self.addCleanup(patch.stop)

    loaded = asyncio.run(static._load_index_after_update())

    self.assertIsNotNone(loaded)
    html, degraded = loaded
    self.assertIs(degraded, True)
    self.assertIn('"schemaVersion":1,"assets":[]', html)

  def test_runtime_hash_recovery_does_not_allow_paths_outside_web_root(self):
    web_dir = self.tmp_path / "web"
    generated = web_dir / "generated"
    generated.mkdir(parents=True)
    outside = self.tmp_path / "outside.js"
    outside.write_text("outside", encoding="utf-8")
    manifest = {
      "schemaVersion": 1,
      "assets": [{
        "id": "outside.worker",
        "kind": "worker",
        "path": "../outside.js",
        "hash": _content_hash(outside.read_bytes()),
      }],
    }
    (generated / "asset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with self.assertRaisesRegex(AssetManifestError, "relative"):
      AssetManifestLoader().load(web_dir)

if __name__ == "__main__":
  unittest.main()
