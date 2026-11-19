"""First-run onboarding and permissions diagnostic dialog.

Checks system permissions (UIA, keyboard hooks, system tray) and provides
advisories on Microsoft Word/Outlook native spellchecker conflicts.
"""

from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSystemTrayIcon,
)

from pywinauto import uia_defines
from store.database import set_setting, get_setting


def check_uia_access() -> bool:
    """Verify that Windows UI Automation is operational."""
    try:
        iuia = uia_defines.IUIA()
        elem = iuia.get_focused_element()
        return elem is not None
    except Exception:
        return False


def check_keyboard_access() -> bool:
    """Verify that keyboard hooks can be registered."""
    try:
        from pynput import keyboard
        listener = keyboard.Listener(on_press=lambda k: None)
        listener.daemon = True
        listener.start()
        listener.stop()
        return True
    except Exception:
        return False


def check_tray_access() -> bool:
    """Verify that the system tray is supported."""
    try:
        return QSystemTrayIcon.isSystemTrayAvailable()
    except Exception:
        return True


class OnboardingDialog(QDialog):
    """First-run onboarding dialog with live diagnostics and conflict guidance."""

    def __init__(self, parent: Optional[QDialog] = None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to PeakGrammar")
        self.resize(540, 480)
        self.setModal(True)

        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # Header Card
        header_card = QFrame(self)
        header_card.setObjectName("card")
        hl = QVBoxLayout(header_card)

        title = QLabel("Getting Started with PeakGrammar", header_card)
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.DemiBold))
        hl.addWidget(title)

        subtitle = QLabel("Background Writing Assistant (Harper + LLM)", header_card)
        subtitle.setStyleSheet("color: #71717a;")
        hl.addWidget(subtitle)
        root.addWidget(header_card)

        # Diagnostics Card
        diag_card = QFrame(self)
        diag_card.setObjectName("card")
        dl = QVBoxLayout(diag_card)
        dl.setSpacing(10)

        diag_title = QLabel("System Readiness Check:", diag_card)
        diag_title.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        dl.addWidget(diag_title)

        # Checklist Items
        self._add_status_row(dl, "Accessibility / UIA Text Acquisition", check_uia_access())
        self._add_status_row(dl, "Global Hotkey & Typing Hooks", check_keyboard_access())
        self._add_status_row(dl, "System Tray Service Support", check_tray_access())
        root.addWidget(diag_card)

        # Conflict Advisory Card
        advisory_card = QFrame(self)
        advisory_card.setObjectName("cardSecondary")
        al = QVBoxLayout(advisory_card)

        adv_title = QLabel("Native Spellchecker Advisory", advisory_card)
        adv_title.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        al.addWidget(adv_title)

        adv_body = QLabel(
            "In apps like Microsoft Word and Outlook, native red underlines may conflict "
            "with background suggestions. We recommend disabling Microsoft Editor, or "
            "using PeakGrammar's on-demand hotkey (<ctrl>+<shift>+e).",
            advisory_card
        )
        adv_body.setWordWrap(True)
        adv_body.setStyleSheet("color: #71717a; font-size: 12px;")
        al.addWidget(adv_body)
        root.addWidget(advisory_card)

        root.addStretch()

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.start_btn = QPushButton("Get Started", self)
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._on_start_clicked)
        btn_row.addWidget(self.start_btn)

        root.addLayout(btn_row)

    def _add_status_row(self, layout: QVBoxLayout, label: str, passed: bool) -> None:
        row = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet("color: #10b981;" if passed else "color: #f87171;")
        dot.setFixedWidth(16)
        row.addWidget(dot)

        txt = QLabel(label)
        txt.setStyleSheet("color: #f0f1f6;" if passed else "color: #8e92a4;")
        row.addWidget(txt, stretch=1)

        status_txt = QLabel("Active" if passed else "Check Permissions")
        status_txt.setStyleSheet("color: #10b981; font-weight: 600;" if passed else "color: #f87171;")
        row.addWidget(status_txt)

        layout.addLayout(row)

    def _on_start_clicked(self) -> None:
        set_setting("onboarding_completed", "1")
        self.accept()
