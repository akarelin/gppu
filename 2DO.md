# gppu — 2Do

## tui

### F12 debug panel for shell-script apps

Right now `gppu.tui.TUIApp` adds the F12 debug panel only to Python Textual
subclasses — shell-script apps (`.sh` entrypoints wrapped by the launcher)
have no way to surface debug output on demand.

Extend the F12 behaviour so it works for `.sh`-based apps too. Options to
consider:

- launcher intercepts the shell script's stderr, buffers it, and exposes
  an F12-triggered overlay
- standard environment hook: `GPPU_DEBUG_FIFO=/tmp/...` that the shell app
  can `echo >> $GPPU_DEBUG_FIFO`, launcher tails the fifo into its own
  in-memory buffer

Either way the UX should match the Python side: same key binding, same
scrollable read-only view, same "clear on close" semantics.
