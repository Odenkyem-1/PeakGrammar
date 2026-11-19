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
from PySide6.QtCore import Qt, QRect, QPoint

from ui.editor import calculate_writing_score, RefinementEditor
from ui.overlay import SuggestionOverlay, calculate_overlay_geometry
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

    def test_overlay_geometry_smart_placement(self):
        screen_geom = QRect(0, 0, 1920, 1040)
        card_size = (360, 140)

        # 1. Normal input field in upper screen -> places cleanly below
        ctrl_rect = (400, 100, 800, 140)
        x, y = calculate_overlay_geometry(screen_geom, card_size, None, ctrl_rect)
        self.assertGreaterEqual(y, 140)  # cleanly below input
        self.assertEqual(x, 400)

        # 2. Input field near bottom of screen -> places cleanly above
        ctrl_bottom_rect = (400, 950, 800, 990)
        x, y = calculate_overlay_geometry(screen_geom, card_size, None, ctrl_bottom_rect)
        self.assertTrue(y < 950)  # above input
        self.assertEqual(y, 950 - 140 - 8)

        # 3. Chat sidebar on right edge -> docks to the left of the sidebar
        sidebar_rect = (1400, 800, 1850, 920)
        x, y = calculate_overlay_geometry(screen_geom, card_size, None, sidebar_rect)
        self.assertTrue(x < 1400)  # to the left of sidebar
        self.assertEqual(x, 1400 - 360 - 12)

        # 4. Caret near edge -> never clips outside screen boundaries
        edge_pos = QPoint(1910, 1030)
        x, y = calculate_overlay_geometry(screen_geom, card_size, edge_pos, None)
        self.assertLessEqual(x + card_size[0], screen_geom.right())
        self.assertLessEqual(y + card_size[1], screen_geom.bottom())
        self.assertGreaterEqual(x, screen_geom.left())
        self.assertGreaterEqual(y, screen_geom.top())

    def test_editor_widget_initialization(self):
        editor = RefinementEditor()
        self.assertIn("Academic", editor.tone_buttons)
        self.assertIn("Professional", editor.tone_buttons)
        self.assertIn("Casual", editor.tone_buttons)
        self.assertIsNotNone(editor.score_gauge)
        self.assertEqual(editor.score_gauge.score, 100)
        self.assertIsNotNone(editor.text_edit)

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
