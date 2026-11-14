"""Developer-friendly text protection and masking.

Safeguards markdown code blocks, inline backtick code, URLs, Windows paths,
mentions, emoji shortcodes, and HTML tags from being flagged as errors or
corrupted during grammar linting or LLM rewriting.
"""

import re
from typing import Optional

# Compiled patterns in priority order
PROTECTED_PATTERNS = [
    # Multiline fenced code blocks (```python ... ```)
    re.compile(r"```[\s\S]*?```"),
    # Inline backtick code (`variable_name`)
    re.compile(r"`[^`\r\n]+`"),
    # Web URLs & localhost endpoints
    re.compile(r"(?:https?://|ftp://|www\.)[^\s<>'\"`]+"),
    # Windows absolute or UNC paths (e.g. C:\Users\name\file.py, \\server\share)
    re.compile(r"(?:[a-zA-Z]:\\|\\\\)(?:[a-zA-Z0-9_\-\. ]+\\)*[a-zA-Z0-9_\-\.]+"),
    # Mention handles (@username)
    re.compile(r"@[\w.\-]+"),
    # Emoji shortcodes (:smile:, :rocket:)
    re.compile(r":[a-zA-Z0-9_\-+]+:"),
    # HTML/XML tags (<div class="test">, <br/>)
    re.compile(r"<[a-zA-Z\/][^>]*>"),
]


def get_protected_spans(text: str) -> list[tuple[int, int]]:
    """Return all (start, end) index tuples of protected segments in text.

    Spans are non-overlapping and sorted by start index.
    """
    spans: list[tuple[int, int]] = []

    for pattern in PROTECTED_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            # Verify this match does not overlap with an already captured span
            overlaps = any(
                not (end <= existing_start or start >= existing_end)
                for existing_start, existing_end in spans
            )
            if not overlaps:
                spans.append((start, end))

    spans.sort(key=lambda s: s[0])
    return spans


def is_span_protected(span: tuple[int, int], protected_spans: list[tuple[int, int]]) -> bool:
    """Return True if any part of span falls inside a protected range."""
    start, end = span
    for p_start, p_end in protected_spans:
        if not (end <= p_start or start >= p_end):
            return True
    return False


def mask_protected(text: str) -> tuple[str, dict[str, str]]:
    """Replace protected content with neutral placeholder tokens.

    Returns:
        (masked_text, placeholders_dict) where placeholders_dict maps
        placeholder keys back to their original raw strings.
    """
    spans = get_protected_spans(text)
    if not spans:
        return text, {}

    placeholders: dict[str, str] = {}
    pieces: list[str] = []
    last_idx = 0

    for i, (start, end) in enumerate(spans):
        # Text preceding the protected segment
        pieces.append(text[last_idx:start])
        raw_val = text[start:end]
        placeholder = f"__PG_TOKEN_{i}__"
        placeholders[placeholder] = raw_val
        pieces.append(placeholder)
        last_idx = end

    # Remaining tail text
    pieces.append(text[last_idx:])
    masked_text = "".join(pieces)
    return masked_text, placeholders


def unmask_text(text: str, placeholders: dict[str, str]) -> str:
    """Restore all placeholder tokens back to their original content."""
    if not placeholders:
        return text

    result = text
    for placeholder, original in placeholders.items():
        result = result.replace(placeholder, original)
    return result
