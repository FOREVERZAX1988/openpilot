#!/usr/bin/env bash

# ===== 只在真正断电冷启动时重启一次 =====
BOOT_ID_FILE="/data/.last_boot_id"
REBOOT_FLAG="/data/.cold_boot_rebooted"

CUR_BOOT_ID=$(cat /proc/sys/kernel/random/boot_id)

# 第一次运行（设备刚刷机 / 第一次上电）
if [ ! -f "$BOOT_ID_FILE" ]; then
  echo "$CUR_BOOT_ID" > "$BOOT_ID_FILE"
  sync
fi

LAST_BOOT_ID=$(cat "$BOOT_ID_FILE")

# 判断是否为“断电冷启动”
if [ "$CUR_BOOT_ID" != "$LAST_BOOT_ID" ]; then
  # 是新的上电启动
  if [ ! -f "$REBOOT_FLAG" ]; then
    echo "[cold-boot] power-on detected, reboot once"

    touch "$REBOOT_FLAG"
    echo "$CUR_BOOT_ID" > "$BOOT_ID_FILE"
    sync
    sleep 2

    reboot
    exit 0
  fi
fi

# 更新 boot_id（正常路径）
echo "$CUR_BOOT_ID" > "$BOOT_ID_FILE"
sync

# ===== 原有逻辑 =====
export ATHENA_HOST='ws://athena.mr-one.cn'
export API_HOST='http://res.mr-one.cn'

exec ./launch_chffrplus.sh
