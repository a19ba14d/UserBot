"""Telegram UserBot + 飞书提醒.

仅做 incoming 监听: 群聊 @ 我 / 私聊消息触发倒计时, 未在期限内由"我"
回复则通过飞书 Webhook 推送提醒. 绝不主动群发任何 Telegram 消息.

================================================================
模块接口契约 (Inter-module Interface Contract)
================================================================

本文件定义了 Agent 2/3/4/5 必须遵守的接口契约, 用于跨模块协作.

任何修改本文件中导出的 ``PendingReminder`` 字段或下方任意类签名的
行为都属于破坏性变更, 需要先与团队同步.

----------------------------------------------------------------
共享数据结构: PendingReminder
----------------------------------------------------------------

由 ``telegram_listener`` 构造, 通过 ``on_trigger`` 回调传给
``reminder_manager``; ``reminder_manager`` 在到期时把它转换成飞书
payload 交给 ``feishu_notifier``.

字段含义:
  * ``chat_id``       — Telegram chat id (群组为负数, 私聊为正)
  * ``chat_title``    — 群名; 私聊时填 "私聊提醒"
  * ``sender_name``   — 发送者显示名 (first_name + last_name 或 username)
  * ``sender_id``     — 发送者 user_id
  * ``message_id``    — 触发消息的 message_id (用于构造 message_link)
  * ``message_text``  — 触发消息的文本; 始终保留, **是否塞入飞书
                        payload 由 reminder_manager 根据
                        ``Config.include_message_text`` 决定**
  * ``message_link``  — 形如 ``https://t.me/c/<...>/<msg_id>`` 的深链
  * ``triggered_at``  — 触发时刻 (本地时间 datetime)

``PendingReminder`` 是 ``frozen=True`` 的 dataclass, 不可修改; 需要
派生新值请使用 ``dataclasses.replace``.

----------------------------------------------------------------
模块: userbot.telegram_listener
----------------------------------------------------------------

class TelegramListener:
    def __init__(
        self,
        client: "telethon.TelegramClient",
        config: "userbot.config.Config",
        on_trigger: Callable[[PendingReminder], Awaitable[None]],
        on_self_reply: Callable[[int], Awaitable[None]],
    ) -> None: ...

    async def run(self) -> None:
        '''注册 NewMessage 事件并阻塞监听直到 stop() 被调用.

        触发条件:
          1. 群聊中消息 @ 了"我自己" (mentioned 或 reply_to_msg 是我发的)
             → 调用 on_trigger(PendingReminder)
          2. 配置 enable_private_chat=True 时, 私聊里收到他人消息
             → 调用 on_trigger(PendingReminder)
             其中私聊 bot 默认忽略, 仅 whitelist_bot_ids /
             whitelist_bot_usernames 命中时允许触发.
          3. 我自己 (out=True) 在某个 chat 发了消息
             → 调用 on_self_reply(chat_id), 用于取消该 chat 的待发提醒

        必须遵守 config 中的 whitelist/blacklist (chat_id 过滤).
        绝不主动 send_message; 仅监听.
        '''

    async def stop(self) -> None:
        '''优雅停机: 解除事件订阅并断开 client.'''

回调语义:
  * ``on_trigger`` — 由 reminder_manager.schedule 提供, 不应抛异常;
    listener 不需要 await 其完成 (fire-and-forget 也可以, 但目前直接
    await 即可, schedule 自身要保证耗时极短).
  * ``on_self_reply`` — 由 reminder_manager.cancel 提供; listener
    收到自己发的消息时调用, 参数仅 chat_id.

----------------------------------------------------------------
模块: userbot.reminder_manager
----------------------------------------------------------------

class ReminderManager:
    def __init__(
        self,
        config: "userbot.config.Config",
        notifier: "userbot.feishu_notifier.FeishuNotifier",
    ) -> None: ...

    async def schedule(self, reminder: PendingReminder) -> None:
        '''登记一条待发提醒.

        以 ``reminder.chat_id`` 为 key 存放. 如果该 chat 已有未完成的
        pending task, **保留更早的 task, 不创建新的, 不刷新倒计时**.
        这样多条触发消息不会推迟原始倒计时, 避免被刷屏的群永远不会提醒.

        内部使用 ``asyncio.create_task`` 起一个后台协程, 等待
        ``config.reminder_seconds`` 秒后调用 ``notifier.send(payload)``;
        在等待期间若被 cancel, 则不发送.
        '''

    async def cancel(self, chat_id: int) -> None:
        '''取消该 chat 的未到期提醒 (如果存在). 幂等.'''

    async def stop_all(self) -> None:
        '''关闭时调用: 取消所有未到期的后台 task.'''

payload 构造规则 (在 schedule 内部到期时执行):
  ``payload = {
      "chat_title":  reminder.chat_title,
      "sender_name": reminder.sender_name,
      "sender_id":   reminder.sender_id,
      "triggered_at": reminder.triggered_at.isoformat(timespec="seconds"),
      "message_link": reminder.message_link,
  }``
  当 ``config.include_message_text=True`` 时追加
  ``payload["message_text"] = reminder.message_text``.

----------------------------------------------------------------
模块: userbot.feishu_notifier
----------------------------------------------------------------

class FeishuNotifier:
    def __init__(self, config: "userbot.config.Config") -> None:
        '''内部维护一个 aiohttp.ClientSession, 懒加载即可.'''

    async def send(self, payload: dict) -> None:
        '''发送一条飞书自定义机器人消息.

        - 若 ``config.feishu_secret`` 非空, 按飞书规范计算 ``timestamp``
          + ``sign`` 并加入请求体.
        - 把 payload 渲染成 markdown / 富文本 (post) 类型即可, 必须
          包含 chat_title / sender_name / triggered_at / message_link.
        - 网络错误应当 catch + log + 不向上抛, 避免影响后续提醒.
        '''

    async def close(self) -> None:
        '''关闭 aiohttp.ClientSession; 关闭后再调 send() 应无副作用.'''

payload 字段约定 (来自 reminder_manager):
  必备: chat_title, sender_name, sender_id, triggered_at, message_link
  可选: message_text  (受 config.include_message_text 控制)

----------------------------------------------------------------
模块: userbot.main / userbot.__main__
----------------------------------------------------------------

由 Agent 5 实现, 负责:
  1. ``setup_logging(config.log_level)``
  2. 实例化 ``FeishuNotifier(config)``
  3. 实例化 ``ReminderManager(config, notifier)``
  4. 构造 ``TelegramClient(config.session_name, config.api_id, config.api_hash)``
  5. 实例化 ``TelegramListener(client, config, manager.schedule, manager.cancel)``
  6. 注册 SIGINT/SIGTERM 处理: 依次 ``listener.stop()``, ``manager.stop_all()``,
     ``notifier.close()``, ``client.disconnect()``
  7. ``await listener.run()``

================================================================
导出
================================================================
"""

from dataclasses import dataclass
from datetime import datetime

__all__ = ["PendingReminder"]


@dataclass(frozen=True)
class PendingReminder:
    """触发提醒所需的全部上下文.

    由 telegram_listener 构造, reminder_manager 消费. 字段含义详见
    模块顶部 docstring.
    """

    chat_id: int
    chat_title: str
    sender_name: str
    sender_id: int
    message_id: int
    message_text: str
    message_link: str
    triggered_at: datetime
