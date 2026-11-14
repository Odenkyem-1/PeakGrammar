"""SQLite database manager and schema definition for PeakGrammar.

Stores user settings, personal dictionary, custom replacement rules,
and aggregate correction statistics (strictly zero raw text logged).
"""

import datetime
import os
import sqlite3
import threading
from typing import Any, Optional

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assistant.db"
)

_LOCAL = threading.local()


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Return a thread-local SQLite connection."""
    target_path = db_path or getattr(_LOCAL, "db_path", DEFAULT_DB_PATH)
    conn = getattr(_LOCAL, "conn", None)
    current_path = getattr(_LOCAL, "db_path", None)

    if conn is None or current_path != target_path:
        conn = sqlite3.connect(target_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        _LOCAL.conn = conn
        _LOCAL.db_path = target_path

    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize all SQLite tables and default settings."""
    conn = get_connection(db_path)
    with conn:
        # Personal dictionary words
        conn.execute("""
            CREATE TABLE IF NOT EXISTS personal_words (
                word TEXT PRIMARY KEY COLLATE NOCASE,
                added_at TEXT NOT NULL
            )
        """)

        # Custom find-and-replace rules (e.g. style conventions, project terms)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_rules (
                pattern TEXT PRIMARY KEY,
                replacement TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Aggregate statistics by date and category - NEVER stores raw user text
        conn.execute("""
            CREATE TABLE IF NOT EXISTS correction_stats (
                date TEXT NOT NULL,
                category TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (date, category)
            )
        """)

        # Key-value store for app configuration
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Text expansion snippets (optional feature)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS text_snippets (
                trigger TEXT PRIMARY KEY,
                expansion TEXT NOT NULL,
                enabled INTEGER DEFAULT 1
            )
        """)

    # Populate default settings if missing
    defaults = {
        "dialect": "American",
        "tone": "Professional",
        "mode": "auto",              # offline | online | auto
        "provider": "groq",          # groq | gemini | openrouter
        "debounce_ms": "700",
        "hotkey": "<ctrl>+<shift>+e",
        "suggest_only": "0",         # 1 = clipboard paste only; 0 = direct UIA write
        "onboarding_completed": "0",
        "theme": "monochrome",
    }
    for k, v in defaults.items():
        if get_setting(k, db_path=db_path) is None:
            set_setting(k, v, db_path=db_path)


# ---------------------------------------------------------------------------
# Settings CRUD
# ---------------------------------------------------------------------------

def get_setting(key: str, default: Optional[str] = None, db_path: Optional[str] = None) -> Optional[str]:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
    row = cur.fetchone()
    return row[0] if row else default


def set_setting(key: str, value: Any, db_path: Optional[str] = None) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            (key, str(value))
        )


def get_all_settings(db_path: Optional[str] = None) -> dict[str, str]:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM app_settings")
    return {row[0]: row[1] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Aggregate Statistics Logging (Privacy-First)
# ---------------------------------------------------------------------------

def log_correction(category: str = "general", db_path: Optional[str] = None) -> None:
    """Record an aggregate correction count for today. Raw text is never stored."""
    today = datetime.date.today().isoformat()
    conn = get_connection(db_path)
    with conn:
        conn.execute("""
            INSERT INTO correction_stats (date, category, count)
            VALUES (?, ?, 1)
            ON CONFLICT(date, category) DO UPDATE SET count = count + 1
        """, (today, category))


def get_weekly_stats(db_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Return daily correction totals for the last 7 days."""
    today = datetime.date.today()
    seven_days_ago = (today - datetime.timedelta(days=6)).isoformat()
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT date, SUM(count) as total_count
        FROM correction_stats
        WHERE date >= ?
        GROUP BY date
        ORDER BY date ASC
    """, (seven_days_ago,))
    return [{"date": row[0], "count": row[1]} for row in cur.fetchall()]


def get_category_breakdown(db_path: Optional[str] = None) -> dict[str, int]:
    """Return total correction counts grouped by category."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT category, SUM(count) as total
        FROM correction_stats
        GROUP BY category
        ORDER BY total DESC
    """)
    return {row[0]: row[1] for row in cur.fetchall()}


def get_total_corrections_count(db_path: Optional[str] = None) -> int:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(count), 0) FROM correction_stats")
    row = cur.fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Snippets CRUD
# ---------------------------------------------------------------------------

def get_snippets(enabled_only: bool = True, db_path: Optional[str] = None) -> dict[str, str]:
    conn = get_connection(db_path)
    cur = conn.cursor()
    if enabled_only:
        cur.execute("SELECT trigger, expansion FROM text_snippets WHERE enabled = 1")
    else:
        cur.execute("SELECT trigger, expansion FROM text_snippets")
    return {row[0]: row[1] for row in cur.fetchall()}


def add_snippet(trigger: str, expansion: str, db_path: Optional[str] = None) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO text_snippets (trigger, expansion, enabled) VALUES (?, ?, 1)",
            (trigger, expansion)
        )


def remove_snippet(trigger: str, db_path: Optional[str] = None) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute("DELETE FROM text_snippets WHERE trigger = ?", (trigger,))
