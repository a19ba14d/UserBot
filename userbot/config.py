"""配置模块: 从环境变量 / .env 加载并校验运行参数."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import FrozenSet

from dotenv import load_dotenv

__all__ = ["Config", "load_config"]


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_int(raw: str | None, default: int, name: str) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数, 当前值: {raw!r}") from exc


def _parse_id_set(raw: str | None) -> FrozenSet[int]:
    if not raw or not raw.strip():
        return frozenset()
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError as exc:
            raise ValueError(f"chat_id 列表中包含非整数: {part!r}") from exc
    return frozenset(out)


@dataclass(frozen=True)
class Config:
    """运行时配置 (不可变)."""

    api_id: int
    api_hash: str
    feishu_webhook_url: str
    session_name: str = "userbot"
    feishu_secret: str = ""
    reminder_seconds: int = 300
    enable_private_chat: bool = True
    include_message_text: bool = True
    whitelist_chat_ids: FrozenSet[int] = field(default_factory=frozenset)
    blacklist_chat_ids: FrozenSet[int] = field(default_factory=frozenset)
    log_level: str = "INFO"

    def is_chat_allowed(self, chat_id: int) -> bool:
        """判断给定 chat_id 是否应当被监听.

        规则:
          1. 黑名单内一律拒绝.
          2. 白名单非空时, 仅白名单内允许.
          3. 白名单为空时, 默认允许 (除非命中黑名单).
        """
        if chat_id in self.blacklist_chat_ids:
            return False
        if self.whitelist_chat_ids and chat_id not in self.whitelist_chat_ids:
            return False
        return True


def load_config() -> Config:
    """从环境变量 (含 .env) 加载配置, 校验必填项后返回 Config.

    缺少 ``TG_API_ID`` / ``TG_API_HASH`` / ``FEISHU_WEBHOOK_URL`` 任意一项
    会抛出 ``ValueError``, 错误信息会列出所有缺失字段.
    """
    load_dotenv()

    raw_api_id = os.getenv("TG_API_ID", "").strip()
    api_hash = os.getenv("TG_API_HASH", "").strip()
    feishu_webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "").strip()

    missing: list[str] = []
    if not raw_api_id:
        missing.append("TG_API_ID")
    if not api_hash:
        missing.append("TG_API_HASH")
    if not feishu_webhook_url:
        missing.append("FEISHU_WEBHOOK_URL")
    if missing:
        raise ValueError(
            "缺少必填的环境变量: " + ", ".join(missing) +
            " (请参考 .env.example 配置 .env)"
        )

    try:
        api_id = int(raw_api_id)
    except ValueError as exc:
        raise ValueError(f"TG_API_ID 必须是整数, 当前值: {raw_api_id!r}") from exc

    return Config(
        api_id=api_id,
        api_hash=api_hash,
        feishu_webhook_url=feishu_webhook_url,
        session_name=os.getenv("TG_SESSION_NAME", "").strip() or "userbot",
        feishu_secret=os.getenv("FEISHU_SECRET", "").strip(),
        reminder_seconds=_parse_int(
            os.getenv("REMINDER_SECONDS"), 300, "REMINDER_SECONDS"
        ),
        enable_private_chat=_parse_bool(os.getenv("ENABLE_PRIVATE_CHAT"), True),
        include_message_text=_parse_bool(os.getenv("INCLUDE_MESSAGE_TEXT"), True),
        whitelist_chat_ids=_parse_id_set(os.getenv("WHITELIST_CHAT_IDS")),
        blacklist_chat_ids=_parse_id_set(os.getenv("BLACKLIST_CHAT_IDS")),
        log_level=(os.getenv("LOG_LEVEL", "").strip() or "INFO").upper(),
    )
