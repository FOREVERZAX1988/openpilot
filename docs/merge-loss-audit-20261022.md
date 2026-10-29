# 合并丢件审计（机械比对）— 2026-10-22 round 23 合并

**问题**：`7399ffe498 port(round 23)` 把本地分支重排到上游 test `9e002fb2` 之后，用户可见多处旧修复消失。
本文用「合并前后本地独有 hunk 的机械比对」把所有被吞掉的内容一次列清，避免再靠回忆逐条抓。

## 1. 方法（可复现）

```
PRE  = d1155add38   # 合并前的本地基线（sp-macan-test2 尖端）
BASE = 9e002fb2dc   # 这次重排用的上游底座
M    = 7399ffe498   # 合并结果
HEAD = 当前 sync/upstream-1024
```

1. `git diff --name-only BASE PRE` → 460 个「本地动过」的文件（审计域）
2. 对每个文件：取 PRE / BASE / HEAD 三个 blob，`本地独有行 = PRE - BASE`；
   若这些行在 HEAD 里也找不到，记为「硬丢」。再过滤：该行里的标识符（≥5 字符）
   在 HEAD 该文件中**完全消失**才算数 —— 这样移动/重排/改字不会误报。
3. 对硬丢的顶层符号回查 HEAD 全树引用，抓「符号没了但调用方还在」。
4. 状态列：
   `full-revert` = 该文件 HEAD 与上游底座逐字节相同（本地改动整份没了）；
   `equals-uptip` = HEAD 与上游 test 尖端相同；`partial` = 只丢了一部分。

## 2. 结论摘要

| 维度 | 结果 |
|---|---|
| 被整份删除的文件 | **0**（没有文件级丢失，全是文件内的 hunk 被吞） |
| 代码文件被吞 | **46** 个，其中整份回退上游 30 个 |
| 测试文件被吞 | **35** 个（回归网被拆，后续合并会静默复发） |
| i18n | **没丢**（见 §5，行级 diff 全是噪音）|
| 子模块 | opendbc 指针只前进 1 个提交且旧指针是其祖先 → 无本地提交丢失；jetlink/panda/msgq/rednose/teleoprtc/tinygrad 指针未动 |
| 已确认「会直接报错」的硬伤 | **3 处**（已在 d727915fd1 修好，见 §3）|

## 3. 本轮已修（符号消失 + 调用方仍在 = 必崩）

| 文件 | 丢了什么 | 谁还在用 | 后果 |
|---|---|---|---|
| `system/ui/widgets/label.py` | `gui_text_box()` | `tici_updater.py:14`、`tici_reset.py:15` 直接 import | ImportError：AGNOS 升级/复位页起不来 |
| `system/ui/lib/emoji.py` | `emoji_is_renderable()` | `label.py:_emoji_runs` | 画到 ★ ✕ → 这类符号时 NameError |
| `system/ui/lib/application.py` | `GuiApplication.fallback_scale()` | `text_measure.py:27` | 显式传 font 的 measure_text → AttributeError（带 CJK 字体的页面）|

提交 `d727915fd1`。验证：三个模块 import 通过；`emoji_is_renderable('★')=False, ('😀')=True`；ruff 干净。

> 注：同一路径上 `is_prebaked_cjk_font()` / `_cjk_atlas_ids` 也一起被删了，但 HEAD 已无调用方，
> 所以 `fallback_scale` 按「实测 em 宽度」重写、不再依赖预烘焙图集的短路分支，语义不变。

## 4. 待判清单：代码文件（按风险分级；分级是我按「用户可见/会不会崩」猜的，可逐条推翻）

- **[P0]** `openpilot/sunnypilot/jetlink_adapter/__init__.py` — partial，硬丢 31 行
  - 消失的顶层符号：`CHESTNUT_IDS`, `OWNER_LOG`, `WARP_DIR`, `warp_path`, `lossless_warp_path`, `Adapter`, `_api`, `_bind`, `_log_failure`, `_failed`
- **[P0]** `openpilot/sunnypilot/carrot/server/services/web_push.py` — full-revert，硬丢 27 行
  - 消失的顶层符号：`_params`, `_migrate_legacy_file`, `load_state`, `save_state`
- **[P0]** `openpilot/sunnypilot/jetlink_adapter/SConscript` — full-revert，硬丢 25 行
- **[P0]** `openpilot/sunnypilot/modeld_v2/compile_modeld.py` — full-revert，硬丢 17 行
  - 消失的顶层符号：`_patch_tinygrad_fetch_fw`, `_patch_ops_serialization`, `read_file_chunked_to_disk`
- **[P0]** `openpilot/sunnypilot/modeld_v2/helpers.py` — full-revert，硬丢 17 行
  - 消失的顶层符号：`_pad_args`, `_dynamic_factory`, `DynamicTinygradUnpickler`, `load_oob`, `dump_oob`
- **[P0]** `openpilot/sunnypilot/carrot/carrot_man.py` — equals-uptip，硬丢 16 行
  - 消失的顶层符号：`CARROT_SERVICES`, `CARROT_PUBLISHED_SERVICES`, `_enable_fault_diagnostics`
- **[P0]** `openpilot/sunnypilot/selfdrive/selfdrived/accelerator_events.py` — full-revert，硬丢 16 行
- **[P0]** `openpilot/common/hardware/comma/agnos_tici.json` — full-revert，硬丢 5 行
- **[P0]** `openpilot/selfdrive/pandad/panda_comms.cc` — full-revert，硬丢 5 行
- **[P0]** `openpilot/sunnypilot/carrot/server/features/push.py` — full-revert，硬丢 4 行
  - 消失的顶层符号：`handle_page`
- **[P0]** `openpilot/sunnypilot/sunnylink/settings_ui.json` — partial，硬丢 3 行
- **[P0]** `openpilot/selfdrive/pandad/pandad.py` — full-revert，硬丢 2 行
  - 消失的顶层符号：`H7_HW_TYPES`, `is_h7_panda_hw`, `should_launch_cpp_directly`
- **[P0]** `openpilot/sunnypilot/sunnylink/settings_ui_src/pages/cruise.yaml` — full-revert，硬丢 2 行
- **[P0]** `openpilot/sunnypilot/carrot/server/config.py` — full-revert，硬丢 1 行
  - 消失的顶层符号：`CARROT_WEB_PUSH_PATH`
- **[P0]** `openpilot/sunnypilot/modeld_v2/compile_modeld_v2.py` — full-revert，硬丢 1 行
- **[P0]** `openpilot/sunnypilot/modeld_v2/model_adapters.py` — full-revert，硬丢 1 行
- **[P1]** `openpilot/selfdrive/selfdrived/events.py` — partial，硬丢 19 行
- **[P1]** `openpilot/system/ui/lib/application.py` — partial，硬丢 18 行
- **[P1]** `openpilot/system/ui/widgets/label.py` — partial，硬丢 6 行
- **[P1]** `openpilot/sunnypilot/carrot/carrot_server.py` — full-revert，硬丢 4 行
- **[P1]** `openpilot/sunnypilot/models/fetcher_zp.py` — full-revert，硬丢 4 行
- **[P1]** `openpilot/selfdrive/ui/sunnypilot/layouts/settings/visuals.py` — partial，硬丢 3 行
- **[P1]** `openpilot/sunnypilot/selfdrive/controls/lib/stopping_controller.py` — partial，硬丢 3 行
- **[P1]** `openpilot/sunnypilot/selfdrive/selfdrived/events.py` — partial，硬丢 3 行
- **[P1]** `openpilot/selfdrive/controls/lib/nnff_variables.py` — partial，硬丢 2 行
- **[P1]** `openpilot/selfdrive/modeld/helpers.py` — partial，硬丢 2 行
- **[P1]** `openpilot/selfdrive/ui/layouts/settings/device.py` — partial，硬丢 2 行
- **[P1]** `openpilot/selfdrive/ui/widgets/offroad_alerts.py` — full-revert，硬丢 2 行
- **[P1]** `openpilot/sunnypilot/carrot/cluster_view/cluster_overlay_renderer.py` — full-revert，硬丢 2 行
- **[P1]** `openpilot/sunnypilot/common/safe_mode.py` — full-revert，硬丢 2 行
- **[P1]** `openpilot/selfdrive/car/cruise.py` — partial，硬丢 1 行
- **[P1]** `openpilot/selfdrive/controls/controlsd.py` — partial，硬丢 1 行
- **[P1]** `openpilot/selfdrive/ui/sunnypilot/layouts/settings/carrot_tuning_items.py` — partial，硬丢 1 行
- **[P1]** `openpilot/sunnypilot/carrot/amap_navi.py` — full-revert，硬丢 1 行
- **[P1]** `openpilot/sunnypilot/carrot/server/features/static.py` — full-revert，硬丢 1 行
- **[P1]** `openpilot/sunnypilot/carrot/server/services/device_info.py` — full-revert，硬丢 1 行
- **[P1]** `openpilot/sunnypilot/carrot/web/sw.js` — full-revert，硬丢 1 行
- **[P1]** `openpilot/sunnypilot/carrot/xiaoge/v_asm_server.py` — partial，硬丢 1 行
  - 消失的顶层符号：`bind_http_server`
- **[P1]** `openpilot/sunnypilot/common/safe_mode_runtime.py` — full-revert，硬丢 1 行
- **[P1]** `openpilot/system/ui/lib/emoji.py` — full-revert，硬丢 1 行
- **[P1]** `openpilot/system/webrtc/carrot/webrtcd.py` — full-revert，硬丢 1 行
- **[P2-CI]** `.github/workflows/sunnypilot-build-model.yaml` — full-revert，硬丢 14 行
- **[P2-CI]** `.github/workflows/build-default-models.yaml` — full-revert，硬丢 10 行
- **[P2-CI]** `.github/workflows/build.yaml` — full-revert，硬丢 9 行
- **[P2-CI]** `.github/workflows/compile-warp-kernels.yaml` — full-revert，硬丢 1 行
- **[P2-CI]** `.lfsconfig` — full-revert，硬丢 1 行

## 5. 明确的「不是问题」

- **i18n 没丢**：`app_zh-CHS.po` 已译条目 合并前 2231 → 现在 2238；`app_zh-CHT.po` 1816 → 1823。
  行级 diff 里 1653 行「丢失」全部是 `#: 源文件:行号` 引用注释随代码重排的噪音。
  唯一真回退：CHT 一条 `Stock → 原廠` 变空（可单独补）。
  真正导致「Macan 定制菜单没翻译」的不是 .po，而是 **带这些字符串的菜单源码被回退了**（见 P0/P1 里
  `carrot_tuning_items.py`、`sunnylink/settings_ui*.json|yaml`、`params_keys.h`），字符串不在了 .pot 自然不会收。
- **docs/**、**tests/** 的丢失不影响行车，但 tests 是下次合并的护栏，建议一起补。
- **opendbc** 子模块前进的 1 个提交是上游的；`b9e3f006` 的 merge-base 就是我们旧指针 `61f4cc84`。

## 6. 复现/复核

```
git diff --stat d1155add38 HEAD            # 344 个文件被改过
git show d1155add38:<file> | diff - <(git show HEAD:<file>)   # 单文件逐条看
```

## 4b. 被吞的回归测试（35 个，符号级清单同样在审计 JSON 里）

这些是把上面 P0/P1 行为钉住的门闩。源码补回来后如果不补测试，下一次合并会再吞一遍而没人知道。

```
  41  full-revert openpilot/sunnypilot/carrot/server/tests/test_web_push.py
  35  full-revert openpilot/sunnypilot/modeld_v2/tests/test_models.py
  27  equals-uptip openpilot/selfdrive/ui/tests/carrot_tuning_render_smoke.py
  22  full-revert openpilot/sunnypilot/selfdrive/selfdrived/tests/test_accelerator_events.py
  21  partial     openpilot/sunnypilot/carrot/tests/test_carrot_man.py
  19  full-revert openpilot/sunnypilot/carrot/tests/test_carrot_ui_reach.py
  17  partial     openpilot/selfdrive/ui/tests/test_radar_points.py
  15  full-revert openpilot/sunnypilot/carrot/tests/audit_ui_reach.py
  13  partial     openpilot/sunnypilot/jetlink_adapter/tests/test_adapter.py
  12  full-revert openpilot/selfdrive/selfdrived/tests/test_modeld_lag.py
  12  full-revert openpilot/sunnypilot/selfdrive/controls/lib/tests/test_carrot_longitudinal_source.py
  11  full-revert openpilot/sunnypilot/common/tests/test_safe_mode.py
  10  full-revert openpilot/sunnypilot/modeld_v2/tests/test_compile_modeld.py
   7  full-revert .github/workflows/test_models.yml
   7  full-revert openpilot/sunnypilot/jetlink_adapter/tests/test_warp_build.py
   6  full-revert openpilot/sunnypilot/carrot/server/tests/test_device_setting_groups.py
   6  full-revert openpilot/sunnypilot/selfdrive/controls/lib/tests/test_longitudinal_planner.py
   5  full-revert openpilot/sunnypilot/selfdrive/controls/lib/tests/test_vehicle_tune_dispatch.py
   3  full-revert openpilot/selfdrive/car/tests/fleet_safety.py
   3  partial     openpilot/selfdrive/car/tests/test_vcruise_pcm_set_speed.py
   3  partial     openpilot/selfdrive/car/tests/vcruise_carrot_onroad_sim.py
   3  full-revert openpilot/sunnypilot/jetlink_adapter/tests/test_seam.py
   3  full-revert openpilot/sunnypilot/modeld_v2/tests/test_fallback.py
   3  full-revert openpilot/sunnypilot/selfdrive/controls/lib/lead_forecast/tests/test_forecast.py
   2  full-revert openpilot/selfdrive/locationd/test/test_imu_calibrationd.py
   2  full-revert openpilot/selfdrive/modeld/tests/test_signal_shadow.py
   2  full-revert openpilot/sunnypilot/carrot/tests/test_carrot_controls.py
   2  equals-uptip openpilot/sunnypilot/carrot/tests/test_carrot_server_params.py
   2  full-revert openpilot/sunnypilot/carrot/tests/test_gps_sources.py
   2  equals-uptip openpilot/sunnypilot/carrot/tests/test_lane_change_gap.py
   2  full-revert openpilot/sunnypilot/system/hardware/tests/test_hardwared_ext.py
   1  full-revert openpilot/common/tests/test_watchdog.py
   1  equals-uptip openpilot/selfdrive/ui/tests/bluetooth_render_smoke.py
   1  full-revert openpilot/sunnypilot/common/tests/test_lateral_arbitration_params.py
   0  deleted     openpilot/sunnypilot/jetlink_adapter/tests/conftest.py
```

## 7. 建议修复批次（按「互相独立、可单独回滚」切）

| 批次 | 内容 | 为什么排这个位置 |
|---|---|---|
| A | `modeld_v2/` 四件套（helpers/compile_modeld/compile_modeld_v2/model_adapters） | 模型加载链，`full-revert` 最彻底；错了模型起不来，对了才谈性能 |
| B | `jetlink_adapter/`（`__init__.py` + `SConscript` + 3 个 tests） | 行车预览轨迹 / jetlink 交接就是这条；需先判定「`__getattr__` 委派 vs PRE 的显式 Adapter」哪套是合并后的正式版 |
| C | `carrot/` 服务与设置行（`carrot_man`、`web_push`/`push`/`config`、`settings_ui.json`/`cruise.yaml`、`carrot_tuning_items`） | Carrot 参数行消失 = 设置界面里整行不出现（Macan 自定义 ACC 步长即此类） |
| D | `pandad.py` + `panda_comms.cc` + `agnos_tici.json` | panda 识别/固件哈希，行车安全相关且改动极小，风险低收益高 |
| E | `selfdrived/events.py` 两处 + `offroad_alerts.py` | 告警 msgid 在源侧 `tr()`，决定中文警告是否显示 |
| F | 35 个测试 + CI（`.github/workflows/*`、`.lfsconfig`） | 护栏与前门，最后补但不补则前面白修 |
