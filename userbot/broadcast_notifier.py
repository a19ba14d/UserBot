"""广播通知器: 把同一条 payload 并发发到多个底层 notifier.

接口与单个 notifier 一致 (async send / async close), 因此可以直接传给
ReminderManager, 后者无需感知有几个目的端.

设计要点:
  - 任意一个 notifier 失败不影响其它 (并发 + return_exceptions=True).
  - close() 关闭所有底层 session.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence

__all__ = ["BroadcastNotifier"]


class BroadcastNotifier:
    """把 payload 广播到一组 notifier."""

    def __init__(self, notifiers: Sequence) -> None:
        self._notifiers = list(notifiers)
        self.logger = logging.getLogger("userbot.broadcast")

    async def send(self, payload: dict) -> None:
        if not self._notifiers:
            self.logger.warning("no notifier registered, skip send")
            return
        await asyncio.gather(
            *(n.send(payload) for n in self._notifiers),
            return_exceptions=True,
        )

    async def close(self) -> None:
        await asyncio.gather(
            *(n.close() for n in self._notifiers),
            return_exceptions=True,
        )
