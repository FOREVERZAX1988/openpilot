#!/usr/bin/env bash

# ===== 冷启动只重启一次 =====
FLAG_FILE="/data/.cold_boot_rebooted"

if [ ! -f "$FLAG_FILE" ]; then
  echo "[cold-boot] first boot, reboot once"

  touch "$FLAG_FILE"
  sync
  sleep 2

  reboot
  exit 0
fi

# ===== 原有环境变量 =====
export ATHENA_HOST='ws://athena.mr-one.cn'
export API_HOST='http://res.mr-one.cn'

# ===== 启动主程序 =====
exec ./launch_chffrplus.sh
