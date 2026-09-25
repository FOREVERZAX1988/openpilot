## 2026-09-19 触摸命中：Carrot 顶部标签栏「点不动 / 点错」+ 设置侧栏「点出不在显示的项目」

### 用户问题
1. 「Carrot 顶部状态栏」点过去不灵活，半天没反应。
2. 「设置选项卡」点击有时不准，经常能点出**不在显示**的项目，怀疑触屏代码有问题。

两条都复现出根因，且都是**命中判定用错了输入源**，不是触摸屏硬件/校准问题。

### 根因 1：标签栏在渲染循环里轮询 raylib 按键沿（大概率丢事件）
- 旧代码在 `carrot_tuning.py::_render_tabs()` 里每帧判断
  `rl.is_mouse_button_pressed(LEFT) and check_collision_point_rec(rl.get_mouse_position(), tab_rect)`。
- raylib 的「刚按下」沿只在**下一次 `poll_input_events()` 之前**有效：
  - 触摸采样线程以 140 Hz 轮询（`application.py:221`、`MOUSE_THREAD_RATE = 140`），
  - `rl.end_drawing()` 每帧也轮询一次（≈60 Hz 渲染），
  - 即「按下」边沿的存活窗口 ≤ 7 ms，而渲染循环每 ~17 ms 才看一次 → **多数点击在某一帧看到之前就被清掉了**，
    表现就是「点了没反应、要戳好几次」。
- 偶尔某一帧抓到了这个沿，用的是 `rl.get_mouse_position()`（**当时**的位置而非按下的位置）：
  手指按下后略有滑动就会选中**隔壁**的 tab。
- 这正是仓库 ruff 明令禁止的两种用法（根目录 `pyproject.toml` TID251）：
  `"pyray.is_mouse_button_pressed".msg = "This can miss events. Use Widget._handle_mouse_press"`。
  改前 `ruff check selfdrive/ui system/ui` 在该文件上报该违规，改后全树 0 条。

### 根因 2：设置侧栏对「上次画过的矩形」做命中（陈旧矩形 → 打开没显示的项）
- `sunnypilot/layouts/settings/settings.py::NavButton._render()` 每帧把 `panel_info.button_rect = rect` 写回；
  父类 `SettingsLayoutSP._handle_mouse_release()` 拿**释放点**去遍历 `self._panels`（面板顺序），**取第一个命中**。
- 侧栏本身是个 `Scroller`，而 `scroller_tici.py::Scroller._render()` 为了省帧时间会
  `continue` 掉**完全在视口外**的行（不渲染、也不处理事件）——
  那些行的 `button_rect` 就**冻结在它最后一次上屏时的位置**（跨着视口边缘，最多重叠 110 px）。
- 侧栏 17 项 × 110 px = 1870 px，视口只有 ~780 px，必然滚动：
  点视口上沿的可见行时，释放点同时落在某条**已滚出屏幕**行的陈旧矩形里，
  于是父类按面板顺序命中了那条（例如 DEVICE），**打开了一个列表里根本看不到的面板**。
- 同一类问题还包括：释放点漂移一格就会选中相邻项（父类只看释放点，不看按下点）。

### 实施
1. `carrot_tuning.py`
   - 删除渲染里的按键轮询；新增 `_handle_mouse_press()`——走 `Widget` 框架事件（`gui_app.mouse_events`，
     由 140 Hz 采样线程喂入，按下沿不会丢），**按下即切换**，用**按下位置**判定（手指后续漂移不再选错）。
   - 拆出纯几何 `tab_index_at(pos, strip_rect)` 与 `_select_tab()`；条带矩形每帧在 `_render_tabs()` 里刷新。
2. `sunnypilot/layouts/settings/settings.py`
   - `NavButton.__init__` 里 `set_click_callback(self._activate)`，点自己 → `parent.set_current_panel()`；
     不再写 `button_rect`，父类 `_handle_mouse_release()` 只留「关闭按钮」（它每帧内联绘制，矩形永不过期）。
   - 效果：命中矩形永远是**该行当前被画出来的那个**，且没被渲染的行（滚出视口）**点不到**。

### 验证
- 新测试 `openpilot/selfdrive/ui/tests/test_settings_touch_hit_test.py`（9 例）+ 既有标签栏 9 例，共 **18 例全过**：
  - 9 个 tab 各占 1/9、条带外（含下方列表）返回 None；
  - 用 `gui_app._mouse_events` 手喂事件走**真实事件路径**：按在索引 5 → 切到 DISPLAY；
    按在条带下方 → 不变；先按 tab0 再在 tab8 释放 → 仍是 tab0（按下点决定）；
  - 侧栏行：按下+释放同行 → 只打开该面板；按下在第 3 行、释放在第 4 行 → **什么都不打开**；
  - 源码守卫：`carrot_tuning.py` 不再出现 `rl.is_mouse_button_pressed(`，
    `settings.py` 不再出现 `panel_info.button_rect = rect`、释放处理里不再出现 `button_rect`。
- 全部测试无需 GPU/窗口（几何是纯函数，事件靠手喂）。
- `ruff`：UI 树里 `is_mouse_button_pressed` 违规 **0**（仅剩 `sunnypilot/lib/drive_stats.py` 的 `time.time`，本次无关、
  改前既有；`carrot_tuning.py` 3 条 E501 也是改前既有）。

### 生效条件
UI 是常驻进程，改完需重启 ui 进程/设备后生效。

### 备注
- 工作区 `openpilot/sunnypilot/carrot/nav_params.json` 的改动是 UnifiedParams 真机落盘的运行时产物，未提交。
- 同一类「按释放点决定子控件」的还有 `OptionControlSP`（+/-）与 `MultipleButtonAction`：
  按下后手指滑过按钮分界会选到另一个方向/选项（同一行内，不会跨行）。
  影响远小于上面两条，本次未动，可另行按同样思路（按下时锁定控件）修。
