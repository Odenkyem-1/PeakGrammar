"""Personal dictionary and custom replacement rules management for PeakGrammar.

Integrates with SQLite storage to allow adding domain-specific terminology,
brand names, jargon, and custom replacement conventions.
"""

import datetime
from typing import Optional
from store.database import get_connection, init_db


class DictionaryStore:
    """Manages the user's personal dictionary and custom linting/style rules."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        init_db(self.db_path)

    # -----------------------------------------------------------------------
    # Personal Words
    # -----------------------------------------------------------------------

    def add_word(self, word: str) -> bool:
        """Add a word to the personal dictionary (case-insensitive unique)."""
        clean_word = word.strip()
        if not clean_word:
            return False

        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO personal_words (word, added_at) VALUES (?, ?)",
                (clean_word, datetime.datetime.now().isoformat())
            )
        return True

    def remove_word(self, word: str) -> bool:
        """Remove a word from the personal dictionary."""
        conn = get_connection(self.db_path)
        with conn:
            cur = conn.execute("DELETE FROM personal_words WHERE word = ? COLLATE NOCASE", (word.strip(),))
            return cur.rowcount > 0

    def has_word(self, word: str) -> bool:
        """Check whether a word exists in the personal dictionary."""
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM personal_words WHERE word = ? COLLATE NOCASE", (word.strip(),))
        return cur.fetchone() is not None

    def get_words(self) -> list[str]:
        """Return all words in the personal dictionary sorted alphabetically."""
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT word FROM personal_words ORDER BY word COLLATE NOCASE ASC")
        return [row[0] for row in cur.fetchall()]

    # -----------------------------------------------------------------------
    # Custom Rules (Pre-processing Find & Replace)
    # -----------------------------------------------------------------------

    def add_rule(self, pattern: str, replacement: str) -> bool:
        """Add or update a custom find-and-replace rule."""
        p = pattern.strip()
        if not p:
            return False

        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO custom_rules (pattern, replacement, created_at) VALUES (?, ?, ?)",
                (p, replacement, datetime.datetime.now().isoformat())
            )
        return True

    def remove_rule(self, pattern: str) -> bool:
        """Remove a custom rule."""
        conn = get_connection(self.db_path)
        with conn:
            cur = conn.execute("DELETE FROM custom_rules WHERE pattern = ?", (pattern.strip(),))
            return cur.rowcount > 0

    def get_rules(self) -> list[tuple[str, str]]:
        """Return all custom rules as a list of (pattern, replacement) tuples."""
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT pattern, replacement FROM custom_rules ORDER BY pattern ASC")
        return [(row[0], row[1]) for row in cur.fetchall()]

    def apply_custom_rules(self, text: str, rules: Optional[list[tuple[str, str]]] = None) -> str:
        """Apply all custom rules sequentially to the provided text."""
        active_rules = rules if rules is not None else self.get_rules()
        for pattern, replacement in active_rules:
            if pattern in text:
                text = text.replace(pattern, replacement)
        return text
