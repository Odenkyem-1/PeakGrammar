"""Main orchestration entry point for PeakGrammar.

Runs PeakGrammar as an offline-first system tray background service on Windows,
coordinating UIA text acquisition, Harper grammar checks, floating overlay,
Refinement Studio, and on-demand LLM rewrites.
"""

import os
import site
import sys

# Ensure project root and venv site-packages are loaded
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

VENV_SITE = os.path.join(PROJECT_ROOT, "venv", "Lib", "site-packages")
if os.path.exists(VENV_SITE):
    site.addsitedir(VENV_SITE)

# 1. Initialize QApplication at the very top for clean DPI / OLE handling
from PySide6.QtCore import Qt, QPoint, QObject, Signal, QTimer
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import (
    QApplication,
    QSystemTrayIcon,
    QMenu,
    QMessageBox,
)

app = QApplication.instance() or QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

# Load Soft-UI monochrome stylesheet
qss_path = os.path.join(PROJECT_ROOT, "ui", "styles.qss")
if os.path.exists(qss_path):
    with open(qss_path, "r", encoding="utf-8") as f:
        app.setStyleSheet(f.read())

# Set application window icon
icon_path = os.path.join(PROJECT_ROOT, "resources", "icons", "app.png")
if os.path.exists(icon_path):
    app.setWindowIcon(QIcon(icon_path))

# 2. Storage & Engine Initialization
from store.database import init_db, get_setting, log_correction
from store.dictionary import DictionaryStore
from core.engine_offline import OfflineEngine
from core.engine_online import OnlineEngine
from core.text_acquisition import get_focused_context, calculate_caret_screen_position
from core.applier import apply_text
from core.debounce import IdleDebouncer
from core.hotkeys import HotkeyManager, KeyboardActivityListener
from ui.overlay import SuggestionOverlay
from ui.editor import RefinementEditor
from ui.settings import SettingsDialog
from ui.onboarding import OnboardingDialog

init_db()
dictionary = DictionaryStore()

active_dialect = get_setting("dialect", "American")
active_provider = get_setting("provider", "groq")

offline = OfflineEngine(dialect=active_dialect, dictionary_store=dictionary)
online = OnlineEngine(provider=active_provider, offline_engine=offline)

overlay = SuggestionOverlay()
editor = RefinementEditor(offline_engine=offline, online_engine=online)


# ---------------------------------------------------------------------------
# 3. Thread-Safe Qt Bridge
# ---------------------------------------------------------------------------
class ServiceBridge(QObject):
    """Bridges background thread triggers (hotkeys, debouncer) to the Qt GUI thread."""
    check_field_requested = Signal()
    open_editor_with_text = Signal(str)


bridge = ServiceBridge()


def trigger_check() -> None:
    """Emits signal to main thread from debouncer or hotkey."""
    bridge.check_field_requested.emit()


# ---------------------------------------------------------------------------
# 4. Field Checking Logic (Runs strictly in main Qt thread)
# ---------------------------------------------------------------------------
_last_inspected_text = ""
_last_dismissed_text = ""


def on_check_field() -> None:
    global _last_inspected_text, _last_dismissed_text

    # Read focused control via Windows UI Automation
    context = get_focused_context()
    if not context or not context.text or not context.text.strip():
        return

    text = context.text.strip()

    # Do not re-trigger on identical text if already dismissed or overlay is active
    if text == _last_dismissed_text:
        return

    _last_inspected_text = text

    # Apply custom replacement rules first (e.g. abbreviations, conventions)
    text_with_rules = dictionary.apply_custom_rules(text)

    # Lint using in-process offline Harper engine
    lints = offline.lint(text_with_rules)
    if not lints:
        overlay.hide()
        return

    # Show the first actionable issue
    lint = lints[0]
    suggestion = lint["suggestions"][0] if lint["suggestions"] else ""
    suggest_only = get_setting("suggest_only", "0") == "1"

    def on_apply() -> None:
        global _last_dismissed_text
        if suggestion:
            new_text = offline.apply_suggestion(text_with_rules, lint, suggestion)
            apply_text(new_text, wrapper=context.wrapper, suggest_only=suggest_only)
            cat = "spelling" if "spell" in lint.get("message", "").lower() else "grammar"
            log_correction(cat)
        _last_dismissed_text = text
        overlay.hide()

    def on_ignore() -> None:
        global _last_dismissed_text
        _last_dismissed_text = text
        overlay.hide()

    def on_dict() -> None:
        global _last_dismissed_text
        word = lint.get("problem_text", "").strip()
        if word:
            dictionary.add_word(word)
            offline.sync_dictionary()
        _last_dismissed_text = text
        overlay.hide()

    def on_rewrite() -> None:
        overlay.hide()
        editor.set_content(text)
        editor.show()
        editor.raise_()
        editor.activateWindow()

    # Calculate caret screen coordinates
    x, y = calculate_caret_screen_position(context.bounding_rect, len(text))
    overlay.show_suggestion(
        lint,
        on_apply=on_apply,
        on_ignore=on_ignore,
        on_dict=on_dict,
        on_rewrite=on_rewrite,
        anchor_pos=QPoint(x, y),
    )


bridge.check_field_requested.connect(on_check_field)


# ---------------------------------------------------------------------------
# 5. Background Listeners (Debounce + Hotkeys)
# ---------------------------------------------------------------------------
debounce_delay = int(get_setting("debounce_ms", "700"))
debouncer = IdleDebouncer(callback=trigger_check, delay_ms=debounce_delay)

# Keystroke listener resets idle debouncer
activity_listener = KeyboardActivityListener(on_activity=debouncer.poke)
activity_listener.start()

# Global hotkey (<ctrl>+<shift>+e) for on-demand check
hotkey_combo = get_setting("hotkey", "<ctrl>+<shift>+e")
hotkey_manager = HotkeyManager(callback=trigger_check, combo=hotkey_combo)
hotkey_manager.start()


# ---------------------------------------------------------------------------
# 6. System Tray Setup
# ---------------------------------------------------------------------------
tray_icon_path = os.path.join(PROJECT_ROOT, "resources", "icons", "tray_adaptive.png")
if not os.path.exists(tray_icon_path):
    tray_icon_path = os.path.join(PROJECT_ROOT, "resources", "icons", "tray.png")

tray = QSystemTrayIcon(QIcon(tray_icon_path), app)
tray.setToolTip("PeakGrammar — Background Writing Assistant")

tray_menu = QMenu()

act_open_editor = QAction("Open Refinement Studio", tray_menu)
act_open_editor.triggered.connect(lambda: (editor.show(), editor.raise_(), editor.activateWindow()))
tray_menu.addAction(act_open_editor)

act_check = QAction(f"Check Active Field ({hotkey_combo})", tray_menu)
act_check.triggered.connect(trigger_check)
tray_menu.addAction(act_check)

act_settings = QAction("Settings", tray_menu)


def open_settings_dialog() -> None:
    dlg = SettingsDialog(dictionary_store=dictionary)
    if dlg.exec():
        # Reload updated settings dynamically
        new_dialect = get_setting("dialect", "American")
        offline.set_dialect(new_dialect)
        online.update_config(provider=get_setting("provider", "groq"))
        debouncer.set_delay(int(get_setting("debounce_ms", "700")))


act_settings.triggered.connect(open_settings_dialog)

tray_menu.addSeparator()

act_quit = QAction("Quit PeakGrammar", tray_menu)
act_quit.triggered.connect(app.quit)
tray_menu.addAction(act_quit)

tray.setContextMenu(tray_menu)


def on_tray_activated(reason: QSystemTrayIcon.ActivationReason) -> None:
    if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
        editor.show()
        editor.raise_()
        editor.activateWindow()


tray.activated.connect(on_tray_activated)
tray.show()


# ---------------------------------------------------------------------------
# 7. Lifecycle Teardown
# ---------------------------------------------------------------------------
def on_app_quit() -> None:
    debouncer.stop()
    activity_listener.stop()
    hotkey_manager.stop()
    overlay.hide()


app.aboutToQuit.connect(on_app_quit)


# ---------------------------------------------------------------------------
# 8. First-Run Onboarding Check
# ---------------------------------------------------------------------------
def run_app() -> int:
    if get_setting("onboarding_completed", "0") != "1":
        onboarding = OnboardingDialog()
        onboarding.exec()

    # Notify via system tray that PeakGrammar is active in the background
    tray.showMessage(
        "PeakGrammar is Running",
        f"Active in background. Press {hotkey_combo} or pause typing to check grammar.",
        QSystemTrayIcon.MessageIcon.Information,
        3000,
    )

    return app.exec()


if __name__ == "__main__":
    sys.exit(run_app())
