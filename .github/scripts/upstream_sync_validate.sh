#!/usr/bin/env bash
# Lightweight smoke checks after upstream merge (no full scons build).
set -euo pipefail

test -f SConstruct
test -d panda
test -f sunnypilot/common/version.h
grep -q 'mouxangithub/opendbc' .gitmodules
grep -q 'mouxangithub/panda' .gitmodules

markers="$(git grep -l -E '^(<{7}|>{7})' -- . 2>/dev/null | head -10 || true)"
if [[ -n "$markers" ]]; then
  echo "Conflict markers remain:"
  echo "$markers"
  exit 1
fi

python3 -m compileall -q sunnypilot/common sunnypilot/system sunnypilot/mads 2>/dev/null || \
  python3 -m compileall -q sunnypilot

echo "Validation OK"
