"""Preferences and settings dialog for PeakGrammar.

Configures Harper dialect, AI credentials, debounce timing, custom dictionary
words, replacement rules, and local-only aggregate statistics.
"""

from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QWidget,
    QLabel,
    QComboBox,
    QSpinBox,
    QLineEdit,
    QCheckBox,
    QPushButton,
    QListWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QFrame,
)

from store.database import (
    get_setting,
    set_setting,
    get_total_corrections_count,
    get_category_breakdown,
    get_weekly_stats,
)
from store.dictionary import DictionaryStore
from core.engine_online import DEFAULT_PROVIDERS, OnlineEngine


class SettingsDialog(QDialog):
    """Multi-tab preferences and diagnostics dialog."""

    def __init__(self, dictionary_store: Optional[DictionaryStore] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.dictionary_store = dictionary_store or DictionaryStore()

        self.setWindowTitle("Settings — PeakGrammar")
        self.resize(680, 520)
        self.setMinimumSize(580, 440)

        self._setup_ui()
        self.load_settings()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # Tabs
        self.tabs = QTabWidget(self)
        main_layout.addWidget(self.tabs, stretch=1)

        # Tab 1: General & Engine
        self.tab_engine = QWidget()
        self._setup_engine_tab()
        self.tabs.addTab(self.tab_engine, "General & Engine")

        # Tab 2: AI Provider
        self.tab_ai = QWidget()
        self._setup_ai_tab()
        self.tabs.addTab(self.tab_ai, "AI Rewriter")

        # Tab 3: Dictionary & Rules
        self.tab_dict = QWidget()
        self._setup_dict_tab()
        self.tabs.addTab(self.tab_dict, "Dictionary & Rules")

        # Tab 4: Statistics & Privacy
        self.tab_stats = QWidget()
        self._setup_stats_tab()
        self.tabs.addTab(self.tab_stats, "Stats & Privacy")

        # Bottom Action Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.save_btn = QPushButton("Save Changes", self)
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self.save_settings)
        btn_row.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        main_layout.addLayout(btn_row)

    def _setup_engine_tab(self) -> None:
        layout = QVBoxLayout(self.tab_engine)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Harper Dialect
        row1 = QHBoxLayout()
        lbl_dialect = QLabel("Harper Dialect:", self.tab_engine)
        lbl_dialect.setFixedWidth(160)
        row1.addWidget(lbl_dialect)
        self.dialect_combo = QComboBox(self.tab_engine)
        self.dialect_combo.addItems(["American", "British", "Australian", "Canadian", "Indian"])
        row1.addWidget(self.dialect_combo, stretch=1)
        layout.addLayout(row1)

        # Mode
        row2 = QHBoxLayout()
        lbl_mode = QLabel("Operating Mode:", self.tab_engine)
        lbl_mode.setFixedWidth(160)
        row2.addWidget(lbl_mode)
        self.mode_combo = QComboBox(self.tab_engine)
        self.mode_combo.addItems(["auto", "offline", "online"])
        row2.addWidget(self.mode_combo, stretch=1)
        layout.addLayout(row2)

        # Debounce Latency
        row3 = QHBoxLayout()
        lbl_debounce = QLabel("Typing Idle Pause (ms):", self.tab_engine)
        lbl_debounce.setFixedWidth(160)
        row3.addWidget(lbl_debounce)
        self.debounce_spin = QSpinBox(self.tab_engine)
        self.debounce_spin.setRange(200, 3000)
        self.debounce_spin.setSingleStep(50)
        self.debounce_spin.setValue(700)
        row3.addWidget(self.debounce_spin, stretch=1)
        layout.addLayout(row3)

        # Global Hotkey
        row4 = QHBoxLayout()
        lbl_hotkey = QLabel("Global Hotkey:", self.tab_engine)
        lbl_hotkey.setFixedWidth(160)
        row4.addWidget(lbl_hotkey)
        self.hotkey_edit = QLineEdit(self.tab_engine)
        self.hotkey_edit.setPlaceholderText("<ctrl>+<shift>+e")
        row4.addWidget(self.hotkey_edit, stretch=1)
        layout.addLayout(row4)

        # Suggest Only Checkbox
        self.suggest_only_check = QCheckBox("Suggest-only mode (copy to clipboard instead of typing)", self.tab_engine)
        layout.addWidget(self.suggest_only_check)

        layout.addStretch()

    def _setup_ai_tab(self) -> None:
        layout = QVBoxLayout(self.tab_ai)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Provider
        row_prov = QHBoxLayout()
        lbl_prov = QLabel("LLM Provider:", self.tab_ai)
        lbl_prov.setFixedWidth(140)
        row_prov.addWidget(lbl_prov)
        self.provider_combo = QComboBox(self.tab_ai)
        self.provider_combo.addItems(["groq", "openrouter", "gemini"])
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        row_prov.addWidget(self.provider_combo, stretch=1)
        layout.addLayout(row_prov)

        # API Key
        row_key = QHBoxLayout()
        lbl_key = QLabel("API Key:", self.tab_ai)
        lbl_key.setFixedWidth(140)
        row_key.addWidget(lbl_key)
        self.api_key_edit = QLineEdit(self.tab_ai)
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("Enter API Key (e.g. gsk_...)")
        row_key.addWidget(self.api_key_edit, stretch=1)

        self.toggle_key_btn = QPushButton("Show", self.tab_ai)
        self.toggle_key_btn.setFixedWidth(60)
        self.toggle_key_btn.clicked.connect(self._toggle_key_visibility)
        row_key.addWidget(self.toggle_key_btn)
        layout.addLayout(row_key)

        # Model Override
        row_model = QHBoxLayout()
        lbl_model = QLabel("Model Name:", self.tab_ai)
        lbl_model.setFixedWidth(140)
        row_model.addWidget(lbl_model)
        self.model_edit = QLineEdit(self.tab_ai)
        row_model.addWidget(self.model_edit, stretch=1)
        layout.addLayout(row_model)

        # Test Connection Button
        test_row = QHBoxLayout()
        self.test_conn_btn = QPushButton("Test API Connection", self.tab_ai)
        self.test_conn_btn.clicked.connect(self._test_connection)
        test_row.addWidget(self.test_conn_btn)
        self.test_status_lbl = QLabel("", self.tab_ai)
        test_row.addWidget(self.test_status_lbl, stretch=1)
        layout.addLayout(test_row)

        layout.addStretch()

    def _setup_dict_tab(self) -> None:
        layout = QVBoxLayout(self.tab_dict)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Personal Words Section
        lbl_words = QLabel("Personal Vocabulary (Bypasses Spellcheck):", self.tab_dict)
        lbl_words.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        layout.addWidget(lbl_words)

        self.words_list = QListWidget(self.tab_dict)
        layout.addWidget(self.words_list, stretch=1)

        w_row = QHBoxLayout()
        self.new_word_edit = QLineEdit(self.tab_dict)
        self.new_word_edit.setPlaceholderText("Enter custom word...")
        w_row.addWidget(self.new_word_edit, stretch=1)

        self.add_word_btn = QPushButton("Add Word", self.tab_dict)
        self.add_word_btn.clicked.connect(self._add_word)
        w_row.addWidget(self.add_word_btn)

        self.remove_word_btn = QPushButton("Remove", self.tab_dict)
        self.remove_word_btn.clicked.connect(self._remove_word)
        w_row.addWidget(self.remove_word_btn)
        layout.addLayout(w_row)

        # Custom Replacement Rules
        lbl_rules = QLabel("Custom Replacement Rules (Find → Replace):", self.tab_dict)
        lbl_rules.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        layout.addWidget(lbl_rules)

        self.rules_table = QTableWidget(self.tab_dict)
        self.rules_table.setColumnCount(2)
        self.rules_table.setHorizontalHeaderLabels(["Pattern", "Replacement"])
        self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.rules_table, stretch=1)

        r_row = QHBoxLayout()
        self.pattern_edit = QLineEdit(self.tab_dict)
        self.pattern_edit.setPlaceholderText("Pattern (e.g. teh)")
        r_row.addWidget(self.pattern_edit, stretch=1)

        self.replace_edit = QLineEdit(self.tab_dict)
        self.replace_edit.setPlaceholderText("Replacement (e.g. the)")
        r_row.addWidget(self.replace_edit, stretch=1)

        self.add_rule_btn = QPushButton("Add Rule", self.tab_dict)
        self.add_rule_btn.clicked.connect(self._add_rule)
        r_row.addWidget(self.add_rule_btn)

        self.remove_rule_btn = QPushButton("Remove", self.tab_dict)
        self.remove_rule_btn.clicked.connect(self._remove_rule)
        r_row.addWidget(self.remove_rule_btn)
        layout.addLayout(r_row)

    def _setup_stats_tab(self) -> None:
        layout = QVBoxLayout(self.tab_stats)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        card = QFrame(self.tab_stats)
        card.setObjectName("card")
        cl = QVBoxLayout(card)

        notice_title = QLabel("Privacy Guarantee", card)
        notice_title.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        cl.addWidget(notice_title)

        notice_body = QLabel(
            "PeakGrammar strictly processes your writing locally via Harper. "
            "Zero keystrokes or text snippets are ever logged or uploaded in the background. "
            "Only local anonymous daily counts of corrections are kept below for your reference.",
            card
        )
        notice_body.setWordWrap(True)
        notice_body.setStyleSheet("color: #71717a;")
        cl.addWidget(notice_body)
        layout.addWidget(card)

        # Stats Summary
        self.total_stats_lbl = QLabel("Total Corrections: 0", self.tab_stats)
        self.total_stats_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        layout.addWidget(self.total_stats_lbl)

        self.stats_list = QListWidget(self.tab_stats)
        layout.addWidget(self.stats_list, stretch=1)

        layout.addStretch()

    # -----------------------------------------------------------------------
    # Logic & Data Persistence
    # -----------------------------------------------------------------------

    def load_settings(self) -> None:
        # Engine
        dialect = get_setting("dialect", "American")
        idx = self.dialect_combo.findText(dialect)
        if idx >= 0:
            self.dialect_combo.setCurrentIndex(idx)

        mode = get_setting("mode", "auto")
        idx_mode = self.mode_combo.findText(mode)
        if idx_mode >= 0:
            self.mode_combo.setCurrentIndex(idx_mode)

        self.debounce_spin.setValue(int(get_setting("debounce_ms", "700")))
        self.hotkey_edit.setText(get_setting("hotkey", "<ctrl>+<shift>+e"))
        self.suggest_only_check.setChecked(get_setting("suggest_only", "0") == "1")

        # AI
        import os, dotenv
        dotenv.load_dotenv()
        prov = get_setting("provider", os.getenv("LLM_PROVIDER", "groq"))
        idx_p = self.provider_combo.findText(prov)
        if idx_p >= 0:
            self.provider_combo.setCurrentIndex(idx_p)

        self.api_key_edit.setText(os.getenv("LLM_API_KEY", ""))
        self.model_edit.setText(os.getenv("LLM_MODEL", DEFAULT_PROVIDERS.get(prov, {}).get("model", "")))

        # Dictionary & Rules
        self._refresh_dictionary_views()

        # Stats
        total = get_total_corrections_count()
        self.total_stats_lbl.setText(f"Total Corrections: {total}")
        self.stats_list.clear()
        for cat, cnt in get_category_breakdown().items():
            self.stats_list.addItem(f"Category [{cat}]: {cnt} corrections")

    def _refresh_dictionary_views(self) -> None:
        self.words_list.clear()
        for word in self.dictionary_store.get_words():
            self.words_list.addItem(word)

        rules = self.dictionary_store.get_rules()
        self.rules_table.setRowCount(len(rules))
        for row, (pat, rep) in enumerate(rules):
            self.rules_table.setItem(row, 0, QTableWidgetItem(pat))
            self.rules_table.setItem(row, 1, QTableWidgetItem(rep))

    def _on_provider_changed(self, provider: str) -> None:
        cfg = DEFAULT_PROVIDERS.get(provider.lower(), {})
        if cfg:
            self.model_edit.setText(cfg.get("model", ""))

    def _toggle_key_visibility(self) -> None:
        if self.api_key_edit.echoMode() == QLineEdit.EchoMode.Password:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_key_btn.setText("Hide")
        else:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_key_btn.setText("Show")

    def _test_connection(self) -> None:
        key = self.api_key_edit.text().strip()
        prov = self.provider_combo.currentText().strip()
        model = self.model_edit.text().strip()

        if not key:
            self.test_status_lbl.setText("Enter an API key first.")
            return

        self.test_status_lbl.setText("Connecting…")
        engine = OnlineEngine(provider=prov, api_key=key, model=model)
        res = engine.rewrite("Test sentence.", tone_or_instruction="Concise", timeout=4.0)

        if res:
            self.test_status_lbl.setText("✓ Connection successful!")
        else:
            self.test_status_lbl.setText("✗ Connection failed. Check key & model.")

    def _add_word(self) -> None:
        w = self.new_word_edit.text().strip()
        if w:
            self.dictionary_store.add_word(w)
            self.new_word_edit.clear()
            self._refresh_dictionary_views()

    def _remove_word(self) -> None:
        item = self.words_list.currentItem()
        if item:
            self.dictionary_store.remove_word(item.text())
            self._refresh_dictionary_views()

    def _add_rule(self) -> None:
        pat = self.pattern_edit.text().strip()
        rep = self.replace_edit.text().strip()
        if pat and rep:
            self.dictionary_store.add_rule(pat, rep)
            self.pattern_edit.clear()
            self.replace_edit.clear()
            self._refresh_dictionary_views()

    def _remove_rule(self) -> None:
        row = self.rules_table.currentRow()
        if row >= 0:
            pat_item = self.rules_table.item(row, 0)
            if pat_item:
                self.dictionary_store.remove_rule(pat_item.text())
                self._refresh_dictionary_views()

    def save_settings(self) -> None:
        set_setting("dialect", self.dialect_combo.currentText())
        set_setting("mode", self.mode_combo.currentText())
        set_setting("debounce_ms", str(self.debounce_spin.value()))
        set_setting("hotkey", self.hotkey_edit.text().strip())
        set_setting("suggest_only", "1" if self.suggest_only_check.isChecked() else "0")
        set_setting("provider", self.provider_combo.currentText())

        # Update .env
        import os
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        key = self.api_key_edit.text().strip()
        prov = self.provider_combo.currentText()
        model = self.model_edit.text().strip()
        dialect = self.dialect_combo.currentText()

        content = (
            f"LLM_PROVIDER={prov}\n"
            f"LLM_API_KEY={key}\n"
            f"LLM_MODEL={model}\n"
            f"HARPER_DIALECT={dialect}\n"
        )
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass

        self.accept()
