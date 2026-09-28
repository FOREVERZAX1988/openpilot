#!/usr/bin/env bash
# Point openpilot submodules at latest master-c3-new tips on mouxangithub forks.
set -euo pipefail

SUBMODULE_OPENDBC="${SUBMODULE_OPENDBC:-opendbc_repo}"
SUBMODULE_PANDA="${SUBMODULE_PANDA:-panda}"
OPENDBC_REMOTE="${OPENDBC_REMOTE:-https://github.com/mouxangithub/opendbc.git}"
PANDA_REMOTE="${PANDA_REMOTE:-https://github.com/mouxangithub/panda.git}"
SUB_REF="${SUB_REF:-master-c3-new}"
FALLBACK_REF="${FALLBACK_REF:-master-c3}"

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

remote_has_branch() {
  local remote="$1" ref="$2"
  git ls-remote --exit-code "$remote" "refs/heads/${ref}" >/dev/null 2>&1
}

update_submodule() {
  local path="$1" remote="$2"
  if [[ ! -d "$path/.git" && ! -f "$path/.git" ]]; then
    echo "skip missing submodule path: $path"
    return 0
  fi

  local ref="$SUB_REF"
  if ! remote_has_branch "$remote" "$ref"; then
    echo "::warning::$path: branch $ref not found on $remote"
    if remote_has_branch "$remote" "$FALLBACK_REF"; then
      echo "::warning::$path: falling back to $FALLBACK_REF"
      ref="$FALLBACK_REF"
    else
      echo "::warning::skip $path: neither $SUB_REF nor $FALLBACK_REF exists on remote"
      return 0
    fi
  fi

  echo "Updating $path -> $remote $ref"
  git -C "$path" remote add fork "$remote" 2>/dev/null || git -C "$path" remote set-url fork "$remote"
  git -C "$path" fetch fork "$ref" --depth=1
  local sha
  sha="$(git -C "$path" rev-parse "fork/$ref")"
  git update-index --cacheinfo 160000,"$sha","$path"
  echo "$path pinned to $sha ($ref)"
}

update_submodule "$SUBMODULE_OPENDBC" "$OPENDBC_REMOTE"
update_submodule "$SUBMODULE_PANDA" "$PANDA_REMOTE"

if git diff --cached --quiet; then
  echo "Submodule pointers unchanged"
  exit 0
fi

git commit -m "sync: bump opendbc/panda submodules to ${SUB_REF}"
