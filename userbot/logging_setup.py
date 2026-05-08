"""日志配置: 统一格式, 抑制 telethon 噪声."""

from __future__ import annotations

import logging
import sys

__all__ = ["setup_logging"]

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    """配置 root logger 输出到 stderr.

    - ``level`` 接受 INFO / DEBUG / WARNING / ERROR / CRITICAL (大小写不敏感).
    - 若 ``level`` 不可识别, 退化为 INFO 并打印一条 warning.
    - 始终抑制 telethon 的 DEBUG 噪声: 默认把 ``telethon`` logger 设为
      WARNING; 仅当用户显式指定 DEBUG 时才让 telethon 也跟着 DEBUG.
    """
    normalized = (level or "INFO").upper()
    numeric = getattr(logging, normalized, None)
    fallback_msg: str | None = None
    if not isinstance(numeric, int):
        fallback_msg = f"未知日志级别 {level!r}, 退化为 INFO"
        numeric = logging.INFO
        normalized = "INFO"

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(handler)
    root.setLevel(numeric)

    telethon_level = logging.DEBUG if normalized == "DEBUG" else logging.WARNING
    logging.getLogger("telethon").setLevel(telethon_level)

    if fallback_msg:
        logging.getLogger(__name__).warning(fallback_msg)
