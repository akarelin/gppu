# .. archived 2026-11-22: two SessionHandler helpers from gppu/fs/handlers.py that nothing called


class SessionHandler:
    @staticmethod
    def _own_type(message: Mapping[str, Any]) -> str | None:
        """The type a harness gives its message, or its role; None only where it gives neither."""
        value = message.get("type") or message.get("role")
        return value if isinstance(value, str) else None

    @staticmethod
    def _agy_session_folder(path: Path) -> bool:
        """Recognize an Agy UUID folder containing a transcript file."""

        return SESSION_UID.fullmatch(path.name) is not None and any(
            (path / ".system_generated" / "logs" / name).is_file()
            for name in ("transcript_full.jsonl", "transcript.jsonl")
        )
