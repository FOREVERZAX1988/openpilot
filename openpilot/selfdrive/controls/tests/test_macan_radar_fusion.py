"""Macan 原厂雷达融合语义：视觉主导，雷达只能改近（2026-10-09）。

用最小桩件直接驱动 RadarD._macan_fuse_leads，把数值钉死，防止回退成
「原厂主导」（route 00000091 seg9：idx=188 冻结 -> 10.09 m 覆盖视觉 6.15 m）。
"""
from types import SimpleNamespace

from openpilot.common.test import OpenpilotTestCase
from openpilot.cereal import log
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.radard import (RadarD, RADAR_TO_CAMERA, MACAN_B1_T_A, MACAN_B1_T_B,
                                                 MACAN_SMOOTH_RC, MACAN_RATE_MIN_STEP)


def _idx_to_drel(idx, v_ego=0.0):
  return (MACAN_B1_T_A * idx + MACAN_B1_T_B) * (v_ego if v_ego > 5.0 else 5.0)


def _drel_to_idx(drel, v_ego=0.0):
  return int(round((drel / (v_ego if v_ego > 5.0 else 5.0) - MACAN_B1_T_B) / MACAN_B1_T_A))


class _Msg:
  def __init__(self, src, address, dat):
    self.src, self.address, self.dat = src, address, dat


def _can(idx=None, v_kph=None):
  out = []
  if idx is not None:
    d = bytearray(8)
    d[3] = idx & 0xFF
    d[4] = (idx >> 8) & 0x03
    out.append(_Msg(2, 780, bytes(d)))
  if v_kph is not None:
    d = bytearray(8)
    raw = int(round(v_kph / 0.32))
    d[5] = raw & 0xFF
    d[6] = (raw >> 8) & 0x03
    out.append(_Msg(2, 804, bytes(d)))
  return out


def _make(radar_drel, radar_vlead=0.0):
  d = RadarD.__new__(RadarD)
  d._macan_fusion_enabled = lambda: True
  d._macan_radar = {'idx': 0, 'obj': 0, 'spd': 0.0}
  d._macan_last_valid_idx = 0.0
  d._macan_last_valid_t = 0.0
  d._macan_hyst_t0 = 0.0
  d._macan_hyst_invalid = False
  d._macan_hyst_win = 0.6
  d._macan_smooth = {}
  d._macan_smooth_v = {}
  d._macan_last_fused = {}
  d.v_ego = 0.0
  d.radar_state = log.RadarState.new_message()
  d.radar_state.leadOne.present = True
  d.radar_state.leadOne.dRel = radar_drel
  d.radar_state.leadOne.vLead = radar_vlead
  d.radar_state.leadOne.vRel = radar_vlead
  return d


def _vision(drel, vlead=0.0, prob=0.9):
  # leadsV3 是雷达坐标系（RADAR_TO_CAMERA 前置于保险杠）
  return SimpleNamespace(prob=prob, x=[drel + RADAR_TO_CAMERA, 0.0], v=[vlead, 0.0])


def _run(d, can, leads_v3):
  d._macan_fuse_leads({'can': can}, leads_v3)
  return d.radar_state.leadOne


class TestMacanRadarFusion(OpenpilotTestCase):
  def test_frozen_idx_farther_than_vision_is_rejected(self):
    """0091 seg9 病灶：idx=188 冻结 -> 10.09 m，视觉 6.15 m。必须保留视觉。"""
    d = _make(radar_drel=_idx_to_drel(188))
    lead = _run(d, _can(idx=188), [_vision(6.15), _vision(0.0, prob=0.0)])
    assert abs(lead.dRel - 6.15) < 1e-6, lead.dRel

  def test_radar_closer_within_gate_is_adopted(self):
    """雷达更近且过门 -> 采纳（可改近）。"""
    vis = 20.0
    idx = _drel_to_idx(17.98)
    d = _make(radar_drel=vis)
    lead = _run(d, _can(idx=idx), [_vision(vis), _vision(0.0, prob=0.0)])
    assert abs(lead.dRel - _idx_to_drel(idx)) < 1e-6, lead.dRel
    assert lead.dRel < vis

  def test_implausible_near_spike_is_rejected(self):
    """雷达近到离谱（idx=1 -> 1.70 m vs 视觉 6.15 m）不得砍车距。"""
    d = _make(radar_drel=6.15)
    lead = _run(d, _can(idx=1), [_vision(6.15), _vision(0.0, prob=0.0)])
    assert abs(lead.dRel - 6.15) < 1e-6, lead.dRel

  def test_no_vision_keeps_radar_lead(self):
    """视觉无目标（prob<0.5）-> 保留上游雷达 lead（low_speed_override 场景）。"""
    d = _make(radar_drel=4.4)
    lead = _run(d, _can(idx=251), [_vision(0.0, prob=0.1), _vision(0.0, prob=0.0)])
    assert abs(lead.dRel - 4.4) < 1e-6, lead.dRel

  def test_vlead_vision_dominant_stock_only_lowers(self):
    vision_vlead = 2.0
    # 原厂前车速度更慢 -> 只允许改低，权重 0.3（信号量化 0.32 km/h/bit）
    stock_kph = 12 * 0.32
    d = _make(radar_drel=20.0, radar_vlead=vision_vlead)
    lead = _run(d, _can(idx=_drel_to_idx(18.0), v_kph=stock_kph), [_vision(20.0, vision_vlead), _vision(0.0, prob=0.0)])
    assert abs(lead.vLead - (0.7 * vision_vlead + 0.3 * stock_kph / 3.6)) < 1e-5, lead.vLead

    # 原厂前车速度更快(3 m/s) -> 不允许改高，保持视觉
    d2 = _make(radar_drel=20.0, radar_vlead=vision_vlead)
    lead2 = _run(d2, _can(idx=_drel_to_idx(18.0), v_kph=10.8), [_vision(20.0, vision_vlead), _vision(0.0, prob=0.0)])
    assert abs(lead2.vLead - vision_vlead) < 1e-6, lead2.vLead

  def test_invalid_idx_never_lengthens(self):
    """idx 无效(0) 且无滞回保持 -> 不得改动视觉距离。"""
    d = _make(radar_drel=6.15)
    lead = _run(d, _can(idx=0), [_vision(6.15), _vision(0.0, prob=0.0)])
    assert abs(lead.dRel - 6.15) < 1e-6, lead.dRel


  # ---- 状态复位 / 换人重播种 (2026-10-10) ----
  # 病灶：lead 丢失后不复位，重捕获的新目标沿用旧目标的平滑器与限幅基准 ->
  # 「新目标 3 m，融合值还在旧目标的 10 m」持续 ~0.5 s -> 纵向少刹车（二次起步险些追尾）。

  def test_lead_lost_resets_state_no_stale_carryover(self):
    d = _make(radar_drel=10.0)
    lead = _run(d, _can(idx=0), [_vision(10.0), _vision(0.0, prob=0.0)])
    assert abs(lead.dRel - 10.0) < 1e-6, lead.dRel
    assert d._macan_last_fused and d._macan_smooth

    # 目标丢失（视觉无目标 + lead 不 present）-> 状态必须清空
    d.radar_state.leadOne.present = False
    _run(d, _can(idx=0), [_vision(0.0, prob=0.0), _vision(0.0, prob=0.0)])
    assert not d._macan_smooth and not d._macan_last_fused and not d._macan_smooth_v,       "目标丢失必须复位融合状态"

    # 重捕获 3 m 处的新目标：第一帧就必须是 3 m，不得从 10 m 斜坡下来
    d.radar_state.leadOne.present = True
    lead = _run(d, _can(idx=0), [_vision(3.0), _vision(0.0, prob=0.0)])
    assert abs(lead.dRel - 3.0) < 1e-6, lead.dRel

  def test_relock_closer_jump_reseeds_instead_of_slewing(self):
    """present 一直为真但目标换人且明显更近 -> 重新播种，不沿用旧基准。"""
    d = _make(radar_drel=20.0)
    lead = _run(d, _can(idx=0), [_vision(20.0), _vision(0.0, prob=0.0)])
    assert abs(lead.dRel - 20.0) < 1e-6, lead.dRel
    lead = _run(d, _can(idx=0), [_vision(6.0), _vision(0.0, prob=0.0)])
    assert abs(lead.dRel - 6.0) < 1e-6, lead.dRel

  def test_relock_farther_jump_stays_rate_limited(self):
    """反向（突然更远）维持限幅+takes平滑：保守方向不得被重播种打开。"""
    d = _make(radar_drel=6.0)
    lead = _run(d, _can(idx=0), [_vision(6.0), _vision(0.0, prob=0.0)])
    assert abs(lead.dRel - 6.0) < 1e-6, lead.dRel
    lead = _run(d, _can(idx=0), [_vision(25.0), _vision(0.0, prob=0.0)])
    smoothed = 6.0 + (DT_MDL / (MACAN_SMOOTH_RC + DT_MDL)) * (25.0 - 6.0)
    expected = min(smoothed, 6.0 + MACAN_RATE_MIN_STEP)
    assert abs(lead.dRel - expected) < 1e-6, (lead.dRel, expected)

  def test_fusion_disabled_resets_state(self):
    d = _make(radar_drel=10.0)
    _run(d, _can(idx=0), [_vision(10.0), _vision(0.0, prob=0.0)])
    assert d._macan_last_fused
    d._macan_fusion_enabled = lambda: False
    _run(d, _can(idx=0), [_vision(10.0), _vision(0.0, prob=0.0)])
    assert not d._macan_last_fused, "融合关闭期间也要复位，避免下次开启沿用旧基准"
