# 2026-09-19 MLB 纵向：panda 拒发所有 OP ACC 帧（融合模式退化成纯原厂 ACC）

设备 tizi（branch macan-long-0919，panda H7/TRES 内置）

## 现场
- 参数正常：MacanFusionMode=1、MacanRadarFusion=1、AlphaLongitudinalEnabled=1，CarParams openpilotLongitudinalControl=True
- 007b 路试 rlog：OP 自算的 ACC_02/0x30c、ACC_05/0x10d、ACC_04/0x324 每帧 src=192（panda rejected），
  bus0 上只剩原厂雷达那份被转发（src=128 与雷达逐字节相同）→ 车按原厂雷达执行 = 体感“纯原厂 ACC”
- panda 上报 safetyModel=volkswagenMlb、safetyParam=1（LONG 标志确实发下去了）

## 根因（合并引入的回归）
- volkswagen_mlb_init() 顺序：先 `volkswagen_longitudinal = GET_FLAG(param, FLAG_VOLKSWAGEN_LONG_CONTROL)`，
  后 `volkswagen_common_init()`
- 上游 be1c003478 “VW: good safety practices (#3607)” 给 volkswagen_common_init() 加了
  `volkswagen_longitudinal = false;`（我方合并前版本没有这行）
- master-c3 合并（cb943a5c6b）把这行带进来 → MLB 读到标志后立刻被清零 → 装的是
  VOLKSWAGEN_MLB_STOCK_TX_MSGS（只有 HCA_01/LDW_02/LS_01）
- MQB/PQ 是“先 common_init 再读标志”，所以只有 MLB 中招；subaru.h 也是先读后 init，但变量不同，已扫过确认无此问题
- 副作用：rx 侧 LS_01 按键接合逻辑也未生效（改走 pcm_cruise_check(TSK_04)）

## 修复
- opendbc ab5549ede0：与 MQB/PQ 对齐——先 `volkswagen_common_init()`，再读标志
- 新增 TestVolkswagenMlbLongSafety 回归守卫：带 LONG_CONTROL 时必须能发 ACC_02/05/04；不带标志时必须全拒
  （把该头文件回滚成旧顺序 → 守卫 3 个用例变红，已实测）
- 测试：test_volkswagen_mlb.py 132 passed（stock 66 + long 66）；mqb/pq 各自 OK；
  meb 的 112 个失败在本改动前后完全一致（既有问题，git stash 对照确认）

## 推送 + 刷机
- opendbc_repo ab5549ede0 → FOREVERZAX1988/opendbc macan-long-0919
- 主仓库 7f56ff4450（bump opendbc_repo）→ FOREVERZAX1988/openpilot macan-long-0919
- 设备 `scons -u` 重编 panda 固件（H7：panda_h7.bin.signed），flash_panda_firmware 刷入
- 刷后签名 8fd37f91029ea794 == expected，firmware_match=true，pandad 存活；刷机瞬间有一条
  “panda timed out onroad”瞬时错误，其后无重复

## 下次路试要看的
1. 0x30c/0x324/0x10d 不应再出现 src=192（OP 的帧要真的出得去）
2. 原厂雷达的 0x30c/0x324/0x10d 不再被转发到 bus0（LONG 配置里这些是 check_relay）
3. LS_01 接合语义变成“主开关 + SET/RESUME 上升沿”（不再走 TSK_04 pcm_cruise_check）
4. 0x10B 从 bus0→bus2 不再转发（OP 自己发 bus2）
LONG 配置此前从未真正生效过，所以这些行为变化首次上线，需要路试验证。
