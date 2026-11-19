#!/usr/bin/env python3

import importlib
import shutil
import sys
import tempfile
import zipapp
from argparse import ArgumentParser
from pathlib import Path

from openpilot.common.basedir import BASEDIR


# cereal lives inside the openpilot package in this fork (openpilot/cereal),
# so it is bundled with the openpilot tree; a legacy top-level cereal/ dir is
# only included when it actually has content.
DIRS = ['cereal', 'openpilot']
EXTS = ['.png', '.py', '.ttf', '.capnp', '.json', '.fnt', '.mo', '.po']
INTERPRETER = '/usr/bin/env python3'


def copy(src, dest):
  if any(src.endswith(ext) for ext in EXTS):
    shutil.copy2(src, dest, follow_symlinks=True)


if __name__ == '__main__':
  parser = ArgumentParser(prog='pack.py', description="package script into a portable executable", epilog='comma.ai')
  parser.add_argument('-e', '--entrypoint', help="function to call in module, default is 'main'", default='main')
  parser.add_argument('-o', '--output', help='output file')
  parser.add_argument('module', help="the module to target, e.g. 'openpilot.system.ui.spinner'")
  args = parser.parse_args()

  if not args.output:
    args.output = args.module

  try:
    mod = importlib.import_module(args.module)
  except ModuleNotFoundError:
    print(f'{args.module} not found, typo?')
    sys.exit(1)

  if not hasattr(mod, args.entrypoint):
    print(f'{args.module} does not have a {args.entrypoint}() function, typo?')
    sys.exit(1)

  with tempfile.TemporaryDirectory() as tmp:
    for directory in DIRS:
      src = Path(BASEDIR) / directory
      if not src.exists() or not any(src.iterdir()):
        continue  # stale layout remnant (e.g. empty root cereal/ in this fork)
      shutil.copytree(src, tmp + '/' + directory, symlinks=False, dirs_exist_ok=True, copy_function=copy)

    # zipimport does not support implicit namespace packages (PEP 420): any
    # package dir without __init__.py that the zipapp imports dies with
    # ModuleNotFoundError on device, even though the same import works fine
    # in a regular checkout. Observed 2026-11-19: openpilot.system.ui has no
    # __init__.py in the source tree, so the updater zipapp crashed at
    # `import openpilot.system.ui.updater` and every AGNOS update fell back
    # to headless flashing. Fill in empty __init__.py for every dir holding
    # python files so the archive is importable anywhere.
    for py in Path(tmp).rglob('*.py'):
      pkg_dir = py.parent
      if not (pkg_dir / '__init__.py').exists():
        (pkg_dir / '__init__.py').write_text('')

    entry = f'{args.module}:{args.entrypoint}'
    zipapp.create_archive(tmp, target=args.output, interpreter=INTERPRETER, main=entry)

  print(f'created executable {Path(args.output).resolve()}')
