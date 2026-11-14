"""Floating suggestion overlay card for PeakGrammar.

A lightweight, frameless, always-on-top card that renders near the active
caret position without stealing application focus.
"""

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
        outer_layout.setContentsMargins(12, 12, 12, 12)

        # Inner card container
        self.card = QWidget(self)
        self.card.setObjectName("suggestionCard")

        # Soft monochrome shadow effect
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 45))
        shadow.setOffset(0, 4)
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)

        # Top row: Category Badge & Dismiss
        top_row = QHBoxLayout()
        self.badge = QLabel("Grammar", self.card)
        self.badge.setObjectName("badgeGrammar")
        top_row.addWidget(self.badge)
        top_row.addStretch()

        self.close_btn = QPushButton("×", self.card)
        self.close_btn.setObjectName("subtle")
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.clicked.connect(self.hide)
        top_row.addWidget(self.close_btn)
        card_layout.addLayout(top_row)

        # Message / Problem preview
        self.msg_label = QLabel(self.card)
        self.msg_label.setWordWrap(True)
        self.msg_label.setFont(QFont("Segoe UI", 10))
        self.msg_label.setStyleSheet("color: #71717a;")
        card_layout.addWidget(self.msg_label)

        # Main suggestion text
        self.suggestion_label = QLabel(self.card)
        self.suggestion_label.setWordWrap(True)
        self.suggestion_label.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        self.suggestion_label.setStyleSheet("color: #18181b;")
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
    ) -> None:
        """Populate and display the suggestion card near the active caret anchor."""
        self._current_apply_cb = on_apply
        self._current_ignore_cb = on_ignore
        self._current_dict_cb = on_dict
        self._current_rewrite_cb = on_rewrite

        problem = lint.get("problem_text", "")
        message = lint.get("message", "Suggested replacement")
        suggestions = lint.get("suggestions", [])
        is_llm = lint.get("type") == "rewrite"

        # Update Badge
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

        if suggestions:
            first_sug = suggestions[0]
            self.suggestion_label.setText(f"→ {first_sug}")
            self.apply_btn.setText(f"Replace with \"{first_sug}\"")
            self.apply_btn.show()
        else:
            self.suggestion_label.setText(problem)
            self.apply_btn.hide()

        # Show/hide dictionary button (relevant for single words)
        is_single_word = len(problem.split()) == 1 and not is_llm
        self.dict_btn.setVisible(is_single_word)
        self.rewrite_btn.setVisible(on_rewrite is not None)

        self.adjustSize()

        # Calculate bounded screen placement
        if anchor_pos is not None:
            screen = QApplication.primaryScreen()
            if screen:
                screen_geom = screen.availableGeometry()
                card_w = self.width()
                card_h = self.height()

                target_x = max(screen_geom.left() + 10, min(anchor_pos.x(), screen_geom.right() - card_w - 10))
                target_y = anchor_pos.y()

                # If it overflows screen bottom, display above the control
                if target_y + card_h > screen_geom.bottom() - 10:
                    target_y = max(screen_geom.top() + 10, target_y - card_h - 40)

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
