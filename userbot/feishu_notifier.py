"""飞书自定义机器人通知器.

接口契约见 ``userbot/__init__.py`` 顶部 docstring.

仅支持 incoming → 飞书 webhook 推送; 任何网络/解析异常都只记录日志,
不向上抛出, 避免影响 reminder_manager 的后续调度.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import time

import aiohttp

from userbot.config import Config

__all__ = ["FeishuNotifier"]


class FeishuNotifier:
    """通过飞书自定义机器人 webhook 推送提醒.

    - 内部维护一个懒加载的 ``aiohttp.ClientSession``, 由 ``_lock`` 保护
      避免并发首次创建多次.
    - ``send()`` 把 payload 渲染为飞书 ``post`` 富文本 (含跳转链接), 末尾
      加一行 "跳转到消息" 超链接.
    - 当 ``config.feishu_secret`` 非空时按飞书规范计算 HMAC-SHA256 签名.
    """

    def __init__(self, config: Config) -> None:
        self.url = config.feishu_webhook_url
        self.secret = config.feishu_secret
        self.logger = logging.getLogger("userbot.feishu")
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=10),
                )
            return self._session

    def _build_body(self, payload: dict) -> dict:
        content_lines: list[list[dict]] = [
            [{"tag": "text", "text": f"群/聊天: {payload['chat_title']}"}],
            [{
                "tag": "text",
                "text": (
                    f"发送人: {payload['sender_name']} "
                    f"(id: {payload['sender_id']})"
                ),
            }],
            [{"tag": "text", "text": f"时间: {payload['triggered_at']}"}],
        ]
        if "message_text" in payload:
            content_lines.append(
                [{"tag": "text", "text": f"内容: {payload['message_text']}"}],
            )
        content_lines.append([
            {"tag": "a", "text": "跳转到消息", "href": payload["message_link"]},
        ])

        body: dict = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": "Telegram 未回复提醒",
                        "content": content_lines,
                    },
                },
            },
        }

        if self.secret:
            timestamp = str(int(time.time()))
            string_to_sign = f"{timestamp}\n{self.secret}"
            sign_bytes = hmac.new(
                string_to_sign.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
            sign = base64.b64encode(sign_bytes).decode("utf-8")
            body["timestamp"] = timestamp
            body["sign"] = sign

        return body

    async def send(self, payload: dict) -> None:
        """发送一条飞书提醒; 任何异常都只记录日志, 不向上抛出."""
        try:
            body = self._build_body(payload)
        except Exception:
            self.logger.exception("failed to build feishu request body")
            return

        try:
            session = await self._get_session()
        except Exception:
            self.logger.exception("failed to acquire aiohttp session")
            return

        try:
            async with session.post(self.url, json=body) as resp:
                text = await resp.text()
                if resp.status != 200:
                    self.logger.error(
                        "feishu webhook returned HTTP %s: %s",
                        resp.status,
                        text[:500],
                    )
                    return
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    self.logger.error(
                        "feishu webhook returned non-JSON: %s",
                        text[:500],
                    )
                    return
                if data.get("code", -1) != 0:
                    self.logger.error("feishu webhook error: %s", data)
                    return
                self.logger.debug("feishu webhook OK: %s", data)
        except asyncio.TimeoutError:
            self.logger.error("feishu webhook timeout (>10s)")
        except aiohttp.ClientError as exc:
            self.logger.error("feishu webhook client error: %s", exc)
        except Exception:
            self.logger.exception("unexpected error sending feishu webhook")

    async def close(self) -> None:
        """关闭底层 session; 重复调用安全."""
        async with self._lock:
            session = self._session
            self._session = None
            if session is not None and not session.closed:
                try:
                    await session.close()
                except Exception:
                    self.logger.exception("error closing feishu aiohttp session")
