## 2026-09-29 触摸「又失效了」：设置侧栏点击命中——9/19 的修复被上游 merge 吃掉，本次重新落地

### 用户反馈
「触摸是不是有问题，之前修过好几次，这次是不是又失效了？尤其点击上半部分的选项，
经常会跳出不在显示列的选项内容。」

### 结论：不是触摸屏硬件问题，是**命中判定用错了输入源**的修复被合回上游版本了
- 9/19 的提交 `91b8494793`（`fix(ui,touch): 标签栏/设置侧栏点击命中`）**不在当前分支历史里**
  （`git merge-base --is-ancestor 91b8494793 HEAD` → NO）。
- 9/28 的 `7e8dd10e5a Merge branch 'test' of mouxangithub/openpilot into tn` 是最近一次改动
  `settings.py` 的提交：侧栏 `NavButton` 又回到「每帧写 `panel_info.button_rect`、父类按释放点
  遍历面板顺序取首个命中」的旧实现。
- 于是老毛病原样复现：侧栏是 `Scroller`，`scroller_tici.py` 会跳过**视口外**行的渲染
  （`continue` → 该行既不绘制也**不再处理事件**），这些行的 `button_rect` 就冻结在它最后一次
  上屏时的位置。19 项 × `NAV_BTN_HEIGHT` 远超视口高度，向上滚出屏幕的行冻结在**视口上沿**，
  点视口上半部分的可见行时释放点同时落在这些陈旧矩形里，父类按面板顺序命中最早的那个
  （DEVICE），打开了一个列表里根本看不到的面板 —— 这正是「点上半部分跳出不在显示列的项」。

### 实施（重新应用，与 9/19 相同思路）
- `sunnypilot/layouts/settings/settings.py`
  - `NavButton.__init__`：`self.set_click_callback(self._activate)`，点自己 → `parent.set_current_panel()`；
    不再写 `panel_info.button_rect`。
  - `SettingsLayoutSP._handle_mouse_release()`：只保留关闭按钮（每帧内联绘制，矩形永不过期），
    不再遍历 `self._panels.items()` 做陈旧矩形扫描。
  - 命中矩形永远是「该行当前被画出来的那个」且被 `_hit_rect = rect ∩ parent_rect`（视口）裁剪：
    部分滚出的行只有可见带能点，完全没渲染的行**点不到**（`_process_mouse_events()` 只在
    `Widget.render()` 里被调用）。
- 测试 `selfdrive/ui/tests/test_settings_touch_hit_test.py`（4 例，无需 GPU/窗口）：
  行内按下+释放 → 只开该面板；按下第 3 行、释放在第 4 行 → 什么都不开；行上半被视口裁掉时
  裁掉的带**不响应**、可见带可点；源码守卫（侧栏不得再出现 `panel_info.button_rect = rect`、
  释放处理里不得出现 `button_rect`/`_panels.items()`）。
  其中「视口裁剪」那例的矩形数据原本写错（`Rectangle(0, -40, ...)` 与视口 `[110, 710)` 完全不相交，
  注释要的是「上沿之上 40 px」），已修正为 `y = 70`（= 110 − 40），该例此前一直失败。

### 9/19 的另一半（Carrot 顶部标签栏）为什么没恢复
- `carrot_tuning.py` 在上游已被重构成**两级页面**：根页是 `Scroller` 里的分组行
  （`CarrotNavRow` + `CarrotGroupKey`），点行进入子页，**顶部标签条已不存在**（全文件无 `tab`/`TabType`）。
- 也就是说「标签栏轮询 `rl.is_mouse_button_pressed` 丢按下沿」这条 bug 随设计一起消失了，无需恢复；
  旧的 `tab_index_at` 相关测试也已随该实现作废（本次未再放回）。

### 验证
- `python -m unittest selfdrive.ui.tests.test_settings_touch_hit_test -v` → **4/4 通过**。
- `ruff check` 两个改动文件 → All checks passed。
- `ruff check --select TID251 selfdrive/ui system/ui` → 仅剩 3 条：`sunnypilot/lib/drive_stats.py` 的
  `time.time`（既有、与本次无关），以及 `sunnypilot/layouts/settings/bluetooth_settings.py:802`
  在渲染里手写 `rl.is_mouse_button_pressed`（Carrot 映射编辑器「Use Carrot mapping」开关）——
  同类「丢按下沿」风险，属遗留项，本次未动。
- 生效条件：UI 是常驻进程，需重启 ui / 设备后生效。

### 残留（影响小，未在本次处理）
- `CarrotNavRow._handle_mouse_release()` 用 `self._rect` 而非 `_hit_rect`：被视口裁掉的那条带里
  释放也会触发（同一条行内，不会跨行）。
- `OptionControlSP`（+/-）与 `MultipleButtonAction` 仍按释放点决定子控件：按下后手指滑过分界会
  选到另一个方向/选项（同一行内）。
- 蓝牙映射编辑器那个手写开关（见上）。

### 与远程的关系
- `macanlong-test` ↔ `origin/macanlong-test`（FOREVERZAX1988/openpilot）：本次提交前 HEAD 已一致
  （`590950e4aa`），本次提交后推送。
- 上游 `mouxan/test`、`mouxan/master-c3` 各多 1 个提交 `587ed051fb`
  （`fix(launch): install pyserial before the AGNOS updater ...`，首启缺 pyserial 会让更新器崩在
  `No module named serial`）——我们**没有**这个修复（`launch_chffrplus.sh` 里无 `pyserial`）。
  建议按上游原意 cherry-pick 而不是整分支 merge（这次就是 merge 把触摸修复带回去的）。
