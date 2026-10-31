"""Blendful 开关在「runner 不支持」时的抖动回归。

背景（2026-10-31 用户实测）：选回默认模型 CD210 时，Lane Center Assist 显示灰色关闭，
但开关每 0.5 秒来回跳一次。

根因：`toggle_item_sp(..., param="Blendful")` 建的 ToggleSP **自己拥有**这个 param，
`sync()` 每 SYNC_INTERVAL 从 params 重读一次，`stored != self._state` 就 set_state(stored)。
而 models.py 每帧在 runner 不支持时强制 `set_state(False)`，但 params 里 Blendful 仍是 1：

    每帧   -> set_state(False)          显示关
    每0.5s -> sync() 读到 1 -> set_state(True)  跳到开
    下一帧 -> set_state(False)          跳回关

修法：不支持期间 `set_sync_paused(True)`，让 sync 不再把存储值拉回来。
"""
import time

from openpilot.system.ui.sunnypilot.widgets import toggle as toggle_mod
from openpilot.system.ui.sunnypilot.widgets.toggle import ToggleSP


class _FakeParams:
  def __init__(self, values):
    self.values = values

  def get_bool(self, key):
    return bool(self.values.get(key, False))


def _make(monkeypatch, stored: bool) -> ToggleSP:
  monkeypatch.setattr(toggle_mod, "unified_params", _FakeParams({"Blendful": stored}))
  return ToggleSP(initial_state=stored, param="Blendful")


def test_sync_undoes_a_forced_off_switch(monkeypatch):
  """不暂停时，强制关闭会被下一次 sync 拉回存储值 —— 这就是用户看到的抖动。"""
  t = _make(monkeypatch, stored=True)
  far = time.monotonic() + 10.0

  t.set_state(False)                    # 模拟 models.py 每帧的强制关闭
  assert t.get_state() is False

  moved = t.sync(now=far)               # 0.5s 后 ToggleSP 自己重读存储
  assert moved is True
  assert t.get_state() is True, "sync 应该把开关拉回 params 里的值（复现抖动）"


def test_paused_sync_leaves_the_switch_off(monkeypatch):
  """暂停后，强制关闭保持关闭 —— 修复后的行为。"""
  t = _make(monkeypatch, stored=True)
  far = time.monotonic() + 10.0

  t.set_sync_paused(True)               # models.py 在 runner 不支持时做这个
  t.set_state(False)

  assert t.sync(now=far) is False, "暂停后 sync 不应再动开关"
  assert t.get_state() is False

  # 再跑几轮，确认它不会「过一会儿又跳回来」
  for _ in range(5):
    t.set_state(False)
    assert t.sync(now=far) is False
    assert t.get_state() is False


def test_resuming_sync_restores_the_stored_value(monkeypatch):
  """切回支持 Blendful 的模型后，恢复同步应该重新采纳存储值。"""
  t = _make(monkeypatch, stored=True)
  far = time.monotonic() + 10.0

  t.set_sync_paused(True)
  t.set_state(False)
  assert t.sync(now=far) is False

  t.set_sync_paused(False)              # runner 又支持了
  assert t.sync(now=far) is True
  assert t.get_state() is True, "恢复同步后应重新采纳 params 里仍是 1 的 Blendful"
