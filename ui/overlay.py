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


def calculate_overlay_geometry(
    screen_geom: QRect,
    card_size: tuple[int, int],
    anchor_pos: Optional[QPoint] = None,
    bounding_rect: Optional[tuple[int, int, int, int]] = None,
) -> tuple[int, int]:
    """Calculate an intelligent, non-disruptive screen position for the floating overlay.

    Ensures the card never obstructs the active caret sightline, never clips
    outside visible multi-monitor screen boundaries, and intelligently docks
    adjacent to narrow sidebars (like chat panels) without overlapping text inputs.
    """
    card_w, card_h = card_size
    MARGIN = 12

    ctrl_left, ctrl_top, ctrl_right, ctrl_bottom = bounding_rect if bounding_rect else (0, 0, 0, 0)
    has_valid_ctrl = (ctrl_right > ctrl_left and ctrl_bottom > ctrl_top)
    ctrl_width = ctrl_right - ctrl_left if has_valid_ctrl else 0
    ctrl_height = ctrl_bottom - ctrl_top if has_valid_ctrl else 0

    # Distinguish between an atomic input field and a whole application window/pane
    is_atomic_input = (
        has_valid_ctrl
        and ctrl_height <= 280
        and ctrl_width < int(screen_geom.width() * 0.85)
    )

    ref_point = anchor_pos or (
        QPoint(ctrl_left + 20, ctrl_bottom) if has_valid_ctrl else QPoint(screen_geom.left() + 200, screen_geom.top() + 200)
    )

    # Strategy 1: Atomic Input Field
    if is_atomic_input:
        space_below = screen_geom.bottom() - ctrl_bottom
        space_above = ctrl_top - screen_geom.top()

        # If input is located in a right-hand sidebar (e.g. Chat or Assistant side pane)
        if ctrl_left > screen_geom.left() + screen_geom.width() * 0.55:
            # Check if there is ample clearance to dock to the LEFT of the sidebar
            if ctrl_left - screen_geom.left() >= card_w + MARGIN:
                target_x = ctrl_left - card_w - MARGIN
                target_y = min(
                    screen_geom.bottom() - card_h - MARGIN,
                    max(screen_geom.top() + MARGIN, ctrl_top)
                )
                return target_x, target_y

        # Standard vertical placement for input fields
        if space_below >= card_h + MARGIN + 8:
            target_y = ctrl_bottom + 8
        elif space_above >= card_h + MARGIN + 8:
            target_y = ctrl_top - card_h - 8
        elif space_below >= space_above:
            target_y = ctrl_bottom + 4
        else:
            target_y = ctrl_top - card_h - 4

        target_x = max(
            screen_geom.left() + MARGIN,
            min(ctrl_left, screen_geom.right() - card_w - MARGIN),
        )

    # Strategy 2: Large Pane / Editor / Free Caret Anchor
    else:
        ax, ay = ref_point.x(), ref_point.y()

        # If caret is on the right third of the screen, place card to the left of caret
        if ax > screen_geom.left() + screen_geom.width() * 0.65 and (ax - screen_geom.left()) >= card_w + MARGIN:
            target_x = ax - card_w - 20
        else:
            target_x = max(screen_geom.left() + MARGIN, min(ax, screen_geom.right() - card_w - MARGIN))

        # Vertical clearance relative to active line
        space_below = screen_geom.bottom() - ay
        space_above = ay - screen_geom.top()

        if space_below >= card_h + MARGIN + 20:
            target_y = ay + 20  # Comfortably below active line
        elif space_above >= card_h + MARGIN + 20:
            target_y = ay - card_h - 20  # Comfortably above active line
        elif space_above >= space_below:
            target_y = max(screen_geom.top() + MARGIN, ay - card_h - 10)
        else:
            target_y = min(screen_geom.bottom() - card_h - MARGIN, ay + 10)

    # Final anti-overlap sightline guarantee: ensure card doesn't cover ref_point caret
    caret_box = (ref_point.x() - 30, ref_point.y() - 15, ref_point.x() + 30, ref_point.y() + 15)
    card_box = (target_x, target_y, target_x + card_w, target_y + card_h)

    overlaps_caret = not (
        card_box[2] < caret_box[0]
        or card_box[0] > caret_box[2]
        or card_box[3] < caret_box[1]
        or card_box[1] > caret_box[3]
    )

    if overlaps_caret:
        # Push vertically away from caret
        if target_y >= ref_point.y():
            target_y = min(screen_geom.bottom() - card_h - MARGIN, ref_point.y() + 24)
        else:
            target_y = max(screen_geom.top() + MARGIN, ref_point.y() - card_h - 24)

    # Strict multi-monitor boundary clamp
    target_x = max(screen_geom.left() + MARGIN, min(target_x, screen_geom.right() - card_w - MARGIN))
    target_y = max(screen_geom.top() + MARGIN, min(target_y, screen_geom.bottom() - card_h - MARGIN))

    return target_x, target_y


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

        # 4. Anti-Overlap Geometry Calculation and Multi-Monitor Screen Clamping
        self.card.adjustSize()
        self.adjustSize()

        hint = self.sizeHint()
        card_w = max(hint.width(), self.width(), 360)
        card_h = max(hint.height(), self.height(), 140)
        self.resize(card_w, card_h)

        ref_point = anchor_pos or QPoint(200, 200)
        screen = QApplication.screenAt(ref_point) or QApplication.primaryScreen()

        if screen:
            screen_geom = screen.availableGeometry()  # Excludes taskbar
            target_x, target_y = calculate_overlay_geometry(
                screen_geom=screen_geom,
                card_size=(card_w, card_h),
                anchor_pos=anchor_pos,
                bounding_rect=bounding_rect,
            )
            self.move(target_x, target_y)

        self.show()

    def apply_current_suggestion(self) -> None:
        """Trigger apply callback and close overlay."""
        self._on_apply_clicked()

    def dismiss_suggestion(self) -> None:
        """Trigger dismiss callback and close overlay."""
        self._on_ignore_clicked()

    def keyPressEvent(self, event) -> None:
        """Handle non-disruptive keyboard shortcuts."""
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.hide()
            if self._current_ignore_cb:
                self._current_ignore_cb()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
            self.hide()
            if self._current_apply_cb:
                self._current_apply_cb()
        else:
            super().keyPressEvent(event)

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
