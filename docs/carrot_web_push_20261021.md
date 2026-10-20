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
3. **manifest 图标用真实尺寸。** 声明 `800x800`（对应 `selfdrive/assets/img_spinner_comma.png`
   的真实尺寸）。上游写 `any`，Chrome 对 PNG 不做 `any` 的可安装判定，会拒掉安装提示。
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
