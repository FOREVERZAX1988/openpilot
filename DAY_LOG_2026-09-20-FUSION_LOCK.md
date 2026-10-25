## 2026-09-20 Macan 融合控制按钮「恒定 true」锁定 + 备份推送

### 用户诉求
把 macan 融合控制按钮改为**恒定 true**（只能用融合控制模式——纯 OP 模式还没搞定），
然后备份推送到远程 `sp-macan-long-dev`；推送前确认没把密钥（含高德 api）带上去。

### 改动（2 仓 4 文件）
| 位置 | 改动 |
|---|---|
| `openpilot/selfdrive/ui/sunnypilot/layouts/settings/vehicle/brands/volkswagen.py` | `update_settings()`：`set_enabled(False)` + `set_state(True)` 恒开锁定；`MacanFusionMode=0` 时自愈回写 1。`_on_enable_fusion_mode()`：强制写 True、被切关则回弹，并置 `OnroadCycleRequested` |
| `openpilot/selfdrive/ui/mici/layouts/settings/toggles.py` | 同一开关锁定：`set_enabled(False)` + 写 True + `set_checked(True)` |
| `openpilot/selfdrive/car/cruise.py` | `VCruiseHelper.macan_fusion` 不再读参数 → Macan 恒走融合（OP 巡航速度跟随原厂 `ACC_02.Wunschgeschw`） |
| opendbc `opendbc/car/volkswagen/carcontroller.py` | `macan_fusion_on` 恒真、`macan_pure_op` 恒 False → 纯 OP 分支（OP 自算 ACC02/04/05 + LS_01 bus2 待命）保留但不可达；原读取两行注释保留 |

> 解禁方式（后续纯 OP 路试通过时）：恢复 3 处被注释/被强制的读取
> （carcontroller 两行、cruise.py 一行；UI 侧把 `set_enabled(False)`/`set_state(True)` 还原为参数驱动）。

### 验证证据
- `python3 -m py_compile`（4 文件）OK；设备无 pytest，套件用 `python3 -m unittest` 跑。
- opendbc `opendbc.car.volkswagen.tests.test_macan_mlb`：**33 passed**（纯 OP 状态机用例仍绿）。
- 主仓 `openpilot.sunnypilot.carrot.tests.test_param_registration`：**2 passed**。
- 设备 Param `/data/params/d/MacanFusionMode` = **1**；未注释的读取点只剩 UI 显示侧。
- UI 重启：kill 88125 → 新 pid **124234** 存活，`/data/log/swaglog.*` 无 Traceback/Exception。

### 推送（`git ls-remote` 核实）
| 仓 | commit | 分支 |
|---|---|---|
| 主仓 | `3e2be75204` | `macan-long-0919` + `sp-macan-long-dev` |
| opendbc | `341e046c2b` | `macan-long-0919` + `sp-macan-long-dev` |

- ai 子模块本次**未改动**（无 gitlink 变更）→ 无需推送；本次记忆写在 `ai/workspace/memory/2026-09-20.md`，
  该目录被 ai 仓 `.gitignore` 忽略（本地记忆，素来不随推送走）。
- 两仓目标分支均为 **fast-forward**（推送前已 fetch 并 `merge-base --is-ancestor` 确认，未强推）。
- 密钥自检：推送 diff 扫 `github_pat_` / `ghp_` / `AKIA` / `[0-9a-f]{32,}` / `api_key` / `token` / `高德`
  → 仅命中 gitlink SHA（正常），无密钥外泄。
- 备份点：改动前 4 个原文件已存 `/data/backup_fusion_lock_0920/`（仓库外，不随推送）。
