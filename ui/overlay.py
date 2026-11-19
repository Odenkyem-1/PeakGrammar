"""Floating suggestion overlay card for PeakGrammar.

A lightweight, frameless, always-on-top card that renders near the active
caret position without stealing application focus, with clear problem text
highlighting and multi-monitor screen boundary clamping.
"""

import html
from typing import Any, Callable, Optional
from PySide6.QtCore import Qt, QPoint, QRect
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGraphicsDropShadowEffect,
    QApplication,
    QFrame,
)


class SuggestionOverlay(QWidget):
    """Non-focus-stealing floating suggestion card anchored near the caret."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Window flags: Tool window, frameless, stays on top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        # Attributes: Show without focus activation, translucent background
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self._current_apply_cb: Optional[Callable[[], None]] = None
        self._current_ignore_cb: Optional[Callable[[], None]] = None
        self._current_dict_cb: Optional[Callable[[], None]] = None
        self._current_rewrite_cb: Optional[Callable[[], None]] = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)

        # Inner card container
        self.card = QFrame(self)
        self.card.setObjectName("suggestionCard")

        # Soft monochrome shadow effect
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 50))
        shadow.setOffset(0, 4)
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)

        # Top row: Category Badge & Dismiss
        top_row = QHBoxLayout()
        self.badge = QLabel("Grammar", self.card)
        self.badge.setObjectName("badgeGrammar")
        top_row.addWidget(self.badge)

        self.msg_label = QLabel(self.card)
        self.msg_label.setFont(QFont("Segoe UI", 10))
        self.msg_label.setStyleSheet("color: #71717a; margin-left: 6px;")
        top_row.addWidget(self.msg_label)

        top_row.addStretch()

        self.close_btn = QPushButton("×", self.card)
        self.close_btn.setObjectName("subtle")
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.clicked.connect(self.hide)
        top_row.addWidget(self.close_btn)
        card_layout.addLayout(top_row)

        # Context snippet preview with highlighted problem text
        self.snippet_container = QFrame(self.card)
        self.snippet_container.setObjectName("cardSecondary")
        snippet_layout = QVBoxLayout(self.snippet_container)
        snippet_layout.setContentsMargins(10, 8, 10, 8)
        snippet_layout.setSpacing(4)

        self.context_label = QLabel(self.snippet_container)
        self.context_label.setWordWrap(True)
        self.context_label.setFont(QFont("Segoe UI", 11))
        self.context_label.setTextFormat(Qt.TextFormat.RichText)
        snippet_layout.addWidget(self.context_label)

        card_layout.addWidget(self.snippet_container)

        # Main suggestion replacement label
        self.suggestion_label = QLabel(self.card)
        self.suggestion_label.setWordWrap(True)
        self.suggestion_label.setFont(QFont("Segoe UI", 11))
        self.suggestion_label.setTextFormat(Qt.TextFormat.RichText)
        card_layout.addWidget(self.suggestion_label)

        # Action Buttons Row
        self.btn_row = QHBoxLayout()
        self.btn_row.setSpacing(8)

        self.apply_btn = QPushButton("Replace", self.card)
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        self.btn_row.addWidget(self.apply_btn)

        self.rewrite_btn = QPushButton("Rewrite (LLM)", self.card)
        self.rewrite_btn.clicked.connect(self._on_rewrite_clicked)
        self.btn_row.addWidget(self.rewrite_btn)

        self.dict_btn = QPushButton("Add Word", self.card)
        self.dict_btn.clicked.connect(self._on_dict_clicked)
        self.btn_row.addWidget(self.dict_btn)

        self.ignore_btn = QPushButton("Ignore", self.card)
        self.ignore_btn.setObjectName("subtle")
        self.ignore_btn.clicked.connect(self._on_ignore_clicked)
        self.btn_row.addWidget(self.ignore_btn)

        card_layout.addLayout(self.btn_row)
        outer_layout.addWidget(self.card)

    def show_suggestion(
        self,
        lint: dict[str, Any],
        on_apply: Callable[[], None],
        on_ignore: Callable[[], None],
        on_dict: Callable[[], None],
        on_rewrite: Optional[Callable[[], None]] = None,
        anchor_pos: Optional[QPoint] = None,
        bounding_rect: Optional[tuple[int, int, int, int]] = None,
        original_text: Optional[str] = None,
    ) -> None:
        """Populate and display the suggestion card with issue highlighting and strict screen clamping."""
        self._current_apply_cb = on_apply
        self._current_ignore_cb = on_ignore
        self._current_dict_cb = on_dict
        self._current_rewrite_cb = on_rewrite

        problem = lint.get("problem_text", "")
        message = lint.get("message", "Suggested replacement")
        suggestions = lint.get("suggestions", [])
        is_llm = lint.get("type") == "rewrite"

        # 1. Update Category Badge
        if is_llm:
            self.badge.setText("LLM Rewrite")
            self.badge.setObjectName("badgeLLM")
        elif "spell" in message.lower():
            self.badge.setText("Spelling")
            self.badge.setObjectName("badgeSpelling")
        else:
            self.badge.setText("Grammar")
            self.badge.setObjectName("badgeGrammar")

        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)

        self.msg_label.setText(message)

        # 2. Render Context Snippet with the Problem Word Highlighted
        text_source = original_text or problem
        span = lint.get("span", (0, len(text_source)))
        start, end = span

        if text_source and 0 <= start <= end <= len(text_source) and problem:
            # Extract surrounding window for readability
            window_start = max(0, start - 25)
            window_end = min(len(text_source), end + 25)
            prefix = "…" if window_start > 0 else ""
            suffix = "…" if window_end < len(text_source) else ""

            before_str = html.escape(text_source[window_start:start])
            problem_str = html.escape(text_source[start:end] or problem)
            after_str = html.escape(text_source[end:window_end])

            # Highlighted problem tag: vibrant tinted chip with colored underline
            msg_lower = message.lower()
            is_clarity = "clarity" in msg_lower or "style" in msg_lower or "wordy" in msg_lower
            if is_clarity:
                chip_style = "background-color: #292015; color: #fbbf24; border: 1px solid #48351a;"
            else:
                chip_style = "background-color: #2b171c; color: #f87171; border: 1px solid #4a242c;"

            highlighted_html = (
                f'<span style="color: #8e92a4;">{prefix}{before_str}</span>'
                f'<span style="{chip_style} padding: 2px 7px; border-radius: 5px; font-weight: 700; text-decoration: underline;">{problem_str}</span>'
                f'<span style="color: #8e92a4;">{after_str}{suffix}</span>'
            )
            self.context_label.setText(highlighted_html)
            self.snippet_container.show()
        else:
            self.snippet_container.hide()

        # 3. Render Suggestion and Primary Replace CTA
        if suggestions:
            first_sug = suggestions[0]
            esc_sug = html.escape(first_sug)
            self.suggestion_label.setText(
                f'<span style="color: #8e92a4; font-size: 11px;">Suggestion:</span> '
                f'<b style="color: #9db0fc; font-size: 13px;">{esc_sug}</b>'
            )
            self.apply_btn.setText(f'Replace with "{first_sug}"')
            self.apply_btn.show()
        else:
            self.suggestion_label.setText(f'<b style="color: #18181b;">{html.escape(problem)}</b>')
            self.apply_btn.hide()

        # Show/hide dictionary button (relevant for single words)
        is_single_word = len(problem.split()) == 1 and not is_llm
        self.dict_btn.setVisible(is_single_word)
        self.rewrite_btn.setVisible(on_rewrite is not None)

        # 4. Accurate Geometry Measurement and Strict Screen Boundary Clamping
        self.card.adjustSize()
        self.adjustSize()

        hint = self.sizeHint()
        card_w = max(hint.width(), self.width(), 360)
        card_h = max(hint.height(), self.height(), 150)
        self.resize(card_w, card_h)

        # Anchor position resolution
        ref_point = anchor_pos or QPoint(200, 200)
        screen = QApplication.screenAt(ref_point) or QApplication.primaryScreen()

        if screen:
            screen_geom = screen.availableGeometry()  # Excludes taskbars

            # Horizontal placement: align to anchor_pos.x(), clamped within screen with 16px margins
            target_x = max(
                screen_geom.left() + 16,
                min(ref_point.x(), screen_geom.right() - card_w - 16)
            )

            # Vertical placement:
            # If bounding_rect is provided: (left, top, right, bottom)
            if bounding_rect and bounding_rect[3] > bounding_rect[1]:
                ctrl_top = bounding_rect[1]
                ctrl_bottom = bounding_rect[3]

                # Check if placing below overflows the screen bottom
                if ctrl_bottom + 8 + card_h > screen_geom.bottom() - 16:
                    # Place ABOVE the control
                    target_y = ctrl_top - card_h - 8
                else:
                    # Place BELOW the control
                    target_y = ctrl_bottom + 8
            else:
                target_y = ref_point.y()
                if target_y + card_h > screen_geom.bottom() - 16:
                    target_y = target_y - card_h - 40

            # Final safety clamp ensuring card is 100% inside screen bounds
            target_y = max(
                screen_geom.top() + 16,
                min(target_y, screen_geom.bottom() - card_h - 16)
            )

            self.move(target_x, target_y)

        self.show()

    def _on_apply_clicked(self) -> None:
        self.hide()
        if self._current_apply_cb:
            self._current_apply_cb()

    def _on_ignore_clicked(self) -> None:
        self.hide()
        if self._current_ignore_cb:
            self._current_ignore_cb()

    def _on_dict_clicked(self) -> None:
        self.hide()
        if self._current_dict_cb:
            self._current_dict_cb()

    def _on_rewrite_clicked(self) -> None:
        self.hide()
        if self._current_rewrite_cb:
            self._current_rewrite_cb()
