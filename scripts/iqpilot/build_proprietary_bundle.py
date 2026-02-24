#!/usr/bin/env python3
import argparse
import compileall
import hashlib
import json
import shutil
import stat
from pathlib import Path

TARGET_DIRS = [
  "sunnypilot/konn3kt",
  "sunnypilot/navd",
]
ROOT_FILES = [
  "sunnypilot/__init__.py",
]


def parse_args() -> argparse.Namespace:
  p = argparse.ArgumentParser(description="Build proprietary IQ Pilot python bundle")
  p.add_argument("--source-root", default=".", help="Repository root")
  p.add_argument("--output", default="dist/iqpilot_proprietary", help="Output directory")
  p.add_argument("--no-strip-source", action="store_true", default=False, help="Keep .py files after compilation")
  p.add_argument("--no-legacy-pyc", action="store_true", default=False, help="Write only __pycache__ pyc files")
  p.add_argument("--optimize", type=int, default=2, choices=[0, 1, 2], help="Python optimization level")
  p.add_argument("--clean", action="store_true", default=False, help="Delete output dir before build")
  return p.parse_args()


def ensure_clean(path: Path, clean: bool) -> None:
  if clean and path.exists():
    shutil.rmtree(path)
  path.mkdir(parents=True, exist_ok=True)


def copy_targets(source_root: Path, python_root: Path) -> None:
  for rel in TARGET_DIRS:
    src = source_root / rel
    dst = python_root / rel
    if not src.exists():
      raise FileNotFoundError(f"Missing target directory: {src}")
    if dst.exists():
      shutil.rmtree(dst)
    shutil.copytree(src, dst, dirs_exist_ok=False)

  for rel in ROOT_FILES:
    src = source_root / rel
    dst = python_root / rel
    if not src.exists():
      raise FileNotFoundError(f"Missing root file: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def write_openpilot_overlay(python_root: Path) -> None:
  openpilot_pkg = python_root / "openpilot"
  openpilot_pkg.mkdir(parents=True, exist_ok=True)

  init_py = openpilot_pkg / "__init__.py"
  init_py.write_text(
    "from pkgutil import extend_path\n"
    "import os\n"
    "__path__ = extend_path(__path__, __name__)\n"
    "_source_openpilot = os.getenv('IQPILOT_SOURCE_ROOT', '/data/openpilot/openpilot')\n"
    "if _source_openpilot and _source_openpilot not in __path__:\n"
    "  __path__.append(_source_openpilot)\n",
    encoding="utf-8",
  )

  link_path = openpilot_pkg / "sunnypilot"
  if link_path.exists() or link_path.is_symlink():
    if link_path.is_dir() and not link_path.is_symlink():
      shutil.rmtree(link_path)
    else:
      link_path.unlink()

  target = Path("..") / "sunnypilot"
  try:
    link_path.symlink_to(target)
  except OSError:
    shutil.copytree(python_root / "sunnypilot", link_path)


def compile_bundle(python_root: Path, optimize: int, legacy_pyc: bool) -> None:
  ok = compileall.compile_dir(
    str(python_root),
    force=True,
    quiet=1,
    optimize=optimize,
    legacy=legacy_pyc,
  )
  if not ok:
    raise RuntimeError("compileall failed for proprietary bundle")


def strip_sources(python_root: Path) -> None:
  for py in python_root.rglob("*.py"):
    py.unlink()

  for pycache in python_root.rglob("__pycache__"):
    if pycache.is_dir():
      shutil.rmtree(pycache)


def write_manifest(output_root: Path, python_root: Path) -> None:
  manifest: dict[str, dict[str, str | int]] = {}

  for f in sorted(python_root.rglob("*")):
    if f.is_dir():
      continue
    rel = f.relative_to(output_root).as_posix()
    digest = hashlib.sha256(f.read_bytes()).hexdigest()
    manifest[rel] = {
      "sha256": digest,
      "size": f.stat().st_size,
      "mode": stat.S_IMODE(f.stat().st_mode),
    }

  manifest_path = output_root / "manifest.json"
  manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")



def main() -> None:
  args = parse_args()
  source_root = Path(args.source_root).resolve()
  output_root = Path(args.output).resolve()
  python_root = output_root / "python"

  ensure_clean(output_root, args.clean)
  python_root.mkdir(parents=True, exist_ok=True)

  copy_targets(source_root, python_root)
  write_openpilot_overlay(python_root)
  compile_bundle(python_root, optimize=args.optimize, legacy_pyc=not args.no_legacy_pyc)

  if not args.no_strip_source:
    strip_sources(python_root)

  write_manifest(output_root, python_root)
  print(f"Bundle built at: {output_root}")


if __name__ == "__main__":
  main()
