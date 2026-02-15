#!/usr/bin/env python3
import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

MODULE_FILES = [
  "__init__.py",
  "helpers.py",
  "event_builder.py",
  "gps_lane_tracker.py",
  "route_manager.py",
  "navd.py",
  "web_server.py",
]


def parse_args() -> argparse.Namespace:
  p = argparse.ArgumentParser(description="Build private navd bundle (.so via Cython)")
  p.add_argument("--private-source", required=True, help="Directory containing private navd source files")
  p.add_argument("--output", default="dist/iqpilot_navd_private", help="Output bundle directory")
  p.add_argument("--clean", action="store_true", default=False, help="Delete output directory before build")
  p.add_argument("--jobs", type=int, default=0, help="Cython parallel build jobs (0=auto)")
  p.add_argument("--no-strip-source", action="store_true", default=False, help="Keep rewritten .py source in output")
  return p.parse_args()


def ensure_clean(path: Path, clean: bool) -> None:
  if clean and path.exists():
    shutil.rmtree(path)
  path.mkdir(parents=True, exist_ok=True)


def rewrite_imports(source: str) -> str:
  source = source.replace("openpilot.sunnypilot.navd.", "iqpilot_private.navd.")
  source = source.replace("sunnypilot.navd.", "iqpilot_private.navd.")
  return source


def write_private_sources(private_source: Path, private_pkg_root: Path) -> None:
  private_pkg_root.mkdir(parents=True, exist_ok=True)

  iq_init = private_pkg_root.parent / "__init__.py"
  iq_init.write_text("", encoding="utf-8")

  for rel in MODULE_FILES:
    src = private_source / rel
    if not src.exists():
      raise FileNotFoundError(f"missing private module source: {src}")

    dst = private_pkg_root / rel
    raw = src.read_text(encoding="utf-8")
    dst.write_text(rewrite_imports(raw), encoding="utf-8")


def build_cython_extensions(output_root: Path, python_root: Path, jobs: int) -> None:
  setup_py = output_root / "_cython_setup_navd.py"
  build_temp = output_root / "_build_temp"
  build_lib = output_root / "_build_lib"

  extensions = "\n".join(
    f'  Extension("iqpilot_private.navd.{m[:-3]}", ["python/iqpilot_private/navd/{m}"]),'
    for m in MODULE_FILES
  )
  setup_py.write_text(
    "from setuptools import Extension, setup\n"
    "from Cython.Build import cythonize\n"
    "extensions = [\n"
    f"{extensions}\n"
    "]\n"
    "setup(\n"
    "  ext_modules=cythonize(\n"
    "    extensions,\n"
    "    compiler_directives={\n"
    "      'language_level': 3,\n"
    "      'binding': False,\n"
    "      'embedsignature': False,\n"
    "      'profile': False,\n"
    "      'linetrace': False,\n"
    "    },\n"
    f"    nthreads={jobs},\n"
    "  )\n"
    ")\n",
    encoding="utf-8",
  )

  try:
    subprocess.run(
      [
        sys.executable,
        str(setup_py.name),
        "build_ext",
        "--build-temp",
        str(build_temp),
        "--build-lib",
        str(python_root),
      ],
      cwd=str(output_root),
      check=True,
    )
  except subprocess.CalledProcessError as exc:
    raise RuntimeError("Cython build failed for navd private bundle") from exc
  finally:
    for p in [setup_py, build_temp, build_lib]:
      if p.exists():
        if p.is_dir():
          shutil.rmtree(p)
        else:
          p.unlink()


def strip_sources(python_root: Path) -> None:
  for cfile in python_root.rglob("*.c"):
    cfile.unlink()

  for py in python_root.rglob("*.py"):
    if py.name == "__init__.py":
      continue
    py.unlink()


def strip_binaries(python_root: Path) -> None:
  strip_bin = shutil.which("strip")
  if not strip_bin:
    return

  for so in python_root.rglob("*.so"):
    subprocess.run([strip_bin, "--strip-unneeded", str(so)], check=False)


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
  private_source = Path(args.private_source).resolve()
  output_root = Path(args.output).resolve()
  python_root = output_root / "python"
  private_pkg_root = python_root / "iqpilot_private" / "navd"

  ensure_clean(output_root, args.clean)
  python_root.mkdir(parents=True, exist_ok=True)

  write_private_sources(private_source, private_pkg_root)
  build_cython_extensions(output_root, python_root, jobs=args.jobs)
  strip_binaries(python_root)

  if not args.no_strip_source:
    strip_sources(python_root)

  write_manifest(output_root, python_root)
  print(f"Navd private bundle built at: {output_root}")


if __name__ == "__main__":
  main()
