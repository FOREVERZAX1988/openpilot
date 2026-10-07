#!/usr/bin/env python3
import math
import numpy as np
from collections import deque
from typing import Any

import capnp
from openpilot.cereal import messaging, log, custom
from opendbc.car.structs import car
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL, Priority, config_realtime_process
from openpilot.common.swaglog import cloudlog
from openpilot.common.simple_kalman import KF1D

from opendbc.car import structs
from opendbc.car.hyundai.values import HyundaiFlags
from opendbc.sunnypilot.car.hyundai.values import HyundaiFlagsSP
from opendbc.sunnypilot.car.volkswagen import macan_calib as _macan_calib


# Default lead acceleration decay set to 50% at 1s
_LEAD_ACCEL_TAU = 1.5

# radar tracks
SPEED, ACCEL = 0, 1     # Kalman filter states enum

# stationary qualification parameters
V_EGO_STATIONARY = 4.   # no stationary object flag below this speed

RADAR_TO_CAMERA = 1.52  # RADAR is ~ 1.5m ahead from center of mesh frame

# Macan Abstandsindex <-> 时距标定（0910 方案B / B1 单表）：t(idx) = A*idx + B
# 干净"同目标"帧、6 route / 15,040 帧重拟合，RMS 0.61 s；视觉-雷达 中位差 -0.77 m、
# 中位绝对差 1.90 m、82.0% 帧 <=5 m、A2 原厂替换率 6.3%（旧 0909 新线性 0.008718/+1.0178
# 为 -7.10 m / 35.3%）。注意：opendbc radar_interface.py 的 A3 使用同一组系数，必须同源修改。
# 详见 ai/docs/MLB_MACAN_PLANB_FIT_0910.md
# 【同源收敛 2026-10-09】标定改为从 macan_calib 单一源取（与 A3 / 仪表 / SnG 门同源）。
MACAN_B1_T_A = _macan_calib.MACAN_B1_T_A
MACAN_B1_T_B = _macan_calib.MACAN_B1_T_B

# ---- A2 判据物理化（2026-09-10）：相对偏差定义在【距离域】，不再用 idx 域 ----
# 旧: ratio = |vis_idx - stock_idx| / stock_idx
#          = |Δt| / (t - B)          <- idx 是 t 的仿射量，展开后多出一个放大因子
#   放大因子 t/(t-B)（B1 的 B=0.332）随距离变小 => 阈值随距离偷偷变严：
#     t=1.5 s -> 名义 30% 实为 23.4%；t=2 s -> 25.0%；t=3 s -> 26.7%；t=4 s -> 27.5%
#   而且原阈值是 2026-09-01 在【旧 0902 表】(等效 B≈0.163) 上标的，换 B1 后同一物理偏差
#   给出的 ratio 再大 ~10% => 有效阈值被静默收紧，已不是当初的操作点。
# 新: rel = |d_vis - d_stock| / d_stock = |Δt| / t   （同一 v 下与距离比等价）
#   -> 换任何表都不会再移动操作点；工具 ai/tools/verify_planB_code_0910.py 早就是物理口径
#      （ratio = |d_vis - d_stock|/d_stock > 0.30），本次把代码对齐到它。
# ---- 融合方向（2026-10-09）：视觉主导，雷达只能改近 ----
# 取代旧的「原厂主导 + 连续权重」方案（MACAN_A2_REL_TH=0.30，已删；见 _macan_fuse_leads）。
# 相对门沿用上游 dist_sane 的 25%；绝对下限由上游的 5.0 m 收紧到 2.0 m —— 只允许
# 「改近」时，5 m 的绝对下限等于允许一个荒谬的近距读数把车距一次砍掉 5 m。
MACAN_FUSE_REL_GATE = 0.25   # |d_vis - d_stock| < 25% * d_vis 才采纳原厂更近值
MACAN_FUSE_MIN_GAP = 2.0     # 绝对下限(m)：d_vis 很小时兜底
MACAN_FUSE_V_MAX_W = 0.30    # 原厂前车速度最大权重（只允许把 vLead 改低）
MACAN_VISION_PROB_MIN = 0.5  # 视觉前车可信门（对齐上游 get_lead 的 lead_prob > .5）

# ---- 落点2: 视觉平滑 + A2 变化率限制 (2026-09-23) ----
# 视觉主导帧在驾驶段 25<->40m 有原生 cv 噪声(±2~5m), 用一阶低通平滑; 同时对最终融合
# dRel 做单帧变化率限幅, 把 15m 级瞬跳斜坡化, 消除用户可见锯齿. 速率上限随 v_ego 缩放,
# 以免压制真实接近/远离(108km/h 单帧约 3m/0.1s).
MACAN_SMOOTH_RC = 0.5       # 视觉平滑一阶低通时间常数(s)
MACAN_RATE_MIN_STEP = 1.0   # 单帧最小可容忍变化(m)
MACAN_RATE_VFACTOR = 1.2    # v_ego 缩放系数(倍 DT_MDL)


class KalmanParams:
  def __init__(self, dt: float):
    # Lead Kalman Filter params, calculating K from A, C, Q, R requires the control library.
    # hardcoding a lookup table to compute K for values of radar_ts between 0.01s and 0.2s
    assert dt > .01 and dt < .2, "Radar time step must be between .01s and 0.2s"
    self.A = [[1.0, dt], [0.0, 1.0]]
    self.C = [1.0, 0.0]
    #Q = np.matrix([[10., 0.0], [0.0, 100.]])
    #R = 1e3
    #K = np.matrix([[ 0.05705578], [ 0.03073241]])
    dts = [i * 0.01 for i in range(1, 21)]
    K0 = [0.12287673, 0.14556536, 0.16522756, 0.18281627, 0.1988689,  0.21372394,
          0.22761098, 0.24069424, 0.253096,   0.26491023, 0.27621103, 0.28705801,
          0.29750003, 0.30757767, 0.31732515, 0.32677158, 0.33594201, 0.34485814,
          0.35353899, 0.36200124]
    K1 = [0.29666309, 0.29330885, 0.29042818, 0.28787125, 0.28555364, 0.28342219,
          0.28144091, 0.27958406, 0.27783249, 0.27617149, 0.27458948, 0.27307714,
          0.27162685, 0.27023228, 0.26888809, 0.26758976, 0.26633338, 0.26511557,
          0.26393339, 0.26278425]
    self.K = [[np.interp(dt, dts, K0)], [np.interp(dt, dts, K1)]]


class Track:
  def __init__(self, identifier: int, v_lead: float, kalman_params: KalmanParams):
    self.identifier = identifier
    self.cnt = 0
    self.aLeadTau = FirstOrderFilter(_LEAD_ACCEL_TAU, 0.45, DT_MDL)
    self.K_A = kalman_params.A
    self.K_C = kalman_params.C
    self.K_K = kalman_params.K
    self.kf = KF1D([[v_lead], [0.0]], self.K_A, self.K_C, self.K_K)

  def update(self, d_rel: float, y_rel: float, v_rel: float, v_lead: float):
    # relative values, copy
    self.dRel = d_rel   # LONG_DIST
    self.yRel = y_rel   # -LAT_DIST
    self.vRel = v_rel   # REL_SPEED
    self.vLead = v_lead

    # computed velocity and accelerations
    if self.cnt > 0:
      self.kf.update(self.vLead)

    self.vLeadK = float(self.kf.x[SPEED][0])
    self.aLeadK = float(self.kf.x[ACCEL][0])

    # Learn if constant acceleration
    if abs(self.aLeadK) < 0.5:
      self.aLeadTau.x = _LEAD_ACCEL_TAU
    else:
      self.aLeadTau.update(0.0)

    self.cnt += 1

  def get_RadarState(self, model_prob: float = 0.0):
    return {
      "dRel": float(self.dRel),
      "yRel": float(self.yRel),
      "vRel": float(self.vRel),
      "vLead": float(self.vLead),
      "vLeadK": float(self.vLeadK),
      "aLeadK": float(self.aLeadK),
      "aLeadTau": float(self.aLeadTau.x),
      "present": True,
      "modelProb": model_prob,
      "radar": True,
      "radarTrackId": self.identifier,
    }

  def potential_low_speed_lead(self, v_ego: float):
    # stop for stuff in front of you and low speed, even without model confirmation
    # Radar points closer than 0.75, are almost always glitches on toyota radars
    return abs(self.yRel) < 1.0 and (v_ego < V_EGO_STATIONARY) and (0.75 < self.dRel < 25)

  def __str__(self):
    ret = f"x: {self.dRel:4.1f}  y: {self.yRel:4.1f}  v: {self.vRel:4.1f}  a: {self.aLeadK:4.1f}"
    return ret


def laplacian_pdf(x: float, mu: float, b: float):
  b = max(b, 1e-4)
  return math.exp(-abs(x-mu)/b)


def match_vision_to_track(v_ego: float, lead: capnp._DynamicStructReader, tracks: dict[int, Track]):
  offset_vision_dist = lead.x[0] - RADAR_TO_CAMERA

  def prob(c):
    prob_d = laplacian_pdf(c.dRel, offset_vision_dist, lead.xStd[0])
    prob_y = laplacian_pdf(c.yRel, -lead.y[0], lead.yStd[0])
    prob_v = laplacian_pdf(c.vRel + v_ego, lead.v[0], lead.vStd[0])

    # This isn't exactly right, but it's a good heuristic
    return prob_d * prob_y * prob_v

  track = max(tracks.values(), key=prob)

  # if no 'sane' match is found return -1
  # stationary radar points can be false positives
  dist_sane = abs(track.dRel - offset_vision_dist) < max([(offset_vision_dist)*.25, 5.0])
  vel_sane = (abs(track.vRel + v_ego - lead.v[0]) < 10) or (v_ego + track.vRel > 3)
  if dist_sane and vel_sane:
    return track
  else:
    return None


def get_RadarState_from_vision(lead_msg: capnp._DynamicStructReader, v_ego: float, model_v_ego: float, lead_prob: float):
  lead_v_rel_pred = lead_msg.v[0] - model_v_ego
  return {
    "dRel": float(lead_msg.x[0] - RADAR_TO_CAMERA),
    "yRel": float(-lead_msg.y[0]),
    "vRel": float(lead_v_rel_pred),
    "vLead": float(v_ego + lead_v_rel_pred),
    "vLeadK": float(v_ego + lead_v_rel_pred),
    "aLeadK": float(lead_msg.a[0]),
    "aLeadTau": 0.3,
    "modelProb": float(lead_prob),
    "present": True,
    "radar": False,
    "radarTrackId": -1,
  }


def get_lead(v_ego: float, ready: bool, tracks: dict[int, Track], lead_msg: capnp._DynamicStructReader,
             model_v_ego: float, lead_prob: float, CP: structs.CarParams, CP_SP: structs.CarParamsSP,
             low_speed_override: bool = True) -> dict[str, Any]:
  # Determine leads, this is where the essential logic happens
  if len(tracks) > 0 and ready and lead_prob > .5:
    track = match_vision_to_track(v_ego, lead_msg, tracks)
  else:
    track = None

  lead_dict = {'present': False}
  if track is not None:
    lead_dict = track.get_RadarState(lead_prob)
    lead_dict = get_custom_yrel(CP, CP_SP, lead_dict, lead_msg)
  elif (track is None) and ready and (lead_prob > .5):
    lead_dict = get_RadarState_from_vision(lead_msg, v_ego, model_v_ego, lead_prob)

  if low_speed_override:
    low_speed_tracks = [c for c in tracks.values() if c.potential_low_speed_lead(v_ego)]
    if len(low_speed_tracks) > 0:
      closest_track = min(low_speed_tracks, key=lambda c: c.dRel)

      # Only choose new track if it is actually closer than the previous one
      if (not lead_dict['present']) or (closest_track.dRel < lead_dict['dRel']):
        lead_dict = closest_track.get_RadarState()

  return lead_dict


def get_custom_yrel(CP: structs.CarParams, CP_SP: structs.CarParamsSP, lead_dict: dict[str, Any],
                    lead_msg: capnp._DynamicStructReader) -> dict[str, Any]:
  if CP.brand == "hyundai" and (CP_SP.flags & HyundaiFlagsSP.ENHANCED_SCC or
                                CP.flags & (HyundaiFlags.CANFD_CAMERA_SCC | HyundaiFlags.CAMERA_SCC)):
    lead_dict['yRel'] = float(-lead_msg.y[0])

  return lead_dict


class RadarD:
  def __init__(self, CP: structs.CarParams, CP_SP: structs.CarParams, delay: float = 0.0):
    self.CP = CP
    self.CP_SP = CP_SP

    self.current_time = 0.0
    self.tracks: dict[int, Track] = {}
    self.kalman_params = KalmanParams(DT_MDL)
    self.lead_prob_filters = [FirstOrderFilter(0.0, 0.2, DT_MDL) for _ in range(2)]

    self.v_ego = 0.0
    self.v_ego_hist = deque([0.0], maxlen=int(round(delay / DT_MDL))+1)
    self.last_v_ego_frame = -1

    self.radar_state: capnp._DynamicStructBuilder | None = None
    self.radar_state_valid = False
    # Macan 原厂雷达融合（bus2 ACC_02.Abstandsindex + ACC_04 前车速度 -> 修正视觉 lead）
    # 标定口径：0910 方案B / B1 单表 t = 0.008969*idx + 0.332（模块常量 MACAN_B1_T_*），
    # 与 opendbc radar_interface.py 的 A3 同源；旧 0902 插值查表与 0909 新线性公式均已废弃。
    self._macan_radar = {'idx': 0, 'obj': 0, 'spd': 0.0}
    self._macan_fusion_on = False
    self._macan_fusion_t = 0.0
    # ---- 落点1: idx 失效保持滞回 (2026-09-22) ----
    # idx 有效<->无效瞬间翻转(0/1021)时, 若滞回窗口内曾有有效 idx, 则保持最近有效值继续融合,
    # 避免 15m 级源切换锯齿(007c seg5/8/10 实证). 仅当无效持续超过窗口才真正放弃融合.
    self._macan_last_valid_idx = 0.0
    self._macan_last_valid_t = 0.0
    self._macan_hyst_t0 = 0.0          # 进入无效态的时间戳
    self._macan_hyst_invalid = False   # 当前是否处于无效保持态
    self._macan_hyst_win = 0.6         # 滞回窗口(s): 无效保持最近有效 idx 的最长时长
    # ---- 落点2: 视觉平滑 + A2 变化率限制 状态 ----
    self._macan_smooth: dict[str, FirstOrderFilter] = {}   # lead_name -> 一阶低通(视觉平滑)
    self._macan_smooth_v: dict[str, FirstOrderFilter] = {}  # lead_name -> 一阶低通(视觉 vLead 平滑)
    self._macan_last_fused: dict[str, float] = {}          # lead_name -> 上一帧融合 dRel(变化率限幅)

    self.ready = False

  def update(self, sm: messaging.SubMaster, rr: car.RadarData):
    self.ready = sm.seen['modelV2']

    if sm.recv_frame['carState'] != self.last_v_ego_frame:
      self.v_ego = sm['carState'].vEgo
      self.v_ego_hist.append(self.v_ego)
      self.last_v_ego_frame = sm.recv_frame['carState']

    ar_pts = {pt.trackId: [pt.dRel, pt.yRel, pt.vRel] for pt in rr.points}

    # *** remove missing points from meta data ***
    for ids in list(self.tracks.keys()):
      if ids not in ar_pts:
        self.tracks.pop(ids, None)

    # *** compute the tracks ***
    for ids in ar_pts:
      rpt = ar_pts[ids]

      # align v_ego by a fixed time to align it with the radar measurement
      v_lead = rpt[2] + self.v_ego_hist[0]

      # create the track if it doesn't exist or it's a new track
      if ids not in self.tracks:
        self.tracks[ids] = Track(ids, v_lead, self.kalman_params)
      self.tracks[ids].update(rpt[0], rpt[1], rpt[2], v_lead)

    # *** publish radarState ***
    self.radar_state_valid = sm.all_checks()
    self.radar_state = log.RadarState.new_message()
    self.radar_state.mdMonoTime = sm.logMonoTime['modelV2']
    self.radar_state.radarErrors = rr.errors

    if len(sm['modelV2'].velocity.x):
      model_v_ego = sm['modelV2'].velocity.x[0]
    else:
      model_v_ego = self.v_ego
    leads_v3 = sm['modelV2'].leadsV3
    if len(leads_v3) > 1:
      for i in range(2):
        # Asymmetric filter on lead prob to keep lead when uncertain
        lead_prob = leads_v3[i].prob
        if lead_prob > self.lead_prob_filters[i].x:
          self.lead_prob_filters[i].x = lead_prob
        else:
          self.lead_prob_filters[i].update(lead_prob)

      self.radar_state.leadOne = get_lead(self.v_ego, self.ready, self.tracks, leads_v3[0], model_v_ego, self.lead_prob_filters[0].x,
                                          self.CP, self.CP_SP, low_speed_override=True)
      self.radar_state.leadTwo = get_lead(self.v_ego, self.ready, self.tracks, leads_v3[1], model_v_ego, self.lead_prob_filters[1].x,
                                          self.CP, self.CP_SP, low_speed_override=False)

      # Macan 原厂雷达融合（视觉主导 + 雷达只能改近，开关 MacanRadarFusion）
      self._macan_fuse_leads(sm, leads_v3)

  def _macan_fusion_enabled(self) -> bool:
    import time
    now = time.monotonic()
    if now - self._macan_fusion_t > 1.0:
      try:
        # 门控补强(2026-09-07)：MacanRadarFusion 也仅在 OP 纵向开启时生效——
        # A1/A2 修正的是 OP 纵向用到的 lead，纯原厂 ACC(关闭OP纵向)时不应改动 lead。
        # 2026-09-15：移除 MacanFusionMode=1 门控 —— 原厂雷达在 st=0/2（关闭/待命）
        # 下仍挥续发送 ACC_Abstandsindex / ACC_Gesetzte_Zeitluecke / ACC_Geschw_Zielfahrzeug
        # 等基础信息信号（routes 0002/0004/0049 实测实铉）。因此 MacanRadarFusion
        # 对融合模式和纯OP模式都有效：开=雷达参与辅助视觉(也驱动仪表盘)/
        # 关=仅视觉判定。
        self._macan_fusion_on = self.CP.carFingerprint == "PORSCHE_MACAN_MK1" \
            and self.CP.openpilotLongitudinalControl \
            and Params().get_bool("MacanRadarFusion")
      except Exception:
        self._macan_fusion_on = False
      self._macan_fusion_t = now
    return self._macan_fusion_on

  def _macan_t_from_idx(self, idx: float) -> float:
    """Abstandsindex -> 时距 t（0910 方案B / B1 单表直线，与雷达接口 A3 同源）。

    无人工分段：旧 idx<100 锚 0.8 s / idx>560 截顶 6.0 s 已删除（前者在 idx=100 处
    会造成 0.8 -> 1.89 s 突跳，且与 A3 的直线不一致）。
    """
    return _macan_calib.t_from_idx(idx)

  def _macan_idx_to_drel(self, idx: float, v_ego: float) -> float:
    """Abstandsindex -> 时距 t -> 距离（B1 逆映射，低速用等效 t*max(v,5)，与 A3 一致）"""
    return _macan_calib.idx_to_drel(idx, v_ego)

  def _macan_drel_to_idx(self, drel: float, v_ego: float) -> float:
    """距离 -> 时距 t -> Abstandsindex（B1 直线反解，与 A3 同源）。

    去掉 100/561 硬锚（旧代码 t<=0.8 -> 100、t>=6.0 -> 561 会在两端制造与 A3
    不一致的阶梯），改为钳到信号有效域 1..1020（A3 里 0 与 >=1021 视为无目标）。
    """
    return float(_macan_calib.drel_to_idx(drel, v_ego))



  def _macan_fuse_leads(self, sm: messaging.SubMaster, leads_v3) -> None:
    """Macan 原厂雷达融合（2026-10-09 语义反转：视觉主导，雷达只能改近）。

    旧语义（A1 速度加权 + A2 距离校验，0910 方案B 起）= 原厂主导：
    A2 用连续权重把原厂距离以 0.7~1.0 的权重替换/混合视觉，A1 把原厂前车速度以
    0.5~0.85 权重并进 vLead（视觉权重上限 0.5）。

    病灶（route 00000091 seg9 实锤）：静止时原厂 vEgo→0 之后 idx 停止重算（冻结），
    d_stock = t(idx)*max(v,5) 退化成【常数】—— idx=188 冻结 -> 10.09 m，而视觉当时
    看到的是真实 6.15 m（车已蠕行靠近 2.4 m）。原厂权重 1.0 把当时唯一准确的视觉
    距离整段丢掉，dRel 被钉在 10.09 m 长达 11 s。

    新语义（对齐上游丰田「视觉门控 + 雷达辅助」，但方向收紧为单向）：
      1. 视觉可用（leadsV3[i].prob >= 0.5）→ 距离与前车速度都以【视觉】为基准；
      2. 原厂 idx 换算距离只有在【更近】且过 sanity 门时才被采纳 —— 可改近、绝不可改远；
      3. vLead 同理：原厂前车速度只允许把 vLead 改【低】（更保守方向），权重 <= 0.3；
      4. 视觉无目标而原厂有目标（上游 get_lead 的 low_speed_override 分支，
         potential_low_speed_lead: v_ego<4 / 0.75<dRel<25 / |yRel|<1）→ 保留原厂值，
         保证「视觉没捕捉到但雷达捕捉到」仍能进执行层（该场景只能靠雷达安全刹车）。

    这样随着上游视觉模型变准，融合值自动收敛到视觉，不会再被冻结的 idx 拖累。
    """
    if not self._macan_fusion_enabled():
      return
    r = self._macan_radar
    r['idx'] = r['obj'] = 0
    r['spd'] = 0.0
    for msg in sm['can']:
      if msg.src != 2:
        continue
      d = msg.dat
      if msg.address == 780 and len(d) >= 7:
        r['idx'] = (d[3] | (d[4] << 8)) & 0x3FF
        r['obj'] = (d[5] >> 6) & 0x3
      elif msg.address == 804 and len(d) >= 7:
        v = ((d[5] | (d[6] << 8)) & 0x3FF) * 0.32  # km/h
        r['spd'] = v if v < 320 else 0.0

    import time
    now = time.monotonic()
    have_stock = False
    if 0 < r['idx'] < 1021:
      self._macan_last_valid_idx = r['idx']
      self._macan_last_valid_t = now
      self._macan_hyst_invalid = False
      have_stock = True
    elif self._macan_last_valid_idx > 0:
      # 无效(0/1021)：滞回保持最近有效值，抑制源切换锯齿（007c seg5/8/10 实证）。
      # 语义反转后保持值只剩「改近」一条出口，最坏影响被 sanity 门限幅。
      if not self._macan_hyst_invalid:
        self._macan_hyst_invalid = True
        self._macan_hyst_t0 = now
        r['idx'] = self._macan_last_valid_idx
        have_stock = True
      elif now - self._macan_hyst_t0 <= self._macan_hyst_win:
        r['idx'] = self._macan_last_valid_idx
        have_stock = True
      else:
        self._macan_hyst_invalid = False
        self._macan_last_valid_idx = 0.0
    # A2 换算：原厂 idx -> 距离（B1 正解，与 A3 同源；低速用等效 t*max(v,5)）
    stock_drel = self._macan_idx_to_drel(r['idx'], self.v_ego) if have_stock else 0.0

    for lead_name, li in (('leadOne', 0), ('leadTwo', 1)):
      lead = getattr(self.radar_state, lead_name)
      if not lead.present:
        continue

      # ---- 视觉基准：modelV2 原始前车（雷达坐标系 -> 减 RADAR_TO_CAMERA 对齐保险杠口径）----
      d_vis = None
      v_vis = None
      try:
        if li < len(leads_v3) and float(leads_v3[li].prob) >= MACAN_VISION_PROB_MIN:
          x_vis = float(leads_v3[li].x[0]) - RADAR_TO_CAMERA
          if 0.0 < x_vis < 150.0:
            d_vis = x_vis
            v_vis = float(leads_v3[li].v[0])
      except Exception:
        d_vis = None
        v_vis = None

      # ---- 距离：视觉主导，雷达只能改近 ----
      if d_vis is not None:
        d_used = d_vis
        gate = max(MACAN_FUSE_REL_GATE * d_vis, MACAN_FUSE_MIN_GAP)
        if 0.0 < stock_drel < d_vis and (d_vis - stock_drel) <= gate:
          d_used = stock_drel          # 原厂更近且过门 -> 采纳（安全方向）
        # 落点2 保持：视觉平滑 + 变化率限幅，压制 25<->40m 原生 cv 噪声与源切换瞬跳
        if lead_name not in self._macan_smooth:
          self._macan_smooth[lead_name] = FirstOrderFilter(d_used, MACAN_SMOOTH_RC, DT_MDL)
        d_used = self._macan_smooth[lead_name].update(d_used)
        max_step = MACAN_RATE_MIN_STEP + MACAN_RATE_VFACTOR * max(self.v_ego, 0.0) * DT_MDL
        prev = self._macan_last_fused.get(lead_name)
        if prev is not None:
          d_used = float(np.clip(d_used, prev - max_step, prev + max_step))
        self._macan_last_fused[lead_name] = d_used
        lead.dRel = d_used
      # d_vis is None -> 保留上游 get_lead 结果（雷达 track / low_speed_override / 无前车）

      # ---- 前车速度：视觉主导，原厂只允许改低 ----
      if v_vis is not None:
        v_used = v_vis
        if have_stock and r['spd'] > 0.0:
          v_stock = r['spd'] / 3.6
          if v_stock < v_used:
            v_used = (1.0 - MACAN_FUSE_V_MAX_W) * v_used + MACAN_FUSE_V_MAX_W * v_stock
        if lead_name not in self._macan_smooth_v:
          self._macan_smooth_v[lead_name] = FirstOrderFilter(v_used, MACAN_SMOOTH_RC, DT_MDL)
        v_used = self._macan_smooth_v[lead_name].update(v_used)
        lead.vLead = v_used
        lead.vLeadK = v_used
        lead.vRel = v_used - self.v_ego

  def publish(self, pm: messaging.PubMaster):
    assert self.radar_state is not None

    radar_msg = messaging.new_message("radarState")
    radar_msg.valid = self.radar_state_valid
    radar_msg.radarState = self.radar_state
    pm.send("radarState", radar_msg)


# fuses camera and radar data for best lead detection
def main() -> None:
  config_realtime_process(5, Priority.CTRL_LOW)

  # wait for stats about the car to come in from controls
  cloudlog.info("radard is waiting for CarParams")
  CP = messaging.log_from_bytes(Params().get("CarParams", block=True), car.CarParams)
  cloudlog.info("radard got CarParams")

  cloudlog.info("radard is waiting for CarParamsSP")
  CP_SP = messaging.log_from_bytes(Params().get("CarParamsSP", block=True), custom.CarParamsSP)
  cloudlog.info("radard got CarParamsSP")

  # *** setup messaging
  sm = messaging.SubMaster(['modelV2', 'carState', 'radarTracks', 'can'], poll='modelV2')
  pm = messaging.PubMaster(['radarState'])

  RD = RadarD(CP, CP_SP, CP.radarDelay)

  while 1:
    sm.update()

    RD.update(sm, sm['radarTracks'])
    RD.publish(pm)


if __name__ == "__main__":
  main()
