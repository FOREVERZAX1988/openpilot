#!/usr/bin/env python3
import math
import os

from cereal import log, car
import cereal.messaging as messaging
from openpilot.common.constants import CV
from openpilot.common.git import get_short_branch
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.locationd.calibrationd import MIN_SPEED_FILTER
from openpilot.system.micd import SAMPLE_RATE, SAMPLE_BUFFER
from openpilot.selfdrive.ui.feedback.feedbackd import FEEDBACK_MAX_DURATION

from openpilot.sunnypilot.selfdrive.selfdrived.events_base import EventsBase, Priority, ET, Alert, \
  NoEntryAlert, SoftDisableAlert, UserSoftDisableAlert, ImmediateDisableAlert, EngagementAlert, NormalPermanentAlert, \
  StartupAlert, AlertCallbackType, wrong_car_mode_alert


AlertSize = log.SelfdriveState.AlertSize
AlertStatus = log.SelfdriveState.AlertStatus
VisualAlert = car.CarControl.HUDControl.VisualAlert
AudibleAlert = car.CarControl.HUDControl.AudibleAlert
EventName = log.OnroadEvent.EventName


# 从枚举中获取事件名称
EVENT_NAME = {v: k for k, v in EventName.schema.enumerants.items()}


class Events(EventsBase):
  def __init__(self):
    super().__init__()
    self.event_counters = dict.fromkeys(EVENTS.keys(), 0)

  def get_events_mapping(self) -> dict[int, dict[str, Alert | AlertCallbackType]]:
    return EVENTS

  def get_event_name(self, event: int):
    return EVENT_NAME[event]

  def get_event_msg_type(self):
    return log.OnroadEvent



# ********** 辅助函数 **********
def get_display_speed(speed_ms: float, metric: bool) -> str:
  """获取带单位的显示速度"""
  speed = int(round(speed_ms * (CV.MS_TO_KPH if metric else CV.MS_TO_MPH)))
  unit = '公里/小时' if metric else '英里/小时'
  return f"{speed} {unit}"


# ********** 警报回调函数 **********


def soft_disable_alert(alert_text_2: str) -> AlertCallbackType:
  """软禁用警报回调"""
  def func(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
    if soft_disable_time < int(0.5 / DT_CTRL):
      return ImmediateDisableAlert(alert_text_2)
    return SoftDisableAlert(alert_text_2)
  return func

def user_soft_disable_alert(alert_text_2: str) -> AlertCallbackType:
  """用户操作导致的软禁用警报回调"""
  def func(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
    if soft_disable_time < int(0.5 / DT_CTRL):
      return ImmediateDisableAlert(alert_text_2)
    return UserSoftDisableAlert(alert_text_2)
  return func

def startup_master_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """启动主警报"""
  branch = get_short_branch()  # 确保get_short_branch被缓存，避免启动时卡顿
  if "REPLAY" in os.environ:
    branch = "回放模式"

  return StartupAlert("请注意安全，这不是自动驾驶", branch, alert_status=AlertStatus.userPrompt)

def below_engage_speed_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """低于启用速度警报"""
  return NoEntryAlert(f"车速需超过 {get_display_speed(CP.minEnableSpeed, metric)} 才能启用")


def below_steer_speed_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """低于转向速度警报"""
  return Alert(
    f"车速低于 {get_display_speed(CP.minSteerSpeed, metric)} 时转向不可用",
    "",
    AlertStatus.userPrompt, AlertSize.small,
    Priority.LOW, VisualAlert.none, AudibleAlert.prompt, 0.4)


def calibration_incomplete_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """标定未完成警报"""
  first_word = '重新标定' if sm['liveCalibration'].calStatus == log.LiveCalibrationData.Status.recalibrating else '标定'
  return Alert(
    f"{first_word}进行中：{sm['liveCalibration'].calPerc:.0f}%",
    f"请保持车速超过 {get_display_speed(MIN_SPEED_FILTER, metric)}",
    AlertStatus.normal, AlertSize.mid,
    Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .2)


def audio_feedback_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """音频反馈录制警报"""
  duration = FEEDBACK_MAX_DURATION - ((sm['audioFeedback'].blockNum + 1) * SAMPLE_BUFFER / SAMPLE_RATE)
  return NormalPermanentAlert(
    "正在录制音频反馈",
    f"剩余 {round(duration)} 秒{'钟' if round(duration) != 1 else ''}。再次点击可提前保存。",
    priority=Priority.LOW)


# *** 调试警报 ***

def out_of_space_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """存储空间不足警报"""
  full_perc = round(100. - sm['deviceState'].freeSpacePercent)
  return NormalPermanentAlert("存储空间不足", f"已使用 {full_perc}%")


def posenet_invalid_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """Posenet速度无效警报"""
  mdl = sm['modelV2'].velocity.x[0] if len(sm['modelV2'].velocity.x) else math.nan
  err = CS.vEgo - mdl
  msg = f"速度误差：{err:.1f} 米/秒"
  return NoEntryAlert(msg, alert_text_1="Posenet速度无效")


def process_not_running_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """进程未运行警报"""
  not_running = [p.name for p in sm['managerState'].processes if not p.running and p.shouldBeRunning]
  msg = ', '.join(not_running)
  return NoEntryAlert(msg, alert_text_1="进程未运行")


def comm_issue_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """进程间通信异常警报"""
  bs = [s for s in sm.data.keys() if not sm.all_checks([s, ])]
  msg = ', '.join(bs[:4])  # 一行显示不下太多内容
  return NoEntryAlert(msg, alert_text_1="进程间通信异常")


def camera_malfunction_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """摄像头故障警报"""
  all_cams = ('roadCameraState', 'driverCameraState', 'wideRoadCameraState')
  bad_cams = [s.replace('State', '') for s in all_cams if s in sm.data.keys() and not sm.all_checks([s, ])]
  bad_cams_cn = {
    'roadCamera': '前视摄像头',
    'driverCamera': '驾驶员摄像头',
    'wideRoadCamera': '广角前视摄像头'
  }
  bad_cams_display = [bad_cams_cn.get(cam, cam) for cam in bad_cams]
  return NormalPermanentAlert("摄像头故障", ', '.join(bad_cams_display))


def calibration_invalid_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """标定无效警报"""
  rpy = sm['liveCalibration'].rpyCalib
  yaw = math.degrees(rpy[2] if len(rpy) == 3 else math.nan)
  pitch = math.degrees(rpy[1] if len(rpy) == 3 else math.nan)
  angles = f"请重新安装设备（俯仰角：{pitch:.1f}°，偏航角：{yaw:.1f}°）"
  return NormalPermanentAlert("标定无效", angles)


def paramsd_invalid_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """参数服务异常警报"""
  if not sm['liveParameters'].angleOffsetValid:
    angle_offset_deg = sm['liveParameters'].angleOffsetDeg
    title = "检测到转向未对准"
    text = f"角度偏移过大（偏移量：{angle_offset_deg:.1f}°）"
  elif not sm['liveParameters'].steerRatioValid:
    steer_ratio = sm['liveParameters'].steerRatio
    title = "转向比不匹配"
    text = f"转向齿条几何结构可能异常（转向比：{steer_ratio:.1f}）"
  elif not sm['liveParameters'].stiffnessFactorValid:
    stiffness_factor = sm['liveParameters'].stiffnessFactor
    title = "轮胎刚度异常"
    text = f"请检查轮胎、胎压或四轮定位（刚度系数：{stiffness_factor:.1f}）"
  else:
    return NoEntryAlert("参数服务临时错误")

  return NoEntryAlert(alert_text_1=title, alert_text_2=text)

def overheat_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """系统过热警报"""
  cpu = max(sm['deviceState'].cpuTempC, default=0.)
  gpu = max(sm['deviceState'].gpuTempC, default=0.)
  temp = max((cpu, gpu, sm['deviceState'].memoryTempC))
  return NormalPermanentAlert("系统过热", f"{temp:.0f} °C")


def low_memory_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """内存不足警报"""
  return NormalPermanentAlert("内存不足", f"已使用 {sm['deviceState'].memoryUsagePercent}%")


def high_cpu_usage_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """CPU使用率过高警报"""
  x = max(sm['deviceState'].cpuUsagePercent, default=0.)
  return NormalPermanentAlert("CPU使用率过高", f"已使用 {x}%")


def modeld_lagging_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """驾驶模型卡顿警报"""
  return NormalPermanentAlert("驾驶模型运行卡顿", f"丢帧率：{sm['modelV2'].frameDropPerc:.1f}%")


def joystick_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """摇杆模式警报"""
  gb = sm['carControl'].actuators.accel / 4.
  steer = sm['carControl'].actuators.torque
  vals = f"油门：{round(gb * 100.)}%，转向：{round(steer * 100.)}%"
  return NormalPermanentAlert("摇杆模式", vals)


def longitudinal_maneuver_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """纵向操控警报"""
  ad = sm['alertDebug']
  audible_alert = AudibleAlert.prompt if 'Active' in ad.alertText1 else AudibleAlert.none
  alert_status = AlertStatus.userPrompt if 'Active' in ad.alertText1 else AlertStatus.normal
  alert_size = AlertSize.mid if ad.alertText2 else AlertSize.small
  return Alert(ad.alertText1, ad.alertText2,
               alert_status, alert_size,
               Priority.LOW, VisualAlert.none, audible_alert, 0.2)


def personality_changed_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """驾驶风格变更警报"""
  personality_map = {
    log.LongitudinalPersonality.standard: "标准",
    log.LongitudinalPersonality.relaxed: "舒适",
    log.LongitudinalPersonality.aggressive: "激进"
  }
  personality_cn = personality_map.get(personality, str(personality))
  return NormalPermanentAlert(f"驾驶风格：{personality_cn}", duration=1.5)


def invalid_lkas_setting_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  """无效的LKAS设置警报"""
  text = "请开启或关闭原厂车道保持辅助系统以启用"
  if CP.brand == "tesla":
    text = "请切换至交通感知巡航控制模式以启用"
  elif CP.brand == "mazda":
    text = "请启用车辆原厂车道保持辅助系统"
  elif CP.brand == "nissan":
    text = "请关闭车辆原厂车道保持辅助系统"
  return NormalPermanentAlert("无效的车道保持设置", text)



EVENTS: dict[int, dict[str, Alert | AlertCallbackType]] = {
  # ********** 无警报的事件 **********

  EventName.stockFcw: {},  # 原厂前碰撞预警
  EventName.actuatorsApiUnavailable: {},  # 执行器API不可用

  # ********** 所有状态下都显示的警报事件 **********

  EventName.joystickDebug: {  # 摇杆调试模式
    ET.WARNING: joystick_alert,
    ET.PERMANENT: NormalPermanentAlert("摇杆模式"),
  },

  EventName.longitudinalManeuver: {  # 纵向操控模式
    ET.WARNING: longitudinal_maneuver_alert,
    ET.PERMANENT: NormalPermanentAlert("纵向操控模式",
                                       "请确保前方道路畅通"),
  },

  EventName.selfdriveInitializing: {  # 系统初始化中
    ET.NO_ENTRY: NoEntryAlert("系统初始化中"),
  },

  EventName.startup: {  # 启动提示
    ET.PERMANENT: StartupAlert("请随时准备接管车辆控制权")
  },

  EventName.startupMaster: {  # 主启动警报
    ET.PERMANENT: startup_master_alert,
  },

  EventName.startupNoControl: {  # 启动无控制权限
    ET.PERMANENT: StartupAlert("行车记录仪模式"),
    ET.NO_ENTRY: NoEntryAlert("行车记录仪模式"),
  },

  EventName.startupNoCar: {  # 不支持的车辆启动
    ET.PERMANENT: StartupAlert("不支持车辆的行车记录仪模式"),
  },

  EventName.startupNoSecOcKey: {  # 无安全密钥启动
    ET.PERMANENT: NormalPermanentAlert("行车记录仪模式",
                                       "安全密钥不可用",
                                       priority=Priority.HIGH),
  },

  EventName.dashcamMode: {  # 行车记录仪模式
    ET.PERMANENT: NormalPermanentAlert("行车记录仪模式",
                                       priority=Priority.LOWEST),
  },

  EventName.invalidLkasSetting: {  # 无效的LKAS设置
    ET.PERMANENT: invalid_lkas_setting_alert,
    ET.NO_ENTRY: NoEntryAlert("无效的车道保持设置"),
  },

  EventName.cruiseMismatch: {  # 巡航控制不匹配
    #ET.PERMANENT: ImmediateDisableAlert("openpilot未能取消巡航控制"),
  },

  # openpilot无法识别车辆。这会将openpilot切换到
  # 只读模式。此问题可通过添加车辆指纹解决。
  # 更多信息请参见 https://github.com/commaai/openpilot/wiki/Fingerprinting
  EventName.carUnrecognized: {  # 车辆未识别
    ET.PERMANENT: NormalPermanentAlert("行车记录仪模式",
                                       "车辆未识别",
                                       priority=Priority.LOWEST),
  },

  EventName.aeb: {  # 自动紧急制动
    ET.PERMANENT: Alert(
      "立即刹车！",
      "紧急制动：检测到碰撞风险",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.none, 2.),
    ET.NO_ENTRY: NoEntryAlert("自动紧急制动：检测到碰撞风险"),
  },

  EventName.stockAeb: {  # 原厂自动紧急制动
    ET.PERMANENT: Alert(
      "立即刹车！",
      "原厂自动紧急制动：检测到碰撞风险",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.none, 2.),
    ET.NO_ENTRY: NoEntryAlert("原厂自动紧急制动：检测到碰撞风险"),
  },

  EventName.fcw: {  # 前碰撞预警
    ET.PERMANENT: Alert(
      "立即刹车！",
      "检测到碰撞风险",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.warningSoft, 2.),
  },

  EventName.ldw: {  # 车道偏离预警
    ET.PERMANENT: Alert(
      "检测到车道偏离",
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.ldw, AudibleAlert.prompt, 3.),
  },

  # ********** 仅在系统激活时显示的警报事件 **********

  EventName.steerTempUnavailableSilent: {  # 转向临时不可用（静默）
    ET.WARNING: Alert(
      "转向功能暂时不可用",
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.prompt, 1.8),
  },

  EventName.preDriverDistracted: {  # 驾驶员注意力不集中预警
    ET.PERMANENT: Alert(
      "请集中注意力",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.promptDriverDistracted: {  # 驾驶员注意力不集中提示
    ET.PERMANENT: Alert(
      "请集中注意力",
      "驾驶员注意力不集中",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.steerRequired, AudibleAlert.promptDistracted, .1),
  },

  EventName.driverDistracted: {  # 驾驶员注意力严重不集中
    ET.PERMANENT: Alert(
      "立即接管车辆！",
      "驾驶员注意力严重不集中",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.warningImmediate, .1),
  },

  EventName.preDriverUnresponsive: {  # 驾驶员无响应预警
    ET.PERMANENT: Alert(
      "请触摸方向盘：未检测到人脸",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .1),
  },

  EventName.promptDriverUnresponsive: {  # 驾驶员无响应提示
    ET.PERMANENT: Alert(
      "请触摸方向盘",
      "驾驶员无响应",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.steerRequired, AudibleAlert.promptDistracted, .1),
  },

  EventName.driverUnresponsive: {  # 驾驶员完全无响应
    ET.PERMANENT: Alert(
      "立即接管车辆！",
      "驾驶员无响应",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.warningImmediate, .1),
  },

  EventName.manualRestart: {  # 手动重启提示
    ET.WARNING: Alert(
      "请接管控制权",
      "请手动恢复驾驶",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2),
  },

  EventName.resumeRequired: {  # 需要恢复行驶
    ET.WARNING: Alert(
      "请按恢复键退出静止状态",
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2),
  },

  EventName.belowSteerSpeed: {  # 低于转向速度
    ET.WARNING: below_steer_speed_alert,
  },

  EventName.preLaneChangeLeft: {  # 准备向左变道
    ET.WARNING: Alert(
      "确认安全后向左打方向开始变道",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.preLaneChangeRight: {  # 准备向右变道
    ET.WARNING: Alert(
      "确认安全后向右打方向开始变道",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.laneChangeBlocked: {  # 变道被阻挡
    ET.WARNING: Alert(
      "盲区检测到车辆",
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.prompt, .1),
  },

  EventName.laneChange: {  # 变道中
    ET.WARNING: Alert(
      "正在变道",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.steerSaturated: {  # 转向饱和
    ET.WARNING: Alert(
      "请接管控制权",
      "转向角度超出限制",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.promptRepeat, 2.),
  },

  # 风扇转速超过50%但未检测到旋转时触发
  EventName.fanMalfunction: {  # 风扇故障
    ET.PERMANENT: NormalPermanentAlert("风扇故障", "可能是硬件问题"),
  },

  # 摄像头未输出画面
  EventName.cameraMalfunction: {  # 摄像头故障
    ET.PERMANENT: camera_malfunction_alert,
    ET.SOFT_DISABLE: soft_disable_alert("摄像头故障"),
    ET.NO_ENTRY: NoEntryAlert("摄像头故障：请重启设备"),
  },
  # 摄像头帧率过低
  EventName.cameraFrameRate: {  # 摄像头帧率问题
    ET.PERMANENT: NormalPermanentAlert("摄像头帧率过低", "请重启设备"),
    ET.SOFT_DISABLE: soft_disable_alert("摄像头帧率过低"),
    ET.NO_ENTRY: NoEntryAlert("摄像头帧率过低：请重启设备"),
  },

  # 未使用的事件

  EventName.locationdTemporaryError: {  # 定位服务临时错误
    ET.NO_ENTRY: NoEntryAlert("定位服务临时错误"),
    ET.SOFT_DISABLE: soft_disable_alert("定位服务临时错误"),
  },

  EventName.locationdPermanentError: {  # 定位服务永久错误
    ET.NO_ENTRY: NoEntryAlert("定位服务永久错误"),
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("定位服务永久错误"),
    ET.PERMANENT: NormalPermanentAlert("定位服务永久错误"),
  },

  # openpilot通过观察
  # 人类驾驶和openpilot驾驶时车辆对转向输入的响应来学习车辆的某些参数。
  # 包括：
  # - 转向比：转向齿条的传动比，方向盘角度除以轮胎角度
  # - 轮胎刚度：轮胎的抓地力
  # - 角度偏移：大多数转向角度传感器在直行时会测量到非零角度
  # 当这些值超出合理性检查范围时会触发此警报。可能由
  # 四轮定位异常或传感器数据错误导致。如果频繁出现此问题，请在GitHub上提交issue
  EventName.paramsdTemporaryError: {  # 参数服务临时错误
    ET.NO_ENTRY: paramsd_invalid_alert,
    ET.SOFT_DISABLE: soft_disable_alert("参数服务临时错误"),
  },

  EventName.paramsdPermanentError: {  # 参数服务永久错误
    ET.NO_ENTRY: NoEntryAlert("参数服务永久错误"),
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("参数服务永久错误"),
    ET.PERMANENT: NormalPermanentAlert("参数服务永久错误"),
  },

  # ********** 影响控制系统状态转换的事件 **********

  EventName.pcmEnable: {  # PCM启用
    ET.ENABLE: EngagementAlert(AudibleAlert.engage),
  },

  EventName.buttonEnable: {  # 按键启用
    ET.ENABLE: EngagementAlert(AudibleAlert.engage),
  },

  EventName.pcmDisable: {  # PCM禁用
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
  },

  EventName.buttonCancel: {  # 取消按键按下
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryAlert("已按下取消键"),
  },

  EventName.brakeHold: {  # 自动驻车
    ET.WARNING: Alert(
      "请按恢复键退出自动驻车",
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2),
  },

  EventName.parkBrake: {  # 手刹已拉起
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryAlert("驻车制动已启用"),
  },

  EventName.pedalPressed: {  # 踏板被踩下
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryAlert("已踩下踏板",
                              visual_alert=VisualAlert.brakePressed),
  },

  EventName.steerDisengage: {  # 转向接管
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryAlert("已接管转向"),
  },

  EventName.preEnableStandstill: {  # 静止状态准备启用
    ET.PRE_ENABLE: Alert(
      "请松开刹车以启用",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .1, creation_delay=1.),
  },

  EventName.gasPressedOverride: {  # 油门接管
    ET.OVERRIDE_LONGITUDINAL: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.steerOverride: {  # 转向接管
    ET.OVERRIDE_LATERAL: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.wrongCarMode: {  # 错误的车辆模式
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: wrong_car_mode_alert,
  },

  EventName.resumeBlocked: {  # 恢复被阻止
    ET.NO_ENTRY: NoEntryAlert("请按设定键启用"),
  },

  EventName.wrongCruiseMode: {  # 错误的巡航模式
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryAlert("自适应巡航已禁用"),
  },

  EventName.steerTempUnavailable: {  # 转向临时不可用
    ET.SOFT_DISABLE: soft_disable_alert("转向功能暂时不可用"),
    ET.NO_ENTRY: NoEntryAlert("转向功能暂时不可用"),
  },

  EventName.steerTimeLimit: {  # 转向时间限制
    ET.SOFT_DISABLE: soft_disable_alert("车辆转向时间限制已到"),
    ET.NO_ENTRY: NoEntryAlert("车辆转向时间限制已到"),
  },

  EventName.outOfSpace: {  # 存储空间不足
    ET.PERMANENT: out_of_space_alert,
    ET.NO_ENTRY: NoEntryAlert("存储空间不足"),
  },

  EventName.belowEngageSpeed: {  # 低于启用速度
    ET.NO_ENTRY: below_engage_speed_alert,
  },

  EventName.sensorDataInvalid: {  # 传感器数据无效
    ET.PERMANENT: Alert(
      "传感器数据无效",
      "可能是硬件问题",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, .2, creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert("传感器数据无效"),
    ET.SOFT_DISABLE: soft_disable_alert("传感器数据无效"),
  },

  EventName.noGps: {  # 无GPS信号
  },

  EventName.tooDistracted: {  # 注意力分散程度过高
    ET.NO_ENTRY: NoEntryAlert("注意力分散程度过高"),
  },

  EventName.excessiveActuation: {  # 执行器动作过度
    ET.SOFT_DISABLE: soft_disable_alert("执行器动作过度"),
    ET.NO_ENTRY: NoEntryAlert("执行器动作过度"),
  },

  EventName.overheat: {  # 系统过热
    ET.PERMANENT: overheat_alert,
    ET.SOFT_DISABLE: soft_disable_alert("系统过热"),
    ET.NO_ENTRY: NoEntryAlert("系统过热"),
  },

  EventName.wrongGear: {  # 错误的挡位
    ET.SOFT_DISABLE: user_soft_disable_alert("挡位未在D挡"),
    ET.NO_ENTRY: NoEntryAlert("挡位未在D挡"),
  },

  # 当标定角度超出可接受范围时触发此警报。
  # 例如设备向左或向右倾斜过多。
  # 通常需要将设备从挡风玻璃上完全取下，
  # 重新安装并确保设备正对前方且水平。
  # 更多信息请参见 https://comma.ai/setup
  EventName.calibrationInvalid: {  # 标定无效
    ET.PERMANENT: calibration_invalid_alert,
    ET.SOFT_DISABLE: soft_disable_alert("标定无效：请重新安装设备并重新标定"),
    ET.NO_ENTRY: NoEntryAlert("标定无效：请重新安装设备并重新标定"),
  },

  EventName.calibrationIncomplete: {  # 标定未完成
    ET.PERMANENT: calibration_incomplete_alert,
    ET.SOFT_DISABLE: soft_disable_alert("标定未完成"),
    ET.NO_ENTRY: NoEntryAlert("标定进行中"),
  },

  EventName.calibrationRecalibrating: {  # 重新标定中
    ET.PERMANENT: calibration_incomplete_alert,
    ET.SOFT_DISABLE: soft_disable_alert("检测到设备重新安装：正在重新标定"),
    ET.NO_ENTRY: NoEntryAlert("检测到重新安装：正在标定"),
  },

  EventName.doorOpen: {  # 车门打开
    ET.SOFT_DISABLE: user_soft_disable_alert("车门已打开"),
    ET.NO_ENTRY: NoEntryAlert("车门已打开"),
  },

  EventName.seatbeltNotLatched: {  # 安全带未系
    ET.SOFT_DISABLE: user_soft_disable_alert("安全带未系"),
    ET.NO_ENTRY: NoEntryAlert("安全带未系"),
  },

  EventName.espDisabled: {  # 电子稳定程序已禁用
    ET.SOFT_DISABLE: soft_disable_alert("电子稳定控制系统已禁用"),
    ET.NO_ENTRY: NoEntryAlert("电子稳定控制系统已禁用"),
  },

  EventName.lowBattery: {  # 电量低
    ET.SOFT_DISABLE: soft_disable_alert("电量不足"),
    ET.NO_ENTRY: NoEntryAlert("电量不足"),
  },

  # openpilot各服务之间按特定
  # 间隔通信。如果通信未按正常时间表进行，则触发此警报。
  # 可能意味着某个服务崩溃、未按正常间隔的10倍时间广播消息，
  # 或平均间隔超过正常值的10%。
  EventName.commIssue: {  # 通信异常
    ET.SOFT_DISABLE: soft_disable_alert("进程间通信异常"),
    ET.NO_ENTRY: comm_issue_alert,
  },
  EventName.commIssueAvgFreq: {  # 通信频率异常
    ET.SOFT_DISABLE: soft_disable_alert("进程间通信速率过低"),
    ET.NO_ENTRY: NoEntryAlert("进程间通信速率过低"),
  },

  EventName.selfdrivedLagging: {  # 自动驾驶进程卡顿
    ET.SOFT_DISABLE: soft_disable_alert("系统运行卡顿"),
    ET.NO_ENTRY: NoEntryAlert("自动驾驶进程卡顿：请重启设备"),
  },

  # 当管理器检测到某个服务在行驶中意外退出时触发
  EventName.processNotRunning: {  # 进程未运行
    ET.NO_ENTRY: process_not_running_alert,
    ET.SOFT_DISABLE: soft_disable_alert("进程未运行"),
  },

  EventName.radarFault: {  # 雷达故障
    ET.SOFT_DISABLE: soft_disable_alert("雷达错误：请重启车辆"),
    ET.NO_ENTRY: NoEntryAlert("雷达错误：请重启车辆"),
  },

  EventName.radarTempUnavailable: {  # 雷达临时不可用
    ET.SOFT_DISABLE: soft_disable_alert("雷达暂时不可用"),
    ET.NO_ENTRY: NoEntryAlert("雷达暂时不可用"),
  },

  # 摄像头的每一帧都应由模型处理。如果模型处理
  # 速度不够快，则必须丢弃帧。当丢弃帧超过20%时触发此警报。
  EventName.modeldLagging: {  # 模型进程卡顿
    ET.SOFT_DISABLE: soft_disable_alert("驾驶模型运行卡顿"),
    ET.NO_ENTRY: NoEntryAlert("驾驶模型运行卡顿"),
    ET.PERMANENT: modeld_lagging_alert,
  },

  # 除了预测路径、车道线和前车数据外，模型还会
  # 预测车辆的当前速度和旋转速度。如果模型在车辆行驶时
  # 对当前速度的预测不确定性很高，通常意味着
  # 模型难以理解当前场景。这用作警告驾驶员的启发式方法。
  EventName.posenetInvalid: {  # Posenet速度无效
    ET.SOFT_DISABLE: soft_disable_alert("Posenet速度无效"),
    ET.NO_ENTRY: posenet_invalid_alert,
  },

  # 当定位器检测到超过40 m/s²（约4G）的加速度时，
  # 会警告驾驶员设备可能已从挡风玻璃掉落。
  EventName.deviceFalling: {  # 设备掉落
    ET.SOFT_DISABLE: soft_disable_alert("设备已从支架掉落"),
    ET.NO_ENTRY: NoEntryAlert("设备已从支架掉落"),
  },

  EventName.lowMemory: {  # 内存不足
    ET.SOFT_DISABLE: soft_disable_alert("内存不足：请重启设备"),
    ET.PERMANENT: low_memory_alert,
    ET.NO_ENTRY: NoEntryAlert("内存不足：请重启设备"),
  },

  EventName.accFaulted: {  # ACC故障
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("巡航故障：请重启车辆"),
    ET.PERMANENT: NormalPermanentAlert("巡航故障：请重启车辆以启用"),
    ET.NO_ENTRY: NoEntryAlert("巡航故障：请重启车辆"),
  },

  EventName.espActive: {  # 电子稳定程序激活
    ET.SOFT_DISABLE: soft_disable_alert("电子稳定控制系统已激活"),
    ET.NO_ENTRY: NoEntryAlert("电子稳定控制系统已激活"),
  },

  EventName.controlsMismatch: {  # 控制不匹配
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("控制不匹配"),
    ET.NO_ENTRY: NoEntryAlert("控制不匹配"),
  },

  # 设备的USB堆栈有时会进入异常状态
  # 导致与panda的连接丢失
  EventName.usbError: {  # USB错误
    ET.SOFT_DISABLE: soft_disable_alert("USB错误：请重启设备"),
    ET.PERMANENT: NormalPermanentAlert("USB错误：请重启设备"),
    ET.NO_ENTRY: NoEntryAlert("USB错误：请重启设备"),
  },

  # 此警报可能因以下原因触发：
  # - 完全未接收到CAN数据
  # - 接收到CAN数据，但某些消息未按正确频率接收
  # 如果您未开发新的车辆适配，这通常由接线故障导致
  EventName.canError: {  # CAN错误
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("CAN总线错误"),
    ET.PERMANENT: Alert(
      "CAN总线错误：请检查连接",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1., creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert("CAN总线错误：请检查连接"),
  },

  EventName.canBusMissing: {  # CAN总线断开
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("CAN总线已断开"),
    ET.PERMANENT: Alert(
      "CAN总线已断开：可能是线缆故障",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1., creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert("CAN总线已断开：请检查连接"),
  },

  EventName.steerUnavailable: {  # 转向不可用
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("车道保持故障：请重启车辆"),
    ET.PERMANENT: NormalPermanentAlert("车道保持故障：请重启车辆以启用"),
    ET.NO_ENTRY: NoEntryAlert("车道保持故障：请重启车辆"),
  },

  EventName.reverseGear: {  # 倒挡
    ET.PERMANENT: Alert(
      "倒车\n挡位",
      "",
      AlertStatus.normal, AlertSize.full,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .2, creation_delay=0.5),
    ET.USER_DISABLE: ImmediateDisableAlert("已挂入倒挡"),
    ET.NO_ENTRY: NoEntryAlert("已挂入倒挡"),
  },

  # 在使用原厂ACC的车辆上，车辆可能因各种原因取消ACC。
  # 发生这种情况时，我们无法再控制车辆，因此需要立即警告用户。
  EventName.cruiseDisabled: {  # 巡航已禁用
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("巡航已关闭"),
  },

  # 当线束盒中的继电器打开时，LKAS摄像头与
  # 车辆其他部分之间的CAN总线被分离。当在车辆侧接收到
  # LKAS摄像头的消息时，通常意味着继电器未正确打开，
  # 从而触发此警报。
  EventName.relayMalfunction: {  # 继电器故障
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("线束继电器故障"),
    ET.PERMANENT: NormalPermanentAlert("线束继电器故障", "请检查硬件"),
    ET.NO_ENTRY: NoEntryAlert("线束继电器故障"),
  },

  EventName.speedTooLow: {  # 速度过低
    ET.IMMEDIATE_DISABLE: Alert(
      "openpilot已取消",
      "速度过低",
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.none, AudibleAlert.disengage, 3.),
  },

  # 当车辆行驶速度超过训练数据中的大多数车辆时，模型输出可能不可预测。
  EventName.speedTooHigh: {  # 速度过高
    ET.WARNING: Alert(
      "速度过高",
      "模型在此速度下预测结果不确定性高",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.promptRepeat, 4.),
    ET.NO_ENTRY: NoEntryAlert("请减速以启用"),
  },

  EventName.vehicleSensorsInvalid: {  # 车辆传感器无效
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("车辆传感器无效"),
    ET.PERMANENT: NormalPermanentAlert("车辆传感器标定中", "请行驶以完成标定"),
    ET.NO_ENTRY: NoEntryAlert("车辆传感器标定中"),
  },

  EventName.personalityChanged: {  # 驾驶风格已变更
    ET.WARNING: personality_changed_alert,
  },

  EventName.userBookmark: {  # 用户书签
    ET.PERMANENT: NormalPermanentAlert("书签已保存", duration=1.5),
  },

  EventName.audioFeedback: {  # 音频反馈
    ET.PERMANENT: audio_feedback_alert,
  },
}


if __name__ == '__main__':
  # 按类型和优先级打印所有警报
  from cereal.services import SERVICE_LIST
  from collections import defaultdict

  event_names = {v: k for k, v in EventName.schema.enumerants.items()}
  alerts_by_type: dict[str, dict[Priority, list[str]]] = defaultdict(lambda: defaultdict(list))

  CP = car.CarParams.new_message()
  CS = car.CarState.new_message()
  sm = messaging.SubMaster(list(SERVICE_LIST.keys()))

  for i, alerts in EVENTS.items():
    for et, alert in alerts.items():
      if callable(alert):
        alert = alert(CP, CS, sm, False, 1, log.LongitudinalPersonality.standard)
      alerts_by_type[et][alert.priority].append(event_names[i])

  all_alerts: dict[str, list[tuple[Priority, list[str]]]] = {}
  for et, priority_alerts in alerts_by_type.items():
    all_alerts[et] = sorted(priority_alerts.items(), key=lambda x: x[0], reverse=True)

  for status, evs in sorted(all_alerts.items(), key=lambda x: x[0]):
    print(f"**** {status} ****")
    for p, alert_list in evs:
      print(f"  {repr(p)}:")
      print("   ", ', '.join(alert_list), "\n")
