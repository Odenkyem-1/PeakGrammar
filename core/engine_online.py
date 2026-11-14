"""Online LLM engine for contextual text rewrites and tone shifts.

Connects to OpenAI-compatible endpoints (Groq, Gemini, OpenRouter) with
strict developer token masking, short timeout (default 6.0s), and automatic
failover to local offline Harper linting.
"""

import os
from typing import Any, Optional
import dotenv
from openai import OpenAI

from core.masking import mask_protected, unmask_text
from core.engine_offline import OfflineEngine

# Provider presets
DEFAULT_PROVIDERS: dict[str, dict[str, str]] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-1.5-flash",
    },
}

TONE_INSTRUCTIONS: dict[str, str] = {
    "Professional": "Rewrite professionally, clearly, and formally.",
    "Friendly": "Rewrite in a warm, polite, and friendly tone.",
    "Confident": "Rewrite with confidence, clarity, and authority.",
    "Concise": "Make it as concise and impactful as possible without losing any meaning.",
    "Academic": "Rewrite in a rigorous academic style with precise vocabulary and clear phrasing.",
}


class OnlineEngine:
    """OpenAI-compatible LLM client with timeouts, masking, and offline fallback."""

    def __init__(
        self,
        provider: str = "groq",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        offline_engine: Optional[OfflineEngine] = None,
    ):
        dotenv.load_dotenv()
        self.provider = (provider or os.getenv("LLM_PROVIDER", "groq")).lower()
        provider_cfg = DEFAULT_PROVIDERS.get(self.provider, DEFAULT_PROVIDERS["groq"])

        self.base_url = base_url if base_url is not None else os.getenv("LLM_BASE_URL", provider_cfg["base_url"])
        self.model = model if model is not None else os.getenv("LLM_MODEL", provider_cfg["model"])
        self.api_key = api_key if api_key is not None else os.getenv("LLM_API_KEY", "")
        self.offline_engine = offline_engine or OfflineEngine()

        self._client: Optional[OpenAI] = None
        self._init_client()

    def _init_client(self) -> None:
        """Instantiate the OpenAI client if an API key is present."""
        if self.api_key and self.api_key.strip():
            try:
                self._client = OpenAI(
                    base_url=self.base_url,
                    api_key=self.api_key.strip(),
                    timeout=6.0,
                    max_retries=1,
                )
            except Exception:
                self._client = None
        else:
            self._client = None

    def update_config(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        """Dynamically update client credentials and reinitialize."""
        if provider:
            self.provider = provider.lower()
            cfg = DEFAULT_PROVIDERS.get(self.provider, DEFAULT_PROVIDERS["groq"])
            self.base_url = cfg["base_url"]
            self.model = cfg["model"]
        if api_key is not None:
            self.api_key = api_key
        if model:
            self.model = model
        self._init_client()

    def is_configured(self) -> bool:
        """Return True if an API client has valid credentials initialized."""
        return self._client is not None and bool(self.api_key.strip())

    def rewrite(
        self,
        text: str,
        tone_or_instruction: str = "Professional",
        timeout: float = 6.0
    ) -> Optional[str]:
        """Rewrite input text using the configured LLM with developer protection.

        Returns:
            The rewritten string, or None if the request failed or timed out.
        """
        if not text or not text.strip() or not self.is_configured():
            return None

        # 1. Protect code blocks, backticks, URLs, and file paths with placeholders
        masked_text, placeholders = mask_protected(text)

        # 2. Determine prompt instruction
        instruction = TONE_INSTRUCTIONS.get(tone_or_instruction, tone_or_instruction)

        system_prompt = (
            "You are a lightweight, expert writing assistant. Return ONLY the revised text. "
            "Do not add conversational preamble, greetings, or explanations. "
            "Preserve all placeholder tokens (__PG_TOKEN_...__), markdown formatting, "
            "code blocks, URLs, and mentions exactly as they are."
        )

        try:
            assert self._client is not None
            # Calculate token allowance with minimum headroom
            max_tokens = max(512, min(4096, len(masked_text) * 4))

            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"{instruction}:\n\n{masked_text}"},
                ],
                temperature=0.2,
                max_tokens=max_tokens,
                timeout=timeout,
            )

            msg = resp.choices[0].message
            content = getattr(msg, "content", None)
            if not content or not content.strip():
                return None

            clean_text = content.strip()
            # Strip enclosing quotation marks if returned as a quote
            if clean_text.startswith('"') and clean_text.endswith('"') and len(clean_text) > 1:
                clean_text = clean_text[1:-1].strip()

            # 3. Restore protected tokens
            return unmask_text(clean_text, placeholders)

        except Exception:
            # Automatic graceful failover
            return None

    def get_suggestions(
        self,
        text: str,
        mode: str = "auto",
        tone: str = "Professional"
    ) -> list[dict[str, Any]]:
        """Unified suggestion dispatch with automatic offline failover.

        - 'offline': strictly uses Harper local linter.
        - 'online': attempts LLM rewrite; falls back to Harper on failure.
        - 'auto': returns Harper lints for real-time checking; online rewrites
                  are reserved for explicit on-demand user actions.
        """
        if mode == "offline":
            return self.offline_engine.lint(text)

        if mode == "online":
            rewritten = self.rewrite(text, tone_or_instruction=tone)
            if rewritten and rewritten.strip() != text.strip():
                return [{
                    "type": "rewrite",
                    "original": text,
                    "replacement": rewritten,
                    "message": f"LLM Rewrite ({tone})",
                    "suggestions": [rewritten],
                    "problem_text": text,
                    "span": (0, len(text)),
                    "applied": None,
                }]
            # Failover to Harper
            return self.offline_engine.lint(text)

        # 'auto' mode default: privacy-preserving offline linting
        return self.offline_engine.lint(text)
