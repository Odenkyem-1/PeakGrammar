"""Main Refinement Studio editor workspace for PeakGrammar.

Provides an interactive soft-UI environment for in-depth text analysis,
offline Harper linting, live writing scores, and tone-guided LLM rewrites.
"""

import math
import re
from typing import Optional
import pyperclip

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLabel,
    QComboBox,
    QPushButton,
    QFrame,
    QProgressBar,
    QApplication,
)

from core.engine_offline import OfflineEngine
from core.engine_online import OnlineEngine


def calculate_writing_score(text: str, issues_count: int) -> int:
    """Calculate an objective writing score from 0 to 100.

    Based on Flesch Reading Ease and penalty for detected grammatical issues.
    """
    clean_text = text.strip()
    if not clean_text:
        return 100

    words = re.findall(r"\b\w+\b", clean_text)
    sentences = [s for s in re.split(r"[.!?]+", clean_text) if s.strip()]

    word_count = len(words)
    sentence_count = max(1, len(sentences))

    if word_count == 0:
        return 100

    # Syllable estimation
    def count_syllables(w: str) -> int:
        w = w.lower()
        count = len(re.findall(r"[aeiouy]+", w))
        if w.endswith("e") and not w.endswith("le") and count > 1:
            count -= 1
        return max(1, count)

    total_syllables = sum(count_syllables(w) for w in words)

    # Standard Flesch Reading Ease Formula
    asl = word_count / sentence_count
    asw = total_syllables / word_count
    flesch = 206.835 - (1.015 * asl) - (84.6 * asw)

    # Base score clamped to 0-100 before applying issue penalty
    base_score = max(0, min(100, int(flesch)))
    penalty = issues_count * 5
    score = max(20, base_score - penalty)
    return score


class RefinementEditor(QWidget):
    """Refinement Studio workspace window."""

    def __init__(
        self,
        offline_engine: Optional[OfflineEngine] = None,
        online_engine: Optional[OnlineEngine] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.offline = offline_engine or OfflineEngine()
        self.online = online_engine or OnlineEngine(offline_engine=self.offline)

        self.setWindowTitle("Refinement Studio — PeakGrammar")
        self.resize(920, 680)
        self.setMinimumSize(700, 500)

        # Debounced live analysis timer
        self._analyze_timer = QTimer(self)
        self._analyze_timer.setSingleShot(True)
        self._analyze_timer.timeout.connect(self._run_offline_analysis)

        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # -------------------------------------------------------------------
        # 1. Header Card
        # -------------------------------------------------------------------
        header = QFrame(self)
        header.setObjectName("card")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 12, 16, 12)

        title = QLabel("Refinement Studio", header)
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #18181b;")
        hl.addWidget(title)

        hl.addStretch()

        # Tone Selector
        tone_lbl = QLabel("Tone:", header)
        tone_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        tone_lbl.setStyleSheet("color: #71717a;")
        hl.addWidget(tone_lbl)

        self.tone = QComboBox(header)
        self.tone.addItems(["Professional", "Friendly", "Confident", "Concise", "Academic"])
        hl.addWidget(self.tone)

        # Mode Indicator
        self.mode_badge = QLabel("Offline (Harper)", header)
        self.mode_badge.setObjectName("badgeSpelling")
        hl.addWidget(self.mode_badge)

        root.addWidget(header)

        # -------------------------------------------------------------------
        # 2. Main Text Workspace Card
        # -------------------------------------------------------------------
        editor_card = QFrame(self)
        editor_card.setObjectName("card")
        el = QVBoxLayout(editor_card)
        el.setContentsMargins(14, 14, 14, 14)
        el.setSpacing(10)

        self.text_edit = QTextEdit(editor_card)
        self.text_edit.setPlaceholderText("Paste or type text here to analyze and refine…")
        self.text_edit.setFont(QFont("Segoe UI", 12))
        self.text_edit.textChanged.connect(self._on_text_changed)
        el.addWidget(self.text_edit, stretch=1)

        # Bottom info row inside editor
        info_row = QHBoxLayout()
        self.status_label = QLabel("Ready", editor_card)
        self.status_label.setStyleSheet("color: #71717a; font-size: 11px;")
        info_row.addWidget(self.status_label)
        info_row.addStretch()

        self.counts_label = QLabel("0 words  •  0 characters", editor_card)
        self.counts_label.setStyleSheet("color: #71717a; font-size: 11px;")
        info_row.addWidget(self.counts_label)
        el.addLayout(info_row)

        root.addWidget(editor_card, stretch=1)

        # -------------------------------------------------------------------
        # 3. Writing Score Card
        # -------------------------------------------------------------------
        score_card = QFrame(self)
        score_card.setObjectName("card")
        sl = QHBoxLayout(score_card)
        sl.setContentsMargins(16, 12, 16, 12)
        sl.setSpacing(16)

        score_title = QLabel("Writing Score", score_card)
        score_title.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        sl.addWidget(score_title)

        self.score_bar = QProgressBar(score_card)
        self.score_bar.setRange(0, 100)
        self.score_bar.setValue(100)
        self.score_bar.setTextVisible(True)
        self.score_bar.setFormat("%v / 100")
        sl.addWidget(self.score_bar, stretch=1)

        self.issues_badge = QLabel("0 issues", score_card)
        self.issues_badge.setStyleSheet("color: #71717a; font-size: 11px; font-weight: 500;")
        sl.addWidget(self.issues_badge)

        root.addWidget(score_card)

        # -------------------------------------------------------------------
        # 4. Action Buttons Row
        # -------------------------------------------------------------------
        actions = QHBoxLayout()
        actions.setSpacing(10)

        self.rewrite_all_btn = QPushButton("Rewrite All (LLM)", self)
        self.rewrite_all_btn.setObjectName("primary")
        self.rewrite_all_btn.clicked.connect(self._on_rewrite_all_clicked)
        actions.addWidget(self.rewrite_all_btn)

        self.check_btn = QPushButton("Check Offline", self)
        self.check_btn.clicked.connect(self._run_offline_analysis)
        actions.addWidget(self.check_btn)

        self.copy_btn = QPushButton("Copy Refined", self)
        self.copy_btn.clicked.connect(self._on_copy_clicked)
        actions.addWidget(self.copy_btn)

        self.clear_btn = QPushButton("Clear", self)
        self.clear_btn.setObjectName("subtle")
        self.clear_btn.clicked.connect(self.text_edit.clear)
        actions.addWidget(self.clear_btn)

        actions.addStretch()
        root.addLayout(actions)

    def set_content(self, text: str) -> None:
        """Load text into the editor."""
        self.text_edit.setPlainText(text)
        self.text_edit.moveCursor(self.text_edit.textCursor().MoveOperation.End)

    def _on_text_changed(self) -> None:
        text = self.text_edit.toPlainText()
        words = len(re.findall(r"\b\w+\b", text))
        chars = len(text)
        self.counts_label.setText(f"{words} words  •  {chars} characters")

        # Debounce analysis by 400ms while user types
        self._analyze_timer.start(400)

    def _run_offline_analysis(self) -> None:
        text = self.text_edit.toPlainText()
        if not text.strip():
            self.score_bar.setValue(100)
            self.issues_badge.setText("0 issues")
            self.status_label.setText("Ready")
            return

        lints = self.offline.lint(text)
        issues_count = len(lints)
        score = calculate_writing_score(text, issues_count)

        self.score_bar.setValue(score)
        self.issues_badge.setText(f"{issues_count} issue{'s' if issues_count != 1 else ''} found")
        self.status_label.setText(f"Checked locally via Harper ({self.offline.dialect_name})")

    def _on_rewrite_all_clicked(self) -> None:
        text = self.text_edit.toPlainText().strip()
        if not text:
            return

        self.status_label.setText("Consulting LLM for rewrite…")
        self.rewrite_all_btn.setEnabled(False)
        QApplication.processEvents()

        tone = self.tone.currentText()
        rewritten = self.online.rewrite(text, tone_or_instruction=tone)

        if rewritten and rewritten.strip():
            self.set_content(rewritten)
            self.status_label.setText(f"Rewritten in {tone} tone.")
            self._run_offline_analysis()
        else:
            self.status_label.setText("Online rewrite unavailable; using offline suggestions.")
            self._run_offline_analysis()

        self.rewrite_all_btn.setEnabled(True)

    def _on_copy_clicked(self) -> None:
        text = self.text_edit.toPlainText()
        if text:
            pyperclip.copy(text)
            self.status_label.setText("Copied to clipboard!")
