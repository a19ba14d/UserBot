import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from userbot.checkin_manager import CheckInManager
from userbot.config import Config


class FakeNotifier:
    def __init__(self) -> None:
        self.payloads = []

    async def send(self, payload: dict) -> None:
        self.payloads.append(payload)


class FakeEntity:
    def __init__(self, peer_id: int) -> None:
        self.id = abs(peer_id)
        self.peer_id = peer_id


class FakeDialog:
    def __init__(self, name: str, entity: FakeEntity) -> None:
        self.name = name
        self.entity = entity


class FakeSender:
    def __init__(self, username: str, bot: bool = True) -> None:
        self.username = username
        self.bot = bot


class FakeButton:
    def __init__(self, text: str, data: bytes = b"callback") -> None:
        self.text = text
        self.data = data


class FakeButtonRow:
    def __init__(self, buttons: list[FakeButton]) -> None:
        self.buttons = buttons


class FakeReplyMarkup:
    def __init__(self, rows: list[FakeButtonRow]) -> None:
        self.rows = rows


class FakeMessage:
    def __init__(
        self,
        message_id: int,
        text: str,
        sender: FakeSender,
        reply_markup: FakeReplyMarkup | None = None,
        on_click=None,
    ) -> None:
        self.id = message_id
        self.raw_text = text
        self.message = text
        self.reply_markup = reply_markup
        self._sender = sender
        self._on_click = on_click
        self.clicks = []

    async def get_sender(self) -> FakeSender:
        return self._sender

    async def click(self, row: int, col: int):
        self.clicks.append((row, col))
        if self._on_click == "raise":
            raise RuntimeError("button expired")
        if self._on_click is not None:
            self._on_click()
        return object()


class FakeClient:
    def __init__(self, entity: FakeEntity, messages: list[FakeMessage]) -> None:
        self.entity = entity
        self.messages = messages

    async def iter_dialogs(self):
        yield FakeDialog("墨链公司-常规打卡群", self.entity)

    async def iter_messages(self, entity, limit: int = 100, min_id: int = 0):  # noqa: ANN001
        count = 0
        for message in sorted(self.messages, key=lambda item: item.id, reverse=True):
            if message.id <= min_id:
                continue
            if count >= limit:
                break
            count += 1
            yield message

    async def get_messages(self, entity, ids: int):  # noqa: ANN001
        for message in self.messages:
            if message.id == ids:
                return message
        return None


class CheckInManagerTests(unittest.IsolatedAsyncioTestCase):
    def make_config(self, state_file: str) -> Config:
        return Config(
            api_id=1,
            api_hash="hash",
            feishu_webhook_url="https://example.invalid/webhook",
            checkin_enabled=True,
            checkin_chat_title="墨链公司-常规打卡群",
            checkin_bot_username="web3checkinandoutbot",
            checkin_button_text="上班打卡",
            checkin_confirm_command="/confirm_checkin",
            checkin_success_keywords=frozenset({"打卡成功"}),
            checkin_result_timeout_seconds=0,
            checkin_state_file=state_file,
        )

    def write_ready_state(self, state_file: str) -> None:
        Path(state_file).write_text(
            json.dumps(
                {
                    "date": "2026-05-20",
                    "scheduled_at": "2026-05-20T11:12:00+08:00",
                    "reminder_sent": True,
                    "confirmed": False,
                    "clicked": False,
                    "completed": False,
                    "status": "awaiting_confirmation",
                }
            ),
            encoding="utf-8",
        )

    async def test_disabled_manager_ignores_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = str(Path(tmp) / "state.json")
            config = self.make_config(state_file)
            config = Config(
                api_id=config.api_id,
                api_hash=config.api_hash,
                feishu_webhook_url=config.feishu_webhook_url,
                checkin_enabled=False,
            )
            entity = FakeEntity(-1003842028710)
            button_message = FakeMessage(
                18742,
                "请选择操作",
                FakeSender("Web3CheckInAndOutbot"),
                FakeReplyMarkup([FakeButtonRow([FakeButton("🟢 上班打卡")])]),
            )
            notifier = FakeNotifier()
            manager = CheckInManager(
                client=FakeClient(entity, [button_message]),
                config=config,
                notifier=notifier,
                clock=lambda: datetime(2026, 5, 20, 11, 20, 0),
            )

            await manager.handle_outgoing_message(-1003842028710, "/confirm_checkin")

            self.assertEqual(button_message.clicks, [])
            self.assertEqual(notifier.payloads, [])

    async def test_confirm_clicks_matching_inline_button_and_records_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = str(Path(tmp) / "state.json")
            self.write_ready_state(state_file)
            entity = FakeEntity(-1003842028710)
            bot = FakeSender("Web3CheckInAndOutbot")
            messages: list[FakeMessage] = []

            def add_success_message() -> None:
                messages.append(FakeMessage(18743, "上班打卡成功", bot))

            button_message = FakeMessage(
                18742,
                "请选择操作",
                bot,
                FakeReplyMarkup([FakeButtonRow([FakeButton("🟢 上班打卡")])]),
                on_click=add_success_message,
            )
            messages.append(button_message)
            notifier = FakeNotifier()
            manager = CheckInManager(
                client=FakeClient(entity, messages),
                config=self.make_config(state_file),
                notifier=notifier,
                clock=lambda: datetime(2026, 5, 20, 11, 20, 0),
            )

            await manager.handle_outgoing_message(-1003842028710, "/confirm_checkin")

            self.assertEqual(button_message.clicks, [(0, 0)])
            saved = json.loads(Path(state_file).read_text(encoding="utf-8"))
            self.assertTrue(saved["completed"])
            self.assertEqual(saved["result_message_id"], 18743)
            self.assertIn("成功", notifier.payloads[-1]["message_text"])

    async def test_confirmation_before_daily_reminder_does_not_click(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = str(Path(tmp) / "state.json")
            Path(state_file).write_text(
                json.dumps(
                    {
                        "date": "2026-05-20",
                        "scheduled_at": "2026-05-20T11:12:00+08:00",
                        "reminder_sent": False,
                        "status": "scheduled",
                    }
                ),
                encoding="utf-8",
            )
            entity = FakeEntity(-1003842028710)
            button_message = FakeMessage(
                18742,
                "请选择操作",
                FakeSender("Web3CheckInAndOutbot"),
                FakeReplyMarkup([FakeButtonRow([FakeButton("🟢 上班打卡")])]),
            )
            notifier = FakeNotifier()
            manager = CheckInManager(
                client=FakeClient(entity, [button_message]),
                config=self.make_config(state_file),
                notifier=notifier,
                clock=lambda: datetime(2026, 5, 20, 10, 59, 0),
            )

            await manager.handle_outgoing_message(-1003842028710, "/confirm_checkin")

            self.assertEqual(button_message.clicks, [])
            self.assertIn("尚未到", notifier.payloads[-1]["message_text"])

    async def test_click_failure_is_recorded_and_notified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = str(Path(tmp) / "state.json")
            self.write_ready_state(state_file)
            entity = FakeEntity(-1003842028710)
            button_message = FakeMessage(
                18742,
                "请选择操作",
                FakeSender("Web3CheckInAndOutbot"),
                FakeReplyMarkup([FakeButtonRow([FakeButton("🟢 上班打卡")])]),
                on_click="raise",
            )
            notifier = FakeNotifier()
            manager = CheckInManager(
                client=FakeClient(entity, [button_message]),
                config=self.make_config(state_file),
                notifier=notifier,
                clock=lambda: datetime(2026, 5, 20, 11, 20, 0),
            )

            with self.assertLogs("userbot.checkin", level="ERROR"):
                await manager.handle_outgoing_message(
                    -1003842028710,
                    "/confirm_checkin",
                )

            saved = json.loads(Path(state_file).read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "click_failed")
            self.assertFalse(saved.get("clicked", False))
            self.assertIn("点击失败", notifier.payloads[-1]["message_text"])

    async def test_first_start_after_random_window_marks_today_missed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = str(Path(tmp) / "state.json")
            manager = CheckInManager(
                client=FakeClient(FakeEntity(-1003842028710), []),
                config=self.make_config(state_file),
                notifier=FakeNotifier(),
                clock=lambda: datetime(2026, 5, 20, 12, 0, 0),
            )

            state = manager._ensure_today_state()

            self.assertEqual(state["date"], "2026-05-20")
            self.assertEqual(state["status"], "missed_window")
            self.assertFalse(state["reminder_sent"])

    async def test_existing_scheduled_state_after_window_is_marked_missed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = str(Path(tmp) / "state.json")
            Path(state_file).write_text(
                json.dumps(
                    {
                        "date": "2026-05-20",
                        "scheduled_at": "2026-05-20T11:21:45+08:00",
                        "reminder_sent": False,
                        "confirmed": False,
                        "clicked": False,
                        "completed": False,
                        "status": "scheduled",
                    }
                ),
                encoding="utf-8",
            )
            manager = CheckInManager(
                client=FakeClient(FakeEntity(-1003842028710), []),
                config=self.make_config(state_file),
                notifier=FakeNotifier(),
                clock=lambda: datetime(2026, 5, 20, 12, 10, 0),
            )

            state = manager._ensure_today_state()

            self.assertEqual(state["status"], "missed_window")
            self.assertFalse(state["reminder_sent"])


if __name__ == "__main__":
    unittest.main()
