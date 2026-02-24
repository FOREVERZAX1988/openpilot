#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <bundle_dir> <install_root>"
  echo "example: $0 dist/iqpilot_proprietary /data/openpilot/.iqpilot"
  exit 1
fi

BUNDLE_DIR="$1"
INSTALL_ROOT="$2"
TMP_ROOT="${INSTALL_ROOT}.tmp.$$"

if [ ! -d "$BUNDLE_DIR" ]; then
  echo "bundle dir not found: $BUNDLE_DIR"
  exit 1
fi

python3 "$SCRIPT_DIR/verify_proprietary_bundle.py" "$BUNDLE_DIR"

rm -rf "$TMP_ROOT"
mkdir -p "$TMP_ROOT"
cp -a "$BUNDLE_DIR"/* "$TMP_ROOT"/

if [ -d "$INSTALL_ROOT" ]; then
  rm -rf "${INSTALL_ROOT}.bak"
  mv "$INSTALL_ROOT" "${INSTALL_ROOT}.bak"
fi

mv "$TMP_ROOT" "$INSTALL_ROOT"

if [ -d "${INSTALL_ROOT}.bak" ]; then
  rm -rf "${INSTALL_ROOT}.bak"
fi

echo "installed: $INSTALL_ROOT"
