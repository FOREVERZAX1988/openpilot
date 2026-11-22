#!/usr/bin/env python3
"""Macan 车距档真值同步：selfdrived 读 /data/params/d/MacanStockGap 的边界与节流。

背景（2026-11-22）：LongitudinalPersonality 以前靠数 buttonEvents 推档位。漏一个
按键、或被 carstate 的 create_button_events 过滤掉，计数器就和仪表永久差一格，
风格也就一直错。改成读 opendbc carstate 写出的真值文件（按键自跟踪 + ACC_02
ACC_Gesetzte_Zeitluecke 纠偏之后的合并结果）。

走普通文件而不是 Params：Params 的 key 表白名单编译进 libparams_c 的 C++ 扩展，
设备上没有 scons，新增 key 要重刷才能用。

失败必须降级、不能崩：文件缺失 / 内容不是 1-4 的整数时返回 None，调用方退回
按键推导。这条路径没有实车也能测，所以固定在这里防回归。
"""

import os
import unittest

from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD

GAP_FILE = "/data/params/d/MacanStockGap"


class _Sm:
  def __init__(self):
    self.frame = 0


class _Harness:
  """只挂 _read_stock_gap 需要的三个属性，避免实例化整个 SelfdriveD（它有 sockets、Params）。"""

  _read_stock_gap = SelfdriveD._read_stock_gap

  def __init__(self):
    self.sm = _Sm()
    self._stock_gap_frame = -10
    self._stock_gap_cached = None


class TestMacanStockGapRead(unittest.TestCase):

  def setUp(self):
    # 这个文件同时是生产路径，跑完要还原，别把车的档位状态改掉
    self._saved = None
    if os.path.exists(GAP_FILE):
      with open(GAP_FILE) as f:
        self._saved = f.read()

  def tearDown(self):
    if self._saved is None:
      if os.path.exists(GAP_FILE):
        os.remove(GAP_FILE)
    else:
      with open(GAP_FILE, "w") as f:
        f.write(self._saved)

  def _write(self, text):
    with open(GAP_FILE, "w") as f:
      f.write(text)

  def _fresh(self, frame=0):
    h = _Harness()
    h.sm.frame = frame
    return h

  def test_valid_bars_round_trip(self):
    """1-4 格都是合法值，映射到 personality 时各有归宿。"""
    for bar in (1, 2, 3, 4):
      self._write(str(bar))
      self.assertEqual(self._fresh()._read_stock_gap(), bar, f"bar={bar}")

  def test_out_of_range_is_none(self):
    """0 格/5 格等非法档必须是 None，不能把风格推到映射表外。"""
    for text in ("0", "5", "9", "-1"):
      self._write(text)
      self.assertIsNone(self._fresh()._read_stock_gap(), f"text={text}")

  def test_garbage_is_none(self):
    """空文件、非数字、浮点、纯空白都走 OSError/ValueError 分支。"""
    for text in ("", "abc", "3.5", " "):
      self._write(text)
      self.assertIsNone(self._fresh()._read_stock_gap(), f"text={repr(text)}")

  def test_missing_file_is_none(self):
    """carstate 还没写（ACC 未上电 / 冷启动）时必须返回 None 而不是抛。"""
    if os.path.exists(GAP_FILE):
      os.remove(GAP_FILE)
    self.assertIsNone(self._fresh()._read_stock_gap())

  def test_throttled_to_ten_frames(self):
    """100ms 节流：帧数增量不足 10 时不重读，返回上次缓存值。"""
    self._write("4")
    h = self._fresh(frame=100)
    self.assertEqual(h._read_stock_gap(), 4)

    self._write("1")            # 文件变了
    h.sm.frame = 105            # 但只过了 5 帧
    self.assertEqual(h._read_stock_gap(), 4, "10 帧节流内不应重读文件")

    h.sm.frame = 110            # 满 10 帧
    self.assertEqual(h._read_stock_gap(), 1, "满 10 帧后应读到新值")

  def test_recovers_after_missing(self):
    """一度缺失返回 None，文件出现后应能恢复，不能永久卡在 None。"""
    if os.path.exists(GAP_FILE):
      os.remove(GAP_FILE)
    h = self._fresh(frame=0)
    self.assertIsNone(h._read_stock_gap())

    self._write("2")
    h.sm.frame = 20
    self.assertEqual(h._read_stock_gap(), 2)


if __name__ == "__main__":
  unittest.main()
