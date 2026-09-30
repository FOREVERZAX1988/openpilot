## 2026-09-19 Carrot 调校页顶部标签栏字体 1.5x

### 用户问题
「Carrot 里面的设置」顶部状态栏字体太小、看着费劲，希望放大 1.5 倍。

### 定位
- 该页 = 设置 → 导航 → Carrot Tuning；顶部整条 strip 里**只有**那 9 个标签文字
  （开始/巡航/导航/速度/调节/显示/轨迹/车辆/开发者），由 `carrot_tuning.py::_render_tabs()` 绘制。
- 根因是字号与全站不一致：`TAB_FONT_SIZE = 24`，而同页列表项用
  `styles.ITEM_TEXT_FONT_SIZE = 50`（styles.py），连一半都不到。
- 设备为 tizi(comma 3X) → BIG_UI → `FONT_SCALE = 1.242`，中文还经 Noto fallback
  （`FALLBACK_FONT_SCALE = 1.25`）：
  - 旧中文标签 ≈ 24 × 1.242 × 1.25 = **37 px/字**
  - 同页列表项 ≈ 50 × 1.242 × 1.25 = **78 px/字**
- 约束：9 个 tab 平分面板宽度，(2160 − 500 − 2×50) / 9 = **173.3 px/个**，
  字号放大后长标签（英文 7–10 字符）会画到自己 tab 外面。

### 实施
- `TAB_FONT_SIZE 24 → 36`（正好 1.5x）；`TAB_HEIGHT 80 → 96`（放大的字形 ≈ 56 px 高，四周仍留 ~25 px）。
- 新增 `_fit_tab_label()`：以 `tab_w − 2×TAB_TEXT_PADDING(12)` 为上限逐像素收缩，
  下限 `TAB_FONT_MIN_SIZE = 24` —— **任何语言下标签都不会比改动前更小**，也绝不越过自己的 tab。
  只对「装不下」的标签收缩，逐标签独立决定。
- 中文实测（PIL 按 Inter/NotoSansSC 真实字宽算，tab_w = 173.3）：
  | 标签 | 中文 | 结果 |
  |---|---|---|
  | 开始/巡航/导航/速度/调节/显示/轨迹/车辆 | 2 字 | **36 px（1.5x）** |
  | 开发者 | 3 字 | 32 px（≈1.33x，唯一的收缩项） |
  英文场景：Navigation 收到 24（≈原大小）、Developer 25、Display/Vehicle 35，其余 36 —— 不会溢出。

### 验证
- 新测试 `openpilot/selfdrive/ui/tests/test_carrot_tuning_tab_bar.py`（9 例，全过）
  —— 断言 1.5x、下限不低于旧值 24、条高够、每个标签（中/英）都不越界、中文不被过度缩放、
  短标签保持满字号、绘制路径确实用了拟合字号（防止有人把 `TAB_FONT_SIZE` 写死回去）。
  用假的 `measure_text_cached` 建模 Inter(0.5 em)/Noto CJK(1 em×1.25)，不需要 GPU/窗口。
- 既有 `openpilot/sunnypilot/carrot/tests/test_param_registration.py` 2 例仍过；
  `ruff` 无新增告警（carrot_tuning.py 里 4 条 E501/TID251 是既有的）。

### 生效条件
UI 是常驻进程，改完需**重启设备**（或重启 ui 进程）后新字号才出现。

### 备注
- 工作区里 `openpilot/sunnypilot/carrot/nav_params.json` 的改动（多出 `"Brightness": 5`、文件尾少一个换行）
  是 UnifiedParams 在真机上把「未注册 param」落盘的运行时产物，不是本次改动，故未提交。
