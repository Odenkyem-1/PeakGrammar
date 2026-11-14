"""Unit tests for online LLM engine and offline failover."""

import os
import site
import sys
import unittest
from unittest.mock import MagicMock

# Ensure project root and venv site-packages are in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

VENV_SITE = os.path.join(PROJECT_ROOT, "venv", "Lib", "site-packages")
if os.path.exists(VENV_SITE):
    site.addsitedir(VENV_SITE)

from core.engine_online import OnlineEngine, TONE_INSTRUCTIONS
from core.engine_offline import OfflineEngine


class TestOnlineEngine(unittest.TestCase):
    def test_tone_instructions_exist(self):
        for tone in ("Professional", "Friendly", "Confident", "Concise", "Academic"):
            self.assertIn(tone, TONE_INSTRUCTIONS)
            self.assertGreater(len(TONE_INSTRUCTIONS[tone]), 10)

    def test_unconfigured_engine_safe_behavior(self):
        # Engine without API key should not crash and should fail closed
        engine = OnlineEngine(provider="groq", api_key="")
        self.assertFalse(engine.is_configured())
        self.assertIsNone(engine.rewrite("Sample text to rewrite."))

    def test_mock_rewrite_with_masking(self):
        engine = OnlineEngine(provider="groq", api_key="mock-test-key")
        self.assertTrue(engine.is_configured())

        # Mock the internal client completions create call
        mock_resp = MagicMock()
        # Simulate LLM preserving the placeholder token and enclosing response in quotes
        mock_resp.choices = [
            MagicMock(message=MagicMock(content='"Check https://github.com for details."'))
        ]

        engine._client = MagicMock()
        engine._client.chat.completions.create.return_value = mock_resp

        result = engine.rewrite(
            text="Check https://github.com for detailz.",
            tone_or_instruction="Professional"
        )

        # Verified quotes were stripped and URL was unmasked
        self.assertEqual(result, "Check https://github.com for details.")

    def test_timeout_and_failover_in_get_suggestions(self):
        mock_offline = MagicMock(spec=OfflineEngine)
        mock_offline.lint.return_value = [{"message": "Mock Harper lint", "suggestions": ["test"]}]

        engine = OnlineEngine(provider="groq", api_key="mock-key", offline_engine=mock_offline)

        # 1. Offline mode always uses offline engine
        res_offline = engine.get_suggestions("Some input text.", mode="offline")
        self.assertEqual(len(res_offline), 1)
        self.assertEqual(res_offline[0]["message"], "Mock Harper lint")

        # 2. Online mode with failing LLM fails over to offline engine
        engine._client = MagicMock()
        engine._client.chat.completions.create.side_effect = TimeoutError("Request timed out")

        res_online = engine.get_suggestions("Some input text.", mode="online")
        self.assertEqual(len(res_online), 1)
        self.assertEqual(res_online[0]["message"], "Mock Harper lint")

        # 3. Auto mode defaults to offline Harper for real-time keystroke privacy
        res_auto = engine.get_suggestions("Some input text.", mode="auto")
        self.assertEqual(len(res_auto), 1)
        self.assertEqual(res_auto[0]["message"], "Mock Harper lint")


if __name__ == "__main__":
    unittest.main()
