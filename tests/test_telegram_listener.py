import unittest
from datetime import datetime

from userbot.config import Config
from userbot.telegram_listener import TelegramListener


class FakeMessage:
    def __init__(self, text: str = "hello", message_id: int = 42) -> None:
        self.out = False
        self.fwd_from = None
        self.message = text
        self.id = message_id
        self.date = datetime(2026, 5, 19, 12, 0, 0)


class FakeChat:
    def __init__(
        self,
        title: str = "Test Group",
        broadcast: bool = False,
        username: str | None = None,
    ) -> None:
        self.title = title
        self.broadcast = broadcast
        self.username = username


class FakeSender:
    def __init__(
        self,
        sender_id: int,
        username: str | None,
        bot: bool,
        first_name: str = "Sender",
    ) -> None:
        self.id = sender_id
        self.username = username
        self.bot = bot
        self.first_name = first_name
        self.last_name = ""


class FakeEvent:
    def __init__(
        self,
        *,
        chat_id: int,
        is_private: bool,
        mentioned: bool,
        sender: FakeSender,
        chat: FakeChat | None = None,
    ) -> None:
        self.chat_id = chat_id
        self.is_private = is_private
        self.mentioned = mentioned
        self.message = FakeMessage()
        self._sender = sender
        self._chat = chat or FakeChat()

    async def get_chat(self) -> FakeChat:
        return self._chat

    async def get_sender(self) -> FakeSender:
        return self._sender


class TelegramListenerPrivateBotFilteringTests(unittest.IsolatedAsyncioTestCase):
    def make_listener(self, config: Config, reminders: list) -> TelegramListener:
        async def on_trigger(reminder) -> None:  # noqa: ANN001
            reminders.append(reminder)

        async def on_self_reply(chat_id: int) -> None:
            raise AssertionError(f"unexpected self reply callback: {chat_id}")

        return TelegramListener(
            client=object(),
            config=config,
            on_trigger=on_trigger,
            on_self_reply=on_self_reply,
        )

    async def test_private_regular_user_still_triggers(self) -> None:
        reminders = []
        config = Config(
            api_id=1,
            api_hash="hash",
            feishu_webhook_url="https://example.invalid/webhook",
        )
        listener = self.make_listener(config, reminders)
        event = FakeEvent(
            chat_id=100,
            is_private=True,
            mentioned=False,
            sender=FakeSender(100, "alice", bot=False),
        )

        await listener._on_incoming(event)

        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0].sender_id, 100)

    async def test_private_bot_ignored_when_not_whitelisted(self) -> None:
        reminders = []
        config = Config(
            api_id=1,
            api_hash="hash",
            feishu_webhook_url="https://example.invalid/webhook",
        )
        listener = self.make_listener(config, reminders)
        event = FakeEvent(
            chat_id=200,
            is_private=True,
            mentioned=False,
            sender=FakeSender(200, "noise_bot", bot=True),
        )

        await listener._on_incoming(event)

        self.assertEqual(reminders, [])

    async def test_private_bot_allowed_by_id(self) -> None:
        reminders = []
        config = Config(
            api_id=1,
            api_hash="hash",
            feishu_webhook_url="https://example.invalid/webhook",
            whitelist_bot_ids=frozenset({300}),
        )
        listener = self.make_listener(config, reminders)
        event = FakeEvent(
            chat_id=300,
            is_private=True,
            mentioned=False,
            sender=FakeSender(300, "noise_bot", bot=True),
        )

        await listener._on_incoming(event)

        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0].sender_id, 300)

    async def test_private_bot_allowed_by_username(self) -> None:
        reminders = []
        config = Config(
            api_id=1,
            api_hash="hash",
            feishu_webhook_url="https://example.invalid/webhook",
            whitelist_bot_usernames=frozenset({"trustedbot"}),
        )
        listener = self.make_listener(config, reminders)
        event = FakeEvent(
            chat_id=400,
            is_private=True,
            mentioned=False,
            sender=FakeSender(400, "TrustedBot", bot=True),
        )

        await listener._on_incoming(event)

        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0].sender_id, 400)

    async def test_group_bot_mention_is_not_filtered_by_private_bot_allowlist(
        self,
    ) -> None:
        reminders = []
        config = Config(
            api_id=1,
            api_hash="hash",
            feishu_webhook_url="https://example.invalid/webhook",
        )
        listener = self.make_listener(config, reminders)
        event = FakeEvent(
            chat_id=-100123,
            is_private=False,
            mentioned=True,
            sender=FakeSender(500, "group_bot", bot=True),
            chat=FakeChat(title="Ops Group"),
        )

        await listener._on_incoming(event)

        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0].chat_title, "Ops Group")


if __name__ == "__main__":
    unittest.main()
