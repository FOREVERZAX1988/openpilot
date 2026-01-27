import time
import numpy as np
from openpilot.common.swaglog import cloudlog

# =========================================================
# ACM (Active Coasting Management) 參數設定區
# =========================================================

# --- 1. 滑行速度區間設定 (單位：km/h) ---
SPEED_OFFSET_MIN_KPH = 2.0 
SPEED_OFFSET_MAX_FLAT_KPH = 10.0
SPEED_OFFSET_MAX_DOWNHILL_KPH = 5.0

# --- 2. 坡度邏輯設定 (單位：弧度 Radians) ---
PITCH_UPHILL_THRESHOLD = 0.015    
PITCH_DOWNHILL_THRESHOLD = -0.030 

# --- 3. 動態 TTC (碰撞時間) 安全設定 [修改區域] ---
# 速度 [36kph, 108kph]
TTC_BP = [10., 30.]

# (A) 有雷達訊號時的 TTC (通常較精準，可維持原設定或稍短)
# 速度對應: [10m/s -> 1.5s, 30m/s -> 2.5s]
TTC_V_RADAR  = [1.5, 2.5]

# (B) 無雷達訊號 (純視覺) 時的 TTC (通常距離跳動大，建議設定保守一點)
# 速度對應: [10m/s -> 3.0s, 30m/s -> 3.0s]
TTC_V_VISION = [3.0, 3.0]

# --- 4. 緊急狀況閾值 ---
EMERGENCY_TTC = 2.0
EMERGENCY_RELATIVE_SPEED = 10.0
EMERGENCY_DECEL_THRESHOLD = -1.5

# --- 5. 其他安全設定 ---
LEAD_COOLDOWN_TIME = 0.5
SPEED_BP = [0., 10., 20., 30.]
MIN_DIST_V = [15., 20., 25., 30.]

# =========================================================
# [新增] Smart Log 設定 (移植自 DTSC)
# =========================================================
FILE_LOG_ENABLED = False  # 若要啟用檔案紀錄，請改為 True

def write_file_log(msg):
    if not FILE_LOG_ENABLED: return
    try:
        # 寫入至 /data/media/0/acm_log.txt
        with open("/data/media/0/acm_log.txt", "a") as f:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            f.write(f"[{timestamp}] {msg}\n")
    except Exception:
        pass

class ACM:
  def __init__(self):
    self.enabled = False
    self._is_in_coast_window = False
    self._has_lead = False
    self._active_prev = False
    self._last_lead_time = 0.0

    self.active = False
    self.just_disabled = False
    
    self.current_ttc_threshold = 3.0
    self.current_pitch = 0.0
    self.current_max_offset = 0.0 
    self.is_radar_lead = False # 用於 Debug 顯示
    
    # [新增] Log 計時變數 (保持結構一致性)
    self.last_log_time = 0.0

  def _check_emergency_conditions(self, lead, v_ego, current_time):
    if not lead or not lead.status:
      return False

    self.lead_ttc = lead.dRel / max(v_ego, 0.1)
    relative_speed = v_ego - lead.vLead
    min_dist_for_speed = np.interp(v_ego, SPEED_BP, MIN_DIST_V)

    if lead.dRel < min_dist_for_speed and (
        self.lead_ttc < EMERGENCY_TTC or
        relative_speed > EMERGENCY_RELATIVE_SPEED):

      self._last_lead_time = current_time
      if self.active:
        msg = f"ACM emergency disable: dRel={lead.dRel:.1f}m, TTC={self.lead_ttc:.1f}s"
        cloudlog.warning(msg)
        write_file_log(msg) # [新增] 寫入 Log
      return True

    return False

  def _update_lead_status(self, lead, v_ego, current_time):
    if lead and lead.status:
      self.lead_ttc = lead.dRel / max(v_ego, 0.1)
      
      # [修改點] 判斷是否有雷達訊號
      # getattr 是為了防止舊版 openpilot 或某些 fork 的 lead 物件沒有 radar 屬性而報錯
      self.is_radar_lead = getattr(lead, 'radar', False)

      if self.is_radar_lead:
          # 有雷達：使用 Radar 參數
          self.current_ttc_threshold = np.interp(v_ego, TTC_BP, TTC_V_RADAR)
      else:
          # 無雷達：使用 Vision 參數 (通常更保守)
          self.current_ttc_threshold = np.interp(v_ego, TTC_BP, TTC_V_VISION)

      if self.lead_ttc < self.current_ttc_threshold:
        self._has_lead = True
        self._last_lead_time = current_time
      else:
        self._has_lead = False
    else:
      self._has_lead = False
      self.lead_ttc = float('inf')

  def _check_cooldown(self, current_time):
    time_since_lead = current_time - self._last_lead_time
    return time_since_lead < LEAD_COOLDOWN_TIME

  def _should_activate(self, user_ctrl_lon, v_ego, v_cruise, in_cooldown, pitch):
    if pitch > PITCH_UPHILL_THRESHOLD:
        self._is_in_coast_window = False
        return False

    if pitch < PITCH_DOWNHILL_THRESHOLD:
        self.current_max_offset = SPEED_OFFSET_MAX_DOWNHILL_KPH 
    else:
        self.current_max_offset = SPEED_OFFSET_MAX_FLAT_KPH     

    lower_bound = v_cruise - (SPEED_OFFSET_MIN_KPH / 3.6)
    upper_bound = v_cruise + (self.current_max_offset / 3.6)
    
    self._is_in_coast_window = lower_bound < v_ego < upper_bound

    return (not user_ctrl_lon and
            not self._has_lead and
            not in_cooldown and
            self._is_in_coast_window)

  def update_states(self, cc, rs, user_ctrl_lon, v_ego, v_cruise):
    if not self.enabled or len(cc.orientationNED) != 3:
      self.active = False
      return

    self.current_pitch = cc.orientationNED[1]
    current_time = time.monotonic()
    lead = rs.leadOne

    if self._check_emergency_conditions(lead, v_ego, current_time):
      self.active = False
      self._active_prev = self.active
      return

    self._update_lead_status(lead, v_ego, current_time)
    in_cooldown = self._check_cooldown(current_time)
    
    self.active = self._should_activate(user_ctrl_lon, v_ego, v_cruise, in_cooldown, self.current_pitch)

    self.just_disabled = self._active_prev and not self.active
    if self.active and not self._active_prev:
      pitch_deg = self.current_pitch * 57.2958
      # 判斷是否為雷達訊號，並轉為字串紀錄
      source_str = "RADAR" if getattr(self, 'is_radar_lead', False) else "VISION"
      
      msg = f"ACM ON: v={v_ego*3.6:.0f}, pitch={pitch_deg:.1f}deg, Max+{self.current_max_offset:.0f}kph, TTC_Src={source_str}"
      cloudlog.info(msg)
      write_file_log(msg) # [新增] 寫入 Log，這裡可以清楚看到是用 Radar 還是 Vision
      
    elif self.just_disabled:
      msg = "ACM OFF"
      cloudlog.info(msg)
      write_file_log(msg) # [新增] 寫入 Log

    self._active_prev = self.active

  def update_a_desired_trajectory(self, a_desired_trajectory):
    if not self.active:
      return a_desired_trajectory

    min_accel = np.min(a_desired_trajectory)
    if min_accel < EMERGENCY_DECEL_THRESHOLD:
      msg = f"ACM aborting: MPC requested {min_accel:.2f} m/s² braking"
      cloudlog.warning(msg)
      write_file_log(msg) # [新增] 寫入 Log
      self.active = False
      return a_desired_trajectory

    modified_trajectory = np.copy(a_desired_trajectory)
    for i in range(len(modified_trajectory)):
      if -1.0 < modified_trajectory[i] < 0:
        modified_trajectory[i] = 0.0
    
    return modified_trajectory
