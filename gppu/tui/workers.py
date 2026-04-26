"""Multi-worker progress visualization for Textual apps.

A :class:`WorkerPool` is a vertical stack of :class:`WorkerRow` widgets —
one per concurrent task — plus an aggregate footer.  Each row shows:

    <spinner>  <state-glyph>  <label>  [<counters>  <detail>]

Lifecycle states come from :data:`gppu.tui.icons.STATE_GLYPHS`
(pending/queued/running/ok/fail/canceled/skipped) and control both the
per-row glyph and the spinner (spinner runs only while ``running``).

The pool is intended to be driven from a worker-orchestrator (e.g.
``concurrent.futures.ThreadPoolExecutor`` or a ``@work(thread=True)``
block) — the orchestrator calls :meth:`WorkerPool.mark` on the main
thread (or via ``app.call_from_thread``) to advance state.  No asyncio
required; the widget doesn't own scheduling.

Example (preservator-style host-parallel pull)::

    pool = WorkerPool(id='hosts', workers=[ws.name for ws in hosts])
    yield pool
    ...
    def on_pull_start(host): pool.mark(host, 'running', 'pulling')
    def on_pull_done(host, n): pool.mark(host, 'ok', f'pulled {n}')
    def on_pull_fail(host, e): pool.mark(host, 'fail', str(e)[:40])

The pool's footer auto-updates with ``N pending / M running / K ok /
L fail`` each time :meth:`mark` lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Static

from .icons import STATE_GLYPHS, glyph_rich
from .launcher import SpinnerIndicator


@dataclass
class WorkerState:
    """Logical state carried by one :class:`WorkerRow`."""
    key: str                       # stable identifier, e.g. host name
    label: str                     # rendered in the row — defaults to key
    state: str = 'pending'         # one of STATE_GLYPHS keys
    detail: str = ''               # free-text trailer ("pulled 1188")
    counters: dict[str, int] = field(default_factory=dict)   # optional numeric extras


class WorkerRow(Horizontal):
    """One row in a :class:`WorkerPool` — spinner + glyph + label + detail."""

    DEFAULT_CSS = """
    WorkerRow {
        height: 1;
        padding: 0 1;
    }
    WorkerRow .worker-spinner { width: 2; }
    WorkerRow .worker-glyph   { width: 2; }
    WorkerRow .worker-label   { width: 16; }
    WorkerRow .worker-detail  { width: 1fr; color: $text-muted; }
    """

    def __init__(self, state: WorkerState) -> None:
        super().__init__(id=f'worker-{_slug(state.key)}',
                         classes='worker-row')
        self.state = state

    def compose(self) -> ComposeResult:
        yield SpinnerIndicator(classes='worker-spinner')
        yield Static(glyph_rich(self.state.state), classes='worker-glyph')
        yield Static(self.state.label or self.state.key, classes='worker-label')
        yield Static(self.state.detail, classes='worker-detail')

    def on_mount(self) -> None:
        # Only spin when the row is actually in flight.
        if self.state.state == 'running':
            self.query_one(SpinnerIndicator).start()

    def refresh_row(self) -> None:
        """Re-render glyph/detail/spinner from self.state.  Call after
        mutating the state in-place (or via :meth:`WorkerPool.mark`)."""
        self.query_one('.worker-glyph', Static).update(
            glyph_rich(self.state.state)
        )
        self.query_one('.worker-detail', Static).update(self.state.detail)
        spinner = self.query_one(SpinnerIndicator)
        if self.state.state == 'running':
            spinner.start()
        else:
            spinner.stop()


class WorkerPool(Vertical):
    """Vertical stack of :class:`WorkerRow` + aggregate footer.

    ``workers`` is the list of keys to seed rows with.  Additional rows
    can be added later via :meth:`add_worker` — useful for dynamic pools
    where the set isn't known up front.
    """

    DEFAULT_CSS = """
    WorkerPool {
        height: auto;
        border: round $panel-lighten-1;
        padding: 0 1;
    }
    WorkerPool #pool-footer {
        color: $text-muted;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, *, workers: Iterable[str] = (),
                 labels: dict[str, str] | None = None,
                 id: str | None = None) -> None:
        super().__init__(id=id)
        labels = labels or {}
        self._states: dict[str, WorkerState] = {
            k: WorkerState(key=k, label=labels.get(k, k))
            for k in workers
        }

    def compose(self) -> ComposeResult:
        for st in self._states.values():
            yield WorkerRow(st)
        yield Static(self._footer_text(), id='pool-footer')

    # ── external API ───────────────────────────────────────────────────────

    def add_worker(self, key: str, label: str | None = None) -> None:
        """Add a new row after mount — e.g. when workers are discovered
        lazily.  No-op if ``key`` already present."""
        if key in self._states:
            return
        st = WorkerState(key=key, label=label or key)
        self._states[key] = st
        self.mount(WorkerRow(st), before='#pool-footer')
        self._refresh_footer()

    def mark(self, key: str, state: str, detail: str = '',
             counters: dict[str, int] | None = None) -> None:
        """Advance ``key``'s state; re-render row + footer.

        Call this from the main thread.  From a worker thread use
        ``app.call_from_thread(pool.mark, key, state, detail)``.
        """
        st = self._states.get(key)
        if st is None:
            # Unknown key — create silently rather than raise; keeps the
            # orchestrator tolerant of dynamic worker sets.
            self.add_worker(key)
            st = self._states[key]
        st.state = state
        st.detail = detail
        if counters:
            st.counters.update(counters)
        try:
            row = self.query_one(f'#worker-{_slug(key)}', WorkerRow)
            row.refresh_row()
        except Exception:
            pass
        self._refresh_footer()

    def get(self, key: str) -> WorkerState | None:
        """Read current state (e.g. for "did this host fail?" checks)."""
        return self._states.get(key)

    # ── internal ───────────────────────────────────────────────────────────

    def _refresh_footer(self) -> None:
        try:
            footer = self.query_one('#pool-footer', Static)
            footer.update(self._footer_text())
        except Exception:
            pass

    def _footer_text(self) -> str:
        if not self._states:
            return '[dim]no workers[/]'
        buckets: dict[str, int] = {}
        for st in self._states.values():
            buckets[st.state] = buckets.get(st.state, 0) + 1
        order = ('running', 'pending', 'queued', 'ok', 'fail',
                 'canceled', 'skipped')
        parts = []
        for key in order:
            n = buckets.get(key, 0)
            if n:
                parts.append(f'{glyph_rich(key)} {n} {key}')
        total = sum(buckets.values())
        return '  '.join(parts) + f'    [dim]({total} total)[/]'


def _slug(key: str) -> str:
    """DOM-safe id fragment — Textual ids reject many chars."""
    return ''.join(c if c.isalnum() or c in '-_' else '-' for c in str(key))
