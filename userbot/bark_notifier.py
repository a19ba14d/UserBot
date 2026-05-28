"""Bark iOS 推送通知器 (https://bark.day.app/).

通过 Bark App 把提醒推到 iPhone, 支持 critical 级别 (绕过静音/勿扰) 和
持续响铃 (call=1, 响 30 秒). 接口与 FeishuNotifier 完全一致, 由
BroadcastNotifier 与其它 notifier 一起广播.

Bark API 形态: POST {server_url}/{device_key}, body 为 JSON.
响应: {"code": 200, "message": "success", "timestamp": ...}.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

__all__ = ["BarkNotifier"]


class BarkNotifier:
    """把 reminder payload 推送到 iOS Bark App."""

    def __init__(self, config) -> None:
        self.device_key = config.bark_device_key
        self.server_url = config.bark_server_url.rstrip("/")
        self.critical = config.bark_critical
        self.call = config.bark_call
        self.sound = config.bark_sound
        self.logger = logging.getLogger("userbot.bark")
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=10),
                )
            return self._session

    def _build_body(self, payload: dict) -> dict:
        chat = payload["chat_title"]
        sender = payload["sender_name"]
        sender_id = payload.get("sender_id", "")
        body_lines = [f"{chat} · {sender} (id: {sender_id})"]

        if "message_text" in payload:
            text = payload["message_text"]
            if len(text) > 200:
                text = text[:200] + "..."
            body_lines.append(text)

        body = {
            "title": payload.get("title", "TG 未回复提醒"),
            "body": "\n".join(body_lines),
            "url": payload["message_link"],
            "group": "TG-Reminder",
            "isArchive": "1",
        }
        if self.critical:
            # critical 级别会绕过静音/勿扰; 需 iOS 设置 → 通知 → Bark → 允许"重要警告"
            body["level"] = "critical"
            body["volume"] = 10
        if self.call:
            # call=1 会让铃声重复 30 秒, 像电话一样
            body["call"] = "1"
        if self.sound:
            body["sound"] = self.sound
        return body

    async def send(self, payload: dict) -> None:
        """推送一条提醒. 任何异常只 log 不抛."""
        if not self.device_key:
            self.logger.debug("bark device_key empty, skip")
            return

        url = f"{self.server_url}/{self.device_key}"
        body = self._build_body(payload)

        try:
            session = await self._get_session()
            async with session.post(url, json=body) as resp:
                text = await resp.text()
                if resp.status != 200:
                    self.logger.error(
                        "bark webhook returned HTTP %s: %s",
                        resp.status, text[:300],
                    )
                    return
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    self.logger.error(
                        "bark webhook returned non-JSON: %s", text[:300],
                    )
                    return
                if data.get("code") != 200:
                    self.logger.error("bark webhook error: %s", data)
                    return
                self.logger.debug("bark webhook OK: %s", data)
        except asyncio.TimeoutError:
            self.logger.error("bark webhook timeout (>10s)")
        except aiohttp.ClientError as e:
            self.logger.error("bark webhook client error: %s", e)
        except Exception:
            self.logger.exception("unexpected error sending bark notification")

    async def close(self) -> None:
        """关闭底层 aiohttp session, 幂等."""
        async with self._lock:
            session = self._session
            self._session = None
        if session is not None and not session.closed:
            try:
                await session.close()
            except Exception:
                self.logger.exception("error while closing bark session")
