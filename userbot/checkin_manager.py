"""上班打卡确认助手.

本模块只实现"提醒 + 本人确认后点击 + 成功校验". 不提供无人值守自动点击.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from telethon.utils import get_peer_id

from userbot.config import Config

__all__ = ["CheckInManager"]


class CheckInManager:
    """每天随机提醒一次, 收到本人确认命令后点击目标 bot 的上班打卡按钮."""

    def __init__(
        self,
        client: Any,
        config: Config,
        notifier: Any,
        *,
        clock: Callable[[], datetime] | None = None,
        random_source: random.Random | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self.notifier = notifier
        self.clock = clock
        self.random = random_source or random.Random()
        self.logger = logging.getLogger("userbot.checkin")
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._target_entity: Any | None = None

    async def start(self) -> None:
        """启动每日提醒循环. 未启用时无副作用."""
        if not self.config.checkin_enabled:
            self.logger.info("check-in assistant disabled")
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop(), name="checkin-manager")
        self.logger.info(
            "check-in assistant enabled: window=%s-%s chat=%r bot=@%s command=%s",
            self.config.checkin_random_start,
            self.config.checkin_random_end,
            self.config.checkin_chat_title,
            self.config.checkin_bot_username,
            self.config.checkin_confirm_command,
        )

    async def stop(self) -> None:
        """停止每日提醒循环."""
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def handle_outgoing_message(self, chat_id: int, text: str) -> None:
        """处理本人发出的 Telegram 消息; 仅确认命令会触发后续流程."""
        if not self.config.checkin_enabled:
            return
        if text.strip() != self.config.checkin_confirm_command:
            return

        async with self._lock:
            state = self._ensure_today_state()
            target = await self._resolve_target_chat()
            if chat_id != self._peer_id(target):
                await self._notify(
                    "上班打卡确认被忽略",
                    "确认命令不在目标群内发送，未执行按钮点击。",
                )
                return

            if not state.get("reminder_sent"):
                if state.get("status") == "missed_window":
                    text = "今日随机提醒窗口已错过，未执行按钮点击。"
                else:
                    text = "今日尚未到随机提醒时间，未执行按钮点击。"
                await self._notify(
                    "上班打卡尚未到确认时间",
                    text,
                )
                return

            if state.get("clicked") or state.get("completed"):
                await self._notify(
                    "上班打卡已处理",
                    "今日已经执行过确认流程，未重复点击。",
                )
                return

            state["confirmed"] = True
            state["confirmed_at"] = self._now_local().isoformat(timespec="seconds")
            state["status"] = "confirmed"
            self._save_state(state)

            await self._execute_confirmed_checkin(target, state)

    async def _run_loop(self) -> None:
        while True:
            try:
                state = self._ensure_today_state()
                now = self._now_local()
                scheduled_at = datetime.fromisoformat(state["scheduled_at"])
                if state.get("completed") or state.get("clicked"):
                    await asyncio.sleep(self._seconds_until_tomorrow(now))
                    continue
                if state.get("status") == "missed_window":
                    await asyncio.sleep(self._seconds_until_tomorrow(now))
                    continue
                if not state.get("reminder_sent") and now >= scheduled_at:
                    state["reminder_sent"] = True
                    state["reminded_at"] = now.isoformat(timespec="seconds")
                    state["status"] = "awaiting_confirmation"
                    self._save_state(state)
                    await self._notify(
                        "上班打卡待确认",
                        (
                            "请在目标群发送 "
                            f"{self.config.checkin_confirm_command} 确认执行上班打卡。"
                        ),
                    )
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("check-in loop error")
                await asyncio.sleep(60)

    async def _execute_confirmed_checkin(self, target: Any, state: dict) -> None:
        message, row, col = await self._find_button_message(target)
        if message is None:
            state["status"] = "button_not_found"
            self._save_state(state)
            await self._notify("上班打卡未执行", "未找到可点击的上班打卡按钮。")
            return

        before_id = getattr(message, "id", 0)
        try:
            await message.click(row, col)
        except Exception as exc:
            state["clicked"] = False
            state["button_message_id"] = before_id
            state["status"] = "click_failed"
            state["error"] = str(exc)
            self._save_state(state)
            self.logger.error("check-in button click failed: %s", exc)
            await self._notify(
                "上班打卡点击失败",
                f"按钮点击失败，未确认打卡完成，请手动检查: {exc}",
            )
            return

        state["clicked"] = True
        state["clicked_at"] = self._now_local().isoformat(timespec="seconds")
        state["button_message_id"] = before_id
        state["status"] = "clicked_waiting_result"
        self._save_state(state)

        result = await self._wait_for_success(target, before_id)
        if result is not None:
            state["completed"] = True
            state["result_message_id"] = getattr(result, "id", None)
            state["status"] = "completed"
            self._save_state(state)
            await self._notify(
                "上班打卡成功",
                f"已收到机器人成功回复: {(result.raw_text or '').strip()}",
            )
            return

        state["status"] = "result_timeout"
        self._save_state(state)
        await self._notify(
            "上班打卡结果待确认",
            "按钮已点击，但未在超时时间内收到成功回复，请手动检查。",
        )

    async def _find_button_message(self, target: Any) -> tuple[Any | None, int, int]:
        async for message in self.client.iter_messages(
            target,
            limit=self.config.checkin_search_limit,
        ):
            if await self._is_target_bot_message(message):
                pos = self._find_button_position(message)
                if pos is not None:
                    return message, pos[0], pos[1]

        fallback_id = self.config.checkin_fallback_message_id
        if fallback_id:
            message = await self.client.get_messages(target, ids=fallback_id)
            if message is not None and await self._is_target_bot_message(message):
                pos = self._find_button_position(message)
                if pos is not None:
                    return message, pos[0], pos[1]

        return None, 0, 0

    async def _wait_for_success(self, target: Any, min_id: int) -> Any | None:
        deadline = asyncio.get_running_loop().time()
        deadline += max(0, self.config.checkin_result_timeout_seconds)
        while True:
            result = await self._find_success_message(target, min_id)
            if result is not None:
                return result
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(2)

    async def _find_success_message(self, target: Any, min_id: int) -> Any | None:
        async for message in self.client.iter_messages(target, limit=20, min_id=min_id):
            if not await self._is_target_bot_message(message):
                continue
            text = (getattr(message, "raw_text", None) or "").strip()
            if any(keyword in text for keyword in self.config.checkin_success_keywords):
                return message
        return None

    async def _is_target_bot_message(self, message: Any) -> bool:
        sender = await message.get_sender()
        if not getattr(sender, "bot", False):
            return False
        username = (getattr(sender, "username", None) or "").strip().lstrip("@").lower()
        return username == self.config.checkin_bot_username

    def _find_button_position(self, message: Any) -> tuple[int, int] | None:
        reply_markup = getattr(message, "reply_markup", None)
        if reply_markup is None:
            return None
        rows = getattr(reply_markup, "rows", []) or []
        for row_index, row in enumerate(rows):
            buttons = getattr(row, "buttons", []) or []
            for col_index, button in enumerate(buttons):
                text = getattr(button, "text", "") or ""
                has_callback = getattr(button, "data", None) is not None
                if self.config.checkin_button_text in text and has_callback:
                    return row_index, col_index
        return None

    async def _resolve_target_chat(self) -> Any:
        if self._target_entity is not None:
            return self._target_entity
        async for dialog in self.client.iter_dialogs():
            if dialog.name == self.config.checkin_chat_title:
                self._target_entity = dialog.entity
                return dialog.entity
        raise RuntimeError(f"找不到目标群: {self.config.checkin_chat_title}")

    def _ensure_today_state(self) -> dict:
        today = self._now_local().date().isoformat()
        state = self._load_state()
        if state.get("date") == today:
            if self._scheduled_state_missed_window(state):
                state["status"] = "missed_window"
                self._save_state(state)
            return state

        now = self._now_local()
        end = self._parse_time(self.config.checkin_random_end)
        end_dt = datetime.combine(now.date(), end, self._timezone())
        missed_window = now > end_dt
        scheduled_at = (
            end_dt if missed_window else self._random_time_for_date(now.date())
        )
        state = {
            "date": today,
            "scheduled_at": scheduled_at.isoformat(timespec="seconds"),
            "reminder_sent": False,
            "confirmed": False,
            "clicked": False,
            "completed": False,
            "status": "missed_window" if missed_window else "scheduled",
        }
        self._save_state(state)
        return state

    def _random_time_for_date(self, target_date: date) -> datetime:
        start = self._parse_time(self.config.checkin_random_start)
        end = self._parse_time(self.config.checkin_random_end)
        start_dt = datetime.combine(target_date, start, self._timezone())
        end_dt = datetime.combine(target_date, end, self._timezone())
        if end_dt < start_dt:
            raise ValueError("CHECKIN_RANDOM_END 不能早于 CHECKIN_RANDOM_START")
        span = int((end_dt - start_dt).total_seconds())
        return start_dt + timedelta(seconds=self.random.randint(0, span))

    def _scheduled_state_missed_window(self, state: dict) -> bool:
        if state.get("status") != "scheduled":
            return False
        if state.get("reminder_sent") or state.get("clicked") or state.get("completed"):
            return False
        now = self._now_local()
        end = self._parse_time(self.config.checkin_random_end)
        end_dt = datetime.combine(now.date(), end, self._timezone())
        return now > end_dt

    def _load_state(self) -> dict:
        path = Path(self.config.checkin_state_file)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self.logger.exception("failed to load check-in state, recreating")
            return {}

    def _save_state(self, state: dict) -> None:
        path = Path(self.config.checkin_state_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(path)

    async def _notify(self, title: str, text: str) -> None:
        now = self._now_local().isoformat(timespec="seconds")
        await self.notifier.send(
            {
                "title": title,
                "chat_title": self.config.checkin_chat_title,
                "sender_name": "CheckInManager",
                "sender_id": 0,
                "triggered_at": now,
                "message_link": f"tg://resolve?domain={self.config.checkin_bot_username}",
                "message_text": text,
            }
        )

    def _now_local(self) -> datetime:
        if self.clock is None:
            return datetime.now(self._timezone())

        now = self.clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=self._timezone())
        return now.astimezone(self._timezone())

    def _timezone(self) -> ZoneInfo:
        return ZoneInfo(self.config.checkin_timezone)

    @staticmethod
    def _parse_time(value: str) -> time:
        hour, minute = value.split(":", 1)
        return time(int(hour), int(minute))

    def _seconds_until_tomorrow(self, now: datetime) -> float:
        tomorrow = datetime.combine(
            now.date() + timedelta(days=1),
            time(0, 0),
            self._timezone(),
        )
        return max(60.0, (tomorrow - now).total_seconds())

    @staticmethod
    def _peer_id(entity: Any) -> int:
        if hasattr(entity, "peer_id"):
            return int(entity.peer_id)
        return int(get_peer_id(entity))
