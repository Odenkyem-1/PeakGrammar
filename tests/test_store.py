"""Unit tests for PeakGrammar store modules."""

import os
import site
import sys
import tempfile
import unittest

# Ensure project root and venv site-packages (with .pth processing) are in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

VENV_SITE = os.path.join(PROJECT_ROOT, "venv", "Lib", "site-packages")
if os.path.exists(VENV_SITE):
    site.addsitedir(VENV_SITE)

from store.database import (
    init_db, get_setting, set_setting, get_all_settings,
    log_correction, get_weekly_stats, get_category_breakdown,
    get_total_corrections_count, add_snippet, get_snippets, remove_snippet
)
from store.dictionary import DictionaryStore


class TestStore(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_file.close()
        self.db_path = self.temp_file.name
        init_db(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_settings(self):
        self.assertEqual(get_setting("dialect", db_path=self.db_path), "American")
        self.assertEqual(get_setting("theme", db_path=self.db_path), "monochrome")
        set_setting("theme", "monochrome_dark", db_path=self.db_path)
        self.assertEqual(get_setting("theme", db_path=self.db_path), "monochrome_dark")
        all_s = get_all_settings(db_path=self.db_path)
        self.assertIn("dialect", all_s)
        self.assertIn("theme", all_s)

    def test_privacy_stats_logging(self):
        self.assertEqual(get_total_corrections_count(db_path=self.db_path), 0)
        log_correction("spelling", db_path=self.db_path)
        log_correction("spelling", db_path=self.db_path)
        log_correction("grammar", db_path=self.db_path)
        self.assertEqual(get_total_corrections_count(db_path=self.db_path), 3)

        breakdown = get_category_breakdown(db_path=self.db_path)
        self.assertEqual(breakdown["spelling"], 2)
        self.assertEqual(breakdown["grammar"], 1)

        weekly = get_weekly_stats(db_path=self.db_path)
        self.assertEqual(len(weekly), 1)
        self.assertEqual(weekly[0]["count"], 3)

    def test_snippets(self):
        add_snippet(";brb", "Be right back", db_path=self.db_path)
        snips = get_snippets(db_path=self.db_path)
        self.assertEqual(snips.get(";brb"), "Be right back")
        remove_snippet(";brb", db_path=self.db_path)
        self.assertNotIn(";brb", get_snippets(db_path=self.db_path))

    def test_dictionary_store(self):
        dict_store = DictionaryStore(db_path=self.db_path)
        self.assertTrue(dict_store.add_word("PeakGrammar"))
        self.assertTrue(dict_store.has_word("peakgrammar"))  # Case-insensitive
        self.assertIn("PeakGrammar", dict_store.get_words())
        self.assertTrue(dict_store.remove_word("PeakGrammar"))
        self.assertFalse(dict_store.has_word("PeakGrammar"))

    def test_custom_rules(self):
        dict_store = DictionaryStore(db_path=self.db_path)
        dict_store.add_rule("teh", "the")
        dict_store.add_rule("dont", "don't")
        rules = dict_store.get_rules()
        self.assertEqual(len(rules), 2)
        replaced = dict_store.apply_custom_rules("teh quick brown fox dont jump")
        self.assertEqual(replaced, "the quick brown fox don't jump")


if __name__ == "__main__":
    unittest.main()
