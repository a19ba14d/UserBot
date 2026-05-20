"""主入口: 装配 client / listener / manager / notifier 并管理生命周期.

启动顺序:
  notifier -> manager -> listener (依赖关系决定)

关闭顺序 (重要):
  manager.stop_all()  # 取消所有 pending reminder, 不会再触发 send
  listener.stop()     # disconnect telegram client, 不会再有 incoming
  notifier.close()    # 此时确保已经没有 send 在跑
"""

from __future__ import annotations

import asyncio
import logging
import signal

from telethon import TelegramClient

from userbot.bark_notifier import BarkNotifier
from userbot.broadcast_notifier import BroadcastNotifier
from userbot.config import load_config
from userbot.feishu_notifier import FeishuNotifier
from userbot.logging_setup import setup_logging
from userbot.reminder_manager import ReminderManager
from userbot.telegram_listener import TelegramListener

__all__ = ["run", "main"]


async def run() -> None:
    """异步主流程. 阻塞监听直到收到 SIGINT/SIGTERM 或 listener 异常退出."""
    config = load_config()
    setup_logging(config.log_level)
    logger = logging.getLogger("userbot.main")
    logger.info("starting userbot...")
    logger.info(
        "config: reminder=%ss private=%s include_text=%s whitelist=%d "
        "blacklist=%d bot_id_whitelist=%d bot_username_whitelist=%d",
        config.reminder_seconds,
        config.enable_private_chat,
        config.include_message_text,
        len(config.whitelist_chat_ids),
        len(config.blacklist_chat_ids),
        len(config.whitelist_bot_ids),
        len(config.whitelist_bot_usernames),
    )

    client = TelegramClient(config.session_name, config.api_id, config.api_hash)

    # 注册所有 notifier; 通过 BroadcastNotifier 广播, 任意一个失败不影响其它
    notifiers: list = [FeishuNotifier(config)]
    if config.bark_device_key:
        notifiers.append(BarkNotifier(config))
        logger.info("bark notifier enabled (server=%s)", config.bark_server_url)
    else:
        logger.info("bark notifier disabled (BARK_DEVICE_KEY empty)")
    notifier = BroadcastNotifier(notifiers)
    manager = ReminderManager(config, notifier)
    listener = TelegramListener(
        client=client,
        config=config,
        on_trigger=manager.schedule,
        on_self_reply=manager.cancel,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        logger.info("received shutdown signal")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            pass

    listener_task = asyncio.create_task(listener.run(), name="listener")
    stop_task = asyncio.create_task(stop_event.wait(), name="stop")

    listener_exc: BaseException | None = None
    try:
        done, pending = await asyncio.wait(
            {listener_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

        # 如果 listener 自己异常退出 (例如鉴权失败), 把异常记下, 在 finally
        # 之后 re-raise; 不能在 finally 之前抛, 否则 cleanup 不会跑.
        if listener_task in done and not listener_task.cancelled():
            listener_exc = listener_task.exception()
    finally:
        logger.info("shutting down...")
        try:
            await manager.stop_all()
        except Exception:
            logger.exception("error during manager.stop_all()")
        try:
            await listener.stop()
        except Exception:
            logger.exception("error during listener.stop()")
        try:
            await notifier.close()
        except Exception:
            logger.exception("error during notifier.close()")
        logger.info("shutdown complete")

    if listener_exc is not None:
        raise listener_exc


def main() -> None:
    """同步入口: 给 ``python -m userbot`` 和 ``python userbot/main.py`` 用."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        # signal handler 已经处理过, 这里兜底
        pass


if __name__ == "__main__":
    main()
