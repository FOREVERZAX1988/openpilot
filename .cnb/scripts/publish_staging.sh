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

# AGNOS 版本仲裁（版本感知，2026-11-21 修复）：
#   master >= staging → 采信 master（正常路径：AGNOS 发版时 master 同步 bump 清单）
#   master <  staging → 锁定到 staging（master 落后于设备实际 AGNOS，防回退错配）
#   BUMP_AGNOS=true   → 无条件采信 master
# 锁定动作严格成对：launch_env.sh 与两个 OTA manifest 一起恢复到 staging 版本。
#
# 历史 bug（两次事故同根因）：
#   2026-11-19  sed 模式不兼容 launch_env.sh if 块内的前导空白，锁定静默无效；
#   2026-11-21  manifest 恢复是无条件的（只查文件存在，不比对版本），master 上的
#               新清单永远被 prev tip 的旧清单覆盖 → staging 冻结在 20.6.13，
#               产出 launch_env=20.6.18 + manifest=20.6.13 错配树。
agnos_ver_of() { # 从 stdin 读 launch_env.sh 文本，提取 AGNOS_VERSION（兼容前导空白与引号）
  grep -m1 'AGNOS_VERSION=' | sed -E 's|^[[:space:]]*export[[:space:]]+AGNOS_VERSION="?([^"]+)"?.*|\1|'
}
manifest_ver_of() { # $1 = OTA manifest 文件路径，提取其指向的 agnos 镜像版本
  grep -oE 'agnos-[0-9]+\.[0-9]+\.[0-9]+' "$1" | head -1 | cut -d- -f2
}

if [ -n "$prev" ] && [ "${BUMP_AGNOS:-false}" != "true" ]; then
  prev_ver=$(git show "FETCH_HEAD:launch_env.sh" 2>/dev/null | agnos_ver_of || true)
  cur_ver=$(agnos_ver_of < launch_env.sh || true)
  if [ -n "$prev_ver" ] && [ -n "$cur_ver" ] && [ "$cur_ver" != "$prev_ver" ]; then
    lower=$(printf '%s\n%s\n' "$cur_ver" "$prev_ver" | sort -V | head -1)
    if [ "$lower" = "$prev_ver" ]; then
      echo "AGNOS: master $cur_ver >= staging $prev_ver, adopting master (no lock)"
    else
      want_line=$(git show "FETCH_HEAD:launch_env.sh" | grep -m1 'AGNOS_VERSION=' | sed 's|^[[:space:]]*||')
      # 兼容行首任意空白（launch_env.sh 的 export 在 if 块内缩进）
      sed -i -E "s|^([[:space:]]*)export AGNOS_VERSION=.*|\1${want_line}|" launch_env.sh
      locked=$(agnos_ver_of < launch_env.sh || true)
      if [ "$locked" = "$prev_ver" ]; then
        echo "AGNOS version lock preserved: staging $prev_ver > master $cur_ver"
      else
        echo "::warning::AGNOS version lock FAILED: wanted '$prev_ver', got '$locked'" >&2
      fi
      # 与锁定版本严格配对：OTA manifest 一并恢复到 staging 版本
      for f in openpilot/common/hardware/comma/agnos.json openpilot/common/hardware/comma/agnos_tici.json; do
        if git cat-file -e "FETCH_HEAD:$f" 2>/dev/null; then
          git checkout FETCH_HEAD -- "$f"
          echo "AGNOS manifest restored from prev staging tip: $f"
        fi
      done
    fi
  fi
fi

# 发布前一致性自检（无条件执行）：launch_env 的 AGNOS_VERSION 必须与两个 OTA
# manifest 指向的镜像版本一致——错配会让设备 updater 按旧 manifest 无限乒乓刷机
# （卡逗号 logo，2026-11-19 事故）。发现错配直接失败：宁可不发，不可错发。
le_ver=$(agnos_ver_of < launch_env.sh || true)
for f in openpilot/common/hardware/comma/agnos.json openpilot/common/hardware/comma/agnos_tici.json; do
  m_ver=$(manifest_ver_of "$f")
  if [ -z "$le_ver" ] || [ "$m_ver" != "$le_ver" ]; then
    echo "::error::AGNOS mismatch: launch_env=$le_ver but $f -> agnos $m_ver; refusing to publish a mismatched tree" >&2
    exit 1
  fi
done
echo "AGNOS consistency check OK: launch_env=$le_ver, both OTA manifests match"

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
