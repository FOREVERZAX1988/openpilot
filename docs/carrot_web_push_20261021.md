# carrot_server: PWA 安装性 + Web Push（上游 059d384378）

上游提交：`059d38437846b55c393d543e2c9e84eb2fcb47c1` — "carrot_server: PWA installability +
Web Push (Galaxy-inspired)"（2026-10-20 16:15 +0800）

## 为什么搬

面板目前只能在手机浏览器里打开，装不到桌面、也没法在 offroad 事件（更新失败、上传失败、
错误弹窗）时主动通知到人。上游这条把面板做成可安装的 PWA 并接上标准 Web Push
（RFC 8291 加密 / RFC 8292 VAPID），纯 server + 前端，不依赖车、不依赖行车状态。

**与既有通知通道是否重复**（注册表里这条的 next 就是问这个）：不重复。
`services/support_discord.py`、`services/dashcam_upload_report.py`、`services/vision_diag.py`
都是往第三方（Discord webhook / 上游服务）发消息，走公网、需要配置凭据；Web Push 是
手机本机的浏览器推送，端点由浏览器分配，车机只在本地存订阅，不引入新的外部服务凭据。

## 落地内容（本树文件）

| 文件 | 作用 |
| --- | --- |
| `server/features/push.py` | `/sw.js`、`/manifest.webmanifest`、`/push` 页面，以及 `/api/push/{status,subscribe,unsubscribe,test}` |
| `server/services/web_push.py` | VAPID 密钥生成、aes128gcm 载荷加密、ES256 JWT 签名、推送发送（只依赖 `cryptography`） |
| `server/features/static.py` | 首页注入 `<link rel="manifest">` + `<meta name="theme-color">` + service worker 注册脚本 |
| `web/manifest.webmanifest`、`web/sw.js` | PWA 清单与 Service Worker（API 网络优先、静态资源缓存优先、push/notificationclick 处理） |
| `web/push.html` | 手机侧订阅页（开启/测试/关闭通知 + 非安全上下文提示） |
| `server/config.py` | 新增 `CARROT_WEB_PUSH_PATH`（state 文件位置） |

## 与上游的差异（local_fix）

1. **状态存文件，不放 Params。** 上游把 VAPID 密钥与订阅写进 Params
   （`WebPushVapidKeys` / `WebPushSubscriptions`）。本仓 Params 是 `params_keys.h` 编译期的
   严格键表（未知键会抛 `UnknownKeyName`），加两个键必须重建 `libparams_c.so`；而在本机
   `scons -j1` 编 `params.cc` 时 `clang++` 被 lowmemorykiller 直接杀掉
   （`dmesg`：`lowmemorykiller: Killing 'clang++' ... to free 1998980kB`），重建做不了。
   于是改为 `/data/carrot/state/web_push.json`（临时文件 + `os.replace` 原子写），
   `params_keys.h` 里那两行**已撤回**，这条移植因此没有任何编译依赖。
   代价：这两个值不进 Params 备份。订阅本身就是一次性的，重装重扫即可。
2. **多一个 `/push` 页面。** 上游只有 API；Service Worker / Push 权限必须由用户手势在安全
   上下文里触发，所以配一个自包含页面，顺手把「http 局域网不能推送」写在页面上。
3. **manifest 图标用真实尺寸，并补齐 192/512。** 最初只声明 `800x800`
   （对应 `selfdrive/assets/img_spinner_comma.png` 的真实尺寸），现场实测**不够**：Chrome 的
   可安装判定要 `192x192` 与 `512x512` 两个尺寸（外加一个 `maskable`），只有 800 不弹安装入口。
   现在 `web/icons/` 里由 800 源图裁出 `icon-192.png` / `icon-512.png` /
   `icon-maskable-512.png`（maskable 版把 logo 缩到 72% 摆在中性底色上，圆角遮罩不会切掉轮子），
   manifest 同时保留 800 那条。
4. `pyproject.toml` 给 `web_push.py` 开 `TID251`：VAPID 的 `exp` 按 RFC 8292 必须是
   wall-clock epoch 秒，不能走 `time.monotonic` 系。

## 验证（车机 offroad，2026-10-21 01:0x，`192.168.10.79:7000`）

- `pytest openpilot/sunnypilot/carrot/server/tests/test_web_push.py` → **8 passed**
  （密钥可加载、载荷与浏览器侧密钥对能解密回原文、超大载荷拒发、JWT 形状与签名可验、
  订阅去重往返、manifest/sw/页面内容、图标尺寸与真实文件一致）
- carrot_server 全套 → **144 passed, 48 skipped**；`ruff check server/` → All checks passed
- 现场 curl：`/push` 200 `text/html`；`/manifest.webmanifest` 200 `application/manifest+json`；
  `/sw.js` 200 `application/javascript`；`/api/push/status` 200，首次调用即生成 VAPID 键并落盘
  （`/data/carrot/state/web_push.json`，公钥 87 字符 b64url = 65 字节）
- 首页注入：`curl /` 里能看到 manifest link、`theme-color`、`serviceWorker.register('/sw.js')`
- `POST /api/push/test`（无订阅）→ 404 `{"error": "no subscriptions"}`，符合预期

## 待驾驶者验收（手机侧，两步）

1. 手机和车机同一个局域网，打开 `http://192.168.10.79:7000/push`：能看到订阅状态，但 http
   不是安全上下文，浏览器不会注册 Service Worker，页面上有黄字说明。这一步只验页面可达。
2. 真正收到推送要 https：用 carrot 里的 cloudflared 隧道拿一个 `https://<随机>.trycloudflare.com`
   域名，手机打开 `https://<域名>/push` → 点「开启通知」允许权限 → 点「发送测试通知」，
   手机应弹出系统通知。前提是车机能出网（浏览器的推送端点在公网），且隧道进程活着。

## 回滚

没有 Param 键、没有编译产物：把 `push_feature.register(app)`、`static.py` 的 `_inject_pwa`
与 `/push` 路由去掉即可，`web_push.json` 留着也无害。

## 现场问题与修复（2026-10-21 06:1x，手机实测）

驾驶者用 `https://expert-hold-movers-cosmetics.trycloudflare.com/push` 验收，三个症状：
点「开启通知」直接返回 `通知权限被拒绝：denied`（浏览器没弹窗）；「发送测试通知」返回
`{"error":"no subscriptions"}`；页面上也没有「添加到主屏幕 / 安装」。

**服务端全绿，是客户端问题。** 现场取证（`127.0.0.1:7000`，同一进程）：
`/push` 200、`/manifest.webmanifest` 200 `application/manifest+json`、
`/sw.js` 200 `application/javascript`、`/shared-assets/img_spinner_comma.png` 200 256KB、
`/api/push/status` 200 且 VAPID 公钥稳定（`/data/carrot/state/web_push.json` 已落盘）。
隧道本身也活着（curl 隧道域名 `/api/push/status` → 200，0.96s）。
`subscriptions: 0` 是**结果**不是原因：权限被拒 → 页面在 `Notification.requestPermission()`
处就 return 了，压根没走到 `pushManager.subscribe`，所以设备端没有订阅可发。

根因三条，都已修：

1. **Service Worker 只在权限通过之后才注册。** 原 `enable()` 先申请权限、后
   `register('/sw.js')`。权限一旦是 `denied`，SW 永远不注册 → 页面不可安装（Chrome 要 SW +
   manifest 才给安装入口）→ 也就没有「添加到主屏幕」。但这正好是最需要修的时候。
   现在 `push.html` 在页面加载时**无条件**注册 SW（与 `static.py` 给首页注入的注册同款），
   权限申请挪到 SW `ready` 之后。`enable()` 里若 `Notification.permission === 'denied'`
   直接走引导，不再假装能弹窗。
2. **`denied` 是不可逆状态，必须给复位路径。** 浏览器只会弹一次，之后
   `requestPermission()` 恒返回 `denied`，页面却只打一行日志。现在识别 Android / iOS / 桌面
   三种平台，分别给出复位步骤（系统层浏览器通知权限、地址栏锁图标 → 权限 → 通知、
   Chrome 站点设置），并加「重新检查」按钮。另加 App 内置浏览器识别
   （微信/QQ/抖音/小红书/B站等 webview 一律直接 `denied` 且不支持安装），命中时置顶提示改用
   Chrome/Safari。
3. **manifest 缺 192/512 图标。** 见 §「与上游的差异」第 3 条，已补
   `icon-192.png` / `icon-512.png` / `icon-maskable-512.png` + `id: "/"` +
   `display_override`，`static.py` 与 `push.html` 都加了 `apple-touch-icon` 与
   `apple-mobile-web-app-*`（iOS 只能从主屏图标唤起才给 standalone）。
   `push.html` 另接了 `beforeinstallprompt`，把「添加到主屏幕」做成了显式按钮，
   `matchMedia('(display-mode: standalone)')` 判断是否已装。

顺带加固：`sw.js` 的 `install` 原来 `cache.addAll(['/'])` 一旦失败整个 SW 装不上（等于推送
全废），改成单个 `cache.add('/')` + `.catch(()=>{})`；shell 缓存版本升到 `carrot-shell-v2`
让老客户端换掉旧 SW。`push.html` 顶部状态行现在直接打印
`权限 / SW 是否接管 / 本机订阅 / display-mode`，下次一眼看出卡在哪一环。

**验证**：`unittest openpilot.sunnypilot.carrot.server.tests.test_web_push` → 6 passed
（新增 `TestPwaInstallability`：manifest 必须有 `192x192:any`、`512x512:any`、
`512x512:maskable`，且每个 `/icons/*` 声明的尺寸与 PNG 头里的真实尺寸一致）；
`ruff check` 通过；改完 kill 掉 carrot_server（manager 会重拉，新 pid 527214）后现场复查：
首页 head 已带 manifest + apple-touch-icon + 三个 apple meta，`/icons/*.png` 200 image/png。

**注意**：trycloudflare 临时隧道每次重启域名都变，等于每次都是新站点——permission、
SW、订阅全部从零开始。验收请在同一个域名上从头走一遍，别跨域名对比状态。
