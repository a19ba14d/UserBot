"""Telegram 事件监听器.

监听 incoming 消息, 区分 "他人触发" 与 "我自己回复":
  * 群聊 @ 我 / 私聊他人消息  → on_trigger(PendingReminder)
  * 我自己 (out=True) 发的消息 → on_self_reply(chat_id)

接口契约见 ``userbot/__init__.py`` 顶部 docstring. 本模块只做监听,
绝不主动 send_message.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from telethon import events

from userbot import PendingReminder
from userbot.config import Config

__all__ = ["TelegramListener"]


logger = logging.getLogger("userbot.listener")


class TelegramListener:
    """Telethon 事件监听器, 把 Telegram 事件翻译成 PendingReminder.

    构造时传入两个 awaitable 回调:
      * ``on_trigger``    — 收到他人触发消息时调用 (一般连到
        ``ReminderManager.schedule``).
      * ``on_self_reply`` — 我自己在某个 chat 发了消息时调用
        (一般连到 ``ReminderManager.cancel``).

    回调若抛出异常, 会被本类 catch 并 log, 不会让 Telethon 主循环挂掉.
    """

    def __init__(
        self,
        client: Any,
        config: Config,
        on_trigger: Callable[[PendingReminder], Awaitable[None]],
        on_self_reply: Callable[[int], Awaitable[None]],
    ) -> None:
        self.client = client
        self.config = config
        self.on_trigger = on_trigger
        self.on_self_reply = on_self_reply
        self._handlers_registered = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def run(self) -> None:
        """启动 client, 注册事件处理器, 阻塞直到 disconnect."""
        self._register_handlers()
        await self.client.start()
        try:
            me = await self.client.get_me()
            display = getattr(me, "first_name", None) or getattr(me, "username", None) or "<unknown>"
            logger.info("Logged in as %s (id=%s)", display, getattr(me, "id", "?"))
        except Exception:
            logger.exception("get_me() 失败, 继续监听 (可能影响日志显示)")
        logger.info(
            "Listening for mentions and private messages "
            "(enable_private_chat=%s, whitelist=%d, blacklist=%d)",
            self.config.enable_private_chat,
            len(self.config.whitelist_chat_ids),
            len(self.config.blacklist_chat_ids),
        )
        await self.client.run_until_disconnected()

    async def stop(self) -> None:
        """优雅停机: 断开 client (Telethon 会自动清理事件订阅)."""
        try:
            if self.client.is_connected():
                await self.client.disconnect()
                logger.info("Telegram client disconnected.")
        except Exception:
            logger.exception("disconnect() 抛异常, 已忽略")

    # ------------------------------------------------------------------
    # 内部: 事件处理器注册
    # ------------------------------------------------------------------
    def _register_handlers(self) -> None:
        if self._handlers_registered:
            return

        @self.client.on(events.NewMessage(incoming=True))
        async def _handle_incoming(event):  # noqa: ANN001
            try:
                await self._on_incoming(event)
            except Exception:
                logger.exception("处理 incoming 事件时发生异常")

        @self.client.on(events.NewMessage(outgoing=True))
        async def _handle_outgoing(event):  # noqa: ANN001
            try:
                await self._on_outgoing(event)
            except Exception:
                logger.exception("处理 outgoing 事件时发生异常")

        self._handlers_registered = True

    # ------------------------------------------------------------------
    # 内部: incoming 处理
    # ------------------------------------------------------------------
    async def _on_incoming(self, event) -> None:  # noqa: ANN001
        # 跳过自己的消息当 incoming 处理 (理论上 Telethon 不会, 但安全)
        if getattr(event.message, "out", False):
            return

        chat = await event.get_chat()

        # 跳过频道广播 (broadcast channel), 这种聊天里 mention 我也不应该计数
        if getattr(chat, "broadcast", False):
            logger.debug("跳过 broadcast 频道消息: chat_id=%s", event.chat_id)
            return

        # ==================================================================
        # 触发条件: 集中在这里, 方便修改.
        # 如果不希望私聊触发提醒, 把下面 ``or (...)`` 整段移除即可.
        # 注意: ``event.mentioned`` 在群聊里被 @ 或被 reply 我自己消息时为 True.
        # ==================================================================
        should_trigger = event.mentioned or (
            event.is_private and self.config.enable_private_chat
        )
        if not should_trigger:
            logger.debug(
                "未触发: chat_id=%s mentioned=%s is_private=%s",
                event.chat_id, event.mentioned, event.is_private,
            )
            return

        # 应用 chat_id 白/黑名单
        if not self.config.is_chat_allowed(event.chat_id):
            logger.debug("白/黑名单过滤: chat_id=%s", event.chat_id)
            return

        sender = await event.get_sender()
        sender_id = getattr(sender, "id", 0) if sender else 0
        sender_name = self._build_sender_name(sender, sender_id)

        if event.is_private:
            chat_title = "私聊提醒"
        else:
            chat_title = getattr(chat, "title", None) or "未命名群组"

        message_text = event.message.message or ""
        message_id = event.message.id
        message_link = self._build_message_link(chat, sender, event)

        # triggered_at: 优先用消息本身的时间 (UTC -> 本地)
        msg_date = getattr(event.message, "date", None)
        if msg_date is not None:
            try:
                triggered_at = datetime.fromtimestamp(msg_date.timestamp())
            except Exception:
                triggered_at = datetime.now()
        else:
            triggered_at = datetime.now()

        reminder = PendingReminder(
            chat_id=event.chat_id,
            chat_title=chat_title,
            sender_name=sender_name,
            sender_id=sender_id,
            message_id=message_id,
            message_text=message_text,
            message_link=message_link,
            triggered_at=triggered_at,
        )

        logger.info(
            "触发: chat=%r sender=%r msg_id=%s link=%s",
            chat_title, sender_name, message_id, message_link,
        )

        try:
            await self.on_trigger(reminder)
        except Exception:
            logger.exception("on_trigger 回调抛异常 (已吞掉, 不影响后续监听)")

    # ------------------------------------------------------------------
    # 内部: outgoing 处理 (我自己回复 → 取消倒计时)
    # ------------------------------------------------------------------
    async def _on_outgoing(self, event) -> None:  # noqa: ANN001
        # 跳过 forward (避免把自己 forward 自己的消息算成回复)
        if getattr(event.message, "fwd_from", None) is not None:
            logger.debug("outgoing 跳过 forward: chat_id=%s", event.chat_id)
            return

        # 仍然受白/黑名单约束: 不在监听范围内的 chat 也不该 cancel
        if not self.config.is_chat_allowed(event.chat_id):
            logger.debug("outgoing 白/黑名单过滤: chat_id=%s", event.chat_id)
            return

        logger.info("自回复: chat_id=%s msg_id=%s", event.chat_id, event.message.id)
        try:
            await self.on_self_reply(event.chat_id)
        except Exception:
            logger.exception("on_self_reply 回调抛异常 (已吞掉)")

    # ------------------------------------------------------------------
    # 内部: 辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _build_sender_name(sender: Optional[Any], sender_id: int) -> str:
        if sender is None:
            return f"用户 {sender_id}" if sender_id else "未知用户"
        first = getattr(sender, "first_name", None) or ""
        last = getattr(sender, "last_name", None) or ""
        full = f"{first} {last}".strip()
        if full:
            return full
        username = getattr(sender, "username", None)
        if username:
            return username
        return f"用户 {sender_id}" if sender_id else "未知用户"

    @staticmethod
    def _build_message_link(chat: Any, sender: Any, event) -> str:  # noqa: ANN001
        """构造消息深链, 支持公开群 / 私有群 / 私聊三种场景."""
        message_id = event.message.id

        # 私聊
        if event.is_private:
            user_id = getattr(sender, "id", None) if sender else None
            if user_id is None:
                user_id = event.chat_id
            return f"tg://openmessage?user_id={user_id}&message_id={message_id}"

        # 公开群/频道: chat 有 username
        chat_username = getattr(chat, "username", None)
        if chat_username:
            return f"https://t.me/{chat_username}/{message_id}"

        # 私有超级群: chat_id 形如 -100xxxxxxxxxx, 去掉 -100 前缀
        chat_id_str = str(event.chat_id)
        if chat_id_str.startswith("-100"):
            return f"https://t.me/c/{chat_id_str[4:]}/{message_id}"

        # 普通群 (basic group) 没有公开深链, 退化成一个可读字符串
        return f"tg://privatepost?chat_id={event.chat_id}&message_id={message_id}"
