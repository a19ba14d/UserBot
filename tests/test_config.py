import os
import unittest
from unittest.mock import patch

from userbot.config import Config, load_config


class ConfigBotWhitelistTests(unittest.TestCase):
    def test_load_config_allows_disabled_feishu_without_webhook_url(self) -> None:
        env = {
            "TG_API_ID": "12345",
            "TG_API_HASH": "hash",
            "FEISHU_ENABLED": "false",
        }

        with patch.dict(os.environ, env, clear=True), patch(
            "userbot.config.load_dotenv",
            lambda: None,
        ):
            config = load_config()

        self.assertFalse(config.feishu_enabled)
        self.assertEqual(config.feishu_webhook_url, "")

    def test_load_config_requires_webhook_url_when_feishu_enabled(self) -> None:
        env = {
            "TG_API_ID": "12345",
            "TG_API_HASH": "hash",
            "FEISHU_ENABLED": "true",
        }

        with patch.dict(os.environ, env, clear=True), patch(
            "userbot.config.load_dotenv",
            lambda: None,
        ):
            with self.assertRaisesRegex(ValueError, "FEISHU_WEBHOOK_URL"):
                load_config()

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


class ConfigCheckInTests(unittest.TestCase):
    def test_load_config_parses_checkin_settings(self) -> None:
        env = {
            "TG_API_ID": "12345",
            "TG_API_HASH": "hash",
            "FEISHU_WEBHOOK_URL": "https://example.invalid/webhook",
            "CHECKIN_ENABLED": "true",
            "CHECKIN_RANDOM_START": "11:00",
            "CHECKIN_RANDOM_END": "11:30",
            "CHECKIN_CHAT_TITLE": "墨链公司-常规打卡群",
            "CHECKIN_BOT_USERNAME": "@Web3CheckInAndOutbot",
            "CHECKIN_BUTTON_TEXT": "上班打卡",
            "CHECKIN_FALLBACK_MESSAGE_ID": "18742",
            "CHECKIN_CONFIRM_COMMAND": "/confirm_checkin",
            "CHECKIN_SUCCESS_KEYWORDS": "打卡成功, 上班打卡成功",
            "CHECKIN_RESULT_TIMEOUT_SECONDS": "15",
            "CHECKIN_STATE_FILE": "/tmp/checkin-state.json",
        }

        with patch.dict(os.environ, env, clear=True), patch(
            "userbot.config.load_dotenv",
            lambda: None,
        ):
            config = load_config()

        self.assertTrue(config.checkin_enabled)
        self.assertEqual(config.checkin_bot_username, "web3checkinandoutbot")
        self.assertEqual(config.checkin_fallback_message_id, 18742)
        self.assertEqual(config.checkin_success_keywords, frozenset({"打卡成功", "上班打卡成功"}))
        self.assertEqual(config.checkin_state_file, "/tmp/checkin-state.json")

    def test_load_config_rejects_disabling_checkin_confirmation(self) -> None:
        env = {
            "TG_API_ID": "12345",
            "TG_API_HASH": "hash",
            "FEISHU_WEBHOOK_URL": "https://example.invalid/webhook",
            "CHECKIN_CONFIRM_REQUIRED": "false",
        }

        with patch.dict(os.environ, env, clear=True), patch(
            "userbot.config.load_dotenv",
            lambda: None,
        ):
            with self.assertRaisesRegex(ValueError, "CHECKIN_CONFIRM_REQUIRED"):
                load_config()


if __name__ == "__main__":
    unittest.main()
