# Complete Build Guide: Background Writing Assistant (Python + Harper + LLM)

## 1. Architecture Overview

The application runs as a **system-tray background service** with four decoupled layers:

| Layer | Responsibility | Technology |
| --- | --- | --- |
| **Text Acquisition** | Reads the focused text field in any app | `pywinauto` (UIA) + `pynput` (hotkeys/idle) |
| **Grammar Engine** | Offline linting (default) | `harper-py` (in-process, Rust-backed) |
| **LLM Enhancement** | Online rewrites, tone, one-click | Free LLM API (Groq / Gemini / OpenRouter) |
| **Suggestion UI** | Floating card near caret | PySide6 frameless, always-on-top window |
| **Data Store** | Settings, personal dictionary, stats | SQLite (local-only) |
| **Main Editor** | Focused refinement workspace | PySide6 soft-UI window |

Data flow:

```
User types → pynput idle timer → pywinauto reads focused field
    → Harper lints (offline, instant)
    → Suggestions pushed to floating overlay
    → User clicks "Rewrite" → LLM (if online) or Harper rules (if offline)
    → App applies text via pywinauto (or copies to clipboard)
    → SQLite logs correction counts (no raw text)
```

---

## 2. Project Structure

```
writing-assistant/
├── main.py                     # Entry point, system tray, orchestration
├── core/
│   ├── engine_offline.py       # Harper wrapper
│   ├── engine_online.py        # LLM client with failover
│   ├── text_acquisition.py     # UIA focused-field reader
│   ├── applier.py              # Write-back / clipboard fallback
│   └── debounce.py             # Idle timer
├── ui/
│   ├── overlay.py              # Floating suggestion card
│   ├── editor.py               # Main refinement window (soft UI)
│   ├── settings.py             # Preferences dialog
│   └── styles.qss              # Soft-UI stylesheet
├── store/
│   ├── database.py             # SQLite setup & queries
│   └── dictionary.py           # Personal dictionary manager
├── resources/
│   └── icons/                  # Tray + app icons
└── requirements.txt
```

---

## 3. Environment Setup

```bash
# Python 3.10+ required (harper-py supports 3.10+)
python -m venv venv
venv\Scripts\activate

pip install pyside6 harper-py pywinauto pynput requests openai python-dotenv
```

`requirements.txt`:

```
pyside6>=6.9
harper-py>=0.1.1
pywinauto>=0.6.9
pynput>=1.8
openai>=1.0
requests>=2.31
python-dotenv>=1.0
```

> **Note:** `harper-py` ships a self-contained Rust wheel (~10 MB). No Java, no server. Cold start is ~0.23 s and 1,007 words lint in ~23 ms.

---

## 4. Core Engine: Offline Harper (Default)

Harper runs **in-process** and should be initialized once and reused.

```python
# core/engine_offline.py
from harper import Linter

class OfflineEngine:
    def __init__(self, dialect: str = "American"):
        self.linter = Linter(dialect=dialect)  # "American", "British", "Australian", "Canadian"

    def lint(self, text: str) -> list[dict]:
        """Return structured suggestions. Harper lints are fast enough for real-time."""
        results = []
        for lint in self.linter.lint(text):
            results.append({
                "span": (lint.span.start, lint.span.end),
                "problem_text": lint.problem_text,
                "message": lint.message,
                "suggestions": [s.replacement for s in lint.suggestions],
                "applied": None,
            })
        return results

    def apply_suggestion(self, text: str, lint: dict, replacement: str) -> str:
        start, end = lint["span"]
        return text[:start] + replacement + text[end:]
```

Harper’s `Linter` API is synchronous and returns spans as string indices, so `text[start:end]` is always the flagged text, emoji included.

### 4.1 Personal Dictionary & Custom Rules

Harper supports user dictionaries and rule configuration. Store custom words and find→replace rules in SQLite and reload them into the linter.

```python
# store/dictionary.py
import sqlite3

class DictionaryStore:
    def __init__(self, db_path="assistant.db"):
        self.conn = sqlite3.connect(db_path)
        self._init()

    def _init(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS personal_words (word TEXT PRIMARY KEY)
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_rules (
                pattern TEXT PRIMARY KEY, replacement TEXT
            )
        """)

    def add_word(self, word: str):
        self.conn.execute("INSERT OR IGNORE INTO personal_words VALUES (?)", (word,))
        self.conn.commit()

    def get_words(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT word FROM personal_words")]

    def add_rule(self, pattern: str, replacement: str):
        self.conn.execute("INSERT OR REPLACE INTO custom_rules VALUES (?, ?)",
                          (pattern, replacement))
        self.conn.commit()

    def get_rules(self) -> list[tuple]:
        return list(self.conn.execute("SELECT pattern, replacement FROM custom_rules"))
```

Apply custom rules **before** Harper linting so your conventions are enforced first:

```python
def apply_custom_rules(text: str, rules: list[tuple]) -> str:
    for pattern, replacement in rules:
        text = text.replace(pattern, replacement)
    return text
```

---

## 5. Text Acquisition (System-Wide)

### 5.1 Reading the Focused Field via UI Automation

Use `pywinauto` with the `uia` backend to read the value pattern of the focused control. This works across Word, Notepad, browsers, and most Win32/UWP apps.

```python
# core/text_acquisition.py
from pywinauto import Desktop
import pywinauto.uia_defines as uia_defs

def get_focused_text() -> tuple[str | None, str | None]:
    """
    Returns (text, app_name). Returns (None, app_name) if the focused
    control does not expose a readable text value.
    """
    try:
        focused = Desktop(backend="uia").window(
            found_index=0,
            active_only=True
        ).focused_element()

        # Try the ValuePattern first
        if hasattr(focused, "iface_value"):
            text = focused.iface_value.CurrentValue
            app_name = focused.top_level_parent().window_text()
            return text, app_name

        # Fallback: TextPattern
        if hasattr(focused, "iface_text"):
            doc = focused.iface_text.DocumentRange
            return doc.GetText(-1).strip(), focused.top_level_parent().window_text()

    except Exception:
        return None, None

    return None, None
```

> **Important:** UIA does not work in terminals, password fields, or some Electron apps. Your app must **fail closed**: if `get_focused_text()` returns `None`, do nothing and do not log the field.

### 5.2 Exclusion List

Never read from sensitive processes.

```python
# core/text_acquisition.py (continued)

EXCLUDED_PROCESSES = {
    "WindowsTerminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
    "idea64.exe", "pycharm64.exe", "code.exe", "devenv.exe",
    "keepass.exe", "bitwarden.exe",
}

def is_excluded(app_name: str | None) -> bool:
    if not app_name:
        return True  # unknown app → fail closed
    return any(ex in app_name.lower() for ex in EXCLUDED_PROCESSES)
```

### 5.3 Global Hotkey (On-Demand Check)

Use `pynput` for a global hotkey that reads the current selection or field on demand.

```python
# core/hotkeys.py
from pynput import keyboard

def register_hotkey(callback, combo="<ctrl>+<shift>+e"):
    def on_activate():
        callback()

    listener = keyboard.GlobalHotKeys({combo: on_activate})
    listener.start()
    return listener
```

`pynput.keyboard.GlobalHotKeys` handles parsing and lifecycle automatically.

### 5.4 Idle Debounce (Real-Time Without Per-Keystroke Cost)

Check only after the user pauses typing for **600–800 ms**.

```python
# core/debounce.py
import threading

class IdleDebouncer:
    def __init__(self, callback, delay_ms=700):
        self.callback = callback
        self.delay = delay_ms / 1000.0
        self._timer = None
        self._lock = threading.Lock()

    def poke(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay, self._fire)
            self._timer.start()

    def _fire(self):
        self.callback()
```

Hook it to `pynput`’s keyboard listener:

```python
from pynput import keyboard

debouncer = IdleDebouncer(check_focused_field)

def on_press(key):
    debouncer.poke()

listener = keyboard.Listener(on_press=on_press)
listener.start()
```

---

## 6. Suggestion UI: Floating Card (Non-Intrusive)

### 6.1 Design Principle

The overlay must **never steal focus**, must be **always-on-top**, and should appear near the caret only when suggestions exist.

```python
# ui/overlay.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QFont

class SuggestionOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 10)

        self.card = QWidget()
        self.card.setObjectName("suggestionCard")
        self.card_layout = QVBoxLayout(self.card)
        self._layout.addWidget(self.card)

        self.message = QLabel()
        self.message.setFont(QFont("Segoe UI", 10))
        self.card_layout.addWidget(self.message)

        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton("Replace")
        self.ignore_btn = QPushButton("Ignore")
        self.dict_btn = QPushButton("Add to Dictionary")
        for b in (self.apply_btn, self.ignore_btn, self.dict_btn):
            btn_row.addWidget(b)
        self.card_layout.addLayout(btn_row)

    def show_suggestion(self, message: str, on_apply, on_ignore, on_dict, caret_pos: QPoint):
        self.message.setText(message)
        self.apply_btn.clicked.connect(on_apply)
        self.ignore_btn.clicked.connect(on_ignore)
        self.dict_btn.clicked.connect(on_dict)
        self.adjustSize()
        self.move(caret_pos)
        self.show()
```

**Caret positioning:** UIA does not expose the caret pixel position directly. Use the bounding rectangle of the focused element and offset it by the character index:

```python
rect = focused.rectangle()
approx_x = rect.left + min(rect.width() - 250, max(0, len(text) * 7))
overlay.move(QPoint(approx_x, rect.bottom + 8))
```

This is approximate but non-intrusive. For a production build, you can refine it by querying the `TextPattern` range bounding rectangles per character.

### 6.2 Soft-UI Stylesheet

The design language is **Soft UI** (neomorphism-lite): rounded corners, soft shadows, layered surfaces, muted gradients—clean but not minimalistic.

```css
/* ui/styles.qss */
#suggestionCard {
    background: #f0f0f3;
    border-radius: 16px;
    border: 1px solid rgba(255, 255, 255, 0.6);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12), 0 2px 6px rgba(0, 0, 0, 0.06);
}

QPushButton {
    background: #e8e8ed;
    border: none;
    border-radius: 10px;
    padding: 6px 14px;
    color: #2c2c34;
    font-weight: 500;
}

QPushButton:hover { background: #dcdce3; }
QPushButton:pressed { background: #d0d0d8; }

QPushButton#primary {
    background: #5b6cff;
    color: white;
}
QPushButton#primary:hover { background: #4a5aee; }
```

Load it in `main.py`:

```python
from PySide6.QtWidgets import QApplication
app = QApplication([])
with open("ui/styles.qss", "r") as f:
    app.setStyleSheet(f.read())
```

### 6.3 Right-Click Context Menu

Add a tray context menu that includes the on-demand check and settings:

```python
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QAction
from PySide6.QtGui import QIcon

tray = QSystemTrayIcon(QIcon("resources/icons/tray.png"))
tray.setToolTip("Writing Assistant")

menu = QMenu()
check_action = QAction("Check Selection / Field")
check_action.triggered.connect(on_demand_check)
menu.addAction(check_action)

settings_action = QAction("Settings")
settings_action.triggered.connect(open_settings)
menu.addAction(settings_action)

menu.addSeparator()
quit_action = QAction("Quit")
quit_action.triggered.connect(app.quit)
menu.addAction(quit_action)

tray.setContextMenu(menu)
tray.show()
```

`QSystemTrayIcon` with a `QMenu` is the standard PySide6 pattern for background apps.

---

## 7. Online LLM Engine (Failover & Privacy)

### 7.1 Provider Strategy

Use an **OpenAI-compatible client** so you can swap providers without code changes. Recommended free providers in 2026:

| Provider | Free Allowance | Best For |
| --- | --- | --- |
| **GroqCloud** | Model-specific daily limits | Fastest inference; ideal for real-time rewrites |
| **Google Gemini** | Free usage on selected models | Generous tier; Gemini 2.5 Pro available |
| **OpenRouter** | 20 RPM, 50 RPD | Widest model choice; `:free` suffix models |

Use `freelm` as an auto-failover wrapper if you want zero-configuration failover across providers.

### 7.2 LLM Client with Timeout and Offline Fallback

```python
# core/engine_online.py
from openai import OpenAI
import os

class OnlineEngine:
    def __init__(self, provider: str = "groq"):
        cfg = {
            "groq": {
                "base_url": "https://api.groq.com/openai/v1",
                "model": "openai/gpt-oss-120b",
            },
            "openrouter": {
                "base_url": "https://openrouter.ai/api/v1",
                "model": "nvidia/nemotron-3.5-lightning:free",
            },
            "gemini": {
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "model": "gemini-2.5-pro",
            },
        }
        c = cfg[provider]
        self.client = OpenAI(base_url=c["base_url"], api_key=os.getenv("LLM_API_KEY"))
        self.model = c["model"]

    def rewrite(self, text: str, instruction: str, timeout: float = 6.0) -> str | None:
        """
        instruction examples: "Fix grammar and spelling",
        "Make concise", "Rewrite professionally", "Improve clarity"
        """
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content":
                     "You are a lightweight writing assistant. Return ONLY the revised text. "
                     "Preserve markdown, code blocks, URLs, and mentions exactly."},
                    {"role": "user", "content": f"{instruction}:\n\n{text}"},
                ],
                temperature=0.2,
                max_tokens=min(2048, len(text) * 2),
                timeout=timeout,
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            return None  # caller falls back to Harper
```

### 7.3 Online/Offline Decision Logic

```python
def get_suggestions(text: str, mode: str = "auto") -> list[dict]:
    """
    mode: "offline" | "online" | "auto"
    "auto" tries LLM only for rewrite actions, uses Harper for linting.
    """
    if mode == "offline":
        return offline.lint(text)

    if mode == "online":
        rewritten = online.rewrite(text, "Fix grammar and improve clarity")
        if rewritten:
            return [{"type": "rewrite", "original": text, "replacement": rewritten}]
        return offline.lint(text)  # failover

    # auto: always lint offline; online only when user clicks a rewrite action
    return offline.lint(text)
```

**Critical privacy rule:** The LLM is contacted **only when the user explicitly clicks a rewrite action**. Real-time linting never leaves the device.

---

## 8. Applying Corrections (Undo-Safe)

### 8.1 Apply via UIA

```python
# core/applier.py
from pywinauto import Desktop

def apply_text(new_text: str) -> bool:
    try:
        focused = Desktop(backend="uia").window(
            found_index=0, active_only=True
        ).focused_element()

        if hasattr(focused, "iface_value"):
            focused.iface_value.SetValue(new_text)
            return True

        # Fallback: select all + type (works in most editable fields)
        focused.type_keys("^a")
        focused.type_keys(new_text, with_spaces=True, with_newlines=True)
        return True
    except Exception:
        return False
```

### 8.2 Clipboard Fallback (Suggest-Only Mode)

If UIA cannot write, copy the suggestion to the clipboard so the user can paste it manually.

```python
import pyperclip

def copy_to_clipboard(text: str):
    pyperclip.copy(text)
```

### 8.3 Undo Consideration

UIA `SetValue` generally **does not** enter the host app’s undo stack. In suggest-only mode (clipboard), the user pastes manually, and `Ctrl+Z` works naturally. For production, prefer **suggest-only** in apps where undo integrity matters (Word, Google Docs), and use **apply mode** only where you have verified undo support.

---

## 9. Main Refinement UI (Soft UI Editor)

The editor is a **dedicated refinement workspace** with a soft-UI aesthetic: layered cards, rounded panels, a writing score, tone picker, and a rewrite button.

```python
# ui/editor.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel,
    QComboBox, QPushButton, QFrame, QProgressBar
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

class RefinementEditor(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Writing Refinement")
        self.resize(900, 680)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # Header card
        header = QFrame()
        header.setObjectName("card")
        hl = QHBoxLayout(header)
        title = QLabel("Refinement Studio")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.DemiBold))
        hl.addWidget(title)
        hl.addStretch()

        self.tone = QComboBox()
        self.tone.addItems(["Professional", "Friendly", "Confident", "Concise", "Academic"])
        hl.addWidget(QLabel("Tone:"))
        hl.addWidget(self.tone)
        root.addWidget(header)

        # Editor card
        editor_card = QFrame()
        editor_card.setObjectName("card")
        el = QVBoxLayout(editor_card)
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Paste or type text here to refine…")
        self.text_edit.setFont(QFont("Segoe UI", 11))
        el.addWidget(self.text_edit)
        root.addWidget(editor_card, stretch=1)

        # Score card
        score_card = QFrame()
        score_card.setObjectName("card")
        sl = QHBoxLayout(score_card)
        sl.addWidget(QLabel("Writing Score"))
        self.score_bar = QProgressBar()
        self.score_bar.setRange(0, 100)
        self.score_bar.setValue(78)
        self.score_bar.setTextVisible(True)
        sl.addWidget(self.score_bar, stretch=1)
        root.addWidget(score_card)

        # Action buttons
        actions = QHBoxLayout()
        self.rewrite_btn = QPushButton("Rewrite Sentence")
        self.rewrite_btn.setObjectName("primary")
        self.rewrite_all_btn = QPushButton("Rewrite All")
        self.check_btn = QPushButton("Check Offline")
        for b in (self.rewrite_btn, self.rewrite_all_btn, self.check_btn):
            actions.addWidget(b)
        actions.addStretch()
        root.addLayout(actions)
```

Soft-UI card styling:

```css
#card {
    background: #f7f7fa;
    border-radius: 18px;
    border: 1px solid #e4e4ec;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.06);
    padding: 12px;
}

QTextEdit {
    background: #fcfcff;
    border: 1px solid #e2e2ea;
    border-radius: 12px;
    padding: 12px;
    selection-background-color: #d6d9ff;
}

QComboBox {
    background: #ececf3;
    border: none;
    border-radius: 8px;
    padding: 6px 10px;
}

QProgressBar {
    background: #e8e8f0;
    border: none;
    border-radius: 7px;
    height: 14px;
}
QProgressBar::chunk {
    background: #5b6cff;
    border-radius: 7px;
}
```

**This editor is not minimalistic:** it uses layered cards, a score visualization, a tone selector, and multiple action buttons—clean but rich.

---

## 10. Features from the Requirements Matrix

### 10.1 Tone, Formality & Audience Goals

Store the active tone in SQLite and pass it as an instruction to the LLM:

```python
TONE_INSTRUCTIONS = {
    "Professional": "Rewrite professionally and formally.",
    "Friendly": "Rewrite in a warm, friendly tone.",
    "Confident": "Rewrite with confidence and authority.",
    "Concise": "Make it as concise as possible without losing meaning.",
    "Academic": "Rewrite in an academic style with precise vocabulary.",
}

instruction = TONE_INSTRUCTIONS[self.tone.currentText()]
```

### 10.2 Developer-Friendly Preservation

Before sending to the LLM or applying Harper, **mask** protected segments:

```python
import re

PROTECTED_PATTERNS = [
    r"https?://\S+", r"`[^`]+`", r"```[\s\S]*?```",
    r"@\w+", r":\w+:", r"[A-Z]:\\[^\s]+",
]

def mask_protected(text: str) -> tuple[str, dict]:
    placeholders = {}
    for i, pat in enumerate(PROTECTED_PATTERNS):
        for match in re.finditer(pat, text):
            key = f"__PROTECTED_{i}_{len(placeholders)}__"
            placeholders[key] = match.group(0)
            text = text.replace(match.group(0), key)
    return text, placeholders

def unmask(text: str, placeholders: dict) -> str:
    for key, original in placeholders.items():
        text = text.replace(key, original)
    return text
```

Apply masking before LLM calls and before applying suggestions to the host app.

### 10.3 Native Spellchecker Conflict

In Word and Outlook, two underline systems will fight. On first run, show a one-time onboarding dialog:

> “For the best experience, disable Microsoft Editor / native spellcheck inside your writing apps. We will otherwise suppress our underlines in apps where native checking is detected.”

Detect native checker via the presence of `WordEditor` or `RichEdit` controls and disable your overlay underlines there, keeping only the on-demand hotkey.

### 10.4 Text-Expansion Snippets (Off by Default)

Store snippets in SQLite and expand on a trigger sequence via `pynput`:

```python
class SnippetExpander:
    def __init__(self, snippets: dict[str, str]):
        self.snippets = snippets
        self.buffer = ""

    def on_key(self, key):
        try:
            self.buffer += key.char
        except AttributeError:
            self.buffer = ""
            return
        for trigger, expansion in self.snippets.items():
            if self.buffer.endswith(trigger):
                self.buffer = self.buffer[:-len(trigger)]
                # type expansion via pynput Controller
                from pynput.keyboard import Controller
                Controller().type(expansion)
                break
        if len(self.buffer) > 20:
            self.buffer = self.buffer[-20:]
```

Exclude this from terminals and IDEs by default (use the same exclusion list).

### 10.5 Local-Only Stats & Weekly Summary

```python
# store/database.py
CREATE_STATS = """
CREATE TABLE IF NOT EXISTS correction_stats (
    date TEXT PRIMARY KEY,
    count INTEGER DEFAULT 0,
    category TEXT
);
"""

def log_correction(category: str):
    today = datetime.date.today().isoformat()
    conn.execute("""
        INSERT INTO correction_stats (date, count, category)
        VALUES (?, 1, ?)
        ON CONFLICT(date) DO UPDATE SET count = count + 1
    """, (today, category))
    conn.commit()
```

Display a weekly summary in the settings window. **Never store the raw text of corrections.**

### 10.6 Permission Onboarding

On first launch, show a live status checklist:

```python
PERMISSIONS = [
    ("Accessibility / UIA access", check_uia_access),
    ("Keyboard monitoring", check_keyboard_access),
    ("System tray", check_tray_access),
]
```

Each row shows a status dot (green/amber/red) and a “Grant” button that opens the relevant Windows settings page.

---

## 11. Main Orchestration (main.py)

```python
# main.py
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from core.engine_offline import OfflineEngine
from core.engine_online import OnlineEngine
from core.text_acquisition import get_focused_text, is_excluded
from core.debounce import IdleDebouncer
from core.hotkeys import register_hotkey
from ui.overlay import SuggestionOverlay
from ui.editor import RefinementEditor
from store.database import init_db
from store.dictionary import DictionaryStore

app = QApplication(sys.argv)
with open("ui/styles.qss", "r") as f:
    app.setStyleSheet(f.read())

init_db()
dictionary = DictionaryStore()
offline = OfflineEngine()
online = OnlineEngine(provider="groq")
overlay = SuggestionOverlay()
editor = RefinementEditor()

def check_focused_field():
    text, app_name = get_focused_text()
    if is_excluded(app_name) or not text:
        return

    # Apply custom rules first
    for pattern, replacement in dictionary.get_rules():
        text = text.replace(pattern, replacement)

    lints = offline.lint(text)
    if not lints:
        overlay.hide()
        return

    # Show the first actionable suggestion
    lint = lints[0]
    msg = lint["message"]
    suggestion = lint["suggestions"][0] if lint["suggestions"] else ""

    def apply():
        new_text = offline.apply_suggestion(text, lint, suggestion)
        from core.applier import apply_text
        apply_text(new_text)
        overlay.hide()

    def ignore():
        overlay.hide()

    def add_dict():
        dictionary.add_word(lint["problem_text"])
        overlay.hide()

    overlay.show_suggestion(msg, apply, ignore, add_dict, caret_pos=editor.pos())

debouncer = IdleDebouncer(check_focused_field)

from pynput import keyboard

def on_press(key):
    debouncer.poke()

key_listener = keyboard.Listener(on_press=on_press)
key_listener.start()

hotkey_listener = register_hotkey(check_focused_field, "<ctrl>+<shift>+e")

# Tray icon setup (abbreviated; see Section 6.3)
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QAction
from PySide6.QtGui import QIcon
tray = QSystemTrayIcon(QIcon("resources/icons/tray.png"))
menu = QMenu()
open_editor = QAction("Open Refinement Studio")
open_editor.triggered.connect(editor.show)
menu.addAction(open_editor)
menu.addSeparator()
quit_act = QAction("Quit")
quit_act.triggered.connect(app.quit)
menu.addAction(quit_act)
tray.setContextMenu(menu)
tray.show()

sys.exit(app.exec())
```

---

## 12. Privacy, Performance & Packaging

### 12.1 Privacy Defaults

- **Offline-first:** Harper runs in-process; no text leaves the machine for linting.
- **LLM only on explicit action:** rewrite buttons are the only trigger.
- **No keystroke logging:** `pynput` is used only for idle detection and hotkeys; the buffer is never persisted.
- **Stats are aggregate only:** store counts and categories, never raw text.
- **Exclusion list enforced:** sensitive apps are skipped entirely.

### 12.2 Performance Targets

| Metric | Target |
| --- | --- |
| Idle CPU | < 1% (debounced checking) |
| Memory | < 80 MB (Harper + PySide6) |
| Cold start | < 1.5 s |
| Harper lint (1,000 words) | ~23 ms |
| LLM timeout | 6 s max, then fallback to Harper |

### 12.3 Packaging with PyInstaller

```bash
pip install pyinstaller
pyinstaller --noconfirm --windowed --onefile ^
  --name "WritingAssistant" ^
  --icon "resources/icons/app.ico" ^
  --add-data "ui/styles.qss;ui" ^
  --add-data "resources/icons;resources/icons" ^
  main.py
```

> `--windowed` prevents a console window. `harper-py`’s wheel is self-contained, so no extra data files are needed for the grammar engine.

---

## 13. Build Order & Milestones

| Week | Milestone | Deliverable |
| --- | --- | --- |
| **1** | Core engine | Harper linting working on hardcoded text; SQLite schema |
| **2** | Text acquisition | Read focused field in Notepad and Word; exclusion list |
| **3** | Suggestion UI | Floating card appears near caret; apply/ignore/dict buttons |
| **4** | Hotkeys + debounce | `Ctrl+Shift+E` on-demand; idle-triggered linting |
| **5** | LLM integration | Groq/Gemini rewrite with 6 s timeout and Harper failover |
| **6** | Soft UI editor | Refinement Studio with tone picker, score, rewrite buttons |
| **7** | Features | Personal dictionary, custom rules, masking, stats, onboarding |
| **8** | Polish & package | Tray, settings, PyInstaller build, performance validation |
