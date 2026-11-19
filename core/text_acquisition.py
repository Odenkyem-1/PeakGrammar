"""Text acquisition layer via Windows UI Automation (UIA).

Inspects the focused control in any desktop application, enforces privacy
exclusion rules, and determines screen coordinates for UI overlay positioning.
"""

import os
from typing import Optional, NamedTuple
import win32api
import win32con
import win32process

from pywinauto import uia_defines
from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.uia_element_info import UIAElementInfo

# Processes where text acquisition must strictly fail closed for security and privacy
EXCLUDED_PROCESSES = {
    "windowsterminal.exe",
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "bash.exe",
    "mintty.exe",
    "idea64.exe",
    "pycharm64.exe",
    "code.exe",
    "devenv.exe",
    "sublime_text.exe",
    "keepass.exe",
    "bitwarden.exe",
    "1password.exe",
    "lastpass.exe",
    "enpass.exe",
}


class FocusedContext(NamedTuple):
    text: str
    app_name: str
    process_name: str
    bounding_rect: tuple[int, int, int, int]  # (left, top, right, bottom)
    wrapper: Optional[UIAWrapper] = None
    selected_text: Optional[str] = None
    is_selection: bool = False


def get_process_name(pid: int) -> str:
    """Return the executable basename for a given process ID."""
    if not pid or pid <= 0:
        return ""
    try:
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
            False,
            pid
        )
        exe_path = win32process.GetModuleFileNameEx(handle, 0)
        win32api.CloseHandle(handle)
        return os.path.basename(exe_path).lower()
    except Exception:
        return ""


def is_excluded(process_name: str, app_title: Optional[str] = None) -> bool:
    """Return True if the target application belongs to the exclusion list."""
    p_lower = (process_name or "").lower().strip()
    if not p_lower:
        # Unknown process -> fail closed
        return True

    if p_lower in EXCLUDED_PROCESSES:
        return True

    if app_title:
        title_lower = app_title.lower()
        if any(term in title_lower for term in ("keepass", "bitwarden", "1password", "password")):
            return True

    return False


def get_focused_context() -> Optional[FocusedContext]:
    """Inspect and return the text and metadata of the currently focused UI control.

    Returns None if:
    - No element is focused.
    - The control is a password field.
    - The process is on the exclusion list.
    - No readable text can be acquired.
    """
    try:
        iuia = uia_defines.IUIA()
        elem = iuia.get_focused_element()
        if not elem:
            return None

        # 1. Security Check: Password field -> fail closed immediately
        try:
            if getattr(elem, "CurrentIsPassword", 0) == 1:
                return None
        except Exception:
            pass

        info = UIAElementInfo(elem)
        pid = info.process_id or 0
        proc_name = get_process_name(pid)
        app_title = info.name or ""

        # 2. Security Check: Process exclusion list
        if is_excluded(proc_name, app_title):
            return None

        wrapper = UIAWrapper(info)

        # 3. Read text: Check for user-highlighted selection first, then ValuePattern, then TextPattern
        selected_text: Optional[str] = None
        selection_rect: Optional[tuple[int, int, int, int]] = None
        is_selection = False

        try:
            doc_sel = wrapper.iface_text.GetSelection()
            if doc_sel and len(doc_sel) > 0:
                st = doc_sel[0].GetText(-1)
                if st and st.strip():
                    selected_text = st.strip()
                    is_selection = True
                    try:
                        pts = doc_sel[0].GetBoundingRectangles()
                        if pts and len(pts) >= 4:
                            selection_rect = (int(pts[0]), int(pts[1]), int(pts[0] + pts[2]), int(pts[1] + pts[3]))
                    except Exception:
                        pass
        except Exception:
            pass

        text: Optional[str] = selected_text
        if text is None:
            try:
                text = wrapper.iface_value.CurrentValue
            except Exception:
                pass

        if text is None:
            try:
                doc = wrapper.iface_text.DocumentRange
                text = doc.GetText(-1)
            except Exception:
                pass

        if text is None:
            try:
                text = wrapper.window_text()
            except Exception:
                pass

        if text is None or not text.strip():
            return None

        # 4. Get bounding rectangle (prefer exact selection coordinates if user highlighted text)
        rect_tuple = (0, 0, 0, 0)
        if selection_rect is not None:
            rect_tuple = selection_rect
        else:
            try:
                r = wrapper.rectangle()
                rect_tuple = (r.left, r.top, r.right, r.bottom)
            except Exception:
                pass

        # Retrieve top level window title if element title is empty
        display_name = app_title
        try:
            top_parent = wrapper.top_level_parent()
            if top_parent:
                top_title = top_parent.window_text()
                if top_title:
                    display_name = top_title
        except Exception:
            pass

        return FocusedContext(
            text=text,
            app_name=display_name or proc_name,
            process_name=proc_name,
            bounding_rect=rect_tuple,
            wrapper=wrapper,
            selected_text=selected_text,
            is_selection=is_selection,
        )

    except Exception:
        return None


def calculate_caret_screen_position(bounding_rect: tuple[int, int, int, int], text_length: int) -> tuple[int, int]:
    """Calculate an approximate (x, y) screen position for the floating suggestion overlay."""
    left, top, right, bottom = bounding_rect
    width = max(0, right - left)

    # Offset x near caret, bounded by the control's right edge
    approx_offset = min(max(0, width - 260), max(0, text_length * 7))
    pos_x = left + approx_offset
    pos_y = bottom + 8  # 8px below the control

    return pos_x, pos_y
