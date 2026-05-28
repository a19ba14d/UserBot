import unittest

from userbot.config import Config
from userbot.feishu_notifier import FeishuNotifier
from userbot.main import _build_notifiers


class MainNotifierTests(unittest.TestCase):
    def test_build_notifiers_skips_feishu_when_disabled(self) -> None:
        config = Config(
            api_id=1,
            api_hash="hash",
            feishu_enabled=False,
            feishu_webhook_url="",
        )

        notifiers = _build_notifiers(config)

        self.assertFalse(any(isinstance(notifier, FeishuNotifier) for notifier in notifiers))

    def test_build_notifiers_includes_feishu_when_enabled(self) -> None:
        config = Config(
            api_id=1,
            api_hash="hash",
            feishu_enabled=True,
            feishu_webhook_url="https://example.invalid/webhook",
        )

        notifiers = _build_notifiers(config)

        self.assertTrue(any(isinstance(notifier, FeishuNotifier) for notifier in notifiers))


if __name__ == "__main__":
    unittest.main()
