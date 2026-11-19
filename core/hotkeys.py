"""Global hotkeys and keyboard input hooks using pynput.

Provides on-demand writing check hotkey (<ctrl>+<shift>+e), typing debounce
triggers, and text expansion snippet processing.
"""

from typing import Any, Callable, Optional
from pynput import keyboard


class HotkeyManager:
    """Manages global hotkey listeners with clean lifecycle management."""

    def __init__(self, callback: Callable[[], None], combo: str = "<ctrl>+<shift>+e"):
        self.callback = callback
        self.combo = combo
        self._listener: Optional[keyboard.GlobalHotKeys] = None

    def start(self) -> None:
        """Start listening for the registered global hotkey."""
        self.stop()
        try:
            self._listener = keyboard.GlobalHotKeys({self.combo: self.callback})
            self._listener.daemon = True
            self._listener.start()
        except Exception:
            self._listener = None

    def stop(self) -> None:
        """Stop and tear down the hotkey listener."""
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def is_alive(self) -> bool:
        return self._listener is not None and self._listener.is_alive()


class KeyboardActivityListener:
    """Listens for keystrokes to trigger the idle debouncer and notify typing activity."""

    def __init__(
        self,
        on_activity: Callable[[], None],
        on_keystroke: Optional[Callable[[Any], None]] = None,
    ):
        self.on_activity = on_activity
        self.on_keystroke = on_keystroke
        self._listener: Optional[keyboard.Listener] = None

    def start(self) -> None:
        self.stop()
        try:
            self._listener = keyboard.Listener(on_press=self._on_press)
            self._listener.daemon = True
            self._listener.start()
        except Exception:
            self._listener = None

    def _on_press(self, key) -> None:
        try:
            self.on_activity()
        except Exception:
            pass

        if self.on_keystroke:
            try:
                self.on_keystroke(key)
            except Exception:
                pass

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None


class SnippetExpander:
    """Expands text shortcuts (e.g. ';brb' -> 'Be right back') on typing match."""

    def __init__(self, snippets: dict[str, str], enabled: bool = False):
        self.snippets = snippets
        self.enabled = enabled
        self.buffer = ""
        self._controller = keyboard.Controller()

    def set_snippets(self, snippets: dict[str, str]) -> None:
        self.snippets = snippets

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def on_key(self, key) -> None:
        """Process a key event and expand snippet if buffer matches any trigger."""
        if not self.enabled or not self.snippets:
            return

        try:
            char = key.char if hasattr(key, "char") and key.char else ""
        except AttributeError:
            char = ""

        if not char:
            if key == keyboard.Key.space:
                char = " "
            elif key == keyboard.Key.enter:
                self.buffer = ""
                return
            else:
                return

        self.buffer += char
        if len(self.buffer) > 30:
            self.buffer = self.buffer[-30:]

        # Check triggers
        for trigger, expansion in self.snippets.items():
            if self.buffer.endswith(trigger):
                self.buffer = ""
                # Backspace the trigger characters
                for _ in range(len(trigger)):
                    self._controller.press(keyboard.Key.backspace)
                    self._controller.release(keyboard.Key.backspace)
                # Type the expansion
                self._controller.type(expansion)
                break
