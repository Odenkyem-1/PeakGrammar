"""Main Refinement Studio editor workspace for PeakGrammar.

Implements the modern dark periwinkle & obsidian slate layout matching
the Refinement Studio design specification:
- Header with Tone Pills and Engine Mode Switcher.
- Split workspace: Left Editor Card with live in-text wavy underlines,
  Right Sidebar with circular Writing Score gauge, metric breakdown bars,
  and interactive individual suggestion cards with Accept / Dismiss.
"""

import html
import re
from typing import Any, Optional
import pyperclip

from PySide6.QtCore import Qt, QTimer, QRectF, Signal
from PySide6.QtGui import (
    QFont,
    QColor,
    QPainter,
    QPen,
    QSyntaxHighlighter,
    QTextCharFormat,
    QCursor,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLabel,
    QPushButton,
    QFrame,
    QProgressBar,
    QScrollArea,
    QApplication,
)

from core.engine_offline import OfflineEngine
from core.engine_online import OnlineEngine


# ---------------------------------------------------------------------------
# 1. Custom Circular Score Gauge Widget
# ---------------------------------------------------------------------------
class CircularScoreWidget(QWidget):
    """Circular ring progress gauge displaying Writing Score / 100."""

    def __init__(self, score: int = 100, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.score = max(0, min(100, score))
        self.setFixedSize(76, 76)

    def set_score(self, score: int) -> None:
        self.score = max(0, min(100, score))
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(6, 6, 64, 64)

        # Dark background ring track
        pen_bg = QPen(QColor("#212330"), 5)
        p.setPen(pen_bg)
        p.drawEllipse(rect)

        # Active progress arc (Periwinkle Blue)
        pen_arc = QPen(QColor("#8b9cfc"), 5)
        pen_arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_arc)

        # Angle spans clockwise from 90 degrees (12 o'clock)
        span_angle = int(-(self.score / 100.0) * 360 * 16)
        p.drawArc(rect, 90 * 16, span_angle)

        # Primary Score Number
        p.setPen(QColor("#ffffff"))
        f_score = QFont("Segoe UI", 16, QFont.Weight.Bold)
        p.setFont(f_score)
        p.drawText(QRectF(0, 16, 76, 24), Qt.AlignmentFlag.AlignCenter, str(self.score))

        # Secondary "/ 100" Label
        p.setPen(QColor("#75798c"))
        f_sub = QFont("Segoe UI", 9)
        p.setFont(f_sub)
        p.drawText(QRectF(0, 39, 76, 16), Qt.AlignmentFlag.AlignCenter, "/ 100")
        p.end()


# ---------------------------------------------------------------------------
# 2. In-Editor Syntax Highlighter (Wavy Underlines on Issues)
# ---------------------------------------------------------------------------
class LintHighlighter(QSyntaxHighlighter):
    """Draws wavy underlines and soft tinted backgrounds on flagged issue spans."""

    def __init__(self, document):
        super().__init__(document)
        self.lints: list[dict[str, Any]] = []

    def set_lints(self, lints: list[dict[str, Any]]) -> None:
        self.lints = lints
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        block_start = self.currentBlock().position()
        block_len = len(text)
        block_end = block_start + block_len

        for lint in self.lints:
            span = lint.get("span", (0, 0))
            l_start, l_end = span
            if l_end > block_start and l_start < block_end:
                s = max(0, l_start - block_start)
                length = min(block_len - s, l_end - (block_start + s))
                if length <= 0:
                    continue

                msg = lint.get("message", "").lower()
                is_clarity = "clarity" in msg or "style" in msg or "wordy" in msg

                fmt = QTextCharFormat()
                fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)

                if is_clarity:
                    fmt.setUnderlineColor(QColor("#f59e0b"))  # Amber
                    fmt.setBackground(QColor(245, 158, 11, 40))
                else:
                    fmt.setUnderlineColor(QColor("#f87171"))  # Coral Red
                    fmt.setBackground(QColor(248, 113, 113, 40))

                self.setFormat(s, length, fmt)


# ---------------------------------------------------------------------------
# 3. Individual Suggestion Item Card
# ---------------------------------------------------------------------------
class SuggestionCard(QFrame):
    """Individual suggestion card widget in the right sidebar list."""

    accepted = Signal(dict)
    dismissed = Signal(dict)

    def __init__(self, lint: dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.lint = lint
        self.setObjectName("cardSecondary")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Header: Dot + Category + Rule description
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        msg = lint.get("message", "Grammar issue")
        is_clarity = "clarity" in msg or "style" in msg or "wordy" in msg
        dot_color = "#f59e0b" if is_clarity else "#f87171"
        category_name = "Clarity" if is_clarity else "Grammar"

        dot = QLabel("●", self)
        dot.setStyleSheet(f"color: {dot_color}; font-size: 10px;")
        top_row.addWidget(dot)

        rule_label = QLabel(f"{category_name} · {msg}", self)
        rule_label.setWordWrap(True)
        rule_label.setStyleSheet("color: #8e92a4; font-size: 11px; font-weight: 500;")
        top_row.addWidget(rule_label, stretch=1)
        layout.addLayout(top_row)

        # Diff row: problem -> replacement
        problem = lint.get("problem_text", "")
        suggestions = lint.get("suggestions", [])
        replacement = suggestions[0] if suggestions else "remove"

        diff_row = QLabel(self)
        diff_row.setWordWrap(True)
        diff_row.setTextFormat(Qt.TextFormat.RichText)
        diff_html = (
            f'<span style="color: #c5c8d6; font-size: 13px;">{html.escape(problem)}</span> '
            f'<span style="color: #8b9cfc; font-size: 13px; font-weight: bold;">→</span> '
            f'<b style="color: #ffffff; font-size: 13px;">{html.escape(replacement)}</b>'
        )
        diff_row.setText(diff_html)
        layout.addWidget(diff_row)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.accept_btn = QPushButton("Accept", self)
        self.accept_btn.setObjectName("acceptBtn")
        self.accept_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.accept_btn.setStyleSheet(
            "background-color: #9db0fc; color: #0d0f17; font-weight: 700; "
            "border: none; border-radius: 14px; padding: 6px 18px; font-size: 12px;"
        )
        self.accept_btn.clicked.connect(lambda: self.accepted.emit(self.lint))
        btn_row.addWidget(self.accept_btn)

        self.dismiss_btn = QPushButton("Dismiss", self)
        self.dismiss_btn.setObjectName("dismissBtn")
        self.dismiss_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.dismiss_btn.setStyleSheet(
            "background-color: #232532; color: #c2c5d4; font-weight: 500; "
            "border: 1px solid #2e3040; border-radius: 14px; padding: 6px 18px; font-size: 12px;"
        )
        self.dismiss_btn.clicked.connect(lambda: self.dismissed.emit(self.lint))
        btn_row.addWidget(self.dismiss_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)


# ---------------------------------------------------------------------------
# 4. Main Refinement Studio Window
# ---------------------------------------------------------------------------
class RefinementEditor(QWidget):
    """Full-featured Refinement Studio editor."""

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
        self.setObjectName("refinementStudio")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.resize(1080, 760)
        self.setMinimumSize(880, 600)

        # Internal state
        self._current_lints: list[dict[str, Any]] = []
        self._active_tone = "Academic"
        self._active_engine = "offline"  # "offline" | "llm"

        # Debounced analysis timer
        self._analyze_timer = QTimer(self)
        self._analyze_timer.setSingleShot(True)
        self._analyze_timer.timeout.connect(self._run_offline_analysis)

        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(14)

        # -------------------------------------------------------------------
        # TOP BAR
        # -------------------------------------------------------------------
        top_bar_widget = QWidget(self)
        top_bar = QHBoxLayout(top_bar_widget)
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(12)

        # App Icon Badge ("P")
        icon_badge = QLabel("P", top_bar_widget)
        icon_badge.setFixedSize(32, 32)
        icon_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_badge.setStyleSheet(
            "background-color: #9db0fc; color: #0d0f17; font-weight: bold; "
            "font-size: 16px; border-radius: 8px;"
        )
        top_bar.addWidget(icon_badge)

        # Title column
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(1)
        app_title = QLabel("Refinement Studio", top_bar_widget)
        app_title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        app_title.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 15px;")
        title_col.addWidget(app_title)

        app_sub = QLabel("PeakGrammar", top_bar_widget)
        app_sub.setStyleSheet("color: #85889a; font-size: 11px;")
        title_col.addWidget(app_sub)
        top_bar.addLayout(title_col)

        top_bar.addStretch()

        # Tone Selector Pills (Segmented Capsule Control)
        tone_lbl = QLabel("Tone", top_bar_widget)
        tone_lbl.setStyleSheet("color: #75798c; font-size: 12px; margin-right: 2px;")
        top_bar.addWidget(tone_lbl)

        tone_frame = QFrame(top_bar_widget)
        tone_frame.setStyleSheet(
            "background-color: #16171f; border: 1px solid #242632; border-radius: 16px; padding: 2px;"
        )
        tf_layout = QHBoxLayout(tone_frame)
        tf_layout.setContentsMargins(2, 2, 2, 2)
        tf_layout.setSpacing(2)

        self.tone_buttons: dict[str, QPushButton] = {}
        for tone_name in ("Academic", "Professional", "Casual"):
            btn = QPushButton(tone_name, tone_frame)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda checked=False, t=tone_name: self._set_tone(t))
            self.tone_buttons[tone_name] = btn
            tf_layout.addWidget(btn)

        self._set_tone(self._active_tone)
        top_bar.addWidget(tone_frame)

        top_bar.addSpacing(8)

        # Engine Toggle Pill (Offline · Harper vs LLM)
        engine_frame = QFrame(top_bar_widget)
        engine_frame.setStyleSheet(
            "background-color: #16171f; border: 1px solid #242632; border-radius: 16px; padding: 2px;"
        )
        ef_layout = QHBoxLayout(engine_frame)
        ef_layout.setContentsMargins(2, 2, 2, 2)
        ef_layout.setSpacing(2)

        self.btn_offline_mode = QPushButton("Offline · Harper", engine_frame)
        self.btn_offline_mode.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_offline_mode.setStyleSheet(
            "background-color: #272937; color: #ffffff; font-weight: 600; "
            "border: none; border-radius: 13px; padding: 4px 12px;"
        )
        self.btn_offline_mode.clicked.connect(lambda: self._set_engine_mode("offline"))
        ef_layout.addWidget(self.btn_offline_mode)

        self.btn_llm_mode = QPushButton("LLM", engine_frame)
        self.btn_llm_mode.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_llm_mode.setStyleSheet(
            "background-color: transparent; color: #75798c; font-weight: 500; "
            "border: none; border-radius: 13px; padding: 4px 12px;"
        )
        self.btn_llm_mode.clicked.connect(lambda: self._set_engine_mode("llm"))
        ef_layout.addWidget(self.btn_llm_mode)

        top_bar.addWidget(engine_frame)
        root.addWidget(top_bar_widget)

        # -------------------------------------------------------------------
        # MAIN BODY (2-COLUMN SPLIT)
        # -------------------------------------------------------------------
        body_layout = QHBoxLayout()
        body_layout.setSpacing(16)

        # === LEFT COLUMN: EDITOR CARD ===
        editor_card = QFrame(self)
        editor_card.setObjectName("card")
        el = QVBoxLayout(editor_card)
        el.setContentsMargins(18, 16, 18, 14)
        el.setSpacing(10)

        # Editor Header Row: "Your text" + Issue Counts
        eh_row = QHBoxLayout()
        lbl_your_text = QLabel("Your text", editor_card)
        lbl_your_text.setStyleSheet("color: #75798c; font-size: 12px; font-weight: 500;")
        eh_row.addWidget(lbl_your_text)
        eh_row.addStretch()

        self.dot_grammar = QLabel("●", editor_card)
        self.dot_grammar.setStyleSheet("color: #f87171; font-size: 10px;")
        eh_row.addWidget(self.dot_grammar)

        self.lbl_grammar_count = QLabel("Grammar 0", editor_card)
        self.lbl_grammar_count.setStyleSheet("color: #8e92a4; font-size: 12px; margin-right: 8px;")
        eh_row.addWidget(self.lbl_grammar_count)

        self.dot_clarity = QLabel("●", editor_card)
        self.dot_clarity.setStyleSheet("color: #f59e0b; font-size: 10px;")
        eh_row.addWidget(self.dot_clarity)

        self.lbl_clarity_count = QLabel("Clarity 0", editor_card)
        self.lbl_clarity_count.setStyleSheet("color: #8e92a4; font-size: 12px;")
        eh_row.addWidget(self.lbl_clarity_count)

        el.addLayout(eh_row)

        # Text Editor
        self.text_edit = QTextEdit(editor_card)
        self.text_edit.setPlaceholderText("Paste or type text here to analyze and refine…")
        self.text_edit.setFont(QFont("Segoe UI", 12))
        self.text_edit.textChanged.connect(self._on_text_changed)
        el.addWidget(self.text_edit, stretch=1)

        # Attach Syntax Highlighter
        self.highlighter = LintHighlighter(self.text_edit.document())

        # Editor Footer Row: "● Checked offline" + Counts
        ef_row = QHBoxLayout()
        self.dot_status = QLabel("●", editor_card)
        self.dot_status.setStyleSheet("color: #818cf8; font-size: 10px;")
        ef_row.addWidget(self.dot_status)

        self.lbl_checked_status = QLabel("Checked offline · 0 issues", editor_card)
        self.lbl_checked_status.setStyleSheet("color: #75798c; font-size: 12px;")
        ef_row.addWidget(self.lbl_checked_status)
        ef_row.addStretch()

        self.counts_label = QLabel("0 words · 0 characters", editor_card)
        self.counts_label.setStyleSheet("color: #75798c; font-size: 12px;")
        ef_row.addWidget(self.counts_label)

        el.addLayout(ef_row)
        body_layout.addWidget(editor_card, stretch=62)

        # === RIGHT COLUMN: SIDEBAR ===
        sidebar_col = QVBoxLayout()
        sidebar_col.setSpacing(14)

        # 1. Writing Score Card
        score_card = QFrame(self)
        score_card.setObjectName("card")
        sc_layout = QVBoxLayout(score_card)
        sc_layout.setContentsMargins(16, 16, 16, 16)
        sc_layout.setSpacing(14)

        # Circular Gauge + Header
        sg_row = QHBoxLayout()
        sg_row.setSpacing(14)

        self.score_gauge = CircularScoreWidget(score=100, parent=score_card)
        sg_row.addWidget(self.score_gauge)

        score_text_col = QVBoxLayout()
        score_text_col.setSpacing(3)
        st_title = QLabel("Writing score", score_card)
        st_title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        st_title.setStyleSheet("color: #f1f2f6;")
        score_text_col.addWidget(st_title)

        self.score_subtitle = QLabel("No issues found", score_card)
        self.score_subtitle.setStyleSheet("color: #8e92a4; font-size: 12px;")
        score_text_col.addWidget(self.score_subtitle)

        score_text_col.addStretch()
        sg_row.addLayout(score_text_col)
        sg_row.addStretch()
        sc_layout.addLayout(sg_row)

        # Metric Bars (Correctness, Clarity, Tone)
        self.bar_correctness, self.val_correctness = self._create_metric_row(sc_layout, "Correctness", 100)
        self.bar_clarity, self.val_clarity = self._create_metric_row(sc_layout, "Clarity", 100)
        self.bar_tone, self.val_tone = self._create_metric_row(sc_layout, "Tone", 100)

        sidebar_col.addWidget(score_card)

        # 2. Suggestions List Card
        sug_card = QFrame(self)
        sug_card.setObjectName("card")
        sug_layout = QVBoxLayout(sug_card)
        sug_layout.setContentsMargins(16, 14, 16, 14)
        sug_layout.setSpacing(10)

        # Suggestions Header + Accept All Link
        sh_row = QHBoxLayout()
        sh_title = QLabel("Suggestions", sug_card)
        sh_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        sh_title.setStyleSheet("color: #f1f2f6;")
        sh_row.addWidget(sh_title)
        sh_row.addStretch()

        self.accept_all_btn = QPushButton("Accept all", sug_card)
        self.accept_all_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.accept_all_btn.setStyleSheet(
            "background: transparent; border: none; color: #8b9cfc; "
            "font-size: 12px; font-weight: 600; padding: 0;"
        )
        self.accept_all_btn.clicked.connect(self._accept_all_suggestions)
        sh_row.addWidget(self.accept_all_btn)
        sug_layout.addLayout(sh_row)

        # Scrollable Suggestions List
        self.scroll_area = QScrollArea(sug_card)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")

        self.sug_container = QWidget()
        self.sug_container.setStyleSheet("background: transparent;")
        self.sug_cards_layout = QVBoxLayout(self.sug_container)
        self.sug_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.sug_cards_layout.setSpacing(10)
        self.sug_cards_layout.addStretch()

        self.scroll_area.setWidget(self.sug_container)
        sug_layout.addWidget(self.scroll_area, stretch=1)

        sidebar_col.addWidget(sug_card, stretch=1)
        body_layout.addLayout(sidebar_col, stretch=38)

        root.addLayout(body_layout, stretch=1)

        # -------------------------------------------------------------------
        # BOTTOM ACTION BAR
        # -------------------------------------------------------------------
        actions = QHBoxLayout()
        actions.setSpacing(10)

        self.clear_btn = QPushButton("Clear", self)
        self.clear_btn.setObjectName("subtle")
        self.clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.clear_btn.clicked.connect(self.text_edit.clear)
        actions.addWidget(self.clear_btn)

        actions.addStretch()

        self.check_btn = QPushButton("Check offline", self)
        self.check_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.check_btn.clicked.connect(self._run_offline_analysis)
        actions.addWidget(self.check_btn)

        self.copy_btn = QPushButton("Copy refined", self)
        self.copy_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.copy_btn.clicked.connect(self._on_copy_clicked)
        actions.addWidget(self.copy_btn)

        self.rewrite_all_btn = QPushButton("Rewrite all with LLM", self)
        self.rewrite_all_btn.setObjectName("primary")
        self.rewrite_all_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.rewrite_all_btn.clicked.connect(self._on_rewrite_all_clicked)
        actions.addWidget(self.rewrite_all_btn)

        root.addLayout(actions)

    def _create_metric_row(
        self, layout: QVBoxLayout, label_text: str, default_val: int
    ) -> tuple[QProgressBar, QLabel]:
        row = QVBoxLayout()
        row.setSpacing(4)

        header = QHBoxLayout()
        lbl = QLabel(label_text, self)
        lbl.setStyleSheet("color: #8e92a4; font-size: 12px;")
        header.addWidget(lbl)
        header.addStretch()

        val_lbl = QLabel(str(default_val), self)
        val_lbl.setStyleSheet("color: #f1f2f6; font-size: 12px; font-weight: 600;")
        header.addWidget(val_lbl)
        row.addLayout(header)

        bar = QProgressBar(self)
        bar.setRange(0, 100)
        bar.setValue(default_val)
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        row.addWidget(bar)

        layout.addLayout(row)
        return bar, val_lbl

    # -----------------------------------------------------------------------
    # Tone & Mode Selection
    # -----------------------------------------------------------------------
    def _set_tone(self, tone: str) -> None:
        self._active_tone = tone
        for name, btn in self.tone_buttons.items():
            if name == tone:
                btn.setStyleSheet(
                    "background-color: #1b223d; color: #9db0fc; font-weight: 600; "
                    "border: 1px solid #3c4b8e; border-radius: 13px; padding: 4px 14px; font-size: 12px;"
                )
            else:
                btn.setStyleSheet(
                    "background-color: transparent; color: #75798c; font-weight: 500; "
                    "border: none; border-radius: 13px; padding: 4px 14px; font-size: 12px;"
                )

    def _set_engine_mode(self, mode: str) -> None:
        self._active_engine = mode
        if mode == "offline":
            self.btn_offline_mode.setStyleSheet(
                "background-color: #272937; color: #ffffff; font-weight: 600; "
                "border: none; border-radius: 13px; padding: 4px 12px;"
            )
            self.btn_llm_mode.setStyleSheet(
                "background-color: transparent; color: #75798c; font-weight: 500; "
                "border: none; border-radius: 13px; padding: 4px 12px;"
            )
        else:
            self.btn_offline_mode.setStyleSheet(
                "background-color: transparent; color: #75798c; font-weight: 500; "
                "border: none; border-radius: 13px; padding: 4px 12px;"
            )
            self.btn_llm_mode.setStyleSheet(
                "background-color: #272937; color: #ffffff; font-weight: 600; "
                "border: none; border-radius: 13px; padding: 4px 12px;"
            )

    # -----------------------------------------------------------------------
    # Editor Analysis & Suggestions Logic
    # -----------------------------------------------------------------------
    def set_content(self, text: str) -> None:
        """Load text into the editor."""
        self.text_edit.setPlainText(text)
        self.text_edit.moveCursor(self.text_edit.textCursor().MoveOperation.End)

    def _on_text_changed(self) -> None:
        text = self.text_edit.toPlainText()
        words = len(re.findall(r"\b\w+\b", text))
        chars = len(text)
        self.counts_label.setText(f"{words} words · {chars} characters")

        # Debounce analysis by 350ms while user types
        self._analyze_timer.start(350)

    def _run_offline_analysis(self) -> None:
        text = self.text_edit.toPlainText()
        if not text.strip():
            self._current_lints = []
            self.highlighter.set_lints([])
            self._update_metrics(100, 100, 100, 100, 0, 0)
            self._render_suggestion_cards([])
            self.lbl_checked_status.setText("Checked offline · 0 issues")
            return

        lints = self.offline.lint(text)
        self._current_lints = lints
        self.highlighter.set_lints(lints)

        # Categorize
        grammar_count = 0
        clarity_count = 0
        for l in lints:
            m = l.get("message", "").lower()
            if "clarity" in m or "style" in m or "wordy" in m:
                clarity_count += 1
            else:
                grammar_count += 1

        self.lbl_grammar_count.setText(f"Grammar {grammar_count}")
        self.lbl_clarity_count.setText(f"Clarity {clarity_count}")
        total_issues = len(lints)
        self.lbl_checked_status.setText(f"Checked offline · {total_issues} issues")

        # Calculate metrics
        correctness = max(40, min(100, 100 - (grammar_count * 8)))
        clarity = max(45, min(100, 100 - (clarity_count * 10)))
        tone = 94 if total_issues <= 1 else max(60, 94 - total_issues * 3)
        overall_score = max(20, min(100, int(0.45 * correctness + 0.35 * clarity + 0.20 * tone)))

        self._update_metrics(overall_score, correctness, clarity, tone, grammar_count, clarity_count)
        self._render_suggestion_cards(lints)

    def _update_metrics(
        self, score: int, correctness: int, clarity: int, tone: int, grammar_c: int, clarity_c: int
    ) -> None:
        self.score_gauge.set_score(score)

        total_issues = grammar_c + clarity_c
        if total_issues == 0:
            self.score_subtitle.setText("No issues found")
        else:
            self.score_subtitle.setText(f"Fix {total_issues} issue{'s' if total_issues != 1 else ''} to improve it")

        self.bar_correctness.setValue(correctness)
        self.val_correctness.setText(str(correctness))

        self.bar_clarity.setValue(clarity)
        self.val_clarity.setText(str(clarity))

        self.bar_tone.setValue(tone)
        self.val_tone.setText(str(tone))

    def _render_suggestion_cards(self, lints: list[dict[str, Any]]) -> None:
        # Clear existing cards
        while self.sug_cards_layout.count() > 1:
            item = self.sug_cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for lint in lints:
            card = SuggestionCard(lint, self.sug_container)
            card.accepted.connect(self._accept_single_suggestion)
            card.dismissed.connect(self._dismiss_single_suggestion)
            self.sug_cards_layout.insertWidget(self.sug_cards_layout.count() - 1, card)

    def _accept_single_suggestion(self, lint: dict[str, Any]) -> None:
        text = self.text_edit.toPlainText()
        suggestions = lint.get("suggestions", [])
        if not suggestions:
            return
        replacement = suggestions[0]
        new_text = self.offline.apply_suggestion(text, lint, replacement)
        self.set_content(new_text)
        self._run_offline_analysis()

    def _dismiss_single_suggestion(self, lint: dict[str, Any]) -> None:
        if lint in self._current_lints:
            self._current_lints.remove(lint)
            self.highlighter.set_lints(self._current_lints)
            self._render_suggestion_cards(self._current_lints)

    def _accept_all_suggestions(self) -> None:
        if not self._current_lints:
            return

        text = self.text_edit.toPlainText()
        # Sort lints in reverse order of span start so earlier spans remain valid
        sorted_lints = sorted(self._current_lints, key=lambda l: l.get("span", (0, 0))[0], reverse=True)

        for lint in sorted_lints:
            suggestions = lint.get("suggestions", [])
            if suggestions:
                text = self.offline.apply_suggestion(text, lint, suggestions[0])

        self.set_content(text)
        self._run_offline_analysis()

    def _on_rewrite_all_clicked(self) -> None:
        text = self.text_edit.toPlainText().strip()
        if not text:
            return

        self.lbl_checked_status.setText("Consulting LLM for rewrite…")
        self.rewrite_all_btn.setEnabled(False)
        QApplication.processEvents()

        rewritten = self.online.rewrite(text, tone_or_instruction=self._active_tone)

        if rewritten and rewritten.strip():
            self.set_content(rewritten)
            self.lbl_checked_status.setText(f"Rewritten in {self._active_tone} tone via LLM")
            self._run_offline_analysis()
        else:
            self.lbl_checked_status.setText("Online rewrite unavailable; using offline suggestions.")
            self._run_offline_analysis()

        self.rewrite_all_btn.setEnabled(True)

    def _on_copy_clicked(self) -> None:
        text = self.text_edit.toPlainText()
        if text:
            pyperclip.copy(text)
            self.lbl_checked_status.setText("Copied refined text to clipboard!")


# Backward compatibility helper
def calculate_writing_score(text: str, issues_count: int) -> int:
    clean_text = text.strip()
    if not clean_text:
        return 100
    words = re.findall(r"\b\w+\b", clean_text)
    if not words:
        return 100
    penalty = issues_count * 6
    return max(20, min(100, 100 - penalty))
