# .. archived 2026-11-22: what gppu's reduction removed from gppu/tui/launcher.py, as it was last


# .. from gppu/v3.7.9
def load_registry(app_dir: Path, launcher: App) -> dict[str, dict]:
    """Everything one launcher offers: the manifests named in the launcher's own ``apps:``, then the sidecars in every
    directory named in its ``utilities:``. Both are read relative to app_dir. This is what a launcher calls."""
    from .sidecar import load_sidecar_registry
    directories = [(app_dir / directory).resolve() for directory in launcher.my_list('utilities')]
    return load_app_registry(app_dir, launcher) | (load_sidecar_registry(*directories) if directories else {})


class TUIApp:
  # .. from fec31bb
  def __init__(self, **kw):
    AsyncApp.__init__(self, **kw)
    TextualApp.__init__(self)
    self._debug_lines: list[str] = []
    self._log_handler = _DebugLogHandler(self._debug_lines)
    self._log_handler.setLevel(logging.DEBUG)
    self._log_handler.addFilter(_EmptyMessageFilter())
    self._log_handler.setFormatter(_LogColorizer())
    logging.getLogger().addHandler(self._log_handler)
