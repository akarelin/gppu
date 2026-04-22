"""Shared debug logging for TUI apps.

Two output modes, either/both:

1. **DebugSink** — a `Callable[[str], None]` that every background call path
   can be handed as an optional ``debug_log``.  Writes each line to:

   - an in-memory ring buffer (so a modal screen can page through it)
   - ``~/.cache/<app_name>/debug.log`` (so the user can
     ``tail -f`` from another terminal without interrupting the TUI)

   Both are always on; the file path is returned so the caller can surface
   it in a toast.  Use :func:`make_debug_sink` to build one.

2. **DebugScreen** — an opt-in modal that renders the in-memory buffer.
   Push it with ``app.push_screen(DebugScreen(sink))``.  Popping returns
   focus to the main screen.  Useful for quick inspection without leaving
   the terminal, but not a substitute for the ``tail -f`` file — when a
   modal is on screen it blocks the main log from scrolling.

3. **DebugMixin** — a :class:`TUIApp` mixin that wires both up and binds
   F12 to "dump to file + toast" (no modal) and Shift+F12 to "open modal".
   Apps that want neither default can override the bindings.

Design note: preservator's earlier "F12 opens modal" UX was rejected —
modal overlays hide the live log, which is exactly when the user most
wants to see it.  The mixin defaults to dump-to-file (non-intrusive); the
modal is still available on a chord but not the main keystroke.
"""

from __future__ import annotations

import collections
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable


DebugLogger = Callable[[str], None]


class DebugSink:
    """In-memory ring buffer + persistent file + callable interface.

    Instances are callable: ``sink('warning message')`` — passing an
    instance anywhere that accepts a ``DebugLogger`` Just Works.
    """

    def __init__(self, app_name: str, *,
                 capacity: int = 5000,
                 cache_root: str | None = None):
        """
        ``app_name`` — used to derive the default file path
        ``~/.cache/<app_name>/debug.log``.  Override with ``cache_root``.
        """
        cache_root = cache_root or os.path.expanduser(f'~/.cache/{app_name}')
        os.makedirs(cache_root, exist_ok=True)
        self.app_name = app_name
        self.path = os.path.join(cache_root, 'debug.log')
        self._buffer: collections.deque[str] = collections.deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._fh = None                     # lazy-open on first write
        self._header_written = False

    def __call__(self, msg: str) -> None:
        ts = datetime.now().strftime('%H:%M:%S')
        line = f'{ts} {msg}'
        with self._lock:
            self._buffer.append(line)
            if self._fh is None:
                self._fh = open(self.path, 'a', encoding='utf-8', errors='replace')
            if not self._header_written:
                self._fh.write(
                    f'\n--- run {datetime.now().isoformat(timespec="seconds")} '
                    f'[{self.app_name}] ---\n'
                )
                self._header_written = True
            self._fh.write(line + '\n')
            self._fh.flush()

    def tail(self, n: int = 100) -> list[str]:
        """Last ``n`` lines from the in-memory buffer."""
        with self._lock:
            if n >= len(self._buffer):
                return list(self._buffer)
            return list(self._buffer)[-n:]

    def dump(self) -> tuple[str, int]:
        """Return the (path, count) the file was written to — useful for
        toast messages like ``'47 warning(s) → ~/.cache/foo/debug.log'``.
        """
        with self._lock:
            return self.path, len(self._buffer)

    def close(self) -> None:
        with self._lock:
            if self._fh:
                self._fh.close()
                self._fh = None


def make_debug_sink(app_name: str, **kwargs) -> DebugSink:
    """Convenience — construct a :class:`DebugSink` bound to ``app_name``."""
    return DebugSink(app_name, **kwargs)


# ── Textual bits (optional — only needed if the app runs under Textual) ────

try:
    from textual.app import ComposeResult
    from textual.binding import Binding
    from textual.screen import Screen
    from textual.widgets import RichLog
    _TEXTUAL = True
except ImportError:
    _TEXTUAL = False


if _TEXTUAL:

    class DebugScreen(Screen):
        """Modal overlay that renders a :class:`DebugSink` buffer.

        Push with ``app.push_screen(DebugScreen(sink))``; pop with Esc or
        F12.  Use sparingly — modal hides the live log.
        """

        BINDINGS = [
            Binding('escape', 'dismiss', 'Back', show=False),
            Binding('f12',    'dismiss', 'Close', show=False),
            Binding('q',      'dismiss', 'Close', show=False),
        ]

        CSS = """
        DebugScreen {
            align: center middle;
        }
        #debug-panel {
            width: 90%;
            height: 90%;
            border: round $warning;
            padding: 1 2;
            background: $boost;
        }
        """

        def __init__(self, sink: DebugSink, tail: int = 500) -> None:
            super().__init__()
            self._sink = sink
            self._tail = tail

        def compose(self) -> ComposeResult:
            yield RichLog(id='debug-panel', markup=False, highlight=False)

        def on_mount(self) -> None:
            panel = self.query_one('#debug-panel', RichLog)
            panel.write(
                f'[debug] {self._sink.path}  '
                f'(tail {self._tail} of {len(self._sink.tail(10**9))})'
            )
            panel.write('')
            for line in self._sink.tail(self._tail):
                panel.write(line)

        def action_dismiss(self) -> None:
            self.app.pop_screen()


    class DebugMixin:
        """Mixin for :class:`gppu.tui.TUIApp` that wires up debug logging.

        Provides:

        - ``self.debug_sink`` — callable :class:`DebugSink` instance
        - ``self.debug_log(msg)`` — thread-safe alias for ``self.debug_sink(msg)``
        - F12 key → "dump buffer to file + toast with path" (no modal)
        - Shift+F12 → open :class:`DebugScreen` modal

        Apps opt in by:

            class MyApp(DebugMixin, TUIApp):
                DEBUG_APP_NAME = 'myapp'   # → ~/.cache/myapp/debug.log
        """

        DEBUG_APP_NAME: str = 'gppu'
        DEBUG_CAPACITY: int = 5000

        # Extend this in subclasses with Textual's BINDINGS + these
        DEBUG_BINDINGS = [
            Binding('f12',       'debug_toast',  'Debug → file', show=False),
            Binding('shift+f12', 'debug_modal',  'Debug panel',  show=False),
        ]

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.debug_sink: DebugSink = make_debug_sink(
                self.DEBUG_APP_NAME, capacity=self.DEBUG_CAPACITY,
            )

        def debug_log(self, msg: str) -> None:
            """Thread-safe — call from any worker.

            Use ``call_from_thread(self.debug_log, msg)`` if the underlying
            Textual driver requires main-thread access for widget updates,
            but ``DebugSink.__call__`` itself is fully thread-safe (it
            holds a lock around buffer + file writes).
            """
            self.debug_sink(msg)

        def action_debug_toast(self) -> None:
            path, count = self.debug_sink.dump()
            try:
                self.notify(f'debug ({count} lines) → {path}', timeout=5)
            except AttributeError:
                # Older Textual without notify — fall back to write to main log
                try:
                    self.bell()
                except Exception:
                    pass

        def action_debug_modal(self) -> None:
            self.push_screen(DebugScreen(self.debug_sink))

else:
    # Textual not installed — expose just the sink for CLI-only apps.
    DebugScreen = None  # type: ignore[assignment]
    DebugMixin = None   # type: ignore[assignment]
