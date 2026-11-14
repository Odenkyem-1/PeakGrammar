"""Integration tests for PeakGrammar main orchestration and lifecycle."""

import os
import site
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure project root and venv site-packages are in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

VENV_SITE = os.path.join(PROJECT_ROOT, "venv", "Lib", "site-packages")
if os.path.exists(VENV_SITE):
    site.addsitedir(VENV_SITE)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal


class TestMainIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

    def test_service_bridge_signal_emission(self):
        class ServiceBridge(QObject):
            check_field_requested = Signal()

        bridge = ServiceBridge()
        received = False

        def slot():
            nonlocal received
            received = True

        bridge.check_field_requested.connect(slot)
        bridge.check_field_requested.emit()
        self.assertTrue(received)

    def test_import_and_init_main_components(self):
        # Verify that all components required by main.py import cleanly
        import main
        self.assertIsNotNone(main.offline)
        self.assertIsNotNone(main.online)
        self.assertIsNotNone(main.overlay)
        self.assertIsNotNone(main.editor)
        self.assertIsNotNone(main.tray)
        self.assertIsNotNone(main.debouncer)
        self.assertIsNotNone(main.hotkey_manager)

    def test_clean_teardown(self):
        import main
        # Ensure teardown executes safely
        main.on_app_quit()


if __name__ == "__main__":
    unittest.main()
