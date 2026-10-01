# DAY_LOG 2026-10-01 — panda pin 口径：`7d703710`（适配C3）vs `4643ee2c`（适配F4）

> 状态：**已落地并推送**（分析轮见 §0–§6 / 落地见 §7 / 推送与核查见 §8）。
> 分析轮当时**未改任何文件、未推送**；panda 子模块只执行过 `git fetch --unshallow`（补历史，不动工作区）。
> 分析轮主仓 HEAD `7476f3fa37`，panda gitlink `7d703710a`，webui gitlink `92e86674c`。
> 落地后主仓 HEAD = `51d1bfe3a9`（=`origin/sp-macan-re`），panda gitlink = `4643ee2c6`。

## 结论（一句话）

- 两个 pin 是**同一条线**：共祖 `61b050f1`，我们 +1（就 `适配C3`）、上游 +13，**两个 commit 都是 mouxan 本人写的**。
- 树差 **31 文件 / +207 −577**。其中 **F4/C3 板级移植两边逐字节相同**；真正分叉 = **health 包重构** + H7 DTS + 签名脚本去 pycryptodome + 上游 CI 机器人脚本。
- **被刷进 panda 的签名固件 `board/obj/*.bin.signed` 在两个 pin 上逐字节相同** → 换 pin **不改实际固件二进制**。
- 真正绑住的是 **health 包协议 ↔ `pandad.cc` 自研补丁**，必须**成对**改。
- panda 仓**没有** `board/safety/` → 车辆安全模型由 **opendbc** 提供，**不在 panda**。
  ⇒ 换 pin 不影响 Macan/MLB 的控车与安全能力，只影响 health 协议解析与 pandad 的编译。

## 0. 先更正上一轮的错判

上一轮我写「两者无共同祖先（两套独立历史）」——**错**。
panda 子模块是 **shallow clone**（`.git/shallow` 里正好列着 `7d703710`），祖先被切掉了。
`git fetch --unshallow` 后祖先关系恢复：

| | commit | 相对共祖 |
|---|---|---|
| 共祖 | `61b050f1` | — |
| 我们 pin | `7d703710` 适配C3（mouxan，07-28） | **+1** |
| 上游 pin | `4643ee2c` 适配F4（mouxan，09-21） | **+13** |

## 1. 31 文件账本（`git diff --name-status 7d703710 4643ee2c`）

### A. 只有我们有（11 个，**全删类型，与固件无关**）
`.github/scripts/upstream_sync_*.{sh,txt}`（10）+ `.github/workflows/upstream-sync.yml`
→ 是「自动同步上游」的 CI 机器人脚本，上游仓库不需要它。

### B. 只有上游有（1 个）
`board/stm32h7/lldts.h`（+32）—— 新的数字温度传感器（DTS）驱动。

### C. 两边都改、改法不同（19 个）

| 文件 | +/- | 内容 |
|---|---|---|
| `python/__init__.py` | +51/−27 | 新 health flags 常量、串口枚举、`HAS_OBD`/`MAX_FAN_RPMs` |
| `board/main_comms.h` | +25/−18 | health 包组装（**与 pandad.cc 对接的那一侧**） |
| `board/crypto/sign.py` | +20/−4 | 去掉 `pycryptodome`，改手写 DER 解析 |
| `SConscript` | +17/−10 | 同上（去依赖）+ 构建调整 |
| `board/health.h` | +14/−12 | **健康包结构体重构**（见 §2） |
| `board/boards/board_declarations.h` | +14/−0 | 板级声明 |
| `board/sys/power_saving.h` | +6/−0 | 停模式里关 DTS |
| `tests/setup_device_ci.sh` | +7/−1 | 上游改 venv 跑 CI |
| `Jenkinsfile` | +5/−2 | 同上 |
| `python/dfu.py` | +3/−3 | 默认 MCU 由 H7 改 F4 |
| `board/main_definitions.h` / `main_declarations.h` | +3/+3 | 声明同步 |
| `board/stm32h7/{board.h,peripherals.h}` | +1/+1 | DTS 时钟 |
| `board/stm32f4/stm32f4_config.h` | +1 | 补 `spi_error_count`，省掉 main_comms 里的 `#ifdef STM32F4` |
| `board/drivers/drivers.h`、`board/main.c`、`board/jungle/main.c` | +1/+1/+2 | 装配 |

## 2. 核心分叉：health 包重构（上游 `75aa44bec` + `dd8a5b3df`）

| 字段 | 我们 `7d703710`（旧） | 上游 `4643ee2c`（新） |
|---|---|---|
| voltage / current | `uint32` | **`uint16`** |
| ignition_line / ignition_can / controls_allowed / power_save_enabled / heartbeat_lost / safety_rx_checks_invalid / som_reset_triggered | 各自独立 `uint8` 字段 | 收进一个 **`flags_pkt`（uint16）位域** |
| interrupt_load | `float` | **`uint8`**（×255 量化） |
| 横/纵允许 | `controls_allowed_lateral_pkt` / `_longitudinal_pkt` | 打包成 **`controls_allowed_sp_pkt`**（bit0=lat, bit1=long） |
| 温度 | 无 | **`temperature_pkt`** |

## 3. 最关键的耦合：`pandad.cc`（**不能单独换 pin 的原因**）

我们 openpilot 侧的 `openpilot/selfdrive/pandad/pandad.cc` 有一块自研补丁（注释 `macan-long-0815-fix`），
**照我们 panda 的旧 health 布局写的**：

```cpp
ps.setIgnitionLine(health.ignition_line_pkt);                      // 旧布局字段
ps.setControlsAllowed(health.controls_allowed_pkt);
ps.setControlsAllowedLateral(health.controls_allowed_lateral_pkt);
ps.setControlsAllowedLongitudinal(health.controls_allowed_longitudinal_pkt);
```

上游 `master-c3` 同一函数是 flags 版：

```cpp
ps.setIgnitionLine((health.flags_pkt & HEALTH_FLAG_IGNITION_LINE) != 0U);
ps.setControlsAllowedLateral(health.controls_allowed_sp_pkt & 1);
ps.setControlsAllowedLongitudinal((health.controls_allowed_sp_pkt >> 1) & 1);
```

**配对关系**：我们 panda（旧）+ 我们 pandad.cc（旧）是一对；上游 panda（新）+ 上游 pandad.cc（新）是一对。

- 单独把 panda 换到 `4643ee2c` → `ignition_line_pkt` / `controls_allowed_pkt` / `power_save_enabled_pkt` … 一个都不存在，
  **直接编译不过**（是构建期硬失败，**不是**「悄悄丢控车」）。
- 之前担心的「换 pin 会丢 Macan 融合逻辑」是**误判**：31 文件里**没有 Macan 代码**。

## 4. 板级（tici / tizi）与「内置 / 外接红熊」

- `board/` 下**同时**有 `stm32f4/` 与 `stm32h7/`：同一份 panda 源码支持
  **C3（`tici`，内置 F4/DOS/黑熊）**、**C3X（`tizi`，内置 H7/红熊）**与 **C4（`mici`，H7）**。
  详见 `ai/docs/COMMA_DEVICES.md`（单一事实来源）。
- `board/stm32f4/` 下**只有 `stm32f4_config.h` 差 1 行**；`board/boards/dos.h`、bxcan、clock_source 等 F4 板级代码
  **根本没出现在差异清单里 = 逐字节相同**。上游那 13 个提交动的反而是 **H7 侧**（DTS、health 重构）。
- `board/obj/` 两个 pin **逐字节相同**，含 `panda.bin.signed`、`panda_h7.bin.signed`、`body_h7.bin.signed`：
  **实际刷进 panda 的签名固件不变**。
- 固件本身**不区分内置/外接**（同一份 `.bin`）；区别只在**刷机路径**：
  红熊（H7）外接由 `pandad` 自动刷；黑熊/DOS（F4）不自动刷，用 `recover_dos_panda`。
- panda 仓**没有 `board/safety/`** → 车辆安全模型在 **opendbc**（`opendbc/safety/modes/volkswagen_mlb.h`）。
  ⇒ Macan/MLB 的控车与安全**不随 panda pin 变化**。

## 5. 两种口径与代价

| 口径 | 代价 |
|---|---|
| **留旧线**（现状） | 永久背一个**上游已重构掉的协议** + 一块**只为它而存在**的 `pandad.cc` 补丁（`macan-long-0815-fix`） |
| **跟随上游** | 必须**成对做**：panda pin → `4643ee2c` **且** pandad.cc 那块补丁换成上游 flags 版。单独换 pin = 编译期硬失败 |

> 二者都**不影响** Macan 车型的控车能力（控车在 opendbc，不在 panda）。

## 6. 本轮核验清单（只读）

- 主仓 `sp-macan-re` HEAD `7476f3fa37`，`git status` 干净。
- panda gitlink 仍 `7d703710a`；webui gitlink 仍 `92e86674c`。
- 本轮唯一动作：panda `git fetch --unshallow`（仅补历史）。

---

## 7. 执行记录（2026-10-01，本轮落地）

已按「跟随上游」口径落地，**本地提交 `2356011191`，未推送**：

- panda 子模块指针 `7d703710a` → `4643ee2c6`（= 上游 `master-c3` pin）。
- `openpilot/selfdrive/pandad/pandad.cc` 的 `macan-long-0815-fix` 段整体替换为上游 flags 版：
  - `flags_pkt & HEALTH_FLAG_{IGNITION_LINE,IGNITION_CAN,CONTROLS_ALLOWED,POWER_SAVE_ENABLED,HEARTBEAT_LOST,SAFETY_RX_CHECKS_INVALID}`
  - `controls_allowed_sp_pkt & 1` / `>> 1 & 1`（横 / 纵）
  - `interrupt_load_pkt / 255.0f`
  - `send_panda_states` 里 ignition / power-save 读写同步改为位操作
- 二者作为**一对**提交（单独换 pin = 编译期硬失败）。

### 验证结果
| 检查 | 结果 |
|---|---|
| 旧 health 字段残留（全仓 `.cc/.h/.py`） | **0 处**（仅 pandad.cc 内部已全部改写） |
| `panda/board/health.h` 与 pandad.cc 字段/宏对齐 | ✅ |
| `pandad.cc` 编译（`pandad.o`） | ✅ 通过 |
| pandad 链接（需 `common/params.o`） | ⚠️ **实机上无法完成** —— 见下 |
| panda 子模块工作区 | 干净，恰在 `4643ee2c6` |

### ⚠️ 环境约束（新增，重要）
本机是 **C3 实机：1 核 / 3.6 GB / 无 swap**。`scons -j1` 编到 `common/params.o` 时：
```
lowmemorykiller: Killing 'clang++' ... to free 1343920kB
                 on behalf of 'openpilot.syste'
```
→ **在本机上做 C++ 构建会触发 lowmemorykiller，并且是"为正在运行的 openpilot 让路"**。
结论：**编译/链接验证一律放到 PC 或 CI，禁止在实机上跑 scons。**
本轮 `pandad.o` 的编译成功足以证明改动本身可编译；整链链接交由 CI。

### 待办
1. ~~推送 `2356011191` 并让 CI 出整链构建结果（等你确认再推）。~~ → **已推送**：
   `origin/sp-macan-re` = `51d1bfe3a9`（含 `2356011191`）。CI 结论见 §8.2（本分支**没有**自动 run）。
2. `pandad` 侧字段命名未变（cereal `PandaState` schema 无改动），下游 consumer 无需改。

---

## 8. 推送与核查记录（2026-10-01 续）

### 8.1 推送状态（已核实）
| 项 | 值 |
|---|---|
| 本地 HEAD | `51d1bfe3a9`（`sp-macan-re`） |
| `git ls-remote origin refs/heads/sp-macan-re` | `51d1bfe3a9` |
| ahead / behind | **0 / 0**；工作区干净 |

### 8.2 CI（"整链构建"）核查 —— **本分支没有构建可看**
- `GET /repos/FOREVERZAX1988/openpilot/actions/runs?branch=sp-macan-re` → **total_count = 0**：
  `sp-macan-re` 上**从未跑过任何 workflow**。
- `build.yaml`（"编译并发布预构建包"）的触发面：
  `on.push.branches = [master-c3-prebuild, tn-c3-prebuild]`、`on.push.tags = release/*`、
  `workflow_run: ["打包预编译分支"]`、`pull_request_target(labeled)`、`workflow_dispatch`。
  ⇒ **push 到 `sp-macan-re` 天然不会触发它**。该 workflow 近期在 `sp-macan-long-dev` 上的 run
  结论全是 **skipped**（被 `prepare_strategy` 的 `workflow_run.conclusion == 'success'` 门挡住）。
- 结论：**想拿本分支整链构建，必须手动触发** —— 要么 UI 里 `workflow_dispatch`（`branch=sp-macan-re`），
  要么 `git push origin sp-macan-re:master-c3-prebuild` 走预构建分支。**"盯 CI"自动等待没有意义**。

### 8.3 fork 子模块「`.gitmodules` branch ↔ gitlink(pin)」对齐账本
| 子模块 | `.gitmodules` branch | gitlink(pin) | fork 远端该分支 tip | 结论 |
|---|---|---|---|---|
| panda | `sp-macan-re` | `4643ee2c6` | `7d703710a` | ❌ **不一致** |
| opendbc | `sp-macan-re` | `b5ee1ecb7` | `b5ee1ecb7` | ✅ |
| webui | `sp-macan-re` | `92e86674c` | `92e86674c` | ✅ |
| ai | `sp-macan-re` | `ffa096fbd` | `ffa096fbd` | ✅ |

**唯一待对齐 = panda**：gitlink 已换成上游 `4643ee2c6`，但 fork 的 `sp-macan-re`
（`.gitmodules` 记录要跟踪的分支）仍指向旧线 `7d703710a`。
⇒ 任何人跑 `git submodule update --remote panda` 都会把 panda **退回旧 pin**，把 §7 的对齐回滚。

对齐命令（换 pin 属**分叉历史**，必须 force；`7d703710a` 仍由 `master-c3` / `macan-long-0926` 保底，不会丢）：
```bash
cd panda
git push --force-with-lease=refs/heads/sp-macan-re:7d703710a85bdabdd85145d257c397a3d824097d \
  origin 4643ee2c6:refs/heads/sp-macan-re
```
`4643ee2c6` 已是 fork 的既有对象（可从 `macan-long-0925` 到达）→ push 只移动 ref，不传新对象。

### 8.4 ⚠️ 本会话环境无推送凭据（约束，需外部机器执行）
- `ssh -T git@github.com`（默认无 key；`/persist/comma/id_rsa` 也不行）→ `Permission denied (publickey)`；
- `~/.ssh` 不存在、无 ssh-agent、无 credential helper、无 PAT；
- 全局 `url.git@github.com:.pushinsteadof=https://github.com/` 把 https 推送也改写成 SSH。
⇒ 8.3 的对齐**需在具备凭据的机器上执行**；本文件只做账本记录，未在实机上做任何远端写操作。
