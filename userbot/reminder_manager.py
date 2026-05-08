"""倒计时提醒管理器.

接口契约见 ``userbot/__init__.py`` 顶部 docstring.

设计要点:
  * 每个 chat_id 任意时刻最多 1 个 pending ``asyncio.Task``.
  * 新触发到来时若已有未到期 task → 保留更早的, 不刷新倒计时.
    这避免了"被刷屏的群里永远不会提醒"的问题.
  * ``_lock`` 仅保护 ``_pending`` dict 的并发修改, 不在锁内 await
    长操作 (如 ``notifier.send``).
  * ``_countdown`` 用 ``try/except CancelledError`` + ``finally`` 模式,
    确保 task 异常不泄漏, 且无论正常完成 / 取消 / 异常都会清理
    ``_pending``.
  * ``CancelledError`` 必须 re-raise, 不能吞掉.
"""

from __future__ import annotations

import asyncio
import logging

from userbot import PendingReminder
from userbot.config import Config

__all__ = ["ReminderManager"]


class ReminderManager:
    """以 ``chat_id`` 为粒度调度飞书提醒."""

    def __init__(self, config: Config, notifier: object) -> None:
        self.config = config
        self.notifier = notifier
        self._pending: dict[int, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger("userbot.reminder")

    async def schedule(self, reminder: PendingReminder) -> None:
        """登记一条待发提醒.

        若该 chat 已有未到期的 task, 保留更早的一个 (不刷新). 这样
        连续多条触发消息不会推迟原始倒计时.
        """
        async with self._lock:
            existing = self._pending.get(reminder.chat_id)
            if existing is not None and not existing.done():
                self.logger.debug(
                    "chat %s already has a pending reminder, keeping the earlier one "
                    "(new trigger from sender=%s ignored to avoid postponing original countdown)",
                    reminder.chat_id,
                    reminder.sender_name,
                )
                return
            task = asyncio.create_task(
                self._countdown(reminder),
                name=f"reminder-{reminder.chat_id}",
            )
            self._pending[reminder.chat_id] = task

        self.logger.info(
            "scheduled reminder for chat %s (sender=%s, in %ss)",
            reminder.chat_id,
            reminder.sender_name,
            self.config.reminder_seconds,
        )

    async def cancel(self, chat_id: int) -> None:
        """取消该 chat 的未到期提醒. 幂等. 等待 task 真正退出后返回."""
        async with self._lock:
            task = self._pending.get(chat_id)

        if task is None or task.done():
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            self.logger.exception(
                "error while cancelling reminder for chat %s", chat_id
            )

        # 即便 task 还未开始执行就被 cancel, 其 finally 也不会跑,
        # 这里兜底清理 _pending, 避免泄漏.
        async with self._lock:
            if self._pending.get(chat_id) is task:
                self._pending.pop(chat_id, None)

        self.logger.debug("reminder for chat %s cancelled by self-reply", chat_id)

    async def stop_all(self) -> None:
        """关闭时调用: 取消所有未到期的后台 task. 退出后 ``_pending`` 必为空."""
        async with self._lock:
            tasks = list(self._pending.values())
            self._pending.clear()

        if not tasks:
            return

        self.logger.info("cancelling %d pending reminder(s)...", len(tasks))
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.logger.info("all pending reminders cancelled")

    async def _countdown(self, reminder: PendingReminder) -> None:
        """后台协程: sleep 到期后调用 notifier.send."""
        try:
            try:
                await asyncio.sleep(self.config.reminder_seconds)
                payload = self._build_payload(reminder)
                try:
                    await self.notifier.send(payload)
                    self.logger.info(
                        "feishu reminder sent for chat %s (sender=%s)",
                        reminder.chat_id,
                        reminder.sender_name,
                    )
                except Exception:
                    self.logger.exception(
                        "failed to send feishu reminder for chat %s",
                        reminder.chat_id,
                    )
            except asyncio.CancelledError:
                self.logger.info(
                    "reminder cancelled for chat %s (sender=%s) — user replied or shutdown",
                    reminder.chat_id,
                    reminder.sender_name,
                )
                raise
        finally:
            current = asyncio.current_task()
            async with self._lock:
                if self._pending.get(reminder.chat_id) is current:
                    self._pending.pop(reminder.chat_id, None)

    def _build_payload(self, reminder: PendingReminder) -> dict:
        """构造飞书 payload.

        ``include_message_text=False`` 时 payload **不包含** ``message_text``
        这个 key (而不是空字符串), 这样下游 notifier 可以用 ``in`` 判断.
        """
        payload: dict = {
            "chat_title": reminder.chat_title,
            "sender_name": reminder.sender_name,
            "sender_id": reminder.sender_id,
            "triggered_at": reminder.triggered_at.isoformat(timespec="seconds"),
            "message_link": reminder.message_link,
        }
        if self.config.include_message_text:
            payload["message_text"] = reminder.message_text
        return payload
