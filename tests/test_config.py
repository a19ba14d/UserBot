import os
import unittest
from unittest.mock import patch

from userbot.config import Config, load_config


class ConfigBotWhitelistTests(unittest.TestCase):
    def test_load_config_normalizes_bot_allowlist_values(self) -> None:
        env = {
            "TG_API_ID": "12345",
            "TG_API_HASH": "hash",
            "FEISHU_WEBHOOK_URL": "https://example.invalid/webhook",
            "WHITELIST_BOT_IDS": "111, 222",
            "WHITELIST_BOT_USERNAMES": "@TrustedBot, helper_bot, @MIXED_CASE",
        }

        with patch.dict(os.environ, env, clear=True), patch(
            "userbot.config.load_dotenv",
            lambda: None,
        ):
            config = load_config()

        self.assertEqual(config.whitelist_bot_ids, frozenset({111, 222}))
        self.assertEqual(
            config.whitelist_bot_usernames,
            frozenset({"trustedbot", "helper_bot", "mixed_case"}),
        )

    def test_load_config_rejects_invalid_bot_id(self) -> None:
        env = {
            "TG_API_ID": "12345",
            "TG_API_HASH": "hash",
            "FEISHU_WEBHOOK_URL": "https://example.invalid/webhook",
            "WHITELIST_BOT_IDS": "111, nope",
        }

        with patch.dict(os.environ, env, clear=True), patch(
            "userbot.config.load_dotenv",
            lambda: None,
        ):
            with self.assertRaisesRegex(ValueError, "WHITELIST_BOT_IDS"):
                load_config()

    def test_private_bot_allowlist_matches_id_or_username(self) -> None:
        config = Config(
            api_id=1,
            api_hash="hash",
            feishu_webhook_url="https://example.invalid/webhook",
            whitelist_bot_ids=frozenset({111}),
            whitelist_bot_usernames=frozenset({"trustedbot"}),
        )

        self.assertTrue(config.is_private_bot_allowed(111, "other_bot"))
        self.assertTrue(config.is_private_bot_allowed(222, "@TrustedBot"))
        self.assertFalse(config.is_private_bot_allowed(222, "unknown_bot"))

    def test_private_bot_allowlist_empty_rejects_all_bots(self) -> None:
        config = Config(
            api_id=1,
            api_hash="hash",
            feishu_webhook_url="https://example.invalid/webhook",
        )

        self.assertFalse(config.is_private_bot_allowed(111, "trustedbot"))


if __name__ == "__main__":
    unittest.main()
