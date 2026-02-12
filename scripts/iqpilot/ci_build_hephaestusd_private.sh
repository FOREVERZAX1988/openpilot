#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
  echo "usage: $0 <private_source_dir> <bundle_output_dir> <artifact_output_dir> [install_root]"
  exit 1
fi

PRIVATE_SOURCE_DIR="$1"
BUNDLE_OUTPUT_DIR="$2"
ARTIFACT_OUTPUT_DIR="$3"
INSTALL_ROOT="${4:-}"

if [ ! -d "$PRIVATE_SOURCE_DIR" ]; then
  echo "private source dir not found: $PRIVATE_SOURCE_DIR"
  exit 1
fi

required=(
  "hephaestusd.py"
)

for f in "${required[@]}"; do
  if [ ! -f "$PRIVATE_SOURCE_DIR/$f" ]; then
    echo "missing required private source file: $PRIVATE_SOURCE_DIR/$f"
    exit 1
  fi
done

scripts/iqpilot/build_hephaestusd_private_bundle.py \
  --clean \
  --private-source "$PRIVATE_SOURCE_DIR" \
  --output "$BUNDLE_OUTPUT_DIR"

scripts/iqpilot/verify_proprietary_bundle.py "$BUNDLE_OUTPUT_DIR"

mkdir -p "$ARTIFACT_OUTPUT_DIR"

ts="$(date +%Y%m%d%H%M%S)"
if command -v zstd >/dev/null 2>&1; then
  artifact_name="iqpilot_hephaestusd_private_${ts}.tar.zst"
  tar -C "$BUNDLE_OUTPUT_DIR" -cf - . | zstd -19 -T0 -o "$ARTIFACT_OUTPUT_DIR/$artifact_name"
else
  artifact_name="iqpilot_hephaestusd_private_${ts}.tar.gz"
  tar -C "$BUNDLE_OUTPUT_DIR" -czf "$ARTIFACT_OUTPUT_DIR/$artifact_name" .
fi
artifact_path="$ARTIFACT_OUTPUT_DIR/$artifact_name"

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$artifact_path" > "$artifact_path.sha256"
else
  shasum -a 256 "$artifact_path" > "$artifact_path.sha256"
fi

if [ -n "$INSTALL_ROOT" ]; then
  scripts/iqpilot/install_proprietary_bundle.sh "$BUNDLE_OUTPUT_DIR" "$INSTALL_ROOT"
fi

echo "bundle_dir=$BUNDLE_OUTPUT_DIR"
echo "artifact=$artifact_path"
echo "checksum=$artifact_path.sha256"
