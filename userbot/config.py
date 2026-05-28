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


def _parse_id_set(raw: str | None, name: str) -> FrozenSet[int]:
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
            raise ValueError(f"{name} 列表中包含非整数: {part!r}") from exc
    return frozenset(out)


def _normalize_bot_username(raw: str | None) -> str:
    if not raw:
        return ""
    return raw.strip().lstrip("@").lower()


def _parse_bot_username_set(raw: str | None) -> FrozenSet[str]:
    if not raw or not raw.strip():
        return frozenset()
    out: list[str] = []
    for part in raw.split(","):
        username = _normalize_bot_username(part)
        if username:
            out.append(username)
    return frozenset(out)


def _parse_str_set(raw: str | None, default: str = "") -> FrozenSet[str]:
    source = raw if raw is not None and raw.strip() else default
    if not source.strip():
        return frozenset()
    out: list[str] = []
    for part in source.split(","):
        value = part.strip()
        if value:
            out.append(value)
    return frozenset(out)


@dataclass(frozen=True)
class Config:
    """运行时配置 (不可变)."""

    api_id: int
    api_hash: str
    feishu_webhook_url: str
    feishu_enabled: bool = True
    session_name: str = "userbot"
    feishu_secret: str = ""
    reminder_seconds: int = 300
    enable_private_chat: bool = True
    include_message_text: bool = True
    whitelist_chat_ids: FrozenSet[int] = field(default_factory=frozenset)
    blacklist_chat_ids: FrozenSet[int] = field(default_factory=frozenset)
    whitelist_bot_ids: FrozenSet[int] = field(default_factory=frozenset)
    whitelist_bot_usernames: FrozenSet[str] = field(default_factory=frozenset)
    log_level: str = "INFO"

    # Bark iOS 推送 (https://bark.day.app); device_key 为空则禁用 Bark.
    bark_device_key: str = ""
    bark_server_url: str = "https://api.day.app"
    bark_critical: bool = True
    bark_call: bool = True
    bark_sound: str = ""

    # 上班打卡确认助手. 只做提醒 + 本人确认后点击, 不支持无人值守自动点击.
    checkin_enabled: bool = False
    checkin_timezone: str = "Asia/Shanghai"
    checkin_random_start: str = "11:00"
    checkin_random_end: str = "11:30"
    checkin_chat_title: str = "墨链公司-常规打卡群"
    checkin_bot_username: str = "web3checkinandoutbot"
    checkin_button_text: str = "上班打卡"
    checkin_fallback_message_id: int = 0
    checkin_confirm_command: str = "/confirm_checkin"
    checkin_success_keywords: FrozenSet[str] = field(
        default_factory=lambda: frozenset({"打卡成功", "上班打卡成功", "成功"})
    )
    checkin_result_timeout_seconds: int = 60
    checkin_state_file: str = "sessions/checkin_state.json"
    checkin_search_limit: int = 800

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

    def is_private_bot_allowed(self, bot_id: int, username: str | None) -> bool:
        """判断私聊 bot 发送者是否允许触发提醒.

        私聊 bot 默认拒绝; ID 或 username 任一命中白名单时允许.
        """
        if bot_id in self.whitelist_bot_ids:
            return True
        normalized_username = _normalize_bot_username(username)
        if (
            normalized_username
            and normalized_username in self.whitelist_bot_usernames
        ):
            return True
        return False


def load_config() -> Config:
    """从环境变量 (含 .env) 加载配置, 校验必填项后返回 Config.

    缺少 ``TG_API_ID`` / ``TG_API_HASH`` 会抛出 ``ValueError``. 默认也要求
    ``FEISHU_WEBHOOK_URL``; 当 ``FEISHU_ENABLED=false`` 时允许留空.
    """
    load_dotenv()

    raw_api_id = os.getenv("TG_API_ID", "").strip()
    api_hash = os.getenv("TG_API_HASH", "").strip()
    feishu_enabled = _parse_bool(os.getenv("FEISHU_ENABLED"), True)
    feishu_webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "").strip()

    missing: list[str] = []
    if not raw_api_id:
        missing.append("TG_API_ID")
    if not api_hash:
        missing.append("TG_API_HASH")
    if feishu_enabled and not feishu_webhook_url:
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

    checkin_confirm_required = _parse_bool(
        os.getenv("CHECKIN_CONFIRM_REQUIRED"),
        True,
    )
    if not checkin_confirm_required:
        raise ValueError("CHECKIN_CONFIRM_REQUIRED 必须保持 true")

    return Config(
        api_id=api_id,
        api_hash=api_hash,
        feishu_webhook_url=feishu_webhook_url,
        feishu_enabled=feishu_enabled,
        session_name=os.getenv("TG_SESSION_NAME", "").strip() or "userbot",
        feishu_secret=os.getenv("FEISHU_SECRET", "").strip(),
        reminder_seconds=_parse_int(
            os.getenv("REMINDER_SECONDS"), 300, "REMINDER_SECONDS"
        ),
        enable_private_chat=_parse_bool(os.getenv("ENABLE_PRIVATE_CHAT"), True),
        include_message_text=_parse_bool(os.getenv("INCLUDE_MESSAGE_TEXT"), True),
        whitelist_chat_ids=_parse_id_set(
            os.getenv("WHITELIST_CHAT_IDS"),
            "WHITELIST_CHAT_IDS",
        ),
        blacklist_chat_ids=_parse_id_set(
            os.getenv("BLACKLIST_CHAT_IDS"),
            "BLACKLIST_CHAT_IDS",
        ),
        whitelist_bot_ids=_parse_id_set(
            os.getenv("WHITELIST_BOT_IDS"),
            "WHITELIST_BOT_IDS",
        ),
        whitelist_bot_usernames=_parse_bot_username_set(
            os.getenv("WHITELIST_BOT_USERNAMES"),
        ),
        log_level=(os.getenv("LOG_LEVEL", "").strip() or "INFO").upper(),
        bark_device_key=os.getenv("BARK_DEVICE_KEY", "").strip(),
        bark_server_url=(
            os.getenv("BARK_SERVER_URL", "").strip() or "https://api.day.app"
        ),
        bark_critical=_parse_bool(os.getenv("BARK_CRITICAL"), True),
        bark_call=_parse_bool(os.getenv("BARK_CALL"), True),
        bark_sound=os.getenv("BARK_SOUND", "").strip(),
        checkin_enabled=_parse_bool(os.getenv("CHECKIN_ENABLED"), False),
        checkin_timezone=(
            os.getenv("CHECKIN_TIMEZONE", "").strip() or "Asia/Shanghai"
        ),
        checkin_random_start=(
            os.getenv("CHECKIN_RANDOM_START", "").strip() or "11:00"
        ),
        checkin_random_end=(
            os.getenv("CHECKIN_RANDOM_END", "").strip() or "11:30"
        ),
        checkin_chat_title=(
            os.getenv("CHECKIN_CHAT_TITLE", "").strip() or "墨链公司-常规打卡群"
        ),
        checkin_bot_username=_normalize_bot_username(
            os.getenv("CHECKIN_BOT_USERNAME", "").strip()
            or "Web3CheckInAndOutbot"
        ),
        checkin_button_text=(
            os.getenv("CHECKIN_BUTTON_TEXT", "").strip() or "上班打卡"
        ),
        checkin_fallback_message_id=_parse_int(
            os.getenv("CHECKIN_FALLBACK_MESSAGE_ID"),
            0,
            "CHECKIN_FALLBACK_MESSAGE_ID",
        ),
        checkin_confirm_command=(
            os.getenv("CHECKIN_CONFIRM_COMMAND", "").strip()
            or "/confirm_checkin"
        ),
        checkin_success_keywords=_parse_str_set(
            os.getenv("CHECKIN_SUCCESS_KEYWORDS"),
            "打卡成功,上班打卡成功,成功",
        ),
        checkin_result_timeout_seconds=_parse_int(
            os.getenv("CHECKIN_RESULT_TIMEOUT_SECONDS"),
            60,
            "CHECKIN_RESULT_TIMEOUT_SECONDS",
        ),
        checkin_state_file=(
            os.getenv("CHECKIN_STATE_FILE", "").strip()
            or "sessions/checkin_state.json"
        ),
        checkin_search_limit=_parse_int(
            os.getenv("CHECKIN_SEARCH_LIMIT"),
            800,
            "CHECKIN_SEARCH_LIMIT",
        ),
    )
