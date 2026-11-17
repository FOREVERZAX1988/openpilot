#!/usr/bin/env bash
# 把 build_stripped.sh 产出的精简树发布到本仓库 staging 分支。
# GitHub Actions release.yaml「同步发布到 CNB 镜像仓库」阶段的 CNB 原生等价。
#
# 增量策略（与 release.yaml 一致）：build_stripped.sh 产出的是孤立单提交，与 CNB 上
# 现有 staging 分支无共同历史，直接 push -f 每次都会全量上传整棵树。这里以 CNB 当前
# staging tip 为父提交，用 commit-tree 重新生成携带同一棵树（HEAD^{tree}）的提交，
# 推送便只包含本次有变化的对象。CNB 分支不存在（首次发布）或 fetch 失败时回退全量；
# FORCE_FULL_PUSH=true 亦可强制全量以重置镜像历史。
set -e

BRANCH=staging
CNB_REPO="${CNB_REPO:-mouxancnb/openpilot}"
TARGET_DIR="${TARGET_DIR:?TARGET_DIR must be set (exported by pipeline env)}"
FORCE_FULL_PUSH="${FORCE_FULL_PUSH:-false}"

if [ -z "${CNB_TOKEN:-}" ]; then
  echo "CNB_TOKEN not available in pipeline env, abort" >&2
  exit 1
fi

# commit-tree 的提交身份（与 build_stripped.sh 的 identity.sh 保持一致；
# 发布阶段是独立脚本，拿不到 build 阶段导出的环境变量）
export GIT_COMMITTER_NAME="github-actions[bot]"
export GIT_COMMITTER_EMAIL="github-actions[bot]@users.noreply.github.com"
export GIT_AUTHOR_NAME="github-actions[bot]"
export GIT_AUTHOR_EMAIL="github-actions[bot]@users.noreply.github.com"

cd "$TARGET_DIR"
git remote remove cnb 2>/dev/null || true
git remote add cnb "https://cnb:${CNB_TOKEN}@cnb.cool/${CNB_REPO}.git"

force_arg="-f"
prev=""
if [ "$FORCE_FULL_PUSH" != "true" ] \
    && git fetch --depth=1 cnb "$BRANCH" \
    && prev=$(git rev-parse -q --verify FETCH_HEAD); then
  echo "incremental push: parented on CNB staging tip ${prev}"
  force_arg=""
else
  echo "full push: CNB branch missing, fetch failed, or FORCE_FULL_PUSH requested"
fi

# AGNOS 锁保护：精简树从 master 重打，launch_env.sh 的 AGNOS_VERSION 会回到
# master 的原始值，而 CNB staging 上可能带着与设备当前 AGNOS 配套的锁定提交
# （版本错配会让设备 OTA 逻辑混乱）。默认保留 prev tip 的 AGNOS 期望；
# 需要随新 AGNOS 升级发布时在流水线 env 设 BUMP_AGNOS=true。
if [ -n "$prev" ] && [ "${BUMP_AGNOS:-false}" != "true" ]; then
  want_ver=$(git show "FETCH_HEAD:launch_env.sh" 2>/dev/null | grep -m1 'AGNOS_VERSION=' || true)
  if [ -n "$want_ver" ] && [ "$(grep -m1 'AGNOS_VERSION=' launch_env.sh || true)" != "$want_ver" ]; then
    sed -i "s|^export AGNOS_VERSION=.*|$want_ver|" launch_env.sh
    echo "AGNOS version lock preserved: $want_ver"
  fi
  # AGNOS OTA manifest 与锁定版本配对，一并保留
  for f in openpilot/common/hardware/comma/agnos.json openpilot/common/hardware/comma/agnos_tici.json; do
    if git cat-file -e "FETCH_HEAD:$f" 2>/dev/null; then
      git checkout FETCH_HEAD -- "$f"
      echo "AGNOS manifest preserved from prev staging tip: $f"
    fi
  done
fi

# 组装待发布提交：
#   增量路径 —— 工作树可能带锁保护修改，write-tree 重组后 commit-tree 挂到 prev
#   全量路径 —— build_stripped 产出的是孤儿提交（refs/heads/tmp），直接沿用
if [ -n "$prev" ]; then
  tree=$(git write-tree)
  new=$(git commit-tree "$tree" -p "$prev" -m "$(git log -1 --format=%B)")
else
  new=$(git rev-parse refs/heads/tmp)
fi
git update-ref refs/heads/tmp "$new"

# 精简树无 LFS 对象，跳过 LFS 钩子并关闭压缩（与产树时的 git 参数一致）
if ! GIT_LFS_SKIP_PUSH=1 git -c pack.window=0 -c pack.depth=0 -c pack.compression=0 \
    push $force_arg cnb "tmp:${BRANCH}" --no-verify; then
  # 增量推送失败（如 fetch 之后远端 tip 又变了）：全量兜底，下次会自动重新挂链
  echo "::warning::incremental push failed, falling back to full push"
  GIT_LFS_SKIP_PUSH=1 git -c pack.window=0 -c pack.depth=0 -c pack.compression=0 \
    push -f cnb "tmp:${BRANCH}" --no-verify
fi
echo "CNB staging updated: https://cnb.cool/${CNB_REPO}/-/tree/${BRANCH}"
