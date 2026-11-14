"""Text application and write-back layer.

Applies corrected or rewritten text back to the host application using
UIA ValuePattern, simulated paste (which preserves host undo stacks),
or safe clipboard fallback.
"""

import time
from typing import Optional
import pyperclip
from pynput.keyboard import Controller, Key
from pywinauto.controls.uiawrapper import UIAWrapper


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the Windows clipboard."""
    try:
        pyperclip.copy(text)
        return True
    except Exception:
        return False


def apply_via_uia(wrapper: UIAWrapper, new_text: str) -> bool:
    """Attempt direct in-place update using UIA ValuePattern."""
    try:
        if hasattr(wrapper, "iface_value") and not wrapper.iface_value.CurrentIsReadOnly:
            wrapper.iface_value.SetValue(new_text)
            return True
    except Exception:
        pass
    return False


def apply_via_paste(new_text: str) -> bool:
    """Replace content by copying to clipboard and sending Ctrl+V.

    Preserves the host application's native undo buffer (e.g. Word, Docs, Notepad).
    """
    try:
        if not copy_to_clipboard(new_text):
            return False

        keyboard = Controller()
        # Small delay to ensure clipboard buffer is populated
        time.sleep(0.05)

        # Select all (Ctrl+A)
        with keyboard.pressed(Key.ctrl):
            keyboard.press("a")
            keyboard.release("a")

        time.sleep(0.02)

        # Paste (Ctrl+V)
        with keyboard.pressed(Key.ctrl):
            keyboard.press("v")
            keyboard.release("v")

        return True
    except Exception:
        return False


def apply_text(
    new_text: str,
    wrapper: Optional[UIAWrapper] = None,
    suggest_only: bool = False
) -> bool:
    """Apply new text to the focused application.

    Args:
        new_text: The corrected or rewritten text.
        wrapper: The UIA control wrapper, if already acquired.
        suggest_only: If True, copies to clipboard without modifying the active control.
    """
    if suggest_only:
        return copy_to_clipboard(new_text)

    # 1. Try UIA SetValue if wrapper is provided
    if wrapper is not None:
        if apply_via_uia(wrapper, new_text):
            return True

    # 2. Try simulated paste fallback (undo-friendly)
    if apply_via_paste(new_text):
        return True

    # 3. Final fallback: Leave in clipboard for manual paste
    return copy_to_clipboard(new_text)
