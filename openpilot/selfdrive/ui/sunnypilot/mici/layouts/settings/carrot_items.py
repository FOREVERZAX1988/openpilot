"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Carrot tuning settings data table for mici.

A direct port of the Big GUI definitions in
``openpilot/selfdrive/ui/sunnypilot/layouts/settings/carrot_tuning_items.py``:
every param key, range, step, label map and user-visible string is kept
verbatim so the two frontends stay in lock-step (and already-extracted
translation msgids keep matching).

Item dicts (built by the small helpers below):
  kind='heading'  a grey section heading inside a group page
  kind='toggle'   bool param  -> BigParamControl
  kind='value'    int param   -> ParamValueButton + picker page (min/max/step
                                 range, optional {value: label} map or fmt)
  kind='action'   button that runs a callback (no param)
  kind='status'   display-only row whose value comes from a callable
"""
from openpilot.system.ui.lib.multilang import tr, tr_noop

_FLM_STATE_LABELS = {
  'idle': '空闲',
  'collecting': '采集中',
  'fitting': '拟合中',
  'accepted': '已应用',
  'rolled_back': '已回滚',
  'error': '出错',
}


def _flm_status_text() -> str:
  """One-line daemon status for the FLM analysis row (see flmanalysisd)."""
  try:
    import json
    from openpilot.common.params import Params
    raw = Params().get('FLMAnalysisStatus', encoding='utf-8') or ''
    if not raw:
      return tr('从未运行')
    d = json.loads(raw)
    state = str(d.get('state', 'idle'))
    detail = str(d.get('detail', '')).strip()
    label = _FLM_STATE_LABELS.get(state, state)
    return f'{label}: {detail}' if detail else label
  except Exception:
    return tr('从未运行')


def _flm_request_analysis() -> None:
  """Ask the flmanalysisd daemon to run one background analysis pass.

  The UI never runs the analyzer itself: the daemon owns offroad gating and
  route selection, this only raises the request flag it watches.
  """
  try:
    from openpilot.common.params import Params
    Params().put_bool('FLMAnalysisRequested', True)
  except Exception:
    pass


def _h(label: str) -> dict:
  return {"kind": "heading", "title": label}


def _t(param: str, title: str, desc: str | None = None) -> dict:
  return {"kind": "toggle", "param": param, "title": title, "desc": desc}


def _v(param: str, title: str, mn: int, mx: int, step: int = 1,
       desc: str | None = None, fmt=None, labels: dict[int, str] | None = None) -> dict:
  return {"kind": "value", "param": param, "title": title, "min": mn, "max": mx,
          "step": step, "desc": desc, "fmt": fmt, "labels": labels}


def _a(title: str, desc: str, btn_text: str, callback) -> dict:
  return {"kind": "action", "title": title, "desc": desc, "btn_text": btn_text, "callback": callback}


def _s(title: str, value_callback, desc: str | None = None) -> dict:
  return {"kind": "status", "title": title, "value_callback": value_callback, "desc": desc}


# (key, title, description) per group page; mirrors CarrotGroupKey / CARROT_GROUPS
# order in Big GUI carrot_tuning.py. Titles/descriptions are untranslated keys.
CARROT_GROUPS: tuple[tuple[str, str, str], ...] = (
  ('start', tr_noop('Start / Engage'),
   tr_noop('How openpilot engages cruise and which steering wheel buttons control it.')),
  ('cruise', tr_noop('Cruise & Following'),
   tr_noop('Following distance, longitudinal gains, acceleration limits and cruise behavior.')),
  ('navi', tr_noop('Navigation'),
   tr_noop('Navigation-based speed control, speed cameras, road limits and speed bumps.')),
  ('speed', tr_noop('Turns & Curves'),
   tr_noop('Automatic turn, fork / merge and curve speed control.')),
  ('tuning', tr_noop('Lateral Tuning'),
   tr_noop('Steering geometry, MPC costs, torque tuning, lane change and blind spot.')),
  ('display', tr_noop('Display & Sound'),
   tr_noop('Cluster HUD, on-screen overlays, sound, YouTube and map style.')),
  ('vehicle', tr_noop('Vehicle'),
   tr_noop('Vehicle-specific overrides and convenience options.')),
  ('dev', tr_noop('Developer'),
   tr_noop('Debug and diagnostic toggles. Use with caution.')),
  ('egpu', tr_noop('eGPU'),
   tr_noop('eGPU / big model status and configuration.')),
)


def build_start_items() -> list[dict]:
  return [
    _h(tr_noop('Auto Start / Cruise')),
    _h(tr_noop('Auto Gas')),
    _v('AutoGasSyncSpeed', tr_noop('Auto Gas Sync Speed'), 0, 200, 5,
       desc=tr_noop('Speed at which cruise set speed is re-synchronized. Tesla BYD only.')),
    _v('CruiseEcoControl', tr_noop('Eco Cruise Control'), 0, 3, 1),
  ]


def build_cruise_items() -> list[dict]:
  return [
    _h(tr_noop('Cruise Buttons & Speed')),
    _v('CruiseSpeedUnit', tr_noop('Cruise Speed Unit'), 1, 20, 1),
    _v('CruiseSpeedUnitBasic', tr_noop('Cruise Speed Unit (Basic)'), 1, 20, 1),
    _v('CruiseSpeed1', tr_noop('Cruise Speed 1'), 0, 200, 1),
    _v('CruiseSpeed2', tr_noop('Cruise Speed 2'), 0, 200, 1),
    _v('CruiseSpeed3', tr_noop('Cruise Speed 3'), 0, 200, 1),
    _v('CruiseSpeed4', tr_noop('Cruise Speed 4'), 0, 200, 1),
    _v('CruiseSpeed5', tr_noop('Cruise Speed 5'), 0, 200, 1),
    _v('CruiseButtonMode', tr_noop('Cruise Button Mode'), 0, 3, 1),
    _v('CruiseButtonLongDelay', tr_noop('Cruise Button Long Delay'), 10, 100, 1),
    _v('CancelButtonMode', tr_noop('Cancel Button Mode'), 0, 3, 1),
    _v('LfaButtonMode', tr_noop('LFA Button Mode'), 0, 2, 1),
    _v('CruiseOnDist', tr_noop('Cruise On Distance'), 0, 200, 1),
    _v('ApplyModelSpeed', tr_noop('Apply Model Speed'), 0, 100, 1),
    _v('AutoEngage', tr_noop('Auto Engage'), 0, 2, 1),
    _h(tr_noop('Following Distance')),
    # How many gap levels the distance button cycles. Belongs with follow distance,
    # not with the navigation section it was briefly placed in.
    _v('CruiseGapLevels', tr_noop('Cruise Gap Levels'), 2, 4, 1),
    _v('TFollowGap1', tr_noop('Follow Time Gap 1'), 50, 300, 5, fmt=lambda v: f'{v / 100.0:.2f}s'),
    _v('TFollowGap2', tr_noop('Follow Time Gap 2'), 50, 300, 5, fmt=lambda v: f'{v / 100.0:.2f}s'),
    _v('TFollowGap3', tr_noop('Follow Time Gap 3'), 50, 300, 5, fmt=lambda v: f'{v / 100.0:.2f}s'),
    _v('TFollowGap4', tr_noop('Follow Time Gap 4'), 50, 300, 5, fmt=lambda v: f'{v / 100.0:.2f}s'),
    _v('DynamicTFollowLC', tr_noop('Dynamic Follow Time on Lane Change'), 0, 200, 5,
       fmt=lambda v: f'{v / 100.0:.2f}s'),
    _h(tr_noop('Longitudinal Gains')),
    _v('LeadAccelResponse', tr_noop('Lead Acceleration Response'), -100, 100, 5,
       desc=tr_noop('How aggressively the car reacts to lead car acceleration changes.')),
    _v('TFollowDecelBoost', tr_noop('Follow Deceleration Boost'), 0, 200, 5),
    # StarPilot's weather adaptation. The state itself is detected by
    # carrot_server from Open-Meteo (or typed in by hand), so all that is left
    # to the user is how much margin each kind of bad weather should add.
    # Everything here defaults to no change, so switching it on is not by
    # itself a behaviour change.
    _h(tr_noop('Weather Adaptation')),
    _t('WeatherOffsetsEnabled', tr_noop('Weather Adaptation'),
       desc=tr_noop('Lengthen the follow time, widen the stopped gap and lower the acceleration and lateral limits in bad weather. ' +
                    'The weather is detected from the car\'s position; these offsets are what gets applied.')),
    _t('WeatherAutoDetect', tr_noop('Detect Weather Automatically'),
       desc=tr_noop('Ask Open-Meteo for the conditions where the car is, instead of entering them by hand. ' +
                    'Uses the mobile data connection while driving.')),
    _v('WeatherIncreaseFollowing', tr_noop('Extra Follow Time'), 0, 300, 10,
       fmt=lambda v: f'{v / 100.0:.1f}s',
       desc=tr_noop('Seconds added to the follow time in bad weather.')),
    _v('WeatherIncreaseStoppedDistance', tr_noop('Extra Stopped Gap'), 0, 2000, 25,
       fmt=lambda v: f'{v / 100.0:.1f}m',
       desc=tr_noop('Metres added to the distance held behind a stopped lead in bad weather.')),
    _v('WeatherReduceAcceleration', tr_noop('Acceleration Reduction'), 0, 100, 5,
       fmt=lambda v: f'{v} %',
       desc=tr_noop('Percent taken off the acceleration ceiling in bad weather.')),
    _v('WeatherReduceLateralAcceleration', tr_noop('Lateral Acceleration Reduction'), 0, 100, 5,
       fmt=lambda v: f'{v} %',
       desc=tr_noop('Percent taken off the lateral acceleration ceiling in bad weather, so curves are taken slower.')),
  ]


def build_navi_items() -> list[dict]:
  return [
    _h(tr_noop('Navigation Speed Control')),
    _v('AutoNaviSpeedCtrlMode', tr_noop('Navigation Speed Ctrl Mode'), 0, 3, 1,
       desc=tr_noop('0=Off, 1=Limit to nav speed, 2=Limit with early decel.')),
    _v('AutoNaviSpeedDecelRate', tr_noop('Navigation Speed Decel Rate'), 0, 500, 10),
    _v('AutoNaviSpeedSafetyFactor', tr_noop('Navigation Speed Safety Factor'), 50, 150, 5,
       desc=tr_noop('Percent of nav speed to use as target (100 = exact limit).')),
    _v('AutoNaviSpeedCtrlEnd', tr_noop('Navigation Speed Ctrl End Distance'), 0, 30, 1,
       desc=tr_noop('Distance after the speed limit point to resume normal cruise.')),
    _h(tr_noop('Stop / Speed Camera')),
    _t('SameSpiCamFilter', tr_noop('Same Direction Speed Cam Filter')),
    # Master switch for the traffic-light stop&go chain, placed next to the
    # other traffic-light controls where users look for it.
    _t('CarrotLongitudinalSourceEnabled', tr_noop('Traffic Light Stop & Go'),
       desc=tr_noop('Master switch for the vision traffic-light chain: brake for red lights and ' +
                    'start on green, no phone connection required. Off disables automatic ' +
                    'traffic-light stops. Phone-app longitudinal tuning (follow time, comfort ' +
                    'braking, stop point) also flows through this switch.')),
    _v('TrafficStopDistanceAdjust', tr_noop('Traffic Stop Distance Adjust'), -500, 500, 10,
       desc=tr_noop('Fine-tune stop distance for traffic lights (cm).')),
    _v('TrafficLightDetectMode', tr_noop('Traffic Light Detect Mode'), 0, 2, 1),
    _h(tr_noop('Road Speed Limits')),
    _v('SpeedFromPCM', tr_noop('Speed Source PCM'), 0, 2, 1,
       desc=tr_noop('1 = take the ACC set speed from the car (PCM). Required on Toyota: its PCM consumes the +/- buttons itself, so openpilot would otherwise keep its own set speed while the cluster moves.')),  # noqa: E501
    _v('AutoRoadSpeedLimitOffset', tr_noop('Road Speed Limit Offset'), -20, 20, 1),
    _v('RoadType', tr_noop('Road Type'), 0, 2, 1),
    _h(tr_noop('Vehicle CAN Speed Arbitration')),
    _v('VehicleSpeedCameraDistanceTime', tr_noop('Speed Camera Alert Time'), 10, 200, 1,
       desc=tr_noop('Synthesises a camera distance when the car sends only an enforcement speed. 0.1 s units; 60 = 6.0 s.')),
    _v('VehicleNaviCanControl', tr_noop('Vehicle Navi CAN Control'), 0, 3, 1,
       desc=tr_noop('Send navigation-based speed limits to the car over CAN.')),  # noqa: E501
    _t('VehicleNaviSchoolZoneControl', tr_noop('School Zone CAN Control')),
    _v('VehicleSpeedCameraControlMode', tr_noop('Speed Camera Control Mode'), 0, 3, 1),
    _h(tr_noop('Section Average Speed')),
    _t('VehicleNaviSectionAvgControl', tr_noop('Section Avg Control'),
       desc=tr_noop('Inside a point-to-point average speed section, allow up to the cruise set speed while the running average stays under the limit. Time banked in congestion is spent over the next kilometre.')),  # noqa: E501
    _v('VehicleNaviSectionAvgMargin', tr_noop('Section Avg Margin'), 0, 10, 1,
       desc=tr_noop('Km/h subtracted from the section limit as the target average. Higher = more headroom before the section cap lifts.')),
    _h(tr_noop('Speed Bumps')),
    _v('AutoNaviSpeedBumpEndDistance', tr_noop('Speed Bump End Distance'), 0, 500, 10),
    _v('AutoNaviCountDownMode', tr_noop('Countdown Mode'), 0, 2, 1),
    _v('AutoNaviSpeedBumpSpeed', tr_noop('Speed Bump Target Speed'), 0, 100, 1),
    _v('AutoNaviSpeedBumpTime', tr_noop('Speed Bump Hold Time'), 0, 20, 1),
    _h(tr_noop('Rear Camera')),
    _v('AutoNaviRearCameraHoldDistance', tr_noop('Rear Camera Hold Distance'), 0, 300, 10,
       desc=tr_noop('Distance over which navigation speed control stays paused while the ' +
                    'rear camera (reverse gear) is active, in centimetres.')),
  ]


def build_speed_items() -> list[dict]:
  return [
    _h(tr_noop('ATC Turn Control')),
    _v('AutoTurnControl', tr_noop('Auto Turn Control'), 0, 3, 1,
       desc=tr_noop('0=Off, 1=Steering only, 2=Speed + steering (default), 3=Speed only.')),
    _v('AutoTurnControlSpeedTurn', tr_noop('Auto Turn Speed Threshold'), 0, 200, 5,
       desc=tr_noop('Speed below which auto turn activates.')),
    _v('AutoTurnControlTurnEnd', tr_noop('Auto Turn End Distance'), 0, 500, 10,
       desc=tr_noop('Distance before the turn to end control.')),
    _t('AutoTurnMapChange', tr_noop('Auto Turn on Navi Lane Change')),
    _v('AutoTurnDistOffset', tr_noop('Auto Turn Distance Offset'), -200, 200, 10,
       desc=tr_noop('Shift the auto turn trigger point earlier or later.')),
    _h(tr_noop('Fork Control')),
    _v('AutoForkDistOffset', tr_noop('Fork Merge Distance Offset'), -200, 200, 10),
    _v('AutoForkDistOffsetH', tr_noop('Fork Merge Distance Offset (Highway)'), -200, 200, 10),
    _v('AutoDoForkBlinkerDist', tr_noop('Fork Blinker Trigger Distance'), 0, 500, 10),
    _v('AutoDoForkBlinkerDistH', tr_noop('Fork Blinker Trigger Distance (Highway)'), 0, 500, 10),
    _v('AutoDoForkNavDist', tr_noop('Fork Navi Trigger Distance'), 0, 500, 10),
    _v('AutoDoForkNavDistH', tr_noop('Fork Navi Trigger Distance (Highway)'), 0, 500, 10),
    _v('AutoDoForkDecalDist', tr_noop('Fork Decel Trigger Distance'), 0, 500, 10),
    _v('AutoDoForkDecalDistH', tr_noop('Fork Decel Trigger Distance (Highway)'), 0, 500, 10),
    _v('AutoForkDecalRate', tr_noop('Fork Decel Rate'), 0, 300, 10),
    _v('AutoForkDecalRateH', tr_noop('Fork Decel Rate (Highway)'), 0, 300, 10),
    _v('AutoForkSpeedMin', tr_noop('Fork Minimum Speed'), 0, 200, 5),
    _v('AutoForkSpeedMinH', tr_noop('Fork Minimum Speed (Highway)'), 0, 200, 5),
    _v('AutoKeepForkSpeed', tr_noop('Fork Keep Speed'), 0, 200, 5),
    _v('AutoKeepForkSpeedH', tr_noop('Fork Keep Speed (Highway)'), 0, 200, 5),
    _h(tr_noop('Turn Speed')),
    _v('MapTurnSpeedFactor', tr_noop('Map Turn Speed Factor'), 50, 150, 5,
       desc=tr_noop('Percent of the nav-recommended turn speed to use.')),
    _v('TurnSpeedControlMode', tr_noop('Turn Speed Control Mode'), 0, 3, 1),
    _h(tr_noop('Curve Speed')),
    _v('AutoCurveSpeedFactor', tr_noop('Curve Speed Factor'), 50, 200, 5,
       desc=tr_noop('How much lateral acceleration to allow below 80 km/h, in percent. ' +
                    'Higher slows more for curves. 100 is neutral.')),
    _v('AutoCurveSpeedAggressiveness', tr_noop('Normal Road Curve Aggressiveness'), 0, 200, 5,
       desc=tr_noop('How early to react to curves on normal roads. Lower reacts to gentler ' +
                    'curves. Only applies while Smart Cruise Control (Vision) is on.')),
    _v('AutoCurveSpeedFactorH', tr_noop('Curve Speed Factor (Highway)'), 50, 200, 5,
       desc=tr_noop('How much lateral acceleration to allow at or above 80 km/h, in percent. ' +
                    'Higher slows more for curves. 100 is neutral.')),
    _v('AutoCurveSpeedAggressivenessH', tr_noop('Highway Curve Aggressiveness'), 0, 200, 5,
       desc=tr_noop('How early to react to curves on the highway. Lower reacts to gentler ' +
                    'curves. Only applies while Smart Cruise Control (Vision) is on.')),
    _v('AutoCurveSpeedLowerLimit', tr_noop('Curve Speed Lower Limit'), 0, 100, 5),
    _v('UseLaneLineCurveSpeed', tr_noop('Lane Line Curve Speed Gate'), 0, 100, 5,
       desc=tr_noop('Below this curve speed (km/h), the lane-line curvature correction is ' +
                    'suppressed so tight bends rely on the map/vision curve speed alone. ' +
                    '0 disables the gate.')),
    _h(tr_noop('Road Limit Raising')),
    _t('AutoUpRoadLimit', tr_noop('Auto Up Road Limit')),
    _v('AutoUpRoadLimit40KMH', tr_noop('Auto Up 40 km/h Road Limit'), 0, 60, 5),
    _t('AutoUpHighwayRoadLimit', tr_noop('Auto Up Highway Limit')),
    _v('AutoUpHighwayRoadLimit40KMH', tr_noop('Auto Up 40 km/h Highway Limit'), 0, 60, 5),
  ]


def build_tuning_items() -> list[dict]:
  return [
    _h(tr_noop('FLM 转矩学习')),
    _t('FlmRuntimeOverridesEnabled', tr_noop('FLM 运行时覆盖'),
       desc=tr_noop('将 FLM 分析得到的摩擦曲线/车辆旋钮应用到转矩控制器')),
    _a(tr_noop('运行 FLM 后台分析'),
       tr_noop('停车时分析最近的行驶路线，自动整定转矩摩擦特性（要求 offroad 且车道居中关闭）'),
       tr_noop('RUN'), _flm_request_analysis),
    _s(tr_noop('分析状态'), _flm_status_text),
    _h(tr_noop('Blind Spot')),
    _t('DisableBlindSpot', tr_noop('Disable Blind Spot')),
    _v('DynamicBlindRange', tr_noop('Dynamic Blind Spot Range'), 0, 200, 5),
    _v('DynamicBlindDistance', tr_noop('Dynamic Blind Spot Distance'), 0, 200, 5),
    _v('SideBsdDelayTime', tr_noop('Side Blind Spot Delay'), 0, 50, 1),
    _v('SideRelDistTime', tr_noop('Side Relative Distance Time'), 0, 50, 1),
    _v('SidevRelDistTime', tr_noop('Side vRel Distance Time'), 0, 50, 1),
  ]


def build_display_items() -> list[dict]:
  return [
    _h(tr_noop('Steering Suspend')),
    _v('LatSuspendAngleDeg', tr_noop('Lateral Suspend Angle'), 45, 300, 1,
       fmt=lambda v: f'{v}\u00b0',
       desc=tr_noop('Steering angle at which lateral control pauses while you steer. ' +
                    '300\u00b0 effectively disables it. CarrotPilot stores 0.1-degree units for this ' +
                    'parameter but its code, like this port, compares the raw value against the ' +
                    'steering angle, so the number reads as degrees here.')),
    _h(tr_noop('Cluster Map')),
    _v('ClusterNaviMapTheme', tr_noop('Cluster Navigation Map Theme'), 0, 2, 1,
       labels={0: tr_noop('Auto'), 1: tr_noop('Dark'), 2: tr_noop('Light')}),
    _v('ClusterNaviMapType', tr_noop('Cluster Navigation Map Type'), 0, 10, 1),
    _v('ClusterNaviMapFps', tr_noop('Cluster Navigation Map FPS'), 1, 60, 1,
       desc=tr_noop('Refresh rate of the external cluster map, in frames per second.')),
    _t('CarrotNaviHudMapProfile', tr_noop('Cluster Map Profile'),
       desc=tr_noop('Enable the cluster map HUD profile overlay.')),
    _h(tr_noop('Cluster HUD (external display required)')),
    # These 16 knobs drive CarrotPilot's USB/GPU external cluster renderer. This port
    # exposes them for unified sunnypilot control and so the value survives across
    # sessions; the renderer itself is not ported yet (see the webui/gui notes).
    _t('ClusterHud', tr_noop('Cluster HUD'),
       desc=tr_noop('Master switch for the external cluster HUD renderer.')),
    _v('ClusterHudBrightness', tr_noop('Cluster HUD Brightness'), 0, 100, 1,
       fmt=lambda v: f'{v}%'),
    _v('ClusterHudCameraViewMode', tr_noop('Cluster HUD Camera View Mode'), 0, 4, 1,
       labels={0: tr_noop('Default'), 1: tr_noop('Ego Bottom'), 2: tr_noop('Road Camera'),
               3: tr_noop('Wide Camera'), 4: tr_noop('Auto Camera')}),
    _v('ClusterHudCoreMode', tr_noop('Cluster HUD Core Mode'), 0, 10, 1),
    _t('ClusterHudDebug', tr_noop('Cluster HUD Debug'),
       desc=tr_noop('Show debug overlays on the external cluster.')),
    _v('ClusterHudEncoder', tr_noop('Cluster HUD Encoder'), 0, 3, 1,
       labels={0: tr_noop('Auto'), 1: tr_noop('JPEG'), 2: tr_noop('Hardware H.264'),
               3: tr_noop('Software H.264')}),
    _v('ClusterHudLiveFps', tr_noop('Cluster HUD Live FPS'), 1, 60, 1),
    _t('ClusterHudMirror', tr_noop('Cluster HUD Mirror'),
       desc=tr_noop('Mirror the external cluster display horizontally.')),
    _v('ClusterHudOrientation', tr_noop('Cluster HUD Orientation'), 0, 3, 1),
    _v('ClusterHudPanelLayout', tr_noop('Cluster HUD Panel Layout'), 0, 1, 1,
       labels={0: tr_noop('Driving Left'), 1: tr_noop('Driving Right')}),
    _v('ClusterHudPriority', tr_noop('Cluster HUD Priority'), 0, 100, 1),
    _t('ClusterHudRadarDisplay', tr_noop('Cluster HUD Radar Display'),
       desc=tr_noop('Draw radar tracks on the external cluster.')),
    _v('ClusterHudRadarInfo', tr_noop('Cluster HUD Radar Info'), 0, 4, 1,
       labels={0: tr_noop('None'), 1: tr_noop('Vehicle Speed'), 2: tr_noop('Speed + Distance'),
               3: tr_noop('All Speeds'), 4: tr_noop('All Speeds + Distance')}),
    _t('ClusterHudRadarSourceColor', tr_noop('Cluster HUD Radar Source Color'),
       desc=tr_noop('Color radar tracks by their detection source.')),
    _v('ClusterHudScreenMode', tr_noop('Cluster HUD Screen Mode'), 0, 6, 1,
       labels={0: tr_noop('Default'), 1: tr_noop('Debug'), 2: tr_noop('Debug System'),
               3: tr_noop('Debug Graph'), 4: tr_noop('Debug Graph Right'),
               5: tr_noop('Trip Report'), 6: tr_noop('Navi')}),
    _v('ClusterHudTheme', tr_noop('Cluster HUD Theme'), 0, 2, 1,
       labels={0: tr_noop('Auto'), 1: tr_noop('Dark'), 2: tr_noop('Light')}),
  ]


def build_vehicle_items() -> list[dict]:
  return [
    _h(tr_noop('Radar / Tracks')),
    _t('EnableRadarTracks', tr_noop('Enable Radar Tracks'),
       desc=tr_noop('BYD only: feed corner-radar tracks into the radar interface.')),
    _v('SoundVolumeAdjust', tr_noop('Alert Volume'), 5, 200, 5,
       desc=tr_noop('Scale every alert sound, in percent. 100 keeps the current loudness.')),
    _v('SoundVolumeAdjustEngage', tr_noop('Engage Chime Volume'), 5, 200, 5,
       desc=tr_noop('Scale the engage / disengage / reverse chimes, in percent.')),
    # Values: 1 = linear scale, 0 = off, -1/-2/-3 = speed breakpoint profiles
    # (30/60/90, 40/80/120, 50/100/150 km/h). The code reads all of them, so this cannot
    # be a toggle - one could only ever write 0 or 1 and the profiles were unreachable.
    _v('EnableSpeedTF', tr_noop('Speed-dependent Follow Time'), -3, 1, 1,
       labels={1: tr_noop('Linear'), 0: tr_noop('Off'), -1: '30/60/90', -2: '40/80/120', -3: '50/100/150'},
       desc=tr_noop('Shrink the follow distance as speed rises. Off disables it; the three ' +
                    'profiles differ in how far up the speed range the gap keeps tightening.')),
    _h(tr_noop('Driving Mode')),
    _v('MyDrivingMode', tr_noop('My Driving Mode'), 1, 4, 1),
    _v('MyDrivingModeAuto', tr_noop('My Driving Mode Auto'), 0, 2, 1),
    _h(tr_noop('Alerts')),
    _t('MuteSeatbelt', tr_noop('Mute Seatbelt Alert'),
       desc=tr_noop('Suppress the seatbelt-not-latched engage block. The car still shows ' +
                    'its own warning; use only where the belt is genuinely fastened.')),
    _t('MuteDoor', tr_noop('Mute Door Alert'),
       desc=tr_noop('Suppress the door-open engage block. The car still shows its own ' +
                    'warning; use only if a sensor falsely reports an open door.')),
  ]


def build_dev_items() -> list[dict]:
  return [
    _h(tr_noop('Hardware / Tests')),
    _t('ShowDebugLog', tr_noop('Show Debug Log')),
    # Unified-control killswitches. All default OFF: they change vehicle
    # behaviour, so they are grouped here and opt-in. The traffic-light master
    # switch used to live here but moved to the Navigation page
    # ("Stop / Speed Camera" section) where users actually look for it.
    _h(tr_noop('Navigation Control (advanced)')),
    _t('CarrotTrafficCongestionEnabled', tr_noop('Traffic Congestion Slowdown'),
       desc=tr_noop('Fold the phone app traffic congestion report into map-based cruise ' +
                    'control. Only ever lowers the target speed. Needs Smart Cruise ' +
                    'Control - Map to be on as well.')),
    _t('CarrotNavLaneGuideBlockEnabled', tr_noop('Lane Guide Blocking'),
       desc=tr_noop('Let the phone app guided-lane arrows block lane changes toward ' +
                    'non-guided lanes. Only ever adds blocking.')),
    _h(tr_noop('ONNX Vision Detection (BSD / Lane)')),
    # Master switch for the xiaoge v_asm ONNX blind-spot / lane server. Off
    # unloads the resident model entirely (see carrot/xiaoge/v_asm_server.py),
    # so the toggle also gates whether the thresholds below do anything.
    _t('OnnxBsdEnabled', tr_noop('ONNX Blind Spot Detection'),
       desc=tr_noop('Run the ONNX blind-spot model on the camera image and report ' +
                    'side obstacles in the UI. Off unloads the model and frees its ' +
                    'memory; the thresholds below have no effect.')),
    # Thresholds and cadence for the xiaoge v_asm ONNX blind-spot / lane server.
    # Ranges mirror the clamps in carrot/xiaoge/v_asm_server.py; anything outside
    # is silently clamped there, so the UI cannot write an unusable value.
    _v('OnnxBsdThreshold', tr_noop('BSD Detection Threshold'), 25, 100, 5,
       desc=tr_noop('Confidence threshold for ONNX blind-spot detection, in percent. ' +
                    'Higher means fewer, more certain detections.')),
    _v('OnnxBsdSmoothingMs', tr_noop('BSD Smoothing Time'), 100, 500, 50,
       fmt=lambda v: f'{v} ms',
       desc=tr_noop('How long a blind-spot object must persist before it is reported.')),
    _v('OnnxBsdIntervalMs', tr_noop('BSD Inference Interval'), 50, 1000, 50,
       fmt=lambda v: f'{v} ms',
       desc=tr_noop('Time between blind-spot inferences.')),
    _v('OnnxLaneThreshold', tr_noop('Lane Detection Threshold'), 5, 100, 5,
       desc=tr_noop('Confidence threshold for ONNX lane detection, in percent.')),
    _v('OnnxLaneIntervalMs', tr_noop('Lane Inference Interval'), 600, 2000, 100,
       fmt=lambda v: f'{v} ms',
       desc=tr_noop('Time between lane inferences. Values below 600 ms are raised by the ' +
                    'server, which would saturate a CPU core.')),
  ]


# Group key -> items builder, mirroring the Big GUI build_*_items() set.
# The eGPU group is not here: it is a custom status page (carrot_egpu.py).
CARROT_ITEM_BUILDERS: dict[str, callable] = {
  'start': build_start_items,
  'cruise': build_cruise_items,
  'navi': build_navi_items,
  'speed': build_speed_items,
  'tuning': build_tuning_items,
  'display': build_display_items,
  'vehicle': build_vehicle_items,
  'dev': build_dev_items,
}
