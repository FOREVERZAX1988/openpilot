# 合并丢件第二轮：顶层符号级机械比对全扫（2026-10-24 07:2x）

驾驶者要求：「用合并前后本地独有 hunk 的机械比对，把那次合并改过的文件逐个扫一遍，
出一份可判定清单，把还没暴露的一次捞干净」。这是第二轮的结论。

## 0. 一句话

全树扫 332 个「合并前本地动过」的文件，**符号级**仍有丢失的是 **29 个文件 / 71 个顶层符号**。
其中真正影响运行、需要回补的只有 **3 条**（pandad 的 H7/DOS 直启、carrot web push 三件套、
v_asm_server 的 bind_http_server）；最有争议的 jetlink warp 那条已判定为**上游意图取代，不是回归**。
其余 22 个是**测试文件**——回归网被拆，不会当场崩，但会让下次合并静默复发。

## 1. 方法（可复现）

脚本：`ai/scripts/merge_loss_symbol_scan.py`

```
PRE  = d1155add38   # 合并前的本地基线（sp-macan-test2 尖端）
BASE = 9e002fb2dc   # 这次重排用的上游底座
HEAD = 当前 sync/upstream-1024
```

审计域 = `git diff --name-only BASE PRE`（= 合并前本地动过、且三边都存在的文件）。

**判定链**：
1. `local_defs` = PRE 里有定义、BASE 里没有定义（= 合并前本地新写的顶层符号）
2. 该符号在 HEAD 同一文件里既无定义也无出现 → 候选丢失
3. 一次 `git grep` 全树（HEAD）反查候选名的外部引用：
   - 还有别的**代码**文件引用 → `CRASH`（定义没了、调用方还在）
   - 没人引用 → `DEAD`（死代码/测试被拆，不崩但回归网漏）

**和第一轮（`docs/merge-loss-audit-20261022.md`）的口径差别**：第一轮是「本地独有行里
任意 ≥5 字符标识符在 HEAD 消失」，噪音很大——注释里的英文单词（`Everything`/`Python`/`False`）
也满足条件，所以第一轮行级口径一开始跑出 179 个文件 / 3266 行。这轮只认**顶层符号定义**
（`def`/`class`/大写常量），把噪音压到 29 个文件，且每条都能落到「哪个符号、谁还在用」。

两轮互补，都留着：行级捞「只改了函数体」的丢失，符号级捞「符号没了」的必崩。

## 2. 结果

| 维度 | 数 |
|---|---|
| 审计域（合并前本地动过） | 332 文件 |
| 候选丢失顶层符号 | 71 个 |
| 涉及文件 | 29 |
| `full-revert`（HEAD 与上游底座逐字节相同 = 本地改动整份没了） | 17 |
| `partial`（只丢一部分） | 12 |
| 反查后 `CRASH` 级候选 | 14 文件 |
| 反查后 `DEAD` 级 | 15 文件 |

> `CRASH` 那 14 条**绝大多数是假警报**，原因见 §3.1：私有名下划线名在别处撞名
> （`_api` 撞 sunnylink、`_bind` 撞 `common/params.py`、`_failed` 撞 `media_pipeline`、
> `request_shutdown` 撞 `webrtcd`），以及**我自己的审计 .md 里提到了这些名字**。
> 排除这两类之后，真硬伤只剩 jetlink 的 `warp_path` 一族。

## 3. 逐条判定（运行期文件）

### 3.1 jetlink warp —— 上游意图取代，**不是回归**（本轮最大的一条「假回归」）

`openpilot/sunnypilot/jetlink_adapter/__init__.py`（partial，丢 `warp_path`/`lossless_warp_path`/
`make_warp` 一族）+ `SConscript`（full-revert，98→13 行）。

看起来像「本地辛苦搭的 warp 构建被吞」，实际是上游 jetlink `0f87696`
（"run modeld's own warp, not one jetlink builds"）的**新意图**已经并进来了：

- HEAD 的 `SConscript` 是一句 `Import('env')  # noqa: F401` 的 no-op，注释写清了为什么；
- HEAD 的 `__init__.py` 里 `Adapter` 继承 `jetlink.openpilot.stock.Stock`，
  `warp_path()` 由子模块提供，`WARP_DIR = 'openpilot/selfdrive/modeld/models'`（`stock.py:72`）；
- HEAD 注释明确写了**故意不指** `openpilot/sunnypilot/modeld_v2/models`：
  「This checkout's copy … is an LFS pointer (132 bytes here), so pointing there would hand the link no warp at all.」

设备上实测核对：

```
openpilot/selfdrive/modeld/models/driving_warp_1928x1208_tinygrad.pkl   837991 B   <- 真产物，stock 指向这里
openpilot/sunnypilot/modeld_v2/models/driving_warp_1928x1208_tinygrad.pkl   132 B   <- LFS 指针桩
openpilot/sunnypilot/jetlink_adapter/models/warp_1928x1208_512x256_tinygrad.pkl  837991 B  <- 旧设计的产物
```

**结论：运行时 warp 供给是好的。** 那么 `jetlink_adapter/tests` 现在
**9 failed + 5 errors** 是**过期测试在断言已被取代的旧设计**，不是运行期回归：

| 红的测试 | 断言的旧设计 |
|---|---|
| `test_warp_build.py` 5 条 | `make_warp` 存在、SConscript 会给每个 camera 产出 `jetlink_adapter/models/warp_*` |
| `test_tinygrad.py` 5 条 ERROR | fixture 里 `op.warp_path = lambda ...` 猴子补丁，HEAD 已无此名 |
| `test_chestnut_parity` / `test_model_manager` / `test_queues`(2 subfail) | 旧的从属断言 |

处置建议：**改测试对齐新设计**（断言 `Stock.WARP_DIR` 与 `modeld/models` 下有真产物），
而不是把旧 warp 构建回贴——回贴会和上游 jetlink `0f87696` 打架。

### 3.2 pandad 的 H7 / C3-DOS 直启 —— **真丢失，建议回补**

`openpilot/selfdrive/pandad/pandad.py`（full-revert）。丢的是三个 tizi 专属修复：

1. `H7_HW_TYPES` + `is_h7_panda_hw()`：first_run 只 reset **H7 系** panda，不去 reset 非 H7；
2. `has_non_h7_panda`：只有存在非 H7 panda 时才设 `BOARDD_SKIP_FW_CHECK=1`；
3. `should_launch_cpp_directly()`：C3 DOS 单内嵌 F4 时**跳过 Python 端的 panda 初始化/flash**，
   直接 `exec ./pandad`（`MANAGER_DAEMON=pandad` + `BOARDD_SKIP_FW_CHECK=1`）。

设备现状（本轮实测进程表）恰好印证这个损失：

```
35082  openpilot.selfdrive.pandad.pandad      <- Python 壳又回来了
35631  ./pandad 1f0040000151303436363037      <- 被 Python 壳拉起的 C++
```

也就是说现在多了一层 Python 包壳、且 first_run 会对**所有** panda 做 reset。
本体不崩（pandad 在跑），但这是**明确被吞的本地修复**，且改动小、判定清晰。

注意回贴时的冲突点：HEAD 已跟随上游把 `HARDWARE.has_internal_panda()` 改成 `COMMA_HARDWARE`、
把 `health["som_reset_triggered"]` 保持成上游写法。**回贴只回三条 H7/DOS 判定，不要把这两处一并退回旧写法。**

### 3.3 carrot web push 三件套 —— **真丢失，建议回补**

| 文件 | 丢的符号 |
|---|---|
| `sunnypilot/carrot/server/config.py` | `CARROT_WEB_PUSH_PATH` |
| `sunnypilot/carrot/server/features/push.py` | `handle_page` |
| `sunnypilot/carrot/server/services/web_push.py` | `load_state` / `save_state` / `_migrate_legacy_file` / `_params` |
| `sunnypilot/carrot/server/tests/test_web_push.py` | `TestPwaInstallability` / `_FakeParams` / `_push_app` / `_state` / 若干 test_ |

`features/push.py` 现在只剩 `from ..services.web_push import ensure_vapid_keys, send_push`，
**页面处理器和状态持久化都没了** → 8088 面板的推送订阅现在是无状态可用、重启即丢。

### 3.4 modeld_v2 helpers / compile_modeld —— **上游取代**

`sunnypilot/modeld_v2/helpers.py` 丢 `dump_oob`/`load_oob`/`_pad_args`/`DynamicTinygradUnpickler`/`_dynamic_factory`，
`sunnypilot/modeld_v2/compile_modeld.py` 丢 `_patch_ops_serialization`/`_patch_tinygrad_fetch_fw`/`read_file_chunked_to_disk`。

但同名函数在 `openpilot/selfdrive/modeld/helpers.py:40`、`openpilot/selfdrive/modeld/compile_modeld.py:16,284`
**都还在**，且 `compile_modeld.py:14` 是从 `openpilot.selfdrive.modeld.helpers` import 的。
判定：上游把这几件并回 `selfdrive/modeld/`，`sunnypilot/modeld_v2/` 那份是**旧副本**，属取代而非丢失。
**但需要一次单独确认**：`sunnypilot/modeld_v2/helpers.py:18` 那句注释
（"removed both from here and moved dump_oob to modeld_v2/helpers.py"）现在指向一个不存在的实现，
是死注释，顺手清掉。

### 3.5 其余 22 个 —— 回归网被拆（不崩，但会静默复发）

全是 `*_test.py` / `test_*.py` / `audit_*.py` / `*_smoke.py`。典型：

- `carrot/tests/test_carrot_ui_reach.py`（整份回退，丢 54 行 UI 可达性断言）
- `sunnypilot/common/tests/test_safe_mode.py`（`TestKeysAreRegistered` / `_declared_keys`）
- `selfdrive/selfdrived/tests/test_modeld_lag.py`（`TestMildTierWiring`）
- `selfdrive/car/tests/test_vcruise_pcm_set_speed.py`（`TestMacanFusionSetSpeed` —— **macan 专属**）
- `sunnypilot/selfdrive/controls/lib/tests/test_vehicle_tune_dispatch.py`（`TestMacanStaysStock` —— **macan 专属**）
- `sunnypilot/carrot/tests/audit_ui_reach.py`（`EXTRA_CONTROL_PARAMS`）

macan 那两条尤其要注意：正是驾驶者报的「macan 车型限制（自定义 ACC 步长本该打不开）」那类断言的归属地。

## 4. 下一步（按建议顺序）

1. **pandad 三条 H7/DOS 判定回补**（§3.2）—— 小、判定清晰、设备现状已印证。
2. **carrot web push 三件套回补**（§3.3）—— 纯 Python，不动安全路径。
3. **jetlink warp 测试对齐新设计**（§3.1）—— 把 9+5 条红改成断言 `Stock.WARP_DIR`，别回贴旧构建。
4. **回归网回补**（§3.5）—— 先从 macan 两条 + `test_carrot_ui_reach` 起。
5. 第一轮 `docs/merge-loss-audit-20261022.md` 里还有 4 条 `WARN … identical (patch lost?)`
   和 2 条 `FAIL … upstream intent missing`，与本轮并集一起清。

## 5. 附带发现（不是回归，但记下来）

全树有 5 个 **LFS 指针桩**（132/134 字节），合并前后都如此，不是这次合并造成的：

```
openpilot/selfdrive/modeld/models/big_driving_tinygrad.pkl                 134 B
openpilot/sunnypilot/modeld_v2/models/{big_,}driving_warp_{1344x760,1928x1208}_tinygrad.pkl  132 B ×4
```

其中 `sunnypilot/modeld_v2/models/*` 那 4 个已被 jetlink 显式绕开（见 §3.1），
`selfdrive/modeld/models/big_driving_tinygrad.pkl` 需要单独确认是否有代码按路径读它。

## 6. 执行进度（2026-10-24 上午，真机）

§3.2 pandad / §3.3 web push / §3.5 主体已落地，三笔提交：

| 提交 | 内容 |
|---|---|
| `bbe5886f06` | pandad 三条 H7/DOS 判定 + carrot web push 全链（§3.2/§3.3） |
| `65c0109059` | 回归网第一批 + **真回归①：macan 融合分支**（§3.1 之外的新发现） |
| `73e7fb3d69` | 回归网第二批 + **真回归②：carrot_man msgq 安全 / ③：LatSuspendAngleDeg 裸读** |

### 6.1 回补过程中新捞出的三条真回归（原审计没列）

1. **`cruise.py` 的 `macan_fusion` 分支整体丢失**（子类 531 行 + 基类 82 行两处）。
   HEAD 里 `macan_fusion` 只剩 `__init__` 一处赋值 → 融合分支不执行 → carrot 状态机
   （`_cruise_speed_min`=5）当家。即 `TestMacanFusionSetSpeed` 注释记录的现场缺陷
   （5 km/h 幽灵速度 + 纵向双源争夺）。回贴时**未**退回已不存在的 `_clamp_set_speed`。
2. **`carrot_man.py` 的共享 msgq 安全整套丢失**：`_publish_msg`/`_pub_lock`/
   `_pub_contention`/`_broadcast_submaster`/`CARROT_SERVICES` 全无，`sm.update(0)` 出现两处。
   即"两个线程同时进 `PubMaster.send`/同时 update 同一 msgq"的堆损坏根因。
   三方合并唯一冲突点正是"广播线程读 `sm` 还是 `self.sm`"，取本地那份。
3. **`carrot_controls.py` 参数裸读**：`get("LatSuspendAngleDeg")` 少了 `return_default=True`
   → 未写过的键给 `float(None)` → `wants_suspend()` 抛 TypeError，而它由 onroad 控制回环轮询。

### 6.2 仍未做（下一轮起点）

- **§3.1 jetlink 测试对齐新设计**：`test_warp_build.py`(5 红)/`test_tinygrad.py`(5 错误)
  等 9 failed + 5 errors。已确认这三个文件（warp_build/tinygrad/chestnut_parity）在 HEAD
  与上游底座**逐字节相同**，红是合并前就有的，属"测试断言旧设计"，不是本轮引入。
  注意 HEAD 已有上游新增的 `jetlink_adapter/warp_build.py`（179 行），对齐应以它为基准。
- **§3.4 死注释**：`sunnypilot/modeld_v2/helpers.py:18` 那句指向不存在实现的注释。
- **§2 的 5 个 LFS 指针桩**（132/134 B）与 `big_driving_tinygrad.pkl` 的按路径读取确认。
- **环境疑点（路试前值得实测一次）**：设备上 `/data/openpilot/tinygrad`（未受管、10-01 部署）
  的 `Buffer.view` 是 `(size, dtype, offset)` 三参，而 `selfdrive/modeld/modeld.py:143`
  的 `input_view()` 传两参，且 `pack_inputs()` 在 `ModelState.__init__` 里无条件调用。
  该行与上游底座逐字节相同，故不是合并问题；需确认 modeld 实际加载的 tinygrad 版本。
