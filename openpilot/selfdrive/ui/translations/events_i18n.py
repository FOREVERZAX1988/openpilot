"""events alert 文案的中英 msgid 映射（i18n 迁移的单一数据源）。

上游 mouxa/test 把官方英文 alert 文案直接汉化成中文写死在三个 events 文件里，
导致 tr() 查 po 表时永远 miss，LanguageSetting 切成任何语言都显示中文。

本表把这批文案还原为英文 msgid（英文原文优先取 git 历史里的 commaai 版本
4c7439c598 / af6622c310），中文原文逐字保留为 zh-CHS / zh-CHT 的 msgstr。

被三个工具消费：
  - ai/tools/apply_events_i18n.py  每轮上游合并后把中文重放成英文 msgid
  - update_translations.py         merge_po 之后补回这些 msgid，避免被清理
  - boot_smoke_test.py             校验 events 源码不含硬编码中文、po 覆盖完整

注意 TPL_MAP 的占位符必须与中文模板数量一致；multilang.tr() 的模板回退
会把运行时拼好的字符串按这些 msgid 反查，并对捕获组再做一次 tr()。
"""

# 静态文案：中文原文 -> 英文 msgid
CONST_MAP: dict[str, str] = {
  "AEB：可能发生碰撞": "AEB: Possible Collision",
  "CAN总线断开连接": "CAN Bus Disconnected",
  "CAN总线断开连接：可能电缆故障": "CAN Bus Disconnected: Likely Cable Fault",
  "CAN总线断开连接：请检查连接": "CAN Bus Disconnected: Check Connections",
  "CAN总线错误：请检查连接": "CAN Error: Check Connections",
  "CAN错误：请开启 CameraSCC": "CAN Error: Enable CameraSCC",
  "CPU使用率过高": "High CPU Usage",
  "Carrot：信号灯状态变化": "Carrot: Traffic Light State Changed",
  "Carrot：准备停车": "Carrot: Preparing to Stop",
  "Carrot：识别到绿灯": "Carrot: Green Light Detected",
  "Chill 模式已关闭": "Chill Mode Off",
  "Chill 模式已开启": "Chill Mode On",
  "LKAS 已关闭": "LKAS Off",
  "LKAS故障：请重启车辆": "LKAS Fault: Restart Car",
  "LKAS故障：重启车辆以启用": "LKAS Fault: Restart Car to Engage",
  "NNFF 扭矩模型已加载": "NNFF Torque Model Loaded",
  "Posenet速度无效": "Posenet Speed Invalid",
  "USB错误：请重启设备": "USB Error: Restart Device",
  "locationd临时错误": "locationd Temporary Error",
  "paramsd 临时错误": "paramsd Temporary Error",
  "sunnypilot 不可用": "sunnypilot Unavailable",
  "sunnypilot 将解除控制": "sunnypilot will disengage",
  "sunnypilot已取消": "sunnypilot Cancelled",
  "不支持车辆的行车记录仪模式": "Dashcam Mode Unsupported for Vehicle",
  "书签已保存": "Bookmark Saved",
  "书签需要先配对设备": "Bookmark Requires Paired Device",
  "仅行车记录仪模式": "Dashcam Mode Only",
  "传感器数据无效": "Sensor Data Invalid",
  "使用小模型行驶": "Driving with Small Model",
  "倒档": "Reverse",
  "倒车中": "Reversing",
  "停车制动已启用": "Park Brake Engaged",
  "公里/时": "km/h",
  "内存不足": "Low Memory",
  "内存不足：请重启设备": "Low Memory: Restart Device",
  "减速以进行接合": "Slow Down to Engage",
  "分心过度": "Too Distracted",
  "制动保持已激活": "Brake Hold Active",
  "刹车！": "BRAKE!",
  "剩余 30 秒。再次按下可提前保存。": "30 Seconds Left. Press Again to Save Early.",
  "原厂AEB：可能发生碰撞": "Stock AEB: Possible Collision",
  "取消按钮被按下": "Cancel Button Pressed",
  "变道不可用：道路边缘": "Lane Change Unavailable: Road Edge",
  "可能发生碰撞": "Possible Collision",
  "可能是硬件问题": "Likely Hardware Issue",
  "右转": "Turn Right",
  "启用主开关以接合": "Enable Main Switch to Engage",
  "启用自适应巡航以接合": "Enable Adaptive Cruise to Engage",
  "在此速度下模型不稳定": "Model Unstable at This Speed",
  "大模型已就绪": "Big Model Ready",
  "大模型已接管": "Big Model Engaged",
  "大模型已断开": "Big Model Disconnected",
  "存储空间不足": "Out of Storage",
  "安全密钥不可用": "Safety Key Unavailable",
  "安全带未系": "Seatbelt Unfastened",
  "巡航已关闭": "Cruise Off",
  "巡航故障：请重启车辆": "Cruise Fault: Restart Car",
  "巡航故障：重启车辆以启用": "Cruise Fault: Restart Car to Engage",
  "左转": "Turn Left",
  "恢复": "restore",
  "按恢复键以解除停止状态": "Press Resume to Exit Stop State",
  "按恢复键以解除制动保持": "Press Resume to Release Brake Hold",
  "挡位不在D挡": "Gear Not in Drive",
  "接管": "Take Over",
  "接管控制": "Take Control",
  "控制不匹配": "Controls Mismatch",
  "控制不匹配：横向": "Controls Mismatch: Lateral",
  "摄像头帧率低": "Low Camera Frame Rate",
  "摄像头帧率低：请重启设备": "Low Camera Frame Rate: Restart Device",
  "摄像头总线检测到 SCC": "SCC Detected on Camera Bus",
  "摄像头故障": "Camera Malfunction",
  "摄像头故障：请重启设备": "Camera Malfunction: Restart Device",
  "操纵杆模式": "Joystick Mode",
  "方向盘被转动": "Steering Wheel Turned",
  "无效的LKAS设置": "Invalid LKAS setting",
  "智能/自适应巡航：已关闭": "Smart/Adaptive Cruise: Off",
  "未配对设备": "Device Not Paired",
  "标准": "Normal",
  "标准LKAS：车道偏离检测": "Stock LKAS: Lane Departure Detection",
  "校准": "Calibration",
  "校准中": "Calibrating",
  "校准无效": "Calibration Invalid",
  "校准无效：重新安装设备并重新校准": "Calibration Invalid: Remount Device and Recalibrate",
  "校准未完成": "Calibration Incomplete",
  "校准进行中": "Calibration in Progress",
  "检查硬件": "Check Hardware",
  "横向已停用": "Lateral Disabled",
  "横向演习模式": "Lateral Maneuver Mode",
  "正在变道": "Changing Lanes",
  "正在右转": "Turning Right",
  "正在左转": "Turning Left",
  "正在录制音频反馈": "Recording Audio Feedback",
  "正在自动调整至上次限速": "Adjusting to Previous Speed Limit",
  "正在调整至限速": "Adjusting to Speed Limit",
  "注意前方物体": "Object Ahead",
  "激进": "Aggressive",
  "电子稳定控制系统已禁用": "ESC Disabled",
  "电子稳定控制系统激活中": "ESC Active",
  "电池电量低": "Low Battery",
  "监测偏离车道": "Lane Departure Detected",
  "盲区检测到车辆": "Vehicle in Blind Spot",
  "盲点检测到车辆": "Blind Spot Vehicle Detected",
  "确保前方道路畅通": "Ensure Road Ahead Is Clear",
  "确认变道": "Confirm Lane Change",
  "立即接管控制": "TAKE CONTROL IMMEDIATELY",
  "立即解除控制": "DISENGAGE IMMEDIATELY",
  "等待转向就绪": "Waiting for Steer Ready",
  "系统初始化中": "System Initializing",
  "系统滞后": "System Lagging",
  "系统过热": "System Overheated",
  "紧急制动：可能发生碰撞": "Emergency Braking: Possible Collision",
  "纵向操作模式": "Longitudinal Maneuver Mode",
  "线束继电器故障": "Harness Relay Fault",
  "自动车道居中已关闭": "Auto Lane Centering Off",
  "自适应巡航已禁用": "Adaptive Cruise Disabled",
  "自驾车进程滞后：请重启设备": "selfdrive Processes Lagging: Restart Device",
  "舒适": "Relaxed",
  "英里/时": "mph",
  "行车记录仪模式": "Dashcam Mode",
  "行驶以校准": "Drive to Calibrate",
  "触摸方向盘": "Touch Steering Wheel",
  "触摸方向盘：未检测到面部": "Touch Steering Wheel: Face Not Detected",
  "警告：此分支未经测试": "WARNING: This branch is not tested",
  "设备从支架掉落": "Device Fell Off Mount",
  "设备重新安装检测到：重新校准中": "Device Remount Detected: Recalibrating",
  "请切换到交通感知巡航控制以启用": "Switch to Traffic-Aware Cruise Control to engage",
  "请切换原厂LKAS状态以启用": "Toggle stock LKAS on or off to engage",
  "请启用您的车辆LKAS以启用": "Enable your car's LKAS to engage",
  "请始终将手放在方向盘上，眼睛注视道路": "Always keep hands on wheel and eyes on road",
  "请手动继续驾驶": "Continue Driving Manually",
  "请按设定键以启用": "Press Set to Engage",
  "请接管": "Please Take Over",
  "请接管控制": "Please Take Control",
  "请确认前方并准备减速": "Confirm Road Ahead and Prepare to Slow",
  "请确认安全后进行右转变道": "Confirm Safe Before Right Lane Change",
  "请确认安全后进行左转变道": "Confirm Safe Before Left Lane Change",
  "请禁用您的车辆原厂LKAS以启用": "Disable your car's stock LKAS to engage",
  "请重启设备": "Restart Device",
  "请随时准备接管您的车辆控制权": "Always Be Ready to Take Control",
  "踏板被按下": "Pedal Pressed",
  "车辆传感器无效": "Vehicle Sensors Invalid",
  "车辆传感器校准中": "Vehicle Sensors Calibrating",
  "车辆未识别": "Vehicle Not Recognized",
  "车辆转向时间限制": "Vehicle Steering Time Limit",
  "车道保持辅助系统（LKAS）设置无效": "Lane Keeping Assist System (LKAS) Setting Invalid",
  "车门开启": "Door Open",
  "转向传动比不匹配": "Steer ratio mismatch",
  "转向暂时不可用": "Steer Temporarily Unavailable",
  "转向系统未对准": "Steering misalignment detected",
  "转向被 panda 安全机制阻止": "Steering Blocked by panda Safety",
  "转向超出限制": "Steering Exceeds Limit",
  "转向超过限制": "Steer Beyond Limit",
  "轮胎刚度异常": "Abnormal tire stiffness",
  "过度操作": "Excessive Steering Input",
  "进程未运行": "Process Not Running",
  "进程间通信速率低": "Low IPC Rate",
  "进程间通信问题": "Communication Issue Between Processes",
  "速度过低": "Speed Too Low",
  "速度过高": "Speed Too High",
  "释放制动以启用": "Release Brake to Engage",
  "重启进入行车记录仪模式": "Reboot to Dashcam Mode",
  "重新接管以切换": "Resume to Switch",
  "重新校准": "Recalibration",
  "限速已变化": "Speed Limit Changed",
  "雷达暂时不可用": "Radar Temporarily Unavailable",
  "雷达错误：请重启车辆": "Radar Error: Restart Car",
  "需要手动控制车速": "Manual Speed Control Required",
  "需要手动转向": "Manual Steering Required",
  "风扇故障": "Fan Malfunction",
  "驾驶员分心": "Driver Distracted",
  "驾驶员无响应": "Driver Unresponsive",
  "驾驶模型滞后": "Driving Model Lagging",
  "请注意": "Pay Attention",
  "请注意路况后再启用": "Pay Attention to Engage",
  # sunnypilot/selfdrive/selfdrived/events_zp.py 的 alert 文案（原判据漏掉的文件）
  "纵向控制初始化中": "Longitudinal Control Initializing",
  "请保持停车": "Please Remain Stopped",
  "停车以启用纵向控制": "Stop to Enable Longitudinal Control",
  "Alpha 纵向将在下次停车时接管": "Alpha Longitudinal Will Engage at Next Stop",
  "请关闭原厂巡航": "Disable Stock Cruise Control",
  "Alpha 纵向正在等待": "Alpha Longitudinal Waiting",
  "纵向控制交还中": "Returning Longitudinal Control",
  "完成后恢复原厂巡航": "Stock Cruise Will Resume When Complete",
  "纵向控制初始化失败": "Longitudinal Control Initialization Failed",
  "重启车辆以重试": "Restart Car to Retry",
  "踩油门保持当前速度": "Press Gas to Maintain Current Speed",
  "前方路缘": "Road Edge Ahead",
  "无法变道：前方路缘": "Lane Change Unavailable: Road Edge Ahead",
  "转向被 Panda 安全机制拦截": "Steering Intercepted by panda Safety",
  "Alpha 纵向已就绪": "Alpha Longitudinal Ready",
  "原厂 AEB 已关闭": "Stock AEB Off",
  "原厂巡航失败": "Stock Cruise Fault",
  "请重启车辆": "Restart Car",
  "请重新安装设备": "Remount Device",
  "转向在": "Steer Unavailable Below",
  "限速辅助：请将设定速度调至": "Speed Limit Assist: Set Speed to",
  "按 + 键调至": "Press + to Set",
  "按 - 键调至": "Press - to Set",
  "正在进行中": "in Progress",
  "速度误差": "Speed Error",
  "米/秒": "m/s",
  "摄氏度": "°C",
  "已用": "used",
  "已丢帧": "frames dropped",
  "剩余": "Left",
  "分钟": "Minutes",
  "驾驶风格": "Driving Personality",
  "油门": "Gas",
  "转向": "Steer",
  "度": "°",
  "偏航角": "Yaw",
  "俯仰角": "Pitch",
  "偏移量": "Offset",
  "系数": "Factor",
  "传动比": "Ratio",
  "角度偏移过大": "Angle offset too high",
  "转向齿条几何可能不正确": "Steering rack geometry may be off",
  "请检查轮胎、胎压或定位": "Check tires, pressure, or alignment",
  "替代模型": "Fuzzy Model",
  "以启用": "to Enable",
  "来启用": "to engage",
  "进行校准": "to Calibrate",
  "以下不可用": "Unavailable Below",
}

# 动态文案：中文模板（f-string 的 {} 占位符）-> 英文 msgid 模板。
# 运行时源码产出的是拼好数值的英文句子，multilang.tr() 用这些模板反查，
# 把数值代回中文 msgstr，因此中文界面逐字不变。
TPL_MAP: dict[str, str] = {
  "速度误差: {:.1f} 米/秒": "Speed Error: {:.1f} m/s",
  "请重新安装设备 (俯仰角: {:.1f}度, 偏航角: {:.1f}度)": "Remount Device (Pitch: {:.1f}°, Yaw: {:.1f}°)",
  "油门: {}%, 转向: {}%": "Gas: {}%, Steer: {}%",
  "请将时速提高至 {} 来启用": "Drive above {} to engage",
  "转向在 {} 以下不可用": "Steer Unavailable Below {}",
  "{}进行中：{:.0f}%": "{} in Progress: {:.0f}%",
  "请将时速提高至 {} 进行校准": "Drive above {} to Calibrate",
  "剩余 {} 分钟": "{} Minutes Left",
  "已用 {}%": "Used: {}%",
  "角度偏移过大 (偏移量: {:.1f}度)": "Angle offset too high (Offset: {:.1f}°)",
  "{:.0f} 摄氏度": "{:.0f} °C",
  "已丢帧 {:.1f}%": "Frames Dropped: {:.1f}%",
  "驾驶风格: {}": "Driving Personality: {}",
  "{}（替代模型）": "{} (Fuzzy Model)",
  "转向齿条几何可能不正确 (传动比: {:.1f})": "Steering rack geometry may be off (Ratio: {:.1f})",
  "请检查轮胎、胎压或定位 (系数: {:.1f})": "Check tires, pressure, or alignment (Factor: {:.1f})",
  "正在调整至限速{}{}": "Adjusting to Speed Limit{}{}",
  "限速辅助：请将设定速度调至 {} {} 以启用": "Speed Limit Assist: Set Speed to {} {} to Enable",
  "按 + 键调至\n{}": "Press + to Set\n{}",
  "按 - 键调至\n{}": "Press - to Set\n{}",
}

# 少数中文常量只作为 f-string 片段出现，单独给英文片段，
# 让 apply_events_i18n.py 能把整条 f-string 逐段还原成英文模板。
FRAG_MAP: dict[str, str] = {
  "速度误差: ": "Speed Error: ",
  " 米/秒": " m/s",
  "请重新安装设备 (俯仰角: ": "Remount Device (Pitch: ",
  "度, 偏航角: ": "°, Yaw: ",
  "度)": "°)",
  "油门: ": "Gas: ",
  "%, 转向: ": "%, Steer: ",
  "请将时速提高至 ": "Drive above ",
  " 来启用": " to engage",
  "转向在 ": "Steer Unavailable Below ",
  " 以下不可用": "",
  "进行中：": " in Progress: ",
  " 进行校准": " to Calibrate",
  "剩余 ": "",
  " 分钟": " Minutes Left",
  "已用 ": "Used: ",
  "已丢帧 ": "Frames Dropped: ",
  " 摄氏度": " °C",
  "角度偏移过大 (偏移量: ": "Angle offset too high (Offset: ",
  "转向齿条几何可能不正确 (传动比: ": "Steering rack geometry may be off (Ratio: ",
  "请检查轮胎、胎压或定位 (系数: ": "Check tires, pressure, or alignment (Factor: ",
  "驾驶风格: ": "Driving Personality: ",
  "（替代模型）": " (Fuzzy Model)",
  "限速辅助：请将设定速度调至 ": "Speed Limit Assist: Set Speed to ",
  " 以启用": " to Enable",
  "正在调整至限速": "Adjusting to Speed Limit",
  "按 + 键调至\n": "Press + to Set\n",
  "按 - 键调至\n": "Press - to Set\n",
}

# f-string 片段拼出来的英文句子 -> 对应中文模板（供 po 注入与 tr 模板回退）。
# key 由 apply_events_i18n.py 在转换 f-string 时按 FRAG_MAP 拼接得到。
def po_entries() -> list[tuple[str, str]]:
  """返回需要写入中文 po 的 (msgid, msgstr) 条目，按 msgid 去重。"""
  entries: dict[str, str] = {}
  for zh, en in CONST_MAP.items():
    entries.setdefault(en, zh)
  for zh_tpl, en_tpl in TPL_MAP.items():
    entries.setdefault(en_tpl, zh_tpl)
  return sorted(entries.items())


def inject_po(po_path: str, language: str) -> tuple[int, int]:
  """把 events msgid 补进中文 po 并对齐译文。返回 (新增, 改译文)。

  映射表里的中文是 fork 汉化的原文，优先于 po 里已有的官方译文：例如官方
  po 把 "km/h" 翻成 "km/h"、"Relaxed" 翻成「从容」，而 fork 显示的是
  「公里/时」「舒适」。不覆盖会让中文界面在迁移后悄悄变字。
  """
  import os
  import re

  def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

  def unesc(s: str) -> str:
    return (s.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\"))

  with open(po_path, encoding="utf-8") as f:
    content = f.read()

  # 清掉本工具以前注入、但已从映射表删除的条目（例如改过占位符的模板），
  # 保证每轮重放幂等，不会在 po 里堆积废弃 msgid。
  valid = {esc(mid) for mid, _ in po_entries()}
  stale_block = re.compile(
    r'\n#: events i18n migration\nmsgid "((?:[^"\\]|\\.)*)"\nmsgstr "(?:[^"\\]|\\.)*"\n'
  )
  content = stale_block.sub(lambda m: m.group(0) if m.group(1) in valid else "", content)

  # 解析现有 msgid -> msgstr（含空译文），用于判断是否需要补。
  # po 里换行/引号是转义的，必须先还原成真实字符串再和映射表比较。
  existing: dict[str, str] = {}
  for m in re.finditer(r'msgid "((?:[^"\\]|\\.)*)"\nmsgstr "((?:[^"\\]|\\.)*)"', content):
    existing.setdefault(unesc(m.group(1)), m.group(2))

  added = filled = 0
  missing = [(mid, mst) for mid, mst in po_entries() if mid not in existing]
  stale = [(mid, mst) for mid, mst in po_entries()
           if mid in existing and existing[mid] != mst and language in ("zh-CHS", "zh-CHT")]

  for mid, mst in stale:
    old = f'msgid "{esc(mid)}"\nmsgstr "{esc(existing[mid])}"'
    new = f'msgid "{esc(mid)}"\nmsgstr "{esc(mst)}"'
    if old in content:
      content = content.replace(old, new, 1)
      filled += 1
    else:
      # 多行 msgstr 等非常规格式：用正则按 msgid 定位后替换紧随的 msgstr
      pattern = re.compile(r'(msgid "' + re.escape(esc(mid)) + r'"\nmsgstr )"(?:[^"\\]|\\.)*"')
      content, n = pattern.subn(lambda m: m.group(1) + '"' + esc(mst) + '"', content, count=1)
      filled += n

  if missing:
    block = "\n".join(
      f'\n#: events i18n migration\nmsgid "{esc(mid)}"\nmsgstr "{esc(mst) if language in ("zh-CHS", "zh-CHT") else ""}"\n'
      for mid, mst in missing
    )
    if not content.endswith("\n"):
      content += "\n"
    content += "# events i18n: 由 openpilot/selfdrive/ui/translations/events_i18n.py 维护\n" + block
    added += len(missing)

  if added or filled:
    with open(po_path, "w", encoding="utf-8") as f:
      f.write(content)
  return added, filled
