"""Unit tests for UI components, writing score, and monochrome stylesheet."""

import os
import site
import sys
import tempfile
import unittest

# Ensure project root and venv site-packages are in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

VENV_SITE = os.path.join(PROJECT_ROOT, "venv", "Lib", "site-packages")
if os.path.exists(VENV_SITE):
    site.addsitedir(VENV_SITE)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from ui.editor import calculate_writing_score, RefinementEditor
from ui.overlay import SuggestionOverlay
from ui.settings import SettingsDialog
from ui.onboarding import OnboardingDialog
from store.dictionary import DictionaryStore


class TestUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create single QApplication instance for Qt widget tests
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

    def test_writing_score_calculation(self):
        # Empty text has baseline 100
        self.assertEqual(calculate_writing_score("", 0), 100)

        # Clean simple sentence has high score
        score_clean = calculate_writing_score("The cat sat on the mat.", 0)
        self.assertGreaterEqual(score_clean, 80)

        # Same sentence with 3 errors is penalized
        score_penalized = calculate_writing_score("The cat sat on the mat.", 3)
        self.assertLess(score_penalized, score_clean)

    def test_stylesheet_file_exists_and_contains_monochrome_rules(self):
        qss_path = os.path.join(PROJECT_ROOT, "ui", "styles.qss")
        self.assertTrue(os.path.exists(qss_path))
        with open(qss_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("#suggestionCard", content)
        self.assertIn("#primary", content)
        self.assertIn("QProgressBar", content)

    def test_overlay_widget_attributes(self):
        overlay = SuggestionOverlay()
        flags = overlay.windowFlags()
        self.assertTrue(flags & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(flags & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(flags & Qt.WindowType.Tool)
        self.assertTrue(overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
        self.assertTrue(overlay.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))

    def test_editor_widget_initialization(self):
        editor = RefinementEditor()
        self.assertEqual(editor.tone.count(), 5)
        self.assertIn("Professional", [editor.tone.itemText(i) for i in range(5)])
        self.assertEqual(editor.score_bar.maximum(), 100)

    def test_settings_dialog_initialization(self):
        temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_file.close()
        dict_store = DictionaryStore(db_path=temp_file.name)

        settings = SettingsDialog(dictionary_store=dict_store)
        self.assertEqual(settings.tabs.count(), 4)
        self.assertEqual(settings.dialect_combo.count(), 5)

        if os.path.exists(temp_file.name):
            try:
                os.remove(temp_file.name)
            except OSError:
                pass

    def test_onboarding_dialog_initialization(self):
        onboarding = OnboardingDialog()
        self.assertTrue(onboarding.isModal())
        self.assertIsNotNone(onboarding.start_btn)


if __name__ == "__main__":
    unittest.main()
