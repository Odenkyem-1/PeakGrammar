"""Thread-safe idle debouncer for typing pause detection.

Prevents expensive per-keystroke text inspection by waiting for the user to
pause typing for a configurable duration (default: 600-800 ms).
"""

import threading
from typing import Callable, Optional


class IdleDebouncer:
    """Idle timer that invokes callback only after no activity occurs for delay_ms."""

    def __init__(self, callback: Callable[[], None], delay_ms: int = 700):
        self.callback = callback
        self.delay = delay_ms / 1000.0
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._is_running = True

    def set_delay(self, delay_ms: int) -> None:
        """Update the debouncing delay in milliseconds."""
        with self._lock:
            self.delay = max(100, delay_ms) / 1000.0

    def poke(self) -> None:
        """Signal user typing activity and reset the idle countdown."""
        with self._lock:
            if not self._is_running:
                return
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self) -> None:
        """Cancel any pending countdown."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def stop(self) -> None:
        """Stop the debouncer completely."""
        with self._lock:
            self._is_running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def _fire(self) -> None:
        """Internal callback invoked when the timer expires."""
        with self._lock:
            self._timer = None
        try:
            self.callback()
        except Exception:
            # Trapped so background thread never crashes unhandled
            pass
