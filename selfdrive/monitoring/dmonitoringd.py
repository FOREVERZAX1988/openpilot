#!/usr/bin/env python3
import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import config_realtime_process
from openpilot.selfdrive.monitoring.helpers import DriverMonitoring


def dmonitoringd_thread():
  config_realtime_process([0, 1, 2, 3], 5)

  params = Params()
  pm = messaging.PubMaster(['driverMonitoringState'])
  sm = messaging.SubMaster(['driverStateV2', 'liveCalibration', 'carState', 'selfdriveState', 'modelV2',
                            'carControl'], poll='driverStateV2')

  DM = DriverMonitoring(
    rhd_saved=params.get_bool("IsRhdDetected"),
    always_on=params.get_bool("AlwaysOnDM"),
    distraction_detection_level=int(params.get("DistractionDetectionLevel") or 1)
  )
  demo_mode=False

  # 20Hz <- dmonitoringmodeld
  while True:
    sm.update()
    if not sm.updated['driverStateV2']:
      # iterate when model has new output
      continue

    # 1. 基础状态检查
    valid = sm.all_checks()
    # 2. 分支1：演示模式（无需always_on，仅driverStateV2有效即可）
    if demo_mode and sm.valid['driverStateV2']:
        DM.run_step(sm, demo=demo_mode)
        # 演示模式下也可按需配置分心率
        DM.set_distract_level_params()
    # 3. 分支2：正式运行（需同时满足always_on和整体有效）
    elif DM.always_on and valid:
        DM.run_step(sm)  # 正式模式不传demo参数
        DM.set_distract_level_params()  # 必配分心率参数

    # publish
    dat = DM.get_state_packet(valid=valid)
    pm.send('driverMonitoringState', dat)

    # load live always-on toggle
    if sm['driverStateV2'].frameId % 40 == 1:
      DM.always_on = params.get_bool("AlwaysOnDM")
      demo_mode = params.get_bool("IsDriverViewEnabled")
      DM.distraction_detection_level = int(params.get("DistractionDetectionLevel") or 1)

    # save rhd virtual toggle every 5 mins
    if (sm['driverStateV2'].frameId % 6000 == 0 and not demo_mode and
     DM.wheelpos.prob_offseter.filtered_stat.n > DM.settings._WHEELPOS_FILTER_MIN_COUNT and
     DM.wheel_on_right == (DM.wheelpos.prob_offseter.filtered_stat.M > DM.settings._WHEELPOS_THRESHOLD)):
      params.put_bool_nonblocking("IsRhdDetected", DM.wheel_on_right)

def main():
  dmonitoringd_thread()


if __name__ == '__main__':
  main()
