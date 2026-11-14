"""Unit tests for text acquisition, applier, debouncer, and hotkeys."""

import os
import site
import sys
import time
import unittest

# Ensure project root and venv site-packages (with .pth processing) are in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

VENV_SITE = os.path.join(PROJECT_ROOT, "venv", "Lib", "site-packages")
if os.path.exists(VENV_SITE):
    site.addsitedir(VENV_SITE)

import pyperclip
from core.text_acquisition import (
    is_excluded,
    calculate_caret_screen_position,
    EXCLUDED_PROCESSES,
)
from core.applier import apply_text, copy_to_clipboard
from core.debounce import IdleDebouncer
from core.hotkeys import SnippetExpander


class TestTextAcquisition(unittest.TestCase):
    def test_exclusion_rules(self):
        # Known excluded processes
        self.assertTrue(is_excluded("powershell.exe"))
        self.assertTrue(is_excluded("cmd.exe"))
        self.assertTrue(is_excluded("code.exe"))
        self.assertTrue(is_excluded("keepass.exe"))
        self.assertTrue(is_excluded("bitwarden.exe"))

        # Empty or unknown process -> fails closed
        self.assertTrue(is_excluded(""))
        self.assertTrue(is_excluded(None))

        # Allowed daily productivity applications
        self.assertFalse(is_excluded("notepad.exe"))
        self.assertFalse(is_excluded("winword.exe"))
        self.assertFalse(is_excluded("chrome.exe"))
        self.assertFalse(is_excluded("slack.exe"))

        # Title-based exclusion
        self.assertTrue(is_excluded("custom_app.exe", app_title="KeePass Database"))
        self.assertTrue(is_excluded("custom_app.exe", app_title="Bitwarden Vault"))

    def test_caret_screen_position_calculation(self):
        # Rect: left=100, top=200, right=500, bottom=250
        rect = (100, 200, 500, 250)
        x, y = calculate_caret_screen_position(rect, text_length=10)
        self.assertGreaterEqual(x, 100)
        self.assertLessEqual(x, 500)
        self.assertEqual(y, 258)  # bottom + 8px


class TestApplier(unittest.TestCase):
    def test_copy_and_suggest_only(self):
        sample_text = "Corrected grammar content for testing."
        res = apply_text(sample_text, suggest_only=True)
        self.assertTrue(res)


class TestDebouncer(unittest.TestCase):
    def test_debounced_fire(self):
        call_count = 0

        def callback():
            nonlocal call_count
            call_count += 1

        debouncer = IdleDebouncer(callback, delay_ms=100)
        # Rapid pokes should only fire once
        debouncer.poke()
        debouncer.poke()
        debouncer.poke()

        # Wait before delay expires
        time.sleep(0.04)
        self.assertEqual(call_count, 0)

        # Wait for delay to expire
        time.sleep(0.12)
        self.assertEqual(call_count, 1)

    def test_debounced_cancel(self):
        call_count = 0

        def callback():
            nonlocal call_count
            call_count += 1

        debouncer = IdleDebouncer(callback, delay_ms=100)
        debouncer.poke()
        debouncer.cancel()
        time.sleep(0.15)
        self.assertEqual(call_count, 0)


class TestSnippetExpander(unittest.TestCase):
    def test_snippet_buffer(self):
        expander = SnippetExpander({";brb": "Be right back"}, enabled=True)
        # Simulate typing keys
        class MockKey:
            def __init__(self, char):
                self.char = char

        for ch in "hello ;b":
            expander.on_key(MockKey(ch))
        self.assertEqual(expander.buffer, "hello ;b")


if __name__ == "__main__":
    unittest.main()
