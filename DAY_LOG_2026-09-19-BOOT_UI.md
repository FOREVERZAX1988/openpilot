# 2026-09-19 卡逗号图标 / Carrot Tuning / 合并回归 —— 排查日志

设备 comma 3，fork `FOREVERZAX1988/openpilot` 分支 `macan-long-0919`（上游 `mouxangithub/openpilot` master-c3）

## 0) 关键机制：屏幕上的"逗号图标"就是编译 Spinner
`openpilot/system/manager/build.py` 在 manager 启动最前面跑 `scons`（先默认并行，失败退 `-j4`，再退 `-j1`），
期间 `Spinner()` 画的**就是那个逗号 logo（带进度环）**。
- 编译/链接没结束 → 一直停在逗号图标（看起来像"卡死"）
- 三次都失败 → 弹 TextWindow "openpilot failed to build" 然后 exit(1)
→ 所以"重启后重新编译了但还是卡逗号图标" = **开机自编译没成功**，不是 LFS、也不是 AGNOS。
  今天查到的三处编译期失败：`modeld.py`/SConscript 上游 API（5d7f30ad37）、cereal schema、
  params_keys.h 被合并覆盖。

## 1) 用户两个猜想：都不成立（已用证据排除）
- **LFS**：`git lfs ls-files` 252 个文件全部 `*`（工作区已是真内容），0 个缺失；
  `Inter-Medium.ttf` 292140 字节真 TTF、`common/hardware/comma/updater` 24.7MB 真脚本。→ 拉齐了。
- **AGNOS 版本**：设备 `/VERSION` = `19.7`，`launch_env.sh` 的 `AGNOS_VERSION` = `19.7` → 一致，
  `/tmp/agnos_pending.log` 不存在（无待刷写）。之前 webui"AGNOS 更新失败"是 `agnos_api.py`
  在嵌套目录布局下把 BASEDIR 当成 openpilot 包目录 → FileNotFoundError（已修，见 n_1789789208590）。

## 2) 卡 UI 的直接崩溃（已修完）
- `system/ui/lib/application.py::_load_fonts` → `KeyError: <FontWeight.NORMAL: 'Inter-Medium.ttf'>`
  （`FontWeight` 里 NORMAL/MEDIUM/DISPLAY_REGULAR/ROMAN 复用同一 ttf 文件名，StrEnum 同名值互为别名，
   别名成员不参与 `for m in FontWeight` 迭代 → `self._fonts[NORMAL]` 必缺）
- `imu_calibration.py` 读 `ImuCalibrationEnabled`、`mapd_manager.py` 读 `Mapd_ClearCache` → `UnknownKeyName`
- 现况：UI 进程 12:59 起持续存活（1h+），12:56 之后再无 crash 日志；
  离屏仿真 `gui_app.init_window()` 能跑完 → `_load_fonts` 已不再抛异常。

## 3) params_keys.h：合并丢 282 key（已修） + 4 个"从未注册"的 key（今天修）
- 44106242e0 把合并覆盖掉的 282 个上游 key 补回。核对：HEAD 580 = 上游 master-c3 556 + 本地自研 24
  （Macan*/DpEpsAssistComp*/UsbGpu*/UseKonikServer/ModelManager_*_USBGPU），`upstream - HEAD = ∅`、
  `合并前本地 - HEAD = ∅` → header 已完整。
- 今天静态扫描"代码引用 vs header 注册"又发现 4 个 key **上游和合并前本地都没有过**（不是合并丢的）：
  `AutoCurveSpeedAggressiveness`(carrot_functions.py:895)、`NavDestination`(athenad.py:399 / carrot_man.py:1724)、
  `TimezoneName`/`TimezoneSource`(carrot_serv.py:542)。143d10ae44 已注册 + 新增回归测试。
  - 为什么"一堆报错"里看不到它们：全是**静默失效**——
    `UnifiedParams._read_from_system()` 吞 UnknownKeyName → 回落默认 0.0
    → 城市道路(roadcate>1) `target_lat_a * 0.0` → 曲率速度恒 5 km/h（该值广播给 Carrot App）；
    裸 `Params().put()` 的 UnknownKeyName 被 try/except 吞掉 → App"发送目的地"失败、手机时区不落盘。
  - Python 回落层（nav_params.json/config.py）已生效：`get_float("AutoCurveSpeedAggressiveness")` = 100 → 系数 1.0；
    C++ 注册表要重编 params.o 才生效。

## 4) 开机编译是内存瓶颈（重要，勿在开机后重编大文件）
今天在设备上手动 `scons openpilot/common/params.o` 被 **SIGKILL（Error -9）**，`-j1` 也一样：
`free` 只剩 ~430MB available，而常驻大内存：`ai.aid` 349MB、`ui` 220MB、`mapd` 129MB、`webuid` 96MB。
- 只 include 该头的 TU 只有 `common/params.cc`（dry-run 确认只重编 params.o + relink libparams_c.so）
- scons 失败会**删掉 params.o**；libparams_c.so 保持旧版本 → 现有进程不受影响（不会变砖），
  但新 key 要等下次开机自编译（11:47 那次开机编译已成功过一次，内存足够）
- 结论：手动改 C++/header 后**不要在当前会话里重编**，留给开机（那时 UI/modeld 还没起来）

## 5) Carrot Tuning 验证（用户反馈：能点但卡 / 很多"?"/ 没翻译）
离屏仿真（`OFFSCREEN=1`，2160x1080）：
- `tools/macan/carrot_ui_audit.py zh-CHS` → 9 个 tab / 225 项 / 每帧 17.2–18.1ms（基线 clear+swap 17.2ms）、
  **缺字形字符 = 0**（改前逐帧全量重绘在 TUNING 55 项时 33.2ms）
- `tools/macan/settings_ui_sim.py zh-CHS` → 17 个面板全 OK、165 条文案**缺字形 = 0**（构造 975ms）
- 翻译覆盖：carrot_tuning.py 226 条 `tr()` 全部在 `app_zh-CHS.po` 有非空 msgstr
- 语言切换（新增 `tools/macan/verify_carrot_lang.py`）：en 构造 → 切 zh-CHS → 257 条中文出现 → 切回 en 归零，
  证明 b935e7e63d 的 `title=lambda: tr(...)` 真的实时跟随
- webui：panel_catalog 324 个 param 全部已注册；`test_carrot_tuning_api`(6) + `test_panel_catalog`(4) passed

## 6) 测试与推送
- `tools/test_runner.py openpilot/sunnypilot/carrot/tests/ -j2` → 180 passed（含新增 2 条 param 注册检查）
- `tools/test_runner.py openpilot/selfdrive/ui openpilot/system/ui -j2` → 96 passed / 1 skipped / 1 xfailed
- 推送：origin/macan-long-0919 = 143d10ae44（含 b935e7e63d）；子模块 ai/opendbc/webui/rednose 全部已同步
  （ai 954157e2、opendbc 6903509f、webui a9c7d76c 均存在于各自 remote 分支）

## 7) 待办
- [ ] 重启一次（触发开机自编译 → 4 个新 key 进 C++ 注册表），重启后确认：UI 起得来 + `Params().all_keys()` 含这 4 个 key
- [ ] 若开机编译失败会弹 "openpilot failed to build" 文本窗（不是静默卡死），可据此判断
- [ ] 城市道路曲率速度（Carrot App 广播值）实车确认不再是 5 km/h
