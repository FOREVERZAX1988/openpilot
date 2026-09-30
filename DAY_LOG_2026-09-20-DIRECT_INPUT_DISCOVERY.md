## 2026-09-20 数字框「直接输入」+ App 发现复核（推送 291690605d / 65606562b6 / webui 8d7530c）

### 用户诉求
1. 「你上面那个说没做的」：给数字框加**直接输入**，按 renderTextRow 的写法改；
2. 复核 CarrotManUdpPort 调不回 0/7706、App 搜不到设备是否真修好，并把改动推远程；
3. 推之前确认没把密钥（含高德 key）带上去。

### 改动
- 设备 UI：`openpilot/system/ui/sunnypilot/widgets/option_control.py` —— 数值框可点，弹出
  `InputDialogSP` 键盘直接键入；普通行 round+钳 [min,max]，`use_float_scaling` 行 ×100 写回，
  `value_map` 行按显示值反查 key（非映射值忽略），非数字/空输入不改值不崩布局；数值框加浅色底作为可点提示。
  `list_view.py::option_item_sp` 透传 title 作键盘标题。
- WebUI（8088）：`web/static/js/panels.js` 把 `renderIntRow()` 的数值 `<span>` 换成
  `<input inputmode=numeric>`，回车/失焦提交，沿用 `renderTextRow` 的输入框写法与 save 路径
  （CarrotManUdpPort 1024→7706 原本要点 6682 次）；`panel_catalog` 下界 1024→0（与自身 desc 一致，"开了关不掉"）。

### 复核证据（本次实机，重启后）
- `git rev-list --left-right --count origin/macan-long-0919...HEAD` → **0 0**（主仓已推）；
  webui `origin/macan-long-0919=8d7530c`、opendbc `=ab5549ede0`、ai `=974d325dd`、panda `master-c3=7d703710`
  —— 所有 gitlink 都能在远端解析（不会指向不存在的 commit）。
- 单测（设备上 `python3 -m unittest`，无需 pytest）：carrot 套件 **197 passed**；
  `test_carrot_option_direct_input` **11 passed**。
- UI 重启后新代码生效：`openpilot.selfdrive.ui.ui` 新 pid 存活、日志无 Traceback；
  当前 Carrot 调校页数值框点一下即出键盘。
- `carrot_man` kill 后 manager 自行拉起（新 pid，etime 19s）→ 验证长尾1 `restart_if_crash=True` 生效；
  重起后 UDP `7706` 重新 bind、`8088` 面板 HTTP 200。
- 发现信标：本机 `0.0.0.0:7705` 监听 8.3s 收到 **4 包（0.48/s ≈ 2s 周期）**，
  payload `{"ip":"192.168.10.79","port":7706,...}` —— 即修好的**广播**（修复前 240s 收 0 包）。
- 密钥检查：高德 key 只是设备 Param（`params_keys.h:346` 标 `DONT_LOG`），仓库/DAY_LOG 只写"32 位 hex"；
  推送 diff 内无 token/长 hex（扫描 `github_pat_`/`ghp_`/`AKIA`/`[0-9a-f]{32}` 无命中）。

### 温度
`carrot_man` CPU ~7–10%，不是热源；thermal zone 58–64℃，`thermal_status=ok`。
长尾3（`_write_navi_debug()` 停车时 payload 不变也 10Hz 写 Params）已改成变化才写，停车降到 ~1Hz
（8.3% → 6.7%）。主要占用来自 camerad / pandad / ui / ai。

### 待用户确认
手机端 navipilot r260726 重新搜索设备（设备侧广播已恢复；7726/7706 + 8088 都在跑）。
