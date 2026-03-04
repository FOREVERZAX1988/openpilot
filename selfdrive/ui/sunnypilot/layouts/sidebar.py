"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import pyray as rl
import time
import statistics
from dataclasses import dataclass
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr_noop


PING_TIMEOUT_NS = 80_000_000_000  # 80 seconds in nanoseconds
METRIC_HEIGHT = 126
METRIC_MARGIN = 30
METRIC_START_Y = 300
HOME_BTN = rl.Rectangle(60, 860, 180, 180)


# Color scheme
class Colors:
  WHITE = rl.WHITE
  WHITE_DIM = rl.Color(255, 255, 255, 85)
  GRAY = rl.Color(84, 84, 84, 255)

  # Status colors
  GOOD = rl.WHITE
  WARNING = rl.Color(218, 202, 37, 255)
  DANGER = rl.Color(201, 34, 49, 255)
  PROGRESS = rl.Color(0, 134, 233, 255)
  DISABLED = rl.Color(128, 128, 128, 255)

  # UI elements
  METRIC_BORDER = rl.Color(255, 255, 255, 85)
  BUTTON_NORMAL = rl.WHITE
  BUTTON_PRESSED = rl.Color(255, 255, 255, 166)


@dataclass(slots=True)
class MetricData:
  label: str
  value: str
  color: rl.Color

  def update(self, label: str, value: str, color: rl.Color):
    self.label = label
    self.value = value
    self.color = color


class SidebarSP:
  def __init__(self):
    # 初始化CPU使用率状态（替换原Sunnylink）
    self._cpu_usage_status = MetricData(tr_noop("CPU%"), "0.0%", Colors.GOOD)

  def _update_cpu_usage_status(self):
    """更新CPU使用率状态，保留1位小数，根据使用率设置颜色"""
    # 从ui_state获取deviceState中的CPU使用率数据
    sm = ui_state.sm
    if not sm.updated.get('deviceState'):
      return

    device_state = sm['deviceState']
    cpu_loads = device_state.cpuUsagePercent

    # 修复：适配capnp列表类型，正确读取CPU使用率
    try:
      # 将capnp列表转为普通float列表
      cpu_loads_list = [float(load) for load in cpu_loads]
      if len(cpu_loads_list) > 0:
        cpu_usage = statistics.mean(cpu_loads_list)
      else:
        cpu_usage = 0.0
    except (TypeError, AttributeError):
      # 极端情况（无数据）下默认0.0
      cpu_usage = 0.0

    # 格式化：保留1位小数
    cpu_value = f"{cpu_usage:.1f}%"

    # 根据使用率设置颜色
    if cpu_usage >= 85.0:
      color = Colors.DANGER       # 高使用率 - 红色
    elif cpu_usage >= 70.0:
      color = Colors.WARNING      # 中高使用率 - 黄色
    else:
      color = Colors.GOOD         # 正常使用率 - 白色

    self._cpu_usage_status.update(tr_noop("CPU%"), cpu_value, color)

  # 兼容原有调用，重命名原sunnylink方法为CPU使用率更新
  _update_sunnylink_status = _update_cpu_usage_status

  def _draw_metrics_w_sunnylink(self, rect: rl.Rectangle, _temp, _panda, _connect):
    # 核心修改：调整显示顺序为 CPU温度→CPU使用率→RAM使用率→PANDA状态
    metrics = [_temp, self._cpu_usage_status, _connect, _panda]
    start_y = int(rect.y) + METRIC_START_Y
    available_height = max(0, int(HOME_BTN.y) - METRIC_MARGIN - METRIC_HEIGHT - start_y)
    spacing = available_height / max(1, len(metrics) - 1)

    return metrics, start_y, spacing
