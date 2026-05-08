# Telegram UserBot 飞书提醒监听器

监听 Telegram 群聊 @ 我的消息和私聊消息. 收到后启动倒计时, 如果在期限内
我没有在该聊天中发送任何消息, 则通过飞书 Webhook 发送提醒.

## 安全边界 (重要, 请先读)

- **仅做 incoming 监听**: 程序不会主动给任何用户/群组发送 Telegram 消息.
- **不群发, 不营销, 不自动回复**: 你的账号只用来"接收触发", 由你本人决定是否回复.
- **隐私可控**: 飞书提醒中是否包含原始消息内容由配置项 `INCLUDE_MESSAGE_TEXT`
  控制 (默认 `true`, 关闭后只发送摘要).
- **不绕过 Telegram 限制**: 触发判断只看消息事件本身, 不做自动批量操作,
  也不调用任何 send_message API.
- **服务器需访问 Telegram API**: 推荐 HK / SG / US 等非大陆 VPS, 否则需要
  自己配置代理 (见"常见问题").
- **`.session` 文件 = 你的 Telegram 账号身份**: 等同于密码, 严禁 commit 到 git
  或泄漏给他人 (`.gitignore` 已默认忽略 `*.session`).

---

## 工作流程

```
群聊收到 "@我" 消息 / 私聊他人消息
        |
        v
TelegramListener -> 构造 PendingReminder
        |
        v
ReminderManager.schedule(reminder)
   |  以 chat_id 为 key
   |  若已有未到期 task -> 保留更早的, 不刷新倒计时
   v
asyncio.sleep(REMINDER_SECONDS)   <-- 倒计时
        |
        +--> 期间我在该 chat 发送任意消息 -> on_self_reply -> cancel(chat_id) -> task 取消, 不发送
        |
        +--> 倒计时结束未回复
                 |
                 v
        FeishuNotifier.send(payload) -> 飞书自定义机器人 webhook
```

要点:

- 同一个 chat 同时只会有 1 个 pending task. 多条触发消息进来, 保留最早的
  那条, 不会推迟倒计时. 这样**被刷屏的群也一定会按原始倒计时提醒**, 不会
  被新消息无限延后.
- 取消是按 `chat_id` 粒度: 我在该 chat 内说任意一句话 (即便不是回复触发消息)
  都会取消提醒.
- 飞书发送失败只 log, 不会影响后续提醒.

---

## 安装

```bash
git clone <repo-url>
cd UserBot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入凭据
```

需要 Python 3.10+.

---

## 配置项详解

所有配置都通过环境变量读取, 推荐写在 `.env` 里 (项目根目录, 已被 `.gitignore`).

| 字段 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `TG_API_ID` | 是 | - | Telegram API ID, 在 https://my.telegram.org → API development tools 申请 |
| `TG_API_HASH` | 是 | - | Telegram API Hash, 同上 |
| `TG_SESSION_NAME` | 否 | `userbot` | Telethon session 文件名 (不带 `.session` 后缀); 也可填绝对路径如 `/app/sessions/userbot` 用于持久化 |
| `FEISHU_WEBHOOK_URL` | 是 | - | 飞书自定义机器人 webhook URL, 形如 `https://open.feishu.cn/open-apis/bot/v2/hook/xxxx` |
| `FEISHU_SECRET` | 否 | 空 | 飞书机器人启用签名校验时的密钥; 不启用留空 |
| `REMINDER_SECONDS` | 否 | `300` | 倒计时秒数; 收到触发后多少秒未回复则发提醒 |
| `ENABLE_PRIVATE_CHAT` | 否 | `true` | 是否启用私聊触发. `false` 时仅监听群聊 @ |
| `INCLUDE_MESSAGE_TEXT` | 否 | `true` | **隐私敏感**. `false` 时飞书 payload 不含消息原文, 只发送 `chat_title + sender + 时间 + 跳转链接` |
| `WHITELIST_CHAT_IDS` | 否 | 空 | 白名单 chat_id, 逗号分隔. 非空时仅监听这些 chat |
| `BLACKLIST_CHAT_IDS` | 否 | 空 | 黑名单 chat_id, 逗号分隔. 命中则忽略 |
| `LOG_LEVEL` | 否 | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` (大小写不敏感) |
| `BARK_DEVICE_KEY` | 否 | 空 | Bark iOS 推送 device key (https://bark.day.app), 留空则禁用 Bark, 仅飞书 |
| `BARK_SERVER_URL` | 否 | `https://api.day.app` | Bark 服务器, 自建实例可改 |
| `BARK_CRITICAL` | 否 | `true` | 用 `critical` 级别推送 (绕过静音/勿扰), 需 iOS 设置允许"重要警告" |
| `BARK_CALL` | 否 | `true` | `call=1` 让铃声重复 30 秒, 像电话一样 |
| `BARK_SOUND` | 否 | 空 | 自定义铃声名 (Bark 内置), 留空用默认 |

获取 chat_id: 跑起来后留意日志中的 `chat_id=...`, 或临时把 `LOG_LEVEL=DEBUG`
看每条消息的 chat_id.

---

## Bark iOS 推送 (可选, 强烈推荐)

光发飞书消息容易被忽略, Bark 可以让 iPhone **像来电一样持续响铃 30 秒**, 即使
手机静音/勿扰也能被叫醒. 推荐和飞书一起用 (二者并发推送, 互不影响).

启用步骤:

1. iPhone App Store 搜 "Bark" → 安装并打开 App.
2. App 首页能看到一段形如 `https://api.day.app/xxxxxxxxxxxx/` 的 URL,
   把中间的 device key 填到 `.env` 的 `BARK_DEVICE_KEY=...`.
3. **重要**: iOS 设置 → 通知 → Bark → 打开"重要警告 (Critical Alerts)".
   不开这个 `critical` 级别就无法绕过静音模式.
4. 重启 UserBot, 看到 `bark notifier enabled` 即生效.

调节强度:

- `BARK_CRITICAL=false` — 关闭 critical (普通推送, 不绕过静音)
- `BARK_CALL=false` — 关闭持续响铃 (只响一声)
- 两个都关 = 普通通知, 看心情用

测试:

```bash
curl -X POST "https://api.day.app/<你的key>" \
  -H "Content-Type: application/json" \
  -d '{"title":"测试","body":"hello","level":"critical","volume":10,"call":"1"}'
```

收到响铃 = 配置正确. 没响就检查 critical alerts 权限.

## 飞书机器人创建步骤

1. 打开飞书 App, 进入要接收提醒的群聊 (建议单独建一个"个人提醒"群).
2. 群设置 (右上角齿轮) → **群机器人** → **添加机器人** → 选择 **自定义机器人**.
3. 给机器人起名 (例如 "TG-UserBot 提醒"), 选个头像.
4. 安全设置至少选一项, 推荐 **签名校验**:
   - 选 "签名校验" → 复制下方密钥, 填到 `.env` 的 `FEISHU_SECRET`.
   - 也可选 "自定义关键词", 但本程序的消息标题固定为 "Telegram 未回复提醒",
     如果走关键词路线请把关键词设成 "提醒".
   - 不要选 "IP 白名单", 除非你的 VPS 有固定出口 IP.
5. "完成" → 复制弹出的 webhook URL, 填到 `.env` 的 `FEISHU_WEBHOOK_URL`.

---

## 首次运行 (Telethon 登录)

```bash
source .venv/bin/activate
python -m userbot
```

首次运行 Telethon 会要求登录:

```
Please enter your phone (or bot token): +8613xxxxxxxxx
Please enter the code you received: 12345
Please enter your password (二步验证密码, 没设就直接回车): ********
```

成功后会在当前目录生成 `userbot.session` 文件 (或 `TG_SESSION_NAME` 指定的路径).

> **警告**: `.session` 文件 = 你的 Telegram 账号身份, 等同于密码:
> - 不要 commit 到 git (项目 `.gitignore` 已默认忽略 `*.session`)
> - 不要发给别人, 不要传到云盘
> - 部署到服务器时, 文件权限设为 `600` (`chmod 600 userbot.session`)
> - 泄漏后立即在 Telegram 设置里 "Active sessions" 终止该 session

二次启动不再需要登录, 直接读取 session 文件.

看到日志 `Logged in as <你的名字>` 和 `Listening for mentions and private messages`
就是成功. 此时让朋友在群里 @ 你 (或私聊你), 不要回复, 等 5 分钟应该收到飞书提醒.

---

## 部署

### A. systemd (Linux VPS, 推荐生产用)

`deploy/userbot.service` 已经写好, 顶部注释里有完整安装步骤. 简要:

```bash
# 在 VPS 上
sudo useradd -r -m -d /opt/userbot userbot
sudo -u userbot git clone <repo-url> /opt/userbot
cd /opt/userbot
sudo -u userbot python3 -m venv .venv
sudo -u userbot .venv/bin/pip install -r requirements.txt
sudo cp .env.example .env  # 编辑填入凭据
sudo chown userbot:userbot .env && sudo chmod 600 .env

# 首次以 userbot 用户在前台跑一次完成 Telethon 登录
sudo -u userbot .venv/bin/python -m userbot
# 看到 "Logged in as ..." 后 Ctrl-C 退出

# 安装并启用 systemd unit
sudo cp deploy/userbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now userbot.service
sudo journalctl -u userbot.service -f
```

unit 已配置 `Restart=on-failure`, 异常崩溃会自动拉起. 想停就 `sudo systemctl stop userbot`.

### B. Docker Compose (推荐, 最简)

项目已带 `docker-compose.yml`, 三条命令搞定:

```bash
# 第一次: 交互式登录, 输入手机号 + 验证码, 看到 "Listening for mentions..." 后 Ctrl-C
docker compose run --rm userbot

# 之后每天: 后台启动
docker compose up -d

# 看日志 (跟随)
docker compose logs -f

# 停止
docker compose down
```

补充:

- `docker compose up -d --build` — 改了代码后重建镜像并起
- `docker compose stop` / `docker compose start` — 不删容器, 只停/起
- `docker compose restart` — 重启 (例如改了 `.env` 后)
- session 持久化在 `./sessions/userbot.session`, 容器重建不丢登录
- `restart: unless-stopped` 已配置, 容器/宿主机重启后自动拉起
- 日志限制 30MB (`max-size: 10m`, `max-file: 3`), 不会撑爆磁盘

### C. 纯 Docker (不用 compose 时)

```bash
docker build -t userbot .

# 首次: 交互式登录
docker run --rm -it \
  --env-file .env \
  -v $(pwd)/sessions:/app/sessions \
  userbot
# 看到 "Logged in as ..." 后 Ctrl-C

# 后台运行
docker run -d --name userbot \
  --env-file .env \
  -v $(pwd)/sessions:/app/sessions \
  --restart unless-stopped \
  userbot
```

`.session` 文件位于容器内 `/app/sessions/userbot.session` (Dockerfile 中
`TG_SESSION_NAME=/app/sessions/userbot`); 必须挂载持久卷否则容器重建要重新登录.

### D. tmux / nohup (单机简易, 不推荐生产)

```bash
nohup .venv/bin/python -m userbot > userbot.log 2>&1 &
disown
```

或 tmux:

```bash
tmux new -s userbot
.venv/bin/python -m userbot
# Ctrl-B D 脱离 (detach), 进程仍在跑
# tmux attach -t userbot 重新连上看日志
```

无自动重启, 进程挂了不会拉起, 建议只用于本地测试.

---

## 隐私

`INCLUDE_MESSAGE_TEXT=false` 时, 飞书 payload 不会包含消息原文, 只有元信息.

**对比示例** (实际飞书机器人会显示成 markdown 卡片):

`INCLUDE_MESSAGE_TEXT=true` (默认):

```
标题: Telegram 未回复提醒
群/聊天: 工作群
发送人: 张三 (id: 123456789)
时间: 2026-05-08T15:30:42
内容: 这个 PR 你看下啊?
跳转到消息  ← 超链接
```

`INCLUDE_MESSAGE_TEXT=false`:

```
标题: Telegram 未回复提醒
群/聊天: 工作群
发送人: 张三 (id: 123456789)
时间: 2026-05-08T15:30:42
跳转到消息  ← 超链接
```

后者飞书侧不再保存任何消息文本; 只能通过点击"跳转到消息"回到 Telegram 查看.
适合工作消息或群里有合规要求时使用.

注: `chat_title` (群名) 始终会发送; 如果群名本身敏感, 建议把该 chat_id 加入
`BLACKLIST_CHAT_IDS` 直接不监听.

---

## 常见问题

**FloodWait 错误**

Telethon 收到 Telegram `FloodWaitError` 会自动 sleep 后重试, 一般不需要干预.
日志会出现 `Sleeping for X seconds (FloodWaitError)`. 如果频率非常高, 检查
是不是把同一账号在多处登录监听 (会互相挤掉 session).

**网络访问不到 Telegram**

国内服务器跑会失败 (`ConnectionError` / DNS 超时). 解决:

- 换 VPS 到 HK / SG / US.
- 或在代码里加 socks 代理. 修改 `userbot/main.py` 中的 `TelegramClient` 构造:

  ```python
  import socks
  client = TelegramClient(
      config.session_name, config.api_id, config.api_hash,
      proxy=(socks.SOCKS5, "127.0.0.1", 1080),
  )
  ```

  需要 `pip install pysocks`.

**时间戳错误 / 飞书签名失败**

服务器系统时间偏差超过几分钟会导致飞书签名校验失败 (`sign match fail`).
确保 NTP 已同步:

```bash
timedatectl status     # 查看 System clock synchronized: yes
sudo timedatectl set-ntp true
```

**.session 怎么迁移到另一台机器**

把 `userbot.session` 文件 (和 `.session-journal` 如果有的话) 一起拷过去, 放到
`TG_SESSION_NAME` 指向的位置, 不需要重新登录. 注意权限和加密传输.

**重新登录 / 切账号**

删除 `userbot.session` 文件再启动, 会重新走登录流程.

**飞书 webhook 返回 19021 等错误**

19021 = 签名校验失败, 检查 `FEISHU_SECRET` 和服务器时间.
9499 = webhook 不存在或被禁用, 检查 URL 是否复制完整.
其他错误参考飞书文档 https://open.feishu.cn/document/.

---

## 调试

```bash
LOG_LEVEL=DEBUG python -m userbot
```

DEBUG 级别会打印:

- 每条 incoming/outgoing 消息的过滤判断 (是否触发, 是否在白/黑名单)
- 飞书 webhook 实际响应
- Telethon 自身的 DEBUG 日志

定位"为什么没有触发"的问题, 先开 DEBUG 看 `chat_id`, `mentioned`, `is_private`
这几个字段.

---

## 项目结构

```
UserBot/
├── README.md
├── Dockerfile
├── docker-compose.yml         # docker compose 一键启停
├── requirements.txt
├── .env.example
├── .gitignore
├── deploy/
│   └── userbot.service        # systemd unit
└── userbot/
    ├── __init__.py            # 接口契约 + PendingReminder
    ├── __main__.py            # python -m userbot 入口
    ├── main.py                # 装配 + 生命周期管理
    ├── config.py              # 环境变量加载
    ├── logging_setup.py       # 日志格式
    ├── telegram_listener.py   # Telethon 事件监听
    ├── reminder_manager.py    # 倒计时管理
    ├── feishu_notifier.py     # 飞书 webhook 推送
    ├── bark_notifier.py       # Bark iOS 推送 (可选)
    └── broadcast_notifier.py  # 多通道并发广播
```

---

## License

仅供个人使用. 使用本程序需自行遵守 Telegram 服务条款及当地法律法规.
