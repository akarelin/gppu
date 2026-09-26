"""Background data-loading helpers for Textual apps.

The duplicated pattern across DA (``rich_tui.py:257``) and SessionManager
(``sm-tui.py:500-522``) looks like:

    @work(thread=True)
    def _load_xxx_bg(self):
        self.call_from_thread(self._set_status, 'Loading…')
        rows = fetch_fn()                       # blocking I/O
        self.call_from_thread(self._populate, rows)

    def _populate(self, rows):
        table = self.query_one('#xxx-table', DataTable)
        for r in rows:
            table.add_row(*row_to_cells(r), key=key_of(r))

This module reduces the five-lines-per-table to one call:

    from gppu.tui import LoaderMixin

    class MyApp(LoaderMixin, TUIApp):
        def on_mount(self):
            self.load_into_table(
                table_id='#sessions-table',
                fetch=lambda: api_get_paginated('/api/traces', max_pages=10),
                row_fn=lambda t: (
                    ('local', t['project'], t['date'], t['name']),
                    t['id'],             # key (optional)
                ),
                status_id='#status-bar',
                status_busy='Loading sessions…',
                status_done=lambda rows: f'✓ {len(rows)} loaded',
            )

Errors during fetch are emitted via ``gppu.Debug(...)`` (Python logging)
and surfaced to the user via ``status_id`` as ``Error: <e>``.

No decorator magic — uses Textual's ``self.run_worker(fn, thread=True)``
so ``LoaderMixin`` can live on any Textual ``App`` / ``Screen`` without
needing ``@work``.
"""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

from gppu import Debug


class LoaderMixin:
    """Mixin for Textual apps — adds ``load_into_table`` and ``load_async``.

    Requires a host class with Textual's ``query_one``, ``call_from_thread``,
    and ``run_worker`` (every ``App`` / ``Screen`` has these).  No other
    dependencies.
    """

    def load_into_table(
        self,
        *,
        table_id: str,
        fetch: Callable[[], Iterable],
        row_fn: Callable[[object], Sequence | tuple[Sequence, object]],
        status_id: str | None = None,
        status_busy: str = 'Loading…',
        status_done: str | Callable[[list], str] | None = None,
        clear_first: bool = True,
        on_done: Callable[[list], None] | None = None,
        name: str = 'loader',
    ) -> None:
        """Run ``fetch`` in a worker thread, populate a ``DataTable`` from it.

        ``row_fn`` returns either a ``Sequence`` of cell values (table key
        auto-assigned) or a ``(cells, key)`` tuple.  Keep this pure — it
        runs on the main thread during population.

        ``status_id`` + ``status_busy`` / ``status_done`` update a ``Static``
        before/after.  ``status_done`` may be a function of the fetched rows
        for counts like ``f'✓ {len(rows)} loaded'``.
        """
        from textual.widgets import DataTable, Static

        def _set(msg: str) -> None:
            if not status_id:
                return
            try:
                self.query_one(status_id, Static).update(msg)
            except Exception:
                pass

        def _populate(rows: list) -> None:
            try:
                table = self.query_one(table_id, DataTable)
            except Exception as e:
                Debug('loader[%s]: table %s missing — %s', name, table_id, e)
                return
            if clear_first:
                table.clear()
            for rec in rows:
                cells_and_key = row_fn(rec)
                if (isinstance(cells_and_key, tuple)
                        and len(cells_and_key) == 2
                        and isinstance(cells_and_key[0], (list, tuple))):
                    cells, key = cells_and_key
                    table.add_row(*cells, key=key)
                else:
                    table.add_row(*cells_and_key)
            if callable(status_done):
                _set(status_done(rows))
            elif status_done:
                _set(status_done)
            if on_done:
                try:
                    on_done(rows)
                except Exception as e:
                    Debug('loader[%s] on_done: %s', name, e)

        def _bg() -> None:
            self.call_from_thread(_set, status_busy)
            try:
                rows = list(fetch())
            except Exception as e:
                Debug('loader[%s] fetch failed: %s', name, e)
                self.call_from_thread(_set, f'Error: {e}')
                return
            self.call_from_thread(_populate, rows)

        self.run_worker(_bg, thread=True, exclusive=False, name=name)

    def load_async(
        self,
        *,
        fetch: Callable[[], object],
        on_done: Callable[[object], None],
        status_id: str | None = None,
        status_busy: str = 'Loading…',
        status_done: str | None = None,
        name: str = 'loader-async',
    ) -> None:
        """Thinner variant — no table, just "bg-fetch then callback".

        Use when you want the loader pattern but not the DataTable wiring
        (e.g. populating a RichLog, Tree, or custom widget).  The callback
        runs on the main thread.
        """
        from textual.widgets import Static

        def _set(msg: str) -> None:
            if not status_id:
                return
            try:
                self.query_one(status_id, Static).update(msg)
            except Exception:
                pass

        def _handle(result: object) -> None:
            try:
                on_done(result)
            except Exception as e:
                Debug('loader[%s] on_done: %s', name, e)
                _set(f'Error: {e}')
                return
            if status_done:
                _set(status_done)

        def _bg() -> None:
            self.call_from_thread(_set, status_busy)
            try:
                result = fetch()
            except Exception as e:
                Debug('loader[%s] fetch failed: %s', name, e)
                self.call_from_thread(_set, f'Error: {e}')
                return
            self.call_from_thread(_handle, result)

        self.run_worker(_bg, thread=True, exclusive=False, name=name)
