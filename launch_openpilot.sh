#!/usr/bin/env bash

# API_HOST / ATHENA_HOST export 已于 2026-10-26 删除：没有任何代码读取这两个变量
# (死配置)。athenad 的服务器由 params UseKonikServer 动态决定，见
# openpilot/system/athena/athenad.py get_athena_host()。
exec ./launch_chffrplus.sh
