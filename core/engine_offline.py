"""Offline grammar and spelling engine powered by Harper.

Runs in-process with a native Rust backend for low-latency, zero-leakage
writing diagnostics.
"""

from typing import Any, Optional
import harper

from core.masking import get_protected_spans, is_span_protected
from store.dictionary import DictionaryStore

DIALECT_MAP = {
    "american": harper.Dialect.AMERICAN,
    "british": harper.Dialect.BRITISH,
    "australian": harper.Dialect.AUSTRALIAN,
    "canadian": harper.Dialect.CANADIAN,
    "indian": harper.Dialect.INDIAN,
}


class OfflineEngine:
    """In-process Harper grammar and spellchecker."""

    def __init__(self, dialect: str = "American", dictionary_store: Optional[DictionaryStore] = None):
        self.dialect_name = dialect
        self.dictionary_store = dictionary_store
        self._init_linter()

    def _init_linter(self) -> None:
        """Instantiate the Harper linter and import user vocabulary."""
        dialect_key = self.dialect_name.strip().lower()
        dialect_enum = DIALECT_MAP.get(dialect_key, harper.Dialect.AMERICAN)
        self.linter = harper.Linter(dialect=dialect_enum)

        # Import custom dictionary words if available
        if self.dictionary_store:
            words = self.dictionary_store.get_words()
            if words:
                self.linter.import_words(words)

    def set_dialect(self, dialect: str) -> None:
        """Update the active dialect and reinitialize the linter."""
        self.dialect_name = dialect
        self._init_linter()

    def sync_dictionary(self) -> None:
        """Reload user dictionary words into Harper's native wordlist."""
        if not self.dictionary_store:
            return
        words = self.dictionary_store.get_words()
        self.linter.clear_words()
        if words:
            self.linter.import_words(words)

    def lint(self, text: str) -> list[dict[str, Any]]:
        """Analyze text and return structured suggestions.

        Protected code blocks, URLs, file paths, and personal dictionary
        words are automatically excluded from diagnostics.
        """
        if not text or not text.strip():
            return []

        # Find spans that must never be flagged (code, paths, links)
        protected_spans = get_protected_spans(text)

        # Cache personal dictionary for fast case-insensitive lookups
        known_words = set(w.lower() for w in self.dictionary_store.get_words()) if self.dictionary_store else set()

        raw_lints = self.linter.lint(text)
        results: list[dict[str, Any]] = []

        for lint in raw_lints:
            span = (lint.span.start, lint.span.end)
            problem_text = lint.problem_text

            # 1. Skip if the lint falls inside a protected segment
            if is_span_protected(span, protected_spans):
                continue

            # 2. Skip if the flagged word is in the user's personal dictionary
            if problem_text.strip().lower() in known_words:
                continue

            # Extract suggested replacement strings
            suggestions = [s.replacement_text for s in lint.suggestions if s.replacement_text]

            results.append({
                "span": span,
                "problem_text": problem_text,
                "message": lint.message,
                "suggestions": suggestions,
                "applied": None,
            })

        return results

    def apply_suggestion(self, text: str, lint: dict[str, Any], replacement: str) -> str:
        """Apply a replacement to text at the lint's span."""
        start, end = lint["span"]
        if start < 0 or end > len(text) or start > end:
            return text
        return text[:start] + replacement + text[end:]
