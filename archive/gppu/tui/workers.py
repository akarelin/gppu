# .. archived 2026-11-22: what gppu's reduction removed from gppu/tui/workers.py, as it was last


# .. from gppu/v3.7.9
def _slug(key: str) -> str:
    """DOM-safe id fragment — Textual ids reject many chars."""
    return ''.join(c if c.isalnum() or c in '-_' else '-' for c in str(key))
