"""Unit tests for offline grammar engine and developer masking."""

import os
import sys
import tempfile
import unittest

# Ensure project root and venv site-packages are in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

VENV_SITE = os.path.join(PROJECT_ROOT, "venv", "Lib", "site-packages")
if os.path.exists(VENV_SITE) and VENV_SITE not in sys.path:
    sys.path.insert(0, VENV_SITE)

from core.masking import (
    get_protected_spans,
    is_span_protected,
    mask_protected,
    unmask_text,
)
from core.engine_offline import OfflineEngine
from store.dictionary import DictionaryStore


class TestMasking(unittest.TestCase):
    def test_protected_spans(self):
        text = (
            "Check https://github.com/peak/grammar and run `pip install test` "
            "then open C:\\Users\\Name\\Project\\main.py with @colleague :rocket:"
        )
        spans = get_protected_spans(text)
        self.assertGreaterEqual(len(spans), 4)

        # Verify segments match expected protected content
        extracted = [text[start:end] for start, end in spans]
        self.assertTrue(any("https://github.com" in s for s in extracted))
        self.assertTrue(any("`pip install test`" in s for s in extracted))
        self.assertTrue(any("C:\\Users\\Name" in s for s in extracted))
        self.assertTrue(any("@colleague" in s for s in extracted))
        self.assertTrue(any(":rocket:" in s for s in extracted))

    def test_mask_and_unmask(self):
        raw = "Visit https://google.com and see `console.log('hello')`."
        masked, placeholders = mask_protected(raw)
        self.assertNotIn("https://google.com", masked)
        self.assertNotIn("console.log", masked)
        self.assertIn("__PG_TOKEN_", masked)

        restored = unmask_text(masked, placeholders)
        self.assertEqual(restored, raw)

    def test_is_span_protected(self):
        protected = [(10, 25)]
        self.assertTrue(is_span_protected((12, 18), protected))
        self.assertTrue(is_span_protected((5, 15), protected))
        self.assertFalse(is_span_protected((0, 5), protected))
        self.assertFalse(is_span_protected((25, 30), protected))


class TestOfflineEngine(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_file.close()
        self.db_path = self.temp_file.name
        self.dict_store = DictionaryStore(db_path=self.db_path)
        self.engine = OfflineEngine(dialect="American", dictionary_store=self.dict_store)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_basic_linting_and_replacement(self):
        sample = "This is an test."
        lints = self.engine.lint(sample)
        self.assertGreater(len(lints), 0)

        # Check first suggestion
        lint = lints[0]
        self.assertEqual(lint["problem_text"], "an")
        self.assertIn("a", lint["suggestions"])

        # Apply suggestion
        fixed = self.engine.apply_suggestion(sample, lint, lint["suggestions"][0])
        self.assertEqual(fixed, "This is a test.")

    def test_personal_dictionary_filter(self):
        # A made-up domain term that would normally trigger a spellcheck lint
        sample = "We deployed the XyloZorba service today."
        lints_before = self.engine.lint(sample)
        self.assertTrue(any("XyloZorba" in l["problem_text"] for l in lints_before))

        # Add to personal dictionary
        self.dict_store.add_word("XyloZorba")
        self.engine.sync_dictionary()

        # Should no longer be flagged
        lints_after = self.engine.lint(sample)
        self.assertFalse(any("XyloZorba" in l["problem_text"] for l in lints_after))

    def test_protected_tokens_not_flagged(self):
        # Code containing variable names that shouldn't trigger spelling lints
        text = "Please examine `my_unusual_var_name_xyz` for errors."
        lints = self.engine.lint(text)
        self.assertFalse(any("my_unusual_var_name_xyz" in l["problem_text"] for l in lints))


if __name__ == "__main__":
    unittest.main()
