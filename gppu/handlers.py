r"""Typed, caller-composed handlers for large file hierarchies.

A domain handler receives one :class:`pathlib.Path` and returns ``(stats,
typed_object)``. Statistics are derived from the complete typed object. Users
select behavior with normal multiple inheritance; this module constructs no
handler objects::

    class MyFiles(
        FileHandler,
        IgnoredHandler,
        MarkdownHandler,
        CSVHandler,
        LogHandler,
        FolderHandler,
    ):
        pass

    files = MyFiles(metadata={"source": "local"})

Every handler copies the optional metadata mapping supplied by its caller.
``Probe.metadata`` combines that mapping with metadata detected by the typed
object. Caller metadata wins when the same key exists in both mappings.

Default calls do not stop a hierarchy scan. A read failure is represented by
:class:`HandlerError`; a composed probe stores it on ``Probe.error`` and
``Record.errors``. Construct a handler with ``strict=True`` when an exception
and traceback are required. Cancellation and process-exit exceptions are not
captured.

Public I/O calls decorated with :func:`gppu.sync` return directly outside an
event loop and are awaitable inside one. Their ``*_sync`` methods are the
strict worker implementations. All local paths are resolved by
:func:`gppu.full_path`.

Archive members use the same :class:`Record` hierarchy as filesystem entries,
with the archive path in ``location``. Ignored folders remain visible but are
not descended into. ``GitHandler`` reads only local history and configuration;
it never fetches or contacts an upstream.
"""

from __future__ import annotations

import asyncio
import csv
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat as stat_module
import subprocess
import tarfile
import tempfile
import zipfile
from collections.abc import AsyncIterator, Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Literal, Protocol, TypeVar, runtime_checkable
from zoneinfo import ZoneInfo

import yaml

from .gppu import OSType, detect_os, full_path, sync

ObjectT = TypeVar("ObjectT")
StatsT = TypeVar("StatsT")
Span = tuple[datetime, datetime]
Signature = tuple[int, int, int]
Harness = Literal[
    "chatgpt",
    "cx",
    "claude",
    "cc",
    "gemini",
    "agy",
    "hermes",
    "openclaw",
    "manus",
]

TIME_KEYS = ("timestamp", "ts", "started_at", "session_start", "time", "created_at")
MODEL_KEYS = ("model", "modelId", "model_slug", "default_model_slug")
ID_KEYS = ("sessionId", "session_id", "id", "remoteSessionId")
ROLES = ("user", "assistant")
SNIFF = 8
UNITS = (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))
UNSAFE = '\\/:*?"<>|\r\n\t'
NAME_LIMIT = 254
FRONTMATTER_TIMEZONE = ZoneInfo("America/Los_Angeles")
PREAMBLE = ("# AGENTS.md instructions",)
# User-role text the harness or a tool generated (sessions-clean, list-sessions): matching text was not typed by a person.
NON_HUMAN = (
    re.compile(r"^\s*\*{0,2}you are a memory relevance compressor utility\b", re.I),
    re.compile(r"^\s*Apply the current project instructions to this scenario:", re.I),
    re.compile(
        r"^\s*</?(?:system-reminder|command-message|command-name|local-command-caveat|local-command-stdout|local-command-stderr|environment_context|recommended_plugins|turn_aborted|scheduled-task|ide_opened_file|ide_selection|bash-input|bash-stdout|bash-stderr|task-notification|subagent_notification|codex_delegation|codex_internal_context|user_shell_command|image)\b",
        re.I,
    ),
    # A slash command carrying no prompt of its own, mistypes included.
    re.compile(r"^\s*/\S*\s*$"),
    # The same command recorded without its slash.
    re.compile(r"^\s*(?:upgrade|login|exit|plugins|marketplace)\s*$", re.I),
    # An instruction file the harness prepends to the first turn.
    re.compile(r"^\s*#\s*AGENTS\.md instructions\b", re.I),
    # A probe that verifies a session's setup by demanding a fixed token back.
    re.compile(
        r"\b(?:reply|respond|output|answer)(?:\s+with)?(?:\s+the)?(?:\s+single)?"
        r"(?:\s+word)?\s+(?:exactly\s+)?[A-Z][A-Z0-9_]{2,}[.!]?\s*$",
        re.I | re.M,
    ),
    # The summary the harness writes in place of a turn when context runs out.
    re.compile(
        r"^\s*This session is being continued from a previous conversation\b", re.I
    ),
    # The harness reporting that a dispatched plan never started.
    re.compile(r"^\s*ultraplan(?:\s+terminated|:\s*session creation failed)\b", re.I),
    # The shell integration asking for a diagnosis of a failed command.
    re.compile(r"^\s*A command failed\. Diagnose the error\b", re.I),
    # A request relayed into a dispatched session, quoted rather than typed.
    re.compile(r"^\s*[Uu]ser['’]s request:"),
    # The harness marking a turn cut short, in place of anything typed.
    re.compile(r"^\s*\[Request interrupted by user\b"),
    # The link a hand-off from ChatGPT opens the session with.
    re.compile(r"^\s*Continuing from \[[^\]]*\]\(chatgpt-conversation://", re.I),
)
# The Chrome extension and the ChatGPT hand-off wrap a typed request in a block of page and conversation context;
# only what follows was typed. A realtime delegation carries the typed request inside <input>.
ENVELOPE = re.compile(r"\A.*?^##\s*My request for Codex:[^\S\n]*$", re.S | re.M)
REALTIME_INPUT = re.compile(
    r"<realtime_delegation>\s*<input>(.*?)</input>", re.I | re.S
)
PLACEHOLDER_TIMES = (
    (1601, 1, 1, 0, 0, 0),  # Windows FILETIME zero
    (1970, 1, 1, 0, 0, 0),  # Unix epoch zero
    (1980, 1, 1, 0, 0, 0),  # DOS zero: the archiver stored no time
    (1981, 1, 1, 1, 1, 2),  # the constant Android build tools stamp on every APK member
)
FUTURE_TOLERANCE = timedelta(days=1)

FILENAME_GMT_TIMES = re.compile(
    r"(?<![A-Za-z0-9])(\d{2}-\d{2}-\d{4},\s*\d{2}\.\d{2}\.\d{2})\s*GMT([+-]\d{1,2})(?!\d)",
    re.I,
)
FILENAME_SHORT_DATE_SPAN = re.compile(r"(?<![A-Za-z0-9])(\d{6})-(\d{6})(?![A-Za-z0-9])")
FILENAME_DATETIMES = (
    (re.compile(r"(?<![A-Za-z0-9])(\d{17})(?![A-Za-z0-9])"), "%Y%m%d%H%M%S%f"),
    (re.compile(r"(?<![A-Za-z0-9])(\d{14})(?![A-Za-z0-9])"), "%Y%m%d%H%M%S"),
    (re.compile(r"(?<![A-Za-z0-9])(\d{8}-\d{6})(?![A-Za-z0-9])"), "%Y%m%d-%H%M%S"),
    (
        re.compile(
            r"(?<![A-Za-z0-9])(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})(?![A-Za-z0-9])"
        ),
        "%Y-%m-%d-%H-%M-%S",
    ),
    (re.compile(r"(?<![A-Za-z0-9])(\d{6}\.\d{6})(?![A-Za-z0-9])"), "%y%m%d.%H%M%S"),
    (re.compile(r"(?<![A-Za-z0-9])(\d{6}-\d{4})(?![A-Za-z0-9])"), "%y%m%d-%H%M"),
)
FILENAME_EPOCHS = re.compile(r"(?<![A-Za-z0-9])([1-9]\d{9})(?![A-Za-z0-9])")
FILENAME_ISO_DATES = re.compile(r"(?<![A-Za-z0-9])(\d{4}-\d{2}-\d{2})(?![A-Za-z0-9])")
FILENAME_SHORT_DATES = re.compile(r"(?<![A-Za-z0-9])(\d{6})(?![A-Za-z0-9])")
FILENAME_DURATION = re.compile(r"(?:~|\()\s*(\d+)\s*([dhms])\)?", re.I)
LOG_TIMESTAMP = re.compile(
    r"^\s*[\[(]?(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
    r"(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
IGNORED_NAME_PATTERNS = (
    "*.tmp",
    "*.bak",
    "*.swp",
    "~$*",
    "Thumbs.db",
    ".DS_Store",
    "desktop.ini",
    "monero-gui-*",
)
IGNORED_FOLDER_PATTERNS = (
    ".git",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".idea",
    ".vscode",
    ".SynologyWorking Directory",
    ".SynologyWorkingDirectory",
    "$RECYCLE.BIN",
    "RECYCLE.BIN",
    "System Volume Information",
    "OneDriveTemp",
    "Cache",
    ".cache",
    "EL.now",
    "monero-gui-*",
)
WINDOWS_HIDDEN = 2
WINDOWS_SYSTEM = 4

HOMES: dict[Harness, tuple[str, ...]] = {
    "hermes": ("state.db",),
    "agy": ("antigravity_state.pbtxt", "jetski_state.pbtxt"),
}
SESSION_UID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
EXPORT_MEMBER = re.compile(r"conversations(?:-\d+)?\.json", re.I)


@dataclass(frozen=True)
class HandlerError:
    """A handler failure retained as data so a hierarchy scan can continue."""

    handler: str
    operation: str
    path: Path | PurePosixPath
    error_type: str
    message: str


class Handler:
    """Cooperative base for caller-composed domain handler mixins.

    ``metadata`` is copied, so later changes to the caller's dictionary do not
    change results. With the default ``strict=False``, public handler calls
    return ``(None, HandlerError)`` on a load failure and ``False`` on an
    identification failure. ``strict=True`` re-raises the original exception.
    Worker-facing ``identify_sync`` and ``call_sync`` implementations remain
    strict; :class:`FileHandler` captures their failures per record.
    """

    name: str

    def __init__(
        self,
        metadata: Mapping[str, Any] | None = None,
        *,
        strict: bool = False,
    ) -> None:
        """Copy caller metadata and set the public-call error policy."""

        super().__init__()
        self.metadata = dict(metadata) if metadata is not None else {}
        self.strict = strict

    def _error(
        self,
        path: Path | PurePosixPath,
        operation: str,
        error: Exception,
    ) -> HandlerError:
        """Describe one failed operation without retaining a traceback."""

        return HandlerError(
            handler=self.name,
            operation=operation,
            path=path,
            error_type=type(error).__name__,
            message=str(error),
        )

    def _safe_identify(
        self,
        path: Path,
        identify: Callable[[Path], bool],
    ) -> bool:
        """Run a strict recognizer under the configured public error policy."""

        try:
            return identify(path)
        except Exception:
            if self.strict:
                raise
            return False

    def _safe_call(
        self,
        path: Path,
        call: Callable[[Path], tuple[Any, Any]],
    ) -> tuple[Any | None, Any | HandlerError]:
        """Run a strict loader and represent its default failure as data."""

        try:
            return call(path)
        except Exception as error:
            if self.strict:
                raise
            return None, self._error(path, "load", error)

    def _safe_operation(
        self,
        path: Path | PurePosixPath,
        operation: str,
        call: Callable[..., Any],
        *arguments: Any,
    ) -> Any | HandlerError:
        """Run any public operation and return a typed error by default."""

        try:
            return call(*arguments)
        except Exception as error:
            if self.strict:
                raise
            return self._error(path, operation, error)

    def _probe_metadata(self, obj: Any) -> dict[str, Any]:
        """Combine copied caller metadata with metadata exposed by ``obj``."""

        metadata: dict[str, Any] = {}
        detected = getattr(obj, "metadata", None)
        if isinstance(detected, Mapping):
            metadata.update(detected)
        metadata.update(self.metadata)
        return metadata


@runtime_checkable
class _SyncHandler(Protocol[ObjectT, StatsT]):
    """Synchronous implementation used while a handler runs in a worker thread."""

    def identify_sync(self, path: Path) -> bool:
        """Recognize ``path`` without entering another event loop."""
        ...

    def call_sync(self, path: Path) -> tuple[StatsT, ObjectT]:
        """Load ``path`` without entering another event loop."""
        ...


@dataclass(frozen=True)
class Probe:
    """One named handler's result, contextual metadata, and optional error."""

    handler: str
    stats: Any | None
    obj: Any | None = field(repr=False, compare=False)
    metadata: dict[str, Any] = field(default_factory=dict)
    error: HandlerError | None = None


@dataclass(frozen=True)
class FileStats:
    """File count, folder count, byte count, and span for one hierarchy."""

    files: int
    folders: int
    bytes: int
    span: Span | None


@dataclass(frozen=True)
class Record:
    """One filesystem or archive entry and the handlers that matched it.

    ``path`` is absolute for a filesystem entry and archive-relative for an
    archive member. ``location`` identifies the containing archive when set.
    """

    path: Path | PurePosixPath
    is_folder: bool
    size: int
    modified_at: datetime | None
    handlers: tuple[str, ...]
    location: str | Path | None = None
    probes: tuple[Probe, ...] = ()
    stats: FileStats | None = None
    errors: tuple[HandlerError, ...] = ()

    @property
    def name(self) -> str:
        """Return the final path component, or the complete root path."""

        return self.path.name or str(self.path)

    @property
    def label(self) -> str:
        """Return the display name with a trailing slash for folders."""

        return self.name + ("/" if self.is_folder else "")

    @property
    def display_path(self) -> str:
        """Return a filesystem path or ``archive::member`` display path."""

        if self.location is None:
            return str(self.path)
        return f"{self.location}::{self.path.as_posix()}"

    @property
    def span(self) -> Span | None:
        """Return the derived hierarchy span when statistics are available."""

        return self.stats.span if self.stats is not None else None

    @property
    def metadata(self) -> dict[str, Any]:
        """Return serializable display metadata for this record."""

        value: dict[str, Any] = {
            "path": self.display_path,
            "type": "folder" if self.is_folder else "file",
            "size": self.size,
            "modified_at": self.modified_at,
            "handlers": self.handlers,
        }
        if self.location is not None:
            value["location"] = str(self.location)
        if self.stats is not None:
            value.update(
                {
                    "files": self.stats.files,
                    "folders": self.stats.folders,
                    "bytes": self.stats.bytes,
                    "span": self.stats.span,
                }
            )
        for probe in self.probes:
            if probe.metadata:
                value[probe.handler] = probe.metadata
        if self.errors:
            value["errors"] = tuple(
                {
                    "handler": error.handler,
                    "operation": error.operation,
                    "error_type": error.error_type,
                    "message": error.message,
                }
                for error in self.errors
            )
        return value


@dataclass
class _FolderFrame:
    """Incremental statistics for one folder currently being traversed."""

    record: Record
    index: int | None
    files: int = 0
    folders: int = 0
    bytes: int = 0
    span: Span | None = None

    def add(self, child: Record) -> None:
        """Accumulate one completed direct child record."""

        if child.stats is None:
            return
        self.files += child.stats.files
        self.folders += child.stats.folders + int(child.is_folder)
        self.bytes += child.stats.bytes
        if child.stats.span is not None:
            self.span = (
                child.stats.span
                if self.span is None
                else (
                    min(self.span[0], child.stats.span[0]),
                    max(self.span[1], child.stats.span[1]),
                )
            )


class FolderHandler(Handler):
    """Identify a physical directory as a folder object.

    A supported folder is an existing local directory that is not a symbolic
    link. The typed object is its resolved :class:`Path`; its own statistics
    are empty because recursive navigation and aggregation belong to
    :class:`FileHandler`.
    """

    name = "folder"

    @sync
    async def identify(self, path: Path) -> bool:
        """Return whether ``path`` is a directory in either call mode."""

        return await asyncio.to_thread(self._safe_identify, path, self.identify_sync)

    def identify_sync(self, path: Path) -> bool:
        """Return whether ``path`` is a non-symlink directory."""

        path = full_path(path)
        return path.is_dir() and not path.is_symlink()

    @sync
    async def __call__(
        self,
        path: Path,
    ) -> tuple[FileStats | None, Path | HandlerError]:
        """Return folder statistics and its resolved path in either call mode."""

        return await asyncio.to_thread(self._safe_call, path, self.call_sync)

    def call_sync(self, path: Path) -> tuple[FileStats, Path]:
        """Return empty aggregate statistics and the resolved folder path."""

        path = full_path(path)
        if not self.identify_sync(path):
            raise ValueError(f"{path}: folder is not identifiable")
        return FileStats(0, 0, 0, None), path


@dataclass(frozen=True)
class IgnoredPath:
    """A visible ignored file or a visible folder that must not be descended."""

    path: Path | PurePosixPath
    reason: str
    no_descent: bool

    @property
    def metadata(self) -> dict[str, Any]:
        """Return the canonical classification and the matched rule."""

        return {
            "classification": "Ignored",
            "reason": self.reason,
            "no_descent": self.no_descent,
        }


class IgnoredHandler(Handler):
    """Identify ignored names and no-descent folder boundaries.

    The native rules are ported from the active FileIndexer configuration and
    TextLake traversal. These case-sensitive file-or-folder patterns match:
    ``*.tmp``, ``*.bak``, ``*.swp``, ``~$*``, ``Thumbs.db``, ``.DS_Store``,
    ``desktop.ini``, and ``monero-gui-*``.

    These case-sensitive folder patterns are visible but never descended:
    ``.git``, ``.svn``, ``__pycache__``, ``.venv``, ``venv``,
    ``node_modules``, ``.idea``, ``.vscode``, ``.SynologyWorking Directory``,
    ``.SynologyWorkingDirectory``, ``$RECYCLE.BIN``, ``RECYCLE.BIN``,
    ``System Volume Information``, ``OneDriveTemp``, ``Cache``, ``.cache``,
    ``EL.now``, and ``monero-gui-*``. Any other dot-prefixed folder and any
    Windows folder carrying ``FILE_ATTRIBUTE_HIDDEN`` or
    ``FILE_ATTRIBUTE_SYSTEM`` is also an ignored no-descent boundary.

    Matching entries remain :class:`Record` objects. This differs from a path
    exclusion, which would remove the entry from the hierarchy entirely.
    Archive-member folders use the name and dot-prefix rules because archive
    listings do not expose Windows filesystem attributes.
    """

    name = "ignored"
    name_patterns = IGNORED_NAME_PATTERNS
    folder_patterns = IGNORED_FOLDER_PATTERNS

    @sync
    async def identify(self, path: Path) -> bool:
        """Recognize an ignored path synchronously or asynchronously."""

        return await asyncio.to_thread(self._safe_identify, path, self.identify_sync)

    def identify_sync(self, path: Path) -> bool:
        """Return whether a physical file or folder matches an ignored rule."""

        return self.reason(full_path(path)) is not None

    @sync
    async def __call__(
        self,
        path: Path,
    ) -> tuple[FileStats | None, IgnoredPath | HandlerError]:
        """Return ignored-path metadata synchronously or asynchronously."""

        return await asyncio.to_thread(self._safe_call, path, self.call_sync)

    def call_sync(self, path: Path) -> tuple[FileStats, IgnoredPath]:
        """Return the matched rule and zero descent statistics for ``path``."""

        path = full_path(path)
        reason = self.reason(path)
        if reason is None:
            raise ValueError(f"{path}: ignored path is not identifiable")
        is_folder = path.is_dir() and not path.is_symlink()
        size = 0 if is_folder else path.stat().st_size
        ignored = IgnoredPath(path, reason, is_folder)
        return FileStats(0 if is_folder else 1, 0, size, None), ignored

    @classmethod
    def reason(cls, path: Path) -> str | None:
        """Return the first active rule matching a physical path."""

        is_folder = path.is_dir() and not path.is_symlink()
        if not is_folder and not path.is_file():
            return None
        if pattern := cls.match(path.name, cls.name_patterns):
            return f"name:{pattern}"
        if not is_folder:
            return None
        if pattern := cls.match(path.name, cls.folder_patterns):
            return f"folder:{pattern}"
        if path.name.startswith("."):
            return "folder:dot-prefix"
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
        if attributes & WINDOWS_HIDDEN:
            return "folder:FILE_ATTRIBUTE_HIDDEN"
        if attributes & WINDOWS_SYSTEM:
            return "folder:FILE_ATTRIBUTE_SYSTEM"
        return None

    @staticmethod
    def match(name: str, patterns: Sequence[str]) -> str | None:
        """Return the first case-sensitive FileIndexer pattern matching ``name``."""

        return next(
            (pattern for pattern in patterns if fnmatch.fnmatchcase(name, pattern)),
            None,
        )

    @classmethod
    def member_reason(cls, path: PurePosixPath, is_folder: bool) -> str | None:
        """Return the name-only ignored rule for one archive member."""

        if pattern := cls.match(path.name, cls.name_patterns):
            return f"name:{pattern}"
        if not is_folder:
            return None
        if pattern := cls.match(path.name, cls.folder_patterns):
            return f"folder:{pattern}"
        return "folder:dot-prefix" if path.name.startswith(".") else None


class FileHandler(Handler):
    """Public base for a caller-selected set of domain handler mixins.

    Put ``FileHandler`` first and domain handlers after it in a subclass. The
    domain handler order in that base list is the identification and probing
    order. ``handler_types`` is derived from the resulting MRO; users neither
    pass constructed handlers nor repeat a registry tuple.

    Identification records every matching handler. Probing loads their typed
    objects and derives recursive :class:`FileStats`. Handler and filesystem
    failures remain attached to their :class:`Record`, so another entry in a
    large tree can still be processed. An ``IgnoredHandler`` match on a folder
    retains that folder as a boundary and prevents descent into its contents.
    ``.git`` is visible during navigation but remains excluded from normalized
    copies.
    """

    name = "file"

    def __init__(
        self,
        metadata: Mapping[str, Any] | None = None,
        *,
        strict: bool = False,
    ) -> None:
        """Initialize mixed-in handlers, caller metadata, and hierarchy caches."""

        super().__init__(metadata, strict=strict)
        self.handler_types = self._handler_types()
        names = [handler.name for handler in self.handler_types]
        if len(names) != len(set(names)):
            raise ValueError("handler names must be unique")
        self.configured = self.handler_types
        self._identified: dict[
            Path,
            tuple[Signature, tuple[str, ...], tuple[HandlerError, ...]],
        ] = {}
        self._probed: dict[Path, tuple[Signature, tuple[Probe, ...]]] = {}
        self._children: dict[Path, tuple[Signature, tuple[Path, ...]]] = {}
        self._walk_errors: dict[Path, HandlerError] = {}

    def _handler_types(self) -> tuple[type[Handler], ...]:
        """Return the most-specific named handler classes in composition order."""

        selected: list[type[Handler]] = []
        names: set[str] = set()
        for handler in type(self).__mro__[1:]:
            if handler in (FileHandler, Handler, _LLMExportHandler):
                continue
            if not issubclass(handler, Handler):
                continue
            name = getattr(handler, "name", None)
            if not isinstance(name, str) or name in names:
                continue
            selected.append(handler)
            names.add(name)
        return tuple(selected)

    @sync
    async def identify(
        self,
        path: Path,
        recursive: bool = True,
    ) -> list[Record] | HandlerError:
        """Identify a hierarchy synchronously or asynchronously.

        Return the root and, by default, all descendants without loading typed
        handler objects.
        """

        return await asyncio.to_thread(
            self._safe_operation,
            path,
            "identify",
            self.identify_sync,
            path,
            recursive,
        )

    def identify_sync(self, path: Path, recursive: bool = True) -> list[Record]:
        """Return metadata and matching handler names without probing objects."""

        root = self._walk_source(path)
        records = [root]
        entered: list[int] = []

        def enter(record: Record) -> bool:
            entered.append(len(records) - 1)
            return True

        def on_folder_done(record: Record) -> None:
            records[entered.pop()] = record

        if recursive and root.is_folder and "ignored" not in root.handlers:
            for record in self.walk_sync(
                root,
                enter=enter,
                on_folder_done=on_folder_done,
            ):
                records.append(record)
        records[0] = self._walk_completed(root)
        return records

    @sync
    async def probe(
        self,
        path: Path,
        recursive: bool = True,
    ) -> list[Record] | HandlerError:
        """Probe a hierarchy synchronously or asynchronously.

        Matching handlers are loaded and folder statistics are accumulated
        from their descendants.
        """

        return await asyncio.to_thread(
            self._safe_operation,
            path,
            "probe",
            self.probe_sync,
            path,
            recursive,
        )

    def probe_sync(self, path: Path, recursive: bool = True) -> list[Record]:
        """Probe matching handlers and derive recursive folder statistics."""

        _, records = self._probe_hierarchy(path, recursive, retain_records=True)
        return records

    def record(self, path: Path) -> Record:
        """Return one cached identification record or a record carrying failure."""

        path = full_path(path)
        try:
            stat = path.stat()
        except Exception as error:
            if self.strict:
                raise
            failure = self._error(path, "stat", error)
            self._walk_errors[path] = failure
            return Record(path, False, 0, None, (), errors=(failure,))
        signature = _signature(stat)
        cached = self._identified.get(path)
        if cached is None or cached[0] != signature:
            identified = tuple(
                (handler, *self._handler_identify(handler, path))
                for handler in self.handler_types
            )
            names = tuple(handler.name for handler, matched, _ in identified if matched)
            errors = tuple(error for _, _, error in identified if error is not None)
            self._identified[path] = signature, names, errors
            self._probed.pop(path, None)
        else:
            names = cached[1]
            errors = cached[2]
            if any(handler.name == "git" for handler in self.handler_types):
                git = next(
                    handler for handler in self.handler_types if handler.name == "git"
                )
                matched, git_error = self._handler_identify(git, path)
                names = tuple(
                    handler.name
                    for handler in self.handler_types
                    if (matched if handler.name == "git" else handler.name in names)
                )
                errors = tuple(error for error in errors if error.handler != "git")
                if git_error is not None:
                    errors += (git_error,)
                self._identified[path] = signature, names, errors
        is_folder = path.is_dir() and not path.is_symlink()
        walk_error = self._walk_errors.get(path)
        if walk_error is not None and walk_error not in errors:
            errors += (walk_error,)
        return Record(
            path=path,
            is_folder=is_folder,
            size=0 if is_folder else stat.st_size,
            modified_at=valid_time(datetime.fromtimestamp(stat.st_mtime, timezone.utc)),
            handlers=names,
            errors=errors,
        )

    def children(self, path: Path | Record) -> tuple[Record, ...]:
        """Return direct children, or an empty tuple after a retained read error."""

        current: Record | None = None
        if isinstance(path, Record):
            if path.location is not None:
                if not path.is_folder or not isinstance(path.location, Path):
                    return ()
                return self._archive_children(path.location, path.path)
            if "archive" in path.handlers:
                return self._archive_children(Path(path.path), PurePosixPath("."))
            if "ignored" in path.handlers:
                return ()
            current = path
            path = Path(path.path)
        path = full_path(path)
        if not path.is_dir() or path.is_symlink():
            return ()
        if current is None:
            current = self.record(path)
            if "ignored" in current.handlers:
                return ()
        try:
            signature = _signature(path.stat())
        except Exception as error:
            if self.strict:
                raise
            self._walk_errors[path] = self._error(path, "list", error)
            return ()
        cached = self._children.get(path)
        if cached is None or cached[0] != signature:
            try:
                paths = tuple(sorted(path.iterdir(), key=_display_order))
            except Exception as error:
                if self.strict:
                    raise
                self._walk_errors[path] = self._error(path, "list", error)
                return ()
            self._children[path] = (signature, paths)
        else:
            paths = cached[1]
        return tuple(
            record for child in paths if (record := self._child(child)) is not None
        )

    def _child(self, path: Path) -> Record | None:
        """Return one child, or ``None`` if it vanished after directory listing."""

        try:
            path.stat()
            return self.record(path)
        except Exception as error:
            if self.strict:
                raise
            self._walk_errors[path] = self._error(path, "stat", error)
            return None

    def _archive_children(
        self,
        archive: Path,
        parent: Path | PurePosixPath,
    ) -> tuple[Record, ...]:
        """Return direct archive members beneath ``parent``."""

        record = self._probe_record(full_path(archive))
        probe = next(
            (probe for probe in record.probes if probe.handler == "archive"), None
        )
        if probe is None or probe.error is not None or not isinstance(probe.obj, tuple):
            if self.strict:
                raise ValueError(f"{archive}: archive handler did not return records")
            return ()
        parent = PurePosixPath(parent.as_posix())
        return tuple(child for child in probe.obj if child.path.parent == parent)

    def _archive_records(
        self,
        archive: Path,
        records: tuple[Record, ...],
    ) -> tuple[Record, ...]:
        """Apply configured ignored rules to archive members and their descent."""

        ignored_handler = next(
            (handler for handler in self.handler_types if handler.name == "ignored"),
            None,
        )
        if ignored_handler is None:
            return records
        skipped: set[PurePosixPath] = set()
        selected: list[Record] = []
        for record in sorted(records, key=lambda item: len(item.path.parts)):
            if any(parent in skipped for parent in record.path.parents):
                continue
            reason = ignored_handler.member_reason(record.path, record.is_folder)
            if reason is not None:
                ignored = IgnoredPath(record.path, reason, record.is_folder)
                probe = Probe(
                    "ignored",
                    FileStats(0 if record.is_folder else 1, 0, record.size, None),
                    ignored,
                    metadata=self._probe_metadata(ignored),
                )
                record = replace(
                    record,
                    handlers=("ignored",),
                    probes=(probe,),
                )
                if record.is_folder:
                    skipped.add(record.path)
            selected.append(record)
        return _complete_archive_records(archive, selected)

    @sync
    async def load(self, path: Path) -> Any | HandlerError:
        """Load the first matching typed object synchronously or asynchronously."""

        return await asyncio.to_thread(
            self._safe_operation,
            path,
            "load",
            self.load_sync,
            path,
        )

    def load_sync(self, path: Path) -> Any:
        """Return the first matching typed object, or ``None`` when unrecognized."""

        result = self._probe_record(full_path(path))
        if not result.probes:
            return None
        probe = result.probes[0]
        return probe.error if probe.error is not None else probe.obj

    @sync
    async def normalize(
        self,
        source: Path,
        destination: Path | None = None,
        recursive: bool = True,
        exclude_handlers: Sequence[str] = (),
    ) -> Path | HandlerError:
        """Normalize a source in place or copy it to an exact destination.

        With no destination, the first matching handler that defines
        ``normalize_name`` supplies the new filename. With a destination, the
        source hierarchy is copied and ``.git`` is excluded.
        """

        return await asyncio.to_thread(
            self._safe_operation,
            source,
            "normalize",
            self.normalize_sync,
            source,
            destination,
            recursive,
            exclude_handlers,
        )

    def normalize_sync(
        self,
        source: Path,
        destination: Path | None = None,
        recursive: bool = True,
        exclude_handlers: Sequence[str] = (),
    ) -> Path | HandlerError:
        """Rename by handler naming or copy to an exact destination hierarchy."""

        source = full_path(source)
        if destination is None:
            result = self._probe_record(source)
            selected = next(
                (
                    (probe, handler)
                    for probe in result.probes
                    for handler in self.handler_types
                    if probe.handler == handler.name
                    and probe.error is None
                    and probe.handler not in exclude_handlers
                    and callable(getattr(handler, "normalize_name", None))
                ),
                None,
            )
            if selected is None:
                raise ValueError(f"{source}: no naming handler")
            probe, handler = selected
            destination = source.with_name(handler.normalize_name(self, probe.obj))
            if destination == source:
                return source
            if destination.exists():
                raise FileExistsError(destination)
            source.rename(destination)
        else:
            destination = full_path(destination)
            if destination.exists():
                raise FileExistsError(destination)
            if source.is_dir() and not source.is_symlink():
                destination.parent.mkdir(parents=True, exist_ok=True)
                if recursive:
                    shutil.copytree(
                        source, destination, ignore=shutil.ignore_patterns(".git")
                    )
                else:
                    destination.mkdir(parents=True)
                    for child in self.children(source):
                        target = destination / child.path.name
                        if child.is_folder:
                            target.mkdir()
                        else:
                            shutil.copy2(child.path, target)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        self.invalidate_sync(source)
        self.invalidate_sync(destination)
        return destination

    @sync
    async def archive_path(
        self,
        source: Path,
        destination: Path,
        name: str,
        extension: str,
        local_time: tzinfo,
    ) -> Path:
        """Build a dated archive destination synchronously or asynchronously."""

        return await asyncio.to_thread(
            self._safe_operation,
            source,
            "archive_path",
            self.archive_path_sync,
            source,
            destination,
            name,
            extension,
            local_time,
        )

    def archive_path_sync(
        self,
        source: Path,
        destination: Path,
        name: str,
        extension: str,
        local_time: tzinfo,
    ) -> Path:
        """Name an archive from the complete source hierarchy span."""

        root = self._probe_root_sync(source)
        if root.span is None:
            raise ValueError(f"{source}: hierarchy has no span")
        return full_path(destination) / ArchiveHandler.archive_name(
            root.span,
            name,
            extension,
            local_time,
        )

    @sync
    async def invalidate(self, path: Path | None = None) -> None | HandlerError:
        """Invalidate cached state synchronously or asynchronously."""

        selected = path if path is not None else PurePosixPath(".")
        return await asyncio.to_thread(
            self._safe_operation,
            selected,
            "invalidate",
            self.invalidate_sync,
            path,
        )

    def invalidate_sync(self, path: Path | None = None) -> None:
        """Discard one cached branch, or the complete hierarchy cache."""

        if path is None:
            self._identified.clear()
            self._probed.clear()
            self._children.clear()
            self._walk_errors.clear()
            for handler in self.handler_types:
                invalidate = handler.__dict__.get("invalidate")
                if invalidate is not None:
                    invalidate(self)
            return
        path = full_path(path)
        for cache in (self._identified, self._probed, self._children):
            for cached in tuple(cache):
                if cached == path or path in cached.parents:
                    cache.pop(cached, None)
        for cached in tuple(self._walk_errors):
            if cached == path or path in cached.parents:
                self._walk_errors.pop(cached, None)
        for handler in self.handler_types:
            invalidate = handler.__dict__.get("invalidate")
            if invalidate is not None:
                invalidate(self, path)

    def walk_sync(
        self,
        path: Path | Record,
        recursive: bool = True,
        enter: Callable[[Record], bool] | None = None,
        on_folder_done: Callable[[Record], None] | None = None,
    ) -> Iterator[Record]:
        """Yield descendants while reporting folder traversal boundaries.

        Direct children are yielded in display order. With ``recursive=True``,
        ``enter(record)`` decides whether each non-ignored folder is descended;
        a refused folder remains in the stream. ``on_folder_done(record)`` is
        called after an entered folder has been completely yielded, and only
        for folders that were entered. The starting path is not yielded and
        does not produce either callback.
        """

        _, children = self._walk_children(path)
        for child in children:
            yield child
            if (
                not recursive
                or not child.is_folder
                or "ignored" in child.handlers
                or (enter is not None and not enter(child))
            ):
                continue
            yield from self.walk_sync(
                child,
                recursive=True,
                enter=enter,
                on_folder_done=on_folder_done,
            )
            if on_folder_done is not None:
                on_folder_done(self._walk_completed(child))

    async def walk(
        self,
        path: Path | Record,
        recursive: bool = True,
        enter: Callable[[Record], bool] | None = None,
        on_folder_done: Callable[[Record], None] | None = None,
    ) -> AsyncIterator[Record]:
        """Asynchronously yield descendants with the ``walk_sync`` semantics.

        Filesystem identification and listing run in a worker thread once per
        visited folder. The callbacks run in the consuming event-loop thread.
        """

        _, children = await asyncio.to_thread(self._walk_children, path)
        for child in children:
            yield child
            if (
                not recursive
                or not child.is_folder
                or "ignored" in child.handlers
                or (enter is not None and not enter(child))
            ):
                continue
            async for found in self.walk(
                child,
                recursive=True,
                enter=enter,
                on_folder_done=on_folder_done,
            ):
                yield found
            if on_folder_done is not None:
                on_folder_done(self._walk_completed(child))

    def _walk_source(self, path: Path | Record) -> Record:
        """Return the starting record after clearing an earlier walk failure."""

        if isinstance(path, Record):
            if path.location is not None:
                return path
            physical = Path(path.path)
            self._walk_errors.pop(physical, None)
            return self._walk_completed(path)
        physical = full_path(path)
        self._walk_errors.pop(physical, None)
        return self.record(physical)

    def _walk_children(
        self,
        path: Path | Record,
    ) -> tuple[Record, tuple[Record, ...]]:
        """Prepare one traversal source and identify its direct children."""

        source = self._walk_source(path)
        return source, self.children(source)

    def _walk_completed(self, record: Record) -> Record:
        """Return ``record`` with only the current filesystem walk failure."""

        if record.location is not None:
            return record
        physical = Path(record.path)
        failure = self._walk_errors.get(physical)
        errors = tuple(
            error
            for error in record.errors
            if not (
                error.handler == self.name
                and error.operation in ("list", "stat")
                and error.path == physical
            )
        )
        if failure is not None:
            errors += (failure,)
        return record if errors == record.errors else replace(record, errors=errors)

    def _probe_hierarchy(
        self,
        path: Path,
        recursive: bool,
        *,
        retain_records: bool,
    ) -> tuple[Record, list[Record]]:
        """Probe a stream, retaining either all records or only its root."""

        source = self._walk_source(path)
        root = self._probe_record(source)
        root = replace(
            root,
            stats=(
                self._folder_stats(root, ())
                if root.is_folder
                else self._file_stats(root)
            ),
        )
        records = [root] if retain_records else []
        if not recursive or not root.is_folder or "ignored" in root.handlers:
            return root, records

        frames = [_FolderFrame(root, 0 if retain_records else None)]
        pending: Record | None = None

        def enter(record: Record) -> bool:
            if pending is None or pending.path != record.path:
                raise RuntimeError("walk yielded a folder without its probe record")
            frames.append(
                _FolderFrame(
                    pending,
                    len(records) - 1 if retain_records else None,
                )
            )
            return True

        def on_folder_done(record: Record) -> None:
            frame = frames.pop()
            completed = self._finish_folder(frame, record)
            if retain_records:
                if frame.index is None:
                    raise RuntimeError("retained folder has no record index")
                records[frame.index] = completed
            frames[-1].add(completed)

        for identified in self.walk_sync(
            source,
            enter=enter,
            on_folder_done=on_folder_done,
        ):
            probed = self._probe_record(identified)
            pending = replace(
                probed,
                stats=(
                    self._folder_stats(probed, ())
                    if probed.is_folder
                    else self._file_stats(probed)
                ),
            )
            if retain_records:
                records.append(pending)
            if not pending.is_folder or "ignored" in pending.handlers:
                frames[-1].add(pending)

        completed_root = self._finish_folder(
            frames.pop(),
            self._walk_completed(source),
        )
        if frames:
            raise RuntimeError("walk ended before every folder was completed")
        if retain_records:
            records[0] = completed_root
        return completed_root, records

    def _probe_root_sync(self, path: Path) -> Record:
        """Return one recursively aggregated root without retaining its stream."""

        root, _ = self._probe_hierarchy(path, True, retain_records=False)
        return root

    @staticmethod
    def _finish_folder(frame: _FolderFrame, walked: Record) -> Record:
        """Merge late traversal errors and finish one folder's statistics."""

        errors = tuple(
            error
            for error in frame.record.errors
            if not (
                error.handler == FileHandler.name
                and error.operation in ("list", "stat")
                and error.path == frame.record.path
            )
        )
        errors += tuple(error for error in walked.errors if error not in errors)
        record = replace(frame.record, errors=errors)
        return replace(
            record,
            stats=FileHandler._folder_stats_from(
                record,
                frame.files,
                frame.folders,
                frame.bytes,
                frame.span,
            ),
        )

    def _probe_record(self, path: Path | Record) -> Record:
        """Load each matching handler while retaining individual failures."""

        if isinstance(path, Record):
            if path.location is not None:
                raise ValueError(f"{path.display_path}: archive member is not physical")
            record = path
            path = full_path(Path(path.path))
        else:
            path = full_path(path)
            record = self.record(path)
        try:
            signature = _signature(path.stat())
        except Exception:
            return replace(record, stats=FileStats(0, 0, 0, None))
        cached = self._probed.get(path)
        if cached is None or cached[0] != signature or "git" in record.handlers:
            selected = {handler.name: handler for handler in self.handler_types}
            probes = tuple(
                self._handler_probe(selected[name], path) for name in record.handlers
            )
            self._probed[path] = (signature, probes)
        else:
            probes = cached[1]
        errors = record.errors + tuple(
            probe.error for probe in probes if probe.error is not None
        )
        return replace(record, probes=probes, errors=errors)

    def _handler_identify(
        self,
        handler: type[Handler],
        path: Path,
    ) -> tuple[bool, HandlerError | None]:
        """Call one recognizer and retain its failure without stopping the tree."""

        try:
            identify_sync = getattr(handler, "identify_sync", None)
            if identify_sync is not None:
                return identify_sync(self, path), None
            return handler.identify(self, path), None
        except Exception as error:
            if self.strict:
                raise
            return False, HandlerError(
                handler.name,
                "identify",
                path,
                type(error).__name__,
                str(error),
            )

    def _handler_probe(self, handler: type[Handler], path: Path) -> Probe:
        """Call one loader and return either its result or a typed error."""

        try:
            call_sync = getattr(handler, "call_sync", None)
            if call_sync is not None:
                stats, obj = call_sync(self, path)
            else:
                stats, obj = handler.__call__(self, path)
            if handler.name == "archive" and isinstance(obj, tuple):
                obj = self._archive_records(path, obj)
                stats = _archive_stats(obj)
            return Probe(
                handler.name,
                stats,
                obj,
                metadata=self._probe_metadata(obj),
            )
        except Exception as error:
            if self.strict:
                raise
            failure = HandlerError(
                handler.name,
                "load",
                path,
                type(error).__name__,
                str(error),
            )
            return Probe(
                handler.name,
                None,
                None,
                metadata=dict(self.metadata),
                error=failure,
            )

    @staticmethod
    def _file_stats(record: Record) -> FileStats:
        """Derive statistics for one file from probes, its name, and mtime."""

        spans = [span for probe in record.probes if (span := _stats_span(probe.stats))]
        span = _combine_spans(spans) or FileHandler._name_span(record.name)
        modified = (
            (record.modified_at, record.modified_at) if record.modified_at else None
        )
        return FileStats(1, 0, record.size, span or modified)

    @staticmethod
    def _folder_stats(record: Record, children: Sequence[Record]) -> FileStats:
        """Aggregate direct child statistics and the folder's own span evidence."""

        child_spans = [
            child.stats.span for child in children if child.stats and child.stats.span
        ]
        return FileHandler._folder_stats_from(
            record,
            sum(child.stats.files for child in children if child.stats),
            sum(
                child.stats.folders + int(child.is_folder)
                for child in children
                if child.stats
            ),
            sum(child.stats.bytes for child in children if child.stats),
            _combine_spans(child_spans),
        )

    @staticmethod
    def _folder_stats_from(
        record: Record,
        files: int,
        folders: int,
        size: int,
        child_span: Span | None,
    ) -> FileStats:
        """Combine incremental child totals with a folder's own span evidence."""

        git_spans = [
            span
            for probe in record.probes
            if probe.handler == "git" and (span := _stats_span(probe.stats))
        ]
        if git_spans:
            spans = git_spans
        else:
            spans = [
                span for probe in record.probes if (span := _stats_span(probe.stats))
            ]
            if named := FileHandler._name_span(record.name):
                spans.append(named)
            if child_span is not None:
                spans.append(child_span)
        modified = (
            (record.modified_at, record.modified_at) if record.modified_at else None
        )
        return FileStats(files, folders, size, _combine_spans(spans) or modified)

    @classmethod
    def _name_span(cls, name: str) -> Span | None:
        """Derive a span from supported dates, timestamps, epochs, and durations."""

        if match := FILENAME_SHORT_DATE_SPAN.search(name):
            dates = tuple(
                moment
                for value in match.groups()
                if (moment := cls._filename_time(value, "%y%m%d")) is not None
            )
            if len(dates) != 2:
                return None
            return cls._date_span(dates)

        times = cls._filename_times(name)
        if times:
            span = min(times), max(times)
            if len(times) == 1 and (duration := FILENAME_DURATION.search(name)):
                seconds = int(duration.group(1)) * next(
                    size for unit, size in UNITS if unit == duration.group(2).casefold()
                )
                if (
                    end := valid_time(span[0] + timedelta(seconds=seconds))
                ) is not None:
                    span = span[0], end
            return span

        dates = cls._filename_dates(name)
        if not dates:
            return None
        return cls._date_span(dates)

    @staticmethod
    def _date_span(dates: Sequence[datetime]) -> Span:
        """Inclusive span covering every representable instant of each date."""

        return min(dates), max(dates) + timedelta(days=1, microseconds=-1)

    @classmethod
    def _filename_times(cls, name: str) -> tuple[datetime, ...]:
        """Parse explicit datetimes or Unix epochs embedded in a filename."""

        if values := FILENAME_GMT_TIMES.findall(name):
            parsed: list[datetime] = []
            for value, offset in values:
                try:
                    zone = timezone(timedelta(hours=int(offset)))
                except ValueError:
                    continue
                if moment := cls._filename_time(value, "%m-%d-%Y, %H.%M.%S", zone):
                    parsed.append(moment)
            return tuple(parsed)

        for pattern, format_string in FILENAME_DATETIMES:
            if values := pattern.findall(name):
                parsed = tuple(
                    moment
                    for value in values
                    if (moment := cls._filename_time(value, format_string)) is not None
                )
                if parsed:
                    return parsed

        if values := FILENAME_EPOCHS.findall(name):
            return tuple(
                moment
                for value in values
                if (
                    moment := valid_time(
                        datetime.fromtimestamp(int(value), timezone.utc)
                    )
                )
                is not None
            )
        return ()

    @classmethod
    def _filename_dates(cls, name: str) -> tuple[datetime, ...]:
        """Parse date-only values embedded in a filename."""

        for pattern, format_string in (
            (FILENAME_ISO_DATES, "%Y-%m-%d"),
            (FILENAME_SHORT_DATES, "%y%m%d"),
        ):
            if values := pattern.findall(name):
                return tuple(
                    moment
                    for value in values
                    if (moment := cls._filename_time(value, format_string)) is not None
                )
        return ()

    @staticmethod
    def _filename_time(
        value: str,
        format_string: str,
        zone: tzinfo | None = None,
    ) -> datetime | None:
        """Parse and validate one filename timestamp."""

        try:
            parsed = datetime.strptime(value, format_string)
        except ValueError:
            return None
        parsed = (
            parsed.replace(tzinfo=zone) if zone is not None else parsed.astimezone()
        )
        return valid_time(parsed)


@dataclass(frozen=True)
class GitRepository:
    """Local repository identity and configured remote metadata."""

    root: Path
    metadata_path: Path
    upstream_remote: str | None
    upstream_url: str | None
    remotes: tuple[tuple[str, str], ...]

    @property
    def metadata(self) -> dict[str, Any]:
        """Return repository paths and URLs suitable for identity matching."""

        return {
            "root": str(self.root),
            "metadata_path": str(self.metadata_path),
            "upstream_remote": self.upstream_remote,
            "upstream_url": self.upstream_url,
            "remotes": dict(self.remotes),
        }


class GitHandler(Handler):
    """Identify tracked paths and derive spans from local Git history.

    Only commits reachable from the current local ``HEAD`` are read; no remote
    command or fetch is used. Repository and currently tracked file paths are
    recognized. A tracked folder's span also includes historical files beneath
    it that have since been deleted.

    The typed :class:`GitRepository` reads every ``remote.<name>.url`` from
    local Git configuration. ``upstream_remote`` is set only when the current
    symbolic branch has both ``branch.<name>.remote`` and
    ``branch.<name>.merge``. ``upstream_url`` is the matching configured remote
    URL. Both are ``None`` for detached ``HEAD`` or a branch without that pair.
    All configured remote URLs remain in ``remotes`` for deduplication.

    The repository map is cached until ``HEAD``, its loose ref, the index, the
    ``HEAD`` log, packed refs, or Git configuration changes.
    """

    name = "git"

    def __init__(
        self,
        metadata: Mapping[str, Any] | None = None,
        *,
        strict: bool = False,
    ) -> None:
        """Initialize metadata, error policy, and repository-history cache."""

        super().__init__(metadata, strict=strict)
        self._git_cache: dict[
            Path,
            tuple[tuple[Any, ...], frozenset[Path], dict[Path, Span]],
        ] = {}

    @sync
    async def identify(self, path: Path) -> bool:
        """Return whether ``path`` is tracked, synchronously or asynchronously."""

        return await asyncio.to_thread(self._safe_identify, path, self.identify_sync)

    def identify_sync(self, path: Path) -> bool:
        """Return whether ``path`` belongs to the current tracked-path map."""

        repository = self._repository(path)
        if repository is None:
            return False
        tracked, _ = self._history(*repository)
        return full_path(path) in tracked

    @sync
    async def __call__(
        self,
        path: Path,
    ) -> tuple[FileStats | None, GitRepository | HandlerError]:
        """Return local-history statistics and repository metadata."""

        return await asyncio.to_thread(self._safe_call, path, self.call_sync)

    def call_sync(self, path: Path) -> tuple[FileStats, GitRepository]:
        """Load local-history statistics and local Git remote configuration."""

        path = full_path(path)
        repository = self._repository(path)
        if repository is None:
            raise ValueError(f"{path}: Git repository is not identifiable")
        tracked, spans = self._history(*repository)
        if path not in tracked:
            raise ValueError(f"{path}: path is not Git-tracked")
        return (
            FileStats(0, 0, 0, spans.get(path)),
            self._repository_object(*repository),
        )

    def invalidate(self, path: Path | None = None) -> None:
        """Discard all Git maps or the map containing ``path``."""

        if path is None:
            self._git_cache.clear()
            return
        repository = self._repository(path)
        if repository is not None:
            self._git_cache.pop(repository[0], None)

    @classmethod
    def _repository(cls, path: Path) -> tuple[Path, Path] | None:
        """Return the nearest repository root and resolved Git metadata path."""

        path = full_path(path)
        start = path if path.is_dir() else path.parent
        for candidate in (start, *start.parents):
            if metadata := cls._metadata(candidate):
                return candidate, metadata
        return None

    def _history(
        self,
        root: Path,
        metadata: Path,
    ) -> tuple[frozenset[Path], dict[Path, Span]]:
        """Return the cached tracked paths and local commit spans for a repository."""

        state = self._state(metadata)
        cached = self._git_cache.get(root)
        if cached is not None and cached[0] == state:
            return cached[1], cached[2]

        names = self._git(root, "ls-files", "-z").split(b"\0")
        tracked: set[Path] = {root}
        for name in names:
            if not name:
                continue
            relative = self._relative(name)
            path = root.joinpath(*relative.parts)
            tracked.add(path)
            for parent in path.parents:
                tracked.add(parent)
                if parent == root:
                    break

        spans: dict[Path, Span] = {}
        moment: datetime | None = None
        history = self._git(
            root,
            "log",
            "--format=%x1e%cI",
            "--name-only",
            "-z",
            "--no-renames",
        )
        for token in history.split(b"\0"):
            if token.startswith(b"\x1e"):
                try:
                    parsed = datetime.fromisoformat(token[1:].decode("ascii"))
                except ValueError as error:
                    raise ValueError(f"{root}: invalid Git commit time") from error
                moment = valid_time(parsed)
                if moment is not None:
                    self._add_span(spans, root, moment)
                continue
            if moment is None:
                continue
            token = token.removeprefix(b"\n")
            if not token:
                continue
            path = root.joinpath(*self._relative(token).parts)
            if path in tracked:
                self._add_span(spans, path, moment)
            for parent in path.parents:
                if parent == root:
                    break
                if parent in tracked:
                    self._add_span(spans, parent, moment)

        frozen = frozenset(tracked)
        self._git_cache[root] = state, frozen, spans
        return frozen, spans

    @classmethod
    def _repository_object(cls, root: Path, metadata: Path) -> GitRepository:
        """Read repository remote identity from local Git configuration."""

        remotes: list[tuple[str, str]] = []
        configured = cls._git_optional(
            root,
            "config",
            "--get-regexp",
            r"^remote\..*\.url$",
        )
        if configured is not None:
            for line in configured.splitlines():
                key, separator, url = line.partition(" ")
                if not separator or not url:
                    continue
                remote = key.removeprefix("remote.").removesuffix(".url")
                remotes.append((remote, url))
        branch = cls._git_optional(root, "symbolic-ref", "--quiet", "--short", "HEAD")
        upstream_remote = None
        if branch is not None:
            remote = cls._git_optional(
                root,
                "config",
                "--get",
                f"branch.{branch}.remote",
            )
            merge = cls._git_optional(
                root,
                "config",
                "--get",
                f"branch.{branch}.merge",
            )
            if remote is not None and merge is not None:
                upstream_remote = remote
        upstream_url = next(
            (url for remote, url in remotes if remote == upstream_remote),
            None,
        )
        return GitRepository(
            root,
            metadata,
            upstream_remote,
            upstream_url,
            tuple(remotes),
        )

    @staticmethod
    def _git(root: Path, *arguments: str) -> bytes:
        """Run one read-only local Git command and return its raw stdout."""

        result = subprocess.run(
            ("git", "-C", str(root), *arguments),
            capture_output=True,
            check=False,
        )
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise ValueError(f"{root}: Git failed: {detail}")
        return result.stdout

    @staticmethod
    def _git_optional(root: Path, *arguments: str) -> str | None:
        """Return stripped local Git output, or ``None`` for an absent value."""

        result = subprocess.run(
            ("git", "-C", str(root), *arguments),
            capture_output=True,
            check=False,
        )
        if result.returncode:
            return None
        value = result.stdout.decode("utf-8", errors="surrogateescape").strip()
        return value or None

    @staticmethod
    def _relative(value: bytes) -> PurePosixPath:
        """Decode and validate one repository-relative path from Git output."""

        path = PurePosixPath(value.decode("utf-8"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe path in Git history: {path}")
        return path

    @staticmethod
    def _add_span(spans: dict[Path, Span], path: Path, moment: datetime) -> None:
        """Extend ``path`` to include one commit timestamp."""

        if span := spans.get(path):
            spans[path] = min(span[0], moment), max(span[1], moment)
        else:
            spans[path] = moment, moment

    @classmethod
    def _state(cls, metadata: Path) -> tuple[Any, ...]:
        """Return the Git metadata state that invalidates a cached history map."""

        common = metadata
        commondir = metadata / "commondir"
        if commondir.is_file():
            common = full_path(metadata / commondir.read_text(encoding="utf-8").strip())
        head_value = (metadata / "HEAD").read_text(encoding="utf-8").strip()
        ref_value: str | None = None
        if head_value.startswith("ref:"):
            ref = common / head_value.removeprefix("ref:").strip()
            if ref.is_file():
                ref_value = ref.read_text(encoding="utf-8").strip()
        signatures = tuple(
            (str(path), _signature(path.stat()))
            for path in (
                metadata / "index",
                metadata / "logs" / "HEAD",
                common / "config",
                common / "packed-refs",
            )
            if path.is_file()
        )
        return head_value, ref_value, signatures

    @staticmethod
    def _metadata(path: Path) -> Path | None:
        """Resolve a repository's directory or indirection-file ``.git`` marker."""

        if not path.is_dir() or path.is_symlink():
            return None
        marker = path / ".git"
        if marker.is_dir():
            return marker
        if not marker.is_file():
            return None
        try:
            target = marker.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return None
        prefix = "gitdir:"
        if not target.casefold().startswith(prefix):
            return None
        metadata = Path(target[len(prefix) :].strip())
        if not metadata.is_absolute():
            metadata = path / metadata
        metadata = full_path(metadata)
        return metadata if metadata.is_dir() else None


@dataclass(frozen=True)
class ArchiveContents:
    """One extraction pass over an archive, member by member.

    ``files`` is where each wanted member was written, ``digests`` the MD5 of
    every member the pass read, and ``errors`` one failure for each member that
    could not be read.
    """

    files: dict[PurePosixPath, Path]
    digests: dict[PurePosixPath, str]
    errors: tuple[HandlerError, ...] = ()


class ArchiveHandler(Handler):
    """Identify and load ZIP, RAR, and TAR.GZ member hierarchies.

    Identification first requires a case-insensitive ``.zip``, ``.rar``, or
    ``.tar.gz`` filename, then verifies only that format. ZIP uses
    :func:`zipfile.is_zipfile`, RAR accepts the RAR 4 or RAR 5 signature, and
    TAR.GZ requires the gzip signature plus a readable TAR structure. Each
    member is a :class:`Record` with a safe relative POSIX path and ``location``
    set to the physical archive. Absolute member paths and ``..`` components
    are errors. Missing parent folders are synthesized so archive traversal
    matches filesystem traversal.

    ZIP timestamps come from the central directory. TAR timestamps come from
    each member's Unix modification time. RAR name, type, size, and optional
    modified time come from the UTF-8 RARLAB technical listing. RAR uses the
    installed native ``rar`` or ``unrar`` command; no Python RAR implementation
    is used. Password-protected or otherwise unreadable archives produce a
    :class:`HandlerError` under the default error policy.
    """

    name = "archive"
    extensions = (".rar", ".tar.gz", ".zip")
    rar_signatures = (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")
    rar_timeout = 1800   # one RAR gets half an hour of the command; a longer one is an error, not a partial extraction

    @sync
    async def identify(self, path: Path) -> bool:
        """Recognize a supported archive synchronously or asynchronously."""

        return await asyncio.to_thread(self._safe_identify, path, self.identify_sync)

    def identify_sync(self, path: Path) -> bool:
        """Recognize a supported extension and its matching archive format."""

        path = full_path(path)
        name = path.name.casefold()
        extension = next(
            (
                extension
                for extension in ArchiveHandler.extensions
                if name.endswith(extension)
            ),
            None,
        )
        if extension is None or not path.is_file():
            return False
        if extension == ".zip":
            return zipfile.is_zipfile(path)
        if extension == ".rar":
            return self._is_rar(path)
        if extension == ".tar.gz":
            return self._is_tar_gz(path)
        return False

    @sync
    async def __call__(
        self,
        path: Path,
    ) -> tuple[FileStats | None, tuple[Record, ...] | HandlerError]:
        """Load archive statistics and member records in either call mode."""

        return await asyncio.to_thread(self._safe_call, path, self.call_sync)

    def call_sync(self, path: Path) -> tuple[FileStats, tuple[Record, ...]]:
        """Load archive statistics and member records without another event loop."""

        path = full_path(path)
        if zipfile.is_zipfile(path):
            records = self._zip_records(path)
        elif self._is_rar(path):
            records = self._rar_records(path)
        elif self._is_tar_gz(path):
            records = self._tar_records(path)
        else:
            raise ValueError(f"{path}: unsupported archive")
        return _archive_stats(records), records

    @sync
    async def extract(
        self,
        path: Path,
        destination: Path,
        members: Collection[PurePosixPath] | None = None,
    ) -> ArchiveContents | HandlerError:
        """Write archive members to a directory in either call mode."""

        return await asyncio.to_thread(
            self._safe_operation,
            path,
            "extract",
            self.extract_sync,
            path,
            destination,
            members,
        )

    def extract_sync(
        self,
        path: Path,
        destination: Path,
        members: Collection[PurePosixPath] | None = None,
    ) -> ArchiveContents:
        """Write ``members`` under ``destination`` and digest what was read.

        ``members`` is every file member by default. Every member is read,
        because the MD5 that read gives identifies content that is copied
        between archives, and because a RAR is stored solid: asking for one
        member decompresses everything before it, so the archive is extracted
        in one command instead of once per member. A ZIP and a TAR.GZ are read
        member by member and only the wanted ones are written. Folder members
        are never written. A member that cannot be read becomes an entry in
        :attr:`ArchiveContents.errors` and does not end the pass.

        Written names are flat and unique, so one destination holds members
        from any depth without creating the archive's folders.
        """

        path = full_path(path)
        destination.mkdir(parents=True, exist_ok=True)
        contents = ArchiveContents(files={}, digests={}, errors=())
        errors: list[HandlerError] = []
        wanted = None if members is None else set(members)
        if zipfile.is_zipfile(path):
            self._zip_extract(path, destination, wanted, contents, errors)
        elif self._is_rar(path):
            self._rar_extract(path, destination, wanted, contents, errors)
        elif self._is_tar_gz(path):
            self._tar_extract(path, destination, wanted, contents, errors)
        else:
            raise ValueError(f"{path}: unsupported archive")
        return replace(contents, errors=tuple(errors))

    def _read_member(
        self,
        member: PurePosixPath,
        source: BinaryIO,
        copy: Path | None,
        contents: ArchiveContents,
        errors: list[HandlerError],
    ) -> None:
        """Read one member once: its MD5, and a copy of it when one is wanted."""

        digest = hashlib.md5()
        try:
            with source, (open(copy, "wb") if copy else nullcontext()) as out:
                for chunk in iter(lambda: source.read(1 << 20), b""):
                    digest.update(chunk)
                    if out is not None:
                        out.write(chunk)
        except Exception as error:
            errors.append(self._error(member, "extract", error))
            return
        contents.digests[member] = digest.hexdigest()
        if copy is not None:
            contents.files[member] = copy

    @staticmethod
    def _copy_path(
        destination: Path,
        index: int,
        member: PurePosixPath,
        wanted: set[PurePosixPath] | None,
    ) -> Path | None:
        """Return the flat unique name a wanted member is written under."""

        if wanted is not None and member not in wanted:
            return None
        return destination / f"{index}_{member.name}"

    def _zip_extract(
        self,
        path: Path,
        destination: Path,
        wanted: set[PurePosixPath] | None,
        contents: ArchiveContents,
        errors: list[HandlerError],
    ) -> None:
        """Read a ZIP member by member, writing the wanted ones."""

        try:
            archive = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile) as error:
            raise ValueError(f"{path}: cannot read ZIP: {error}") from error
        with archive:
            for index, info in enumerate(archive.infolist()):
                if info.is_dir():
                    continue
                member = _record_path(info.filename)
                copy = self._copy_path(destination, index, member, wanted)
                try:
                    source = archive.open(info)
                except Exception as error:
                    errors.append(self._error(member, "extract", error))
                    continue
                self._read_member(member, source, copy, contents, errors)

    def _tar_extract(
        self,
        path: Path,
        destination: Path,
        wanted: set[PurePosixPath] | None,
        contents: ArchiveContents,
        errors: list[HandlerError],
    ) -> None:
        """Read a TAR.GZ in one sequential pass, writing the wanted members."""

        try:
            archive = tarfile.open(path, "r:*")
        except (OSError, tarfile.TarError) as error:
            raise ValueError(f"{path}: cannot read TAR.GZ: {error}") from error
        with archive:
            for index, info in enumerate(archive):
                if not info.isfile():
                    continue
                member = _record_path(info.name)
                copy = self._copy_path(destination, index, member, wanted)
                source = archive.extractfile(info)
                if source is None:
                    continue
                self._read_member(member, source, copy, contents, errors)

    def _rar_extract(
        self,
        path: Path,
        destination: Path,
        wanted: set[PurePosixPath] | None,
        contents: ArchiveContents,
        errors: list[HandlerError],
    ) -> None:
        """Extract a solid RAR in one command, then read what it wrote."""

        executable = self.rar_executable()
        try:
            subprocess.run(
                [
                    str(executable),
                    "x",
                    "-y",
                    "-inul",
                    "-p-",
                    str(path),
                    str(destination) + os.sep,
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=True,
                timeout=self.rar_timeout,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError(f"{path}: cannot extract RAR: {error}") from error
        for written in sorted(destination.rglob("*")):
            if not written.is_file():
                continue
            member = PurePosixPath(written.relative_to(destination).as_posix())
            try:
                source = written.open("rb")
            except OSError as error:
                errors.append(self._error(member, "extract", error))
                continue
            self._read_member(member, source, None, contents, errors)
            if wanted is None or member in wanted:
                contents.files[member] = written

    @classmethod
    def _is_rar(cls, path: Path) -> bool:
        """Return whether ``path`` starts with a RAR 4 or RAR 5 signature."""

        try:
            with path.open("rb") as stream:
                header = stream.read(max(map(len, cls.rar_signatures)))
        except OSError:
            return False
        return any(header.startswith(signature) for signature in cls.rar_signatures)

    @staticmethod
    def rar_executable() -> Path:
        """Return the installed RARLAB command used to list RAR archives.

        macOS and Debian installations expose ``rar`` or ``unrar`` through
        ``PATH``. Windows is checked the same way first, followed by the native
        WinRAR installation directories because its installer does not add the
        commands to ``PATH``. Absence is an error instead of a reduced parser.
        """

        for command in ("rar", "unrar"):
            if executable := shutil.which(command):
                return full_path(executable)

        if detect_os() == OSType.W11:
            roots = tuple(
                Path(os.environ[name])
                for name in ("ProgramFiles", "ProgramFiles(x86)")
                if name in os.environ
            )
            for executable in ("Rar.exe", "UnRAR.exe"):
                for root in roots:
                    candidate = root / "WinRAR" / executable
                    if candidate.is_file():
                        return full_path(candidate)

        raise FileNotFoundError(
            "RARLAB rar or unrar executable is required to read RAR archives"
        )

    @staticmethod
    def _is_tar_gz(path: Path) -> bool:
        """Return whether ``path`` has gzip bytes and a readable TAR structure."""

        try:
            with path.open("rb") as stream:
                compressed = stream.read(2) == b"\x1f\x8b"
        except OSError:
            return False
        return compressed and tarfile.is_tarfile(path)

    @classmethod
    def archive_name(
        cls,
        span: Span,
        name: str,
        extension: str,
        local_time: tzinfo,
    ) -> str:
        """Return the required end/start archive name for a hierarchy span."""

        extension = "." + extension.casefold().lstrip(".")
        if extension not in cls.extensions:
            raise ValueError(f"unsupported archive extension: {extension}")
        safe_name = " ".join(
            "".join(" " if char in UNSAFE else char for char in name).split()
        )
        if not safe_name:
            raise ValueError("archive name is empty")
        start, end = (moment.astimezone(local_time) for moment in span)
        return f"{end:%y%m%d}_end-{start:%y%m%d}_start_{safe_name}{extension}"

    @staticmethod
    def _zip_records(path: Path) -> tuple[Record, ...]:
        """Read ZIP metadata into a complete archive-member hierarchy."""

        try:
            with zipfile.ZipFile(path) as archive:
                return _complete_archive_records(
                    path,
                    tuple(
                        Record(
                            path=_record_path(info.filename),
                            is_folder=info.is_dir(),
                            size=info.file_size,
                            modified_at=_archive_time(info.date_time),
                            handlers=(),
                            location=path,
                        )
                        for info in archive.infolist()
                        if _record_path(info.filename) != PurePosixPath(".")
                    ),
                )
        except (OSError, zipfile.BadZipFile) as error:
            raise ValueError(f"{path}: cannot read ZIP: {error}") from error

    @classmethod
    def _rar_records(cls, path: Path) -> tuple[Record, ...]:
        """Read RAR metadata from the portable RARLAB technical listing."""

        executable = cls.rar_executable()
        try:
            completed = subprocess.run(
                [
                    str(executable),
                    "lt",
                    "-c-",
                    "-p-",
                    "-scf",
                    "-y",
                    str(path),
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
            )
        except OSError as error:
            raise ValueError(f"{path}: cannot run {executable}: {error}") from error

        try:
            output = completed.stdout.decode("utf-8")
            errors = completed.stderr.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"{path}: RAR command did not return UTF-8") from error
        if completed.returncode:
            detail = errors.strip() or output.strip()
            raise ValueError(
                f"{path}: RAR command exited with {completed.returncode}: {detail}"
            )

        entries: list[dict[str, str]] = []
        entry: dict[str, str] | None = None
        for line in output.splitlines():
            field = re.match(r"^\s*([^:]+):\s?(.*)$", line)
            if field is None:
                continue
            key, value = (part.strip() for part in field.groups())
            if key == "Name":
                if entry is not None:
                    entries.append(entry)
                entry = {}
            if entry is not None:
                entry[key] = value
        if entry is not None:
            entries.append(entry)

        try:
            records = tuple(cls._rar_record(path, entry) for entry in entries)
        except (KeyError, ValueError) as error:
            raise ValueError(
                f"{path}: invalid RAR technical listing: {error}"
            ) from error
        return _complete_archive_records(path, records)

    @staticmethod
    def _rar_record(path: Path, fields: Mapping[str, str]) -> Record:
        """Convert one RARLAB technical-listing entry into a member record."""

        member = _record_path(fields["Name"])
        is_folder = fields["Type"] == "Directory"
        size = 0 if is_folder else int(fields["Size"])
        modified = next(
            (
                value
                for key, value in fields.items()
                if key.casefold() in ("modified", "mtime")
            ),
            None,
        )
        modified_at = (
            _archive_time(datetime.fromisoformat(modified))
            if modified is not None
            else None
        )
        return Record(
            path=member,
            is_folder=is_folder,
            size=size,
            modified_at=modified_at,
            handlers=(),
            location=path,
        )

    @staticmethod
    def _tar_records(path: Path) -> tuple[Record, ...]:
        """Read TAR metadata into a complete archive-member hierarchy."""

        try:
            with tarfile.open(path, "r:*") as archive:
                return _complete_archive_records(
                    path,
                    tuple(
                        Record(
                            path=_record_path(info.name),
                            is_folder=info.isdir(),
                            size=info.size,
                            modified_at=_archive_time(info.mtime),
                            handlers=(),
                            location=path,
                        )
                        for info in archive.getmembers()
                        if _record_path(info.name) != PurePosixPath(".")
                    ),
                )
        except (OSError, tarfile.TarError) as error:
            raise ValueError(f"{path}: cannot read TAR.GZ: {error}") from error


class _FrontmatterLoader(yaml.SafeLoader):
    """Load safe YAML while retaining timestamp scalars as written."""


_FrontmatterLoader.yaml_implicit_resolvers = {
    first: [
        (tag, pattern)
        for tag, pattern in resolvers
        if tag != "tag:yaml.org,2002:timestamp"
    ]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


@dataclass(frozen=True)
class MarkdownFile:
    """A Markdown file and its complete YAML frontmatter mapping.

    ``title`` and ``name`` implement the declared ``title|name`` equivalence:
    each uses the supplied peer field and then the filename when its own field
    is absent. ``tags`` normalizes the standard YAML list to strings while the
    original value remains unchanged in ``frontmatter``. ``span`` is present
    only when both ``created`` and ``updated`` are valid date values.
    """

    path: Path
    frontmatter: dict[str, Any]

    @property
    def metadata(self) -> dict[str, Any]:
        """Return a copy of every source frontmatter key and value."""

        return dict(self.frontmatter)

    @property
    def title(self) -> str:
        """Return frontmatter ``title``, ``name``, or the filename stem."""

        value = self.frontmatter.get("title")
        if value is None:
            value = self.frontmatter.get("name")
        return self.path.stem if value is None else str(value)

    @property
    def name(self) -> str:
        """Return frontmatter ``name``, ``title``, or the filename stem."""

        value = self.frontmatter.get("name")
        if value is None:
            value = self.frontmatter.get("title")
        return self.path.stem if value is None else str(value)

    @property
    def tags(self) -> tuple[str, ...]:
        """Return frontmatter tags without splitting a scalar tag value."""

        value = self.frontmatter.get("tags")
        if value is None:
            return ()
        values = value if isinstance(value, list) else [value]
        return tuple(str(item) for item in values if item is not None)

    @property
    def span(self) -> Span | None:
        """Return the chronological ``created`` to ``updated`` span."""

        created = self._time(self.frontmatter.get("created"))
        updated = self._time(self.frontmatter.get("updated"))
        return (
            (min(created, updated), max(created, updated))
            if created is not None and updated is not None
            else None
        )

    @staticmethod
    def _time(value: Any) -> datetime | None:
        """Parse one frontmatter date in its offset or the project timezone."""

        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed = datetime(value.year, value.month, value.day)
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.strip())
            except ValueError:
                return None
        else:
            return None
        return (
            parsed
            if parsed.tzinfo is not None
            else parsed.replace(tzinfo=FRONTMATTER_TIMEZONE)
        )


class MarkdownHandler(Handler):
    """Identify Markdown files and read their complete YAML frontmatter.

    Supported input is a physical file whose suffix is ``.md`` ignoring case,
    decoded as UTF-8 with an optional BOM. Frontmatter exists only when the
    first decoded line strips to ``---`` and ends at a later line that strips
    to ``---``. The enclosed text must be an empty YAML document or a YAML
    mapping accepted by :class:`yaml.SafeLoader`. YAML timestamp scalars remain
    strings; every key and nested value remains in ``MarkdownFile.frontmatter``.
    The Markdown body is not parsed.

    ``title`` and ``name`` use their matching frontmatter field, then the peer
    field, then the filename stem. ``tags`` accepts a YAML list or one scalar
    and exposes a tuple of strings. ``span`` requires both ``created`` and
    ``updated`` values accepted by :meth:`datetime.fromisoformat`; a date-only
    value starts at midnight and a value without an offset uses
    ``America/Los_Angeles``. The earlier parsed value is the start and the later
    is the end.

    A missing frontmatter block is valid and produces an empty mapping. With
    the default error policy, malformed YAML, a non-mapping document, or an
    unclosed block returns ``(None, HandlerError)`` instead of stopping a tree.
    """

    name = "markdown"

    @sync
    async def identify(self, path: Path) -> bool:
        """Recognize a Markdown file synchronously or asynchronously."""

        return await asyncio.to_thread(self._safe_identify, path, self.identify_sync)

    def identify_sync(self, path: Path) -> bool:
        """Return whether ``path`` is a physical ``.md`` file."""

        path = full_path(path)
        return path.suffix.casefold() == ".md" and path.is_file()

    @sync
    async def __call__(
        self,
        path: Path,
    ) -> tuple[FileStats | None, MarkdownFile | HandlerError]:
        """Read a Markdown file synchronously or asynchronously."""

        return await asyncio.to_thread(self._safe_call, path, self.call_sync)

    def call_sync(self, path: Path) -> tuple[FileStats, MarkdownFile]:
        """Return statistics and a Markdown object with all frontmatter keys."""

        path = full_path(path)
        if not self.identify_sync(path):
            raise ValueError(f"{path}: Markdown file is not identifiable")
        markdown = MarkdownFile(path, self._frontmatter(path))
        return FileStats(1, 0, path.stat().st_size, markdown.span), markdown

    @staticmethod
    def _frontmatter(path: Path) -> dict[str, Any]:
        """Read the complete leading YAML mapping, or an empty mapping."""

        with path.open(encoding="utf-8-sig") as stream:
            if stream.readline().strip() != "---":
                return {}
            lines: list[str] = []
            for line in stream:
                if line.strip() == "---":
                    break
                lines.append(line)
            else:
                raise ValueError(f"{path}: YAML frontmatter has no closing ---")
        try:
            frontmatter = yaml.load("".join(lines), Loader=_FrontmatterLoader)
        except yaml.YAMLError as error:
            raise ValueError(f"{path}: invalid YAML frontmatter: {error}") from error
        if frontmatter is None:
            return {}
        if not isinstance(frontmatter, dict):
            raise ValueError(f"{path}: YAML frontmatter must be a mapping")
        return frontmatter


@dataclass(frozen=True)
class CSVFile:
    """A complete comma-separated table and timestamps found in time columns."""

    path: Path
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    timestamps: tuple[datetime, ...]

    @property
    def span(self) -> Span | None:
        """Return the earliest-to-latest valid timestamp cell."""

        return (min(self.timestamps), max(self.timestamps)) if self.timestamps else None


class CSVHandler(Handler):
    """Read comma-separated text and derive a span from named time columns.

    Supported input is a physical file whose suffix is ``.csv`` ignoring case,
    decoded as UTF-8 with an optional BOM. Python's strict :mod:`csv` reader is
    used with the ``excel`` dialect: comma delimiter, double-quote quoting,
    doubled embedded quotes, and either CRLF or LF records. The first record is
    the complete header and every later record is retained without type
    conversion. An empty file has an empty header and no rows.

    A header matches a time column case-insensitively after surrounding spaces
    are removed. The built-in names are ``timestamp``, ``ts``, ``started_at``,
    ``session_start``, ``time``, and ``created_at``. Values in those columns
    support ISO 8601 date or date-time spelling accepted by
    :meth:`datetime.fromisoformat`, including ``Z`` and numeric offsets, plus
    Unix seconds greater than 1,000,000,000 and Unix milliseconds greater than
    10,000,000,000. Offset-free values use ``America/Los_Angeles``. Invalid,
    placeholder, and future values do not contribute to the span.

    Add a column name or a :meth:`datetime.strptime` format in a subclass; the
    base handler remains unchanged::

        class BillingCSVHandler(CSVHandler):
            time_keys = (*CSVHandler.time_keys, "billed_at")
            time_formats = (*CSVHandler.time_formats, "%m/%d/%Y %H:%M")

    The subclass can then be one of the caller's ``FileHandler`` mixins. With
    the default error policy, invalid CSV or undecodable text returns ``(None,
    HandlerError)`` instead of stopping a tree.
    """

    name = "csv"
    time_keys = TIME_KEYS
    time_formats: tuple[str, ...] = ()

    @sync
    async def identify(self, path: Path) -> bool:
        """Recognize a CSV file synchronously or asynchronously."""

        return await asyncio.to_thread(self._safe_identify, path, self.identify_sync)

    def identify_sync(self, path: Path) -> bool:
        """Return whether ``path`` is a physical ``.csv`` file."""

        path = full_path(path)
        return path.suffix.casefold() == ".csv" and path.is_file()

    @sync
    async def __call__(
        self,
        path: Path,
    ) -> tuple[FileStats | None, CSVFile | HandlerError]:
        """Read a CSV file synchronously or asynchronously."""

        return await asyncio.to_thread(self._safe_call, path, self.call_sync)

    def call_sync(self, path: Path) -> tuple[FileStats, CSVFile]:
        """Return file statistics and the complete parsed CSV table."""

        path = full_path(path)
        if not self.identify_sync(path):
            raise ValueError(f"{path}: CSV file is not identifiable")
        try:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                records = tuple(tuple(row) for row in csv.reader(stream, strict=True))
        except csv.Error as error:
            raise ValueError(f"{path}: invalid CSV: {error}") from error
        header = records[0] if records else ()
        rows = records[1:]
        indexes = tuple(
            index
            for index, name in enumerate(header)
            if name.strip().casefold()
            in {time_key.casefold() for time_key in self.time_keys}
        )
        timestamps = tuple(
            timestamp
            for row in rows
            for index in indexes
            if index < len(row)
            and (timestamp := self._timestamp(row[index])) is not None
        )
        csv_file = CSVFile(path, header, rows, timestamps)
        return FileStats(1, 0, path.stat().st_size, csv_file.span), csv_file

    @classmethod
    def _timestamp(cls, value: str) -> datetime | None:
        """Parse one built-in or subclass-supplied CSV timestamp spelling."""

        value = value.strip()
        if not value:
            return None
        parsed: datetime | None = None
        try:
            number = float(value)
        except ValueError:
            number = 0
        if number > 1_000_000_000:
            seconds = number / 1000 if number > 10_000_000_000 else number
            try:
                parsed = datetime.fromtimestamp(seconds, timezone.utc)
            except (OSError, OverflowError, ValueError):
                return None
        else:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                for time_format in cls.time_formats:
                    try:
                        parsed = datetime.strptime(value, time_format)
                    except ValueError:
                        continue
                    break
        if parsed is None:
            return None
        localized = (
            parsed
            if parsed.tzinfo is not None
            else parsed.replace(tzinfo=FRONTMATTER_TIMEZONE)
        )
        return valid_time(localized)


@dataclass(frozen=True)
class LogFile:
    """A complete text log and the absolute timestamps found at row starts."""

    path: Path
    rows: tuple[str, ...]
    timestamps: tuple[datetime, ...]

    @property
    def span(self) -> Span | None:
        """Return the first-to-last recorded timestamp, if any rows have one."""

        return (min(self.timestamps), max(self.timestamps)) if self.timestamps else None


class LogHandler(Handler):
    """Identify ``.log`` files and derive spans from timestamped rows.

    Supported input is a physical file whose suffix is ``.log`` ignoring case,
    decoded as UTF-8 with an optional BOM. Every row is retained without its
    line ending. A timestamp must begin after optional whitespace and one
    optional ``[`` or ``(``. Its exact accepted shape is
    ``YYYY-MM-DD[T or space]HH:MM:SS``, an optional dot-or-comma fractional
    second, and optional ``Z``, ``+HH:MM``, ``-HH:MM``, ``+HHMM``, or ``-HHMM``
    offset. Text may follow immediately after that timestamp.

    Offset-free timestamps use ``America/Los_Angeles``. Invalid, placeholder,
    and future timestamps do not contribute. The span is the earliest through
    latest accepted row timestamp. A file with no accepted timestamp has no
    span. With the default error policy, undecodable text returns ``(None,
    HandlerError)`` instead of stopping a tree.
    """

    name = "log"

    @sync
    async def identify(self, path: Path) -> bool:
        """Recognize a log file synchronously or asynchronously."""

        return await asyncio.to_thread(self._safe_identify, path, self.identify_sync)

    def identify_sync(self, path: Path) -> bool:
        """Return whether ``path`` is a physical ``.log`` file."""

        path = full_path(path)
        return path.suffix.casefold() == ".log" and path.is_file()

    @sync
    async def __call__(
        self,
        path: Path,
    ) -> tuple[FileStats | None, LogFile | HandlerError]:
        """Read a log file synchronously or asynchronously."""

        return await asyncio.to_thread(self._safe_call, path, self.call_sync)

    def call_sync(self, path: Path) -> tuple[FileStats, LogFile]:
        """Return all log rows and statistics spanning timestamped rows."""

        path = full_path(path)
        if not self.identify_sync(path):
            raise ValueError(f"{path}: log file is not identifiable")
        rows = tuple(path.read_text(encoding="utf-8-sig").splitlines())
        timestamps = tuple(
            timestamp for row in rows if (timestamp := self._timestamp(row)) is not None
        )
        log = LogFile(path, rows, timestamps)
        return FileStats(1, 0, path.stat().st_size, log.span), log

    @staticmethod
    def _timestamp(row: str) -> datetime | None:
        """Parse an absolute ISO timestamp from the beginning of one row."""

        match = LOG_TIMESTAMP.match(row)
        if match is None:
            return None
        try:
            parsed = datetime.fromisoformat(match.group("timestamp"))
        except ValueError:
            return None
        localized = (
            parsed
            if parsed.tzinfo is not None
            else parsed.replace(tzinfo=FRONTMATTER_TIMEZONE)
        )
        return valid_time(localized)


@dataclass(frozen=True)
class EmailFile:
    """An email file with metadata derived only from its filename.

    ``timestamp``, ``subject``, and ``party`` are all ``None`` when the filename
    does not use the supported convention. ``collision`` is the optional final
    decimal suffix used to distinguish otherwise identical paths.
    """

    path: Path
    timestamp: datetime | None
    subject: str | None
    party: str | None
    collision: int | None

    @property
    def span(self) -> Span | None:
        """Return the filename timestamp as a one-instant span."""

        return (self.timestamp, self.timestamp) if self.timestamp is not None else None

    @property
    def metadata(self) -> dict[str, Any]:
        """Return only metadata present in the supported filename."""

        return {
            key: value
            for key, value in (
                ("timestamp", self.timestamp),
                ("subject", self.subject),
                ("party", self.party),
                ("collision", self.collision),
            )
            if value is not None
        }


class EmailHandler(Handler):
    """Identify email files and derive metadata from their filenames.

    Supported input is an existing physical file whose suffix is ``.msg`` or
    ``.eml`` ignoring case. The handler does not open or parse Outlook MSG,
    MIME headers, bodies, attachments, or embedded messages. Message parsing is
    explicitly represented by :meth:`parse_message` returning
    :data:`NotImplemented`.

    Filename metadata uses exactly
    ``YYMMDD.HHMMSS - subject - party[ - collision]`` before the extension.
    Separators are one space, hyphen, one space. The timestamp uses
    ``%y%m%d.%H%M%S`` and ``America/Los_Angeles``. The optional collision is a
    decimal integer. Splitting from the right allows the subject to contain the
    separator. A filename outside this convention remains a valid email file
    with no filename-derived fields or span.
    """

    name = "email"
    extensions = (".eml", ".msg")

    @sync
    async def identify(self, path: Path) -> bool:
        """Recognize an email file synchronously or asynchronously."""

        return await asyncio.to_thread(self._safe_identify, path, self.identify_sync)

    def identify_sync(self, path: Path) -> bool:
        """Return whether ``path`` is a physical MSG or EML file."""

        path = full_path(path)
        return path.suffix.casefold() in self.extensions and path.is_file()

    @sync
    async def __call__(
        self,
        path: Path,
    ) -> tuple[FileStats | None, EmailFile | HandlerError]:
        """Read filename metadata synchronously or asynchronously."""

        return await asyncio.to_thread(self._safe_call, path, self.call_sync)

    def call_sync(self, path: Path) -> tuple[FileStats, EmailFile]:
        """Return file statistics and metadata without parsing the message."""

        path = full_path(path)
        if not self.identify_sync(path):
            raise ValueError(f"{path}: email file is not identifiable")
        timestamp, subject, party, collision = self._filename(path)
        email = EmailFile(path, timestamp, subject, party, collision)
        return FileStats(1, 0, path.stat().st_size, email.span), email

    @staticmethod
    def parse_message(path: Path) -> Any:
        """Return ``NotImplemented``; email payload parsing is not implemented."""

        return NotImplemented

    @staticmethod
    def _filename(
        path: Path,
    ) -> tuple[datetime | None, str | None, str | None, int | None]:
        """Parse the supported timestamp, subject, party, and collision suffix."""

        timestamp_text, separator, remainder = path.stem.partition(" - ")
        if not separator:
            return None, None, None, None
        collision: int | None = None
        content, separator, final = remainder.rpartition(" - ")
        if not separator:
            return None, None, None, None
        if final.isdecimal():
            collision = int(final)
            content, separator, final = content.rpartition(" - ")
            if not separator:
                return None, None, None, None
        subject = content.strip()
        party = final.strip()
        if not subject or not party:
            return None, None, None, None
        try:
            timestamp = datetime.strptime(timestamp_text, "%y%m%d.%H%M%S").replace(
                tzinfo=FRONTMATTER_TIMEZONE
            )
        except ValueError:
            return None, None, None, None
        return valid_time(timestamp), subject, party, collision


CHROMIUM_MARKER = "History"
FIREFOX_MARKER = "places.sqlite"
CHROMIUM_BROWSERS = ("edge", "brave", "opera", "vivaldi", "chrome", "chromium")
SQLITE_HEADER = b"SQLite format 3\x00"
CHROMIUM_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class BrowserProfile:
    """One browser profile's history, bookmarks, and downloads, as counts and a span.

    ``family`` is ``chromium`` or ``firefox``. ``browser`` is the product read
    from the profile's own path, and ``profile`` is the folder holding the
    database. No URL, page title, or visited page is read or retained.
    """

    path: Path
    family: str
    browser: str
    profile: str
    history: int
    urls: int
    favorites: int
    downloads: int
    span: Span | None

    @property
    def metadata(self) -> dict[str, Any]:
        """Return the browser, the profile, and what each table holds."""

        return {
            "family": self.family,
            "browser": self.browser,
            "profile": self.profile,
            "history": self.history,
            "urls": self.urls,
            "favorites": self.favorites,
            "downloads": self.downloads,
        }


class BrowserHandler(Handler):
    """Identify a browser profile and count its history, bookmarks, and downloads.

    Supported input is a Chromium ``History`` database, a Firefox
    ``places.sqlite``, or a directory holding either. Both must start with the
    SQLite file header and carry that engine's tables: ``urls`` or ``visits``
    for Chromium, ``moz_places`` for Firefox. A directory is the profile, so
    identifying one answers for the database inside it.

    The database is copied with its ``-wal`` and ``-shm`` companions and opened
    read-only from the copy, so a running browser is neither locked nor read
    mid-write. Only counts and the earliest and latest times are read: visits,
    URLs, bookmarks, and downloads. No URL, page title, or search term is read
    or retained, and a Chromium profile's ``Bookmarks`` JSON contributes its
    bookmark count and ``date_added`` times only.

    Chromium times are microseconds from 1601-01-01 UTC and Firefox times are
    microseconds from the Unix epoch. Placeholder and future values do not
    contribute, so a profile with no usable time has no span. A file or folder
    that is not a browser profile is unrecognized rather than an error.
    """

    name = "browser-history"

    @sync
    async def identify(self, path: Path) -> bool:
        """Recognize a browser profile synchronously or asynchronously."""

        return await asyncio.to_thread(self._safe_identify, path, self.identify_sync)

    def identify_sync(self, path: Path) -> bool:
        """Return whether ``path`` is a profile database or a folder with one."""

        return self._database(full_path(path)) is not None

    @sync
    async def __call__(
        self,
        path: Path,
    ) -> tuple[FileStats | None, BrowserProfile | HandlerError]:
        """Read a browser profile synchronously or asynchronously."""

        return await asyncio.to_thread(self._safe_call, path, self.call_sync)

    def call_sync(self, path: Path) -> tuple[FileStats, BrowserProfile]:
        """Return profile statistics and the counts read from its database."""

        path = full_path(path)
        database = self._database(path)
        if database is None:
            raise ValueError(f"{path}: not a browser profile")
        profile = (
            self._chromium(database)
            if database.name == CHROMIUM_MARKER
            else self._firefox(database)
        )
        return FileStats(1, 0, database.stat().st_size, profile.span), profile

    @classmethod
    def _database(cls, path: Path) -> Path | None:
        """Return the profile database at or inside ``path``, if there is one."""

        if path.is_dir():
            return next(
                (
                    found
                    for marker in (CHROMIUM_MARKER, FIREFOX_MARKER)
                    if (found := cls._database(path / marker)) is not None
                ),
                None,
            )
        if path.name.casefold() not in (CHROMIUM_MARKER.casefold(), FIREFOX_MARKER):
            return None
        try:
            with path.open("rb") as stream:
                header = stream.read(len(SQLITE_HEADER))
        except OSError:
            return None
        return path if header == SQLITE_HEADER else None

    @staticmethod
    @contextmanager
    def _read_only(path: Path) -> Iterator[sqlite3.Connection]:
        """Open a copy of the database so a running browser is never locked."""

        with tempfile.TemporaryDirectory() as folder:
            copy = Path(folder) / path.name
            for suffix in ("", "-wal", "-shm"):
                companion = Path(str(path) + suffix)
                if companion.is_file():
                    shutil.copy2(companion, Path(str(copy) + suffix))
            connection = sqlite3.connect(f"file:{copy.as_posix()}?mode=ro", uri=True)
            try:
                yield connection
            finally:
                connection.close()

    @staticmethod
    def _columns(connection: sqlite3.Connection) -> dict[str, set[str]]:
        """Return every table in the database with its column names."""

        return {
            str(name): {
                str(column[1])
                for column in connection.execute(f'PRAGMA table_info("{name}")')
            }
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    @staticmethod
    def _counted(
        connection: sqlite3.Connection,
        query: str,
        moment: Callable[[Any], datetime | None],
        times: list[datetime],
    ) -> int:
        """Run one count/min/max query and keep the times it returned."""

        row = connection.execute(query).fetchone()
        if row is None:
            return 0
        times += [value for value in map(moment, row[1:]) if value is not None]
        return int(row[0] or 0)

    @staticmethod
    def _chromium_time(value: Any) -> datetime | None:
        """Convert microseconds from 1601-01-01 UTC into a recorded time."""

        try:
            return valid_time(CHROMIUM_EPOCH + timedelta(microseconds=int(value)))
        except (OverflowError, TypeError, ValueError):
            return None

    @staticmethod
    def _firefox_time(value: Any) -> datetime | None:
        """Convert microseconds from the Unix epoch into a recorded time."""

        try:
            return valid_time(
                datetime.fromtimestamp(int(value) / 1_000_000, timezone.utc)
            )
        except (OSError, OverflowError, TypeError, ValueError):
            return None

    @staticmethod
    def _browser(path: Path) -> str:
        """Name the Chromium product from the profile's own path."""

        value = str(path).casefold()
        return next((name for name in CHROMIUM_BROWSERS if name in value), "chromium")

    @classmethod
    def _chromium(cls, path: Path) -> BrowserProfile:
        """Read a Chromium profile's visits, URLs, downloads, and bookmarks."""

        times: list[datetime] = []
        history = urls = downloads = 0
        with cls._read_only(path) as connection:
            columns = cls._columns(connection)
            if "visits" in columns and "visit_time" in columns["visits"]:
                history = cls._counted(
                    connection,
                    "SELECT count(*), min(visit_time), max(visit_time) FROM visits",
                    cls._chromium_time,
                    times,
                )
            elif "urls" in columns and "last_visit_time" in columns["urls"]:
                history = cls._counted(
                    connection,
                    "SELECT count(*), min(last_visit_time), max(last_visit_time) "
                    "FROM urls WHERE last_visit_time IS NOT NULL",
                    cls._chromium_time,
                    times,
                )
            if "urls" in columns:
                urls = cls._counted(
                    connection,
                    "SELECT count(*) FROM urls",
                    cls._chromium_time,
                    times,
                )
            if "downloads" in columns:
                downloads = cls._counted(
                    connection,
                    "SELECT count(*), min(start_time), max(start_time) FROM downloads"
                    if "start_time" in columns["downloads"]
                    else "SELECT count(*) FROM downloads",
                    cls._chromium_time,
                    times,
                )
        favorites = cls._bookmarks(path.parent / "Bookmarks", times)
        return BrowserProfile(
            path=path,
            family="chromium",
            browser=cls._browser(path),
            profile=path.parent.name,
            history=history,
            urls=urls,
            favorites=favorites,
            downloads=downloads,
            span=(min(times), max(times)) if times else None,
        )

    @classmethod
    def _bookmarks(cls, path: Path, times: list[datetime]) -> int:
        """Count the bookmarks in a Chromium profile and keep their times."""

        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return 0
        if not isinstance(document, Mapping):
            return 0
        found = 0
        pending = list((document.get("roots") or {}).values())
        while pending:
            node = pending.pop()
            if not isinstance(node, Mapping):
                continue
            if node.get("type") == "url":
                found += 1
                if moment := cls._chromium_time(node.get("date_added")):
                    times.append(moment)
            children = node.get("children")
            if isinstance(children, list):
                pending += children
        return found

    @classmethod
    def _firefox(cls, path: Path) -> BrowserProfile:
        """Read a Firefox profile's visits, places, bookmarks, and downloads."""

        times: list[datetime] = []
        history = urls = favorites = downloads = 0
        with cls._read_only(path) as connection:
            columns = cls._columns(connection)
            if (
                "moz_historyvisits" in columns
                and "visit_date" in columns["moz_historyvisits"]
            ):
                history = cls._counted(
                    connection,
                    "SELECT count(*), min(visit_date), max(visit_date) "
                    "FROM moz_historyvisits",
                    cls._firefox_time,
                    times,
                )
            if "moz_places" in columns:
                urls = cls._counted(
                    connection,
                    "SELECT count(*) FROM moz_places",
                    cls._firefox_time,
                    times,
                )
            if "moz_bookmarks" in columns:
                favorites = cls._counted(
                    connection,
                    "SELECT count(*), min(dateAdded), max(dateAdded) "
                    "FROM moz_bookmarks WHERE type = 1"
                    if "dateAdded" in columns["moz_bookmarks"]
                    else "SELECT count(*) FROM moz_bookmarks WHERE type = 1",
                    cls._firefox_time,
                    times,
                )
            if "moz_annos" in columns and "moz_anno_attributes" in columns:
                source = (
                    "FROM moz_annos annotation JOIN moz_anno_attributes attribute "
                    "ON annotation.anno_attribute_id = attribute.id "
                    "WHERE attribute.name = 'downloads/destinationFileURI'"
                )
                downloads = cls._counted(
                    connection,
                    f"SELECT count(*), min(annotation.dateAdded), "
                    f"max(annotation.dateAdded) {source}"
                    if "dateAdded" in columns["moz_annos"]
                    else f"SELECT count(*) {source}",
                    cls._firefox_time,
                    times,
                )
        return BrowserProfile(
            path=path,
            family="firefox",
            browser="firefox",
            profile=path.parent.name,
            history=history,
            urls=urls,
            favorites=favorites,
            downloads=downloads,
            span=(min(times), max(times)) if times else None,
        )


class ImageHandler(Handler):
    """Placeholder for image EXIF metadata after media-format recognition."""


class VideoHandler(Handler):
    """Placeholder for video EXIF metadata after media-format recognition."""


@dataclass(frozen=True)
class SessionTurn:
    """One extracted user or assistant message with provenance flags."""

    role: str
    text: str
    timestamp: datetime | None
    meta: bool = False
    sidechain: bool = False


@dataclass(frozen=True)
class SessionFile:
    """One complete native or exported session.

    Native sessions use an absolute ``path`` and no ``location``. Exported
    sessions use the JSON member as ``path`` and the physical ZIP or extracted
    conversation JSON file as ``location``. ``records`` retains the original
    source objects while ``turns`` contains normalized user and assistant
    messages.
    """

    path: Path | PurePosixPath
    harness: Harness
    uid: str | None
    parent_uid: str | None
    subagent: bool
    records: tuple[Mapping[str, Any], ...]
    turns: tuple[SessionTurn, ...]
    span: Span | None
    models: tuple[str, ...]
    topic: str
    sidechain_only: bool = False
    location: Path | None = None

    @property
    def span_start(self) -> datetime | None:
        """Return the first valid session timestamp."""

        return self.span[0] if self.span else None

    @property
    def span_end(self) -> datetime | None:
        """Return the last valid session timestamp."""

        return self.span[1] if self.span else None

    @property
    def user_messages(self) -> tuple[str, ...]:
        """Return mainline, non-metadata user-message text."""

        return tuple(
            turn.text
            for turn in self.turns
            if turn.role == "user" and not turn.meta and not turn.sidechain
        )

    @property
    def human_messages(self) -> tuple[str, ...]:
        """What a person typed: user messages without their envelopes, leaving out generated ones."""
        return tuple(text for message in self.user_messages if (text := typed(message)))

    @property
    def length(self) -> str:
        """Return the rounded session duration using the largest suitable unit."""

        if self.span is None:
            return ""
        seconds = round((self.span[1] - self.span[0]).total_seconds())
        if not seconds:
            return ""
        unit, size = next(pair for pair in UNITS if seconds >= pair[1])
        return f"~{round(seconds / size)}{unit}"

    @property
    def label(self) -> str:
        """Return the date, turn count, duration, and topic display label."""

        start = f"{self.span[0].astimezone():%y%m%d-%H%M} " if self.span else ""
        topic = f" - {self.topic}" if self.topic else ""
        return f"{start}{len(self.turns)}{self.length}{topic}"

    @property
    def name(self) -> str:
        """Return a length-limited normalized filename retaining id and suffix."""

        tail = (f".{self.uid}" if self.uid else "") + self.path.suffix
        label = self.label
        if len(label) + len(tail) > NAME_LIMIT:
            label = label[: NAME_LIMIT - len(tail)].rstrip()
        return f"{label}{tail}"


@dataclass(frozen=True)
class SessionFolder:
    """Sessions read from one directory or one LLM export ZIP."""

    path: Path
    harness: Harness
    files: tuple[SessionFile, ...]

    @property
    def uid(self) -> str | None:
        """Return the shared session id only when every identified id agrees."""

        values = {file.uid for file in self.files if file.uid}
        return values.pop() if len(values) == 1 else None


SessionObject = SessionFile | SessionFolder


@dataclass(frozen=True)
class SessionStats:
    """Physical-file, session, turn, byte, span, and model statistics."""

    files: int
    sessions: int
    turns: int
    bytes: int
    span_start: datetime | None
    span_end: datetime | None
    models: tuple[str, ...]

    @property
    def span(self) -> Span | None:
        """Return the complete span when both bounds are available."""

        return (
            (self.span_start, self.span_end)
            if self.span_start is not None and self.span_end is not None
            else None
        )

    @classmethod
    def from_object(cls, obj: SessionObject) -> SessionStats:
        """Derive statistics from a session or collection of sessions.

        Multiple conversations inside one export ZIP count as one physical
        file for ``files`` and ``bytes``. Extracted exports count their
        conversation JSON files. Each immutable id counts as one session.
        """

        files = (obj,) if isinstance(obj, SessionFile) else obj.files
        spans = [file.span for file in files if file.span]
        paths = {file.location or Path(file.path) for file in files}
        span = _combine_spans(spans)
        return cls(
            files=len(paths),
            sessions=len({file.uid for file in files if file.uid}),
            turns=sum(len(file.turns) for file in files),
            bytes=sum(path.stat().st_size for path in paths),
            span_start=span[0] if span else None,
            span_end=span[1] if span else None,
            models=tuple(
                dict.fromkeys(model for file in files for model in file.models)
            ),
        )


class _LLMExportHandler(Handler):
    """Shared folder and ZIP mechanics for ChatGPT and Anthropic handlers."""

    def __init__(
        self,
        metadata: Mapping[str, Any] | None = None,
        *,
        strict: bool = False,
    ) -> None:
        """Initialize metadata, error policy, and provider export cache."""

        super().__init__(metadata, strict=strict)
        self._llm_export_cache: dict[
            tuple[Harness, Path], tuple[Signature, SessionFolder]
        ] = {}

    @staticmethod
    def _source_names(path: Path) -> frozenset[str]:
        """Return direct folder filenames or ZIP member filenames."""

        if path.is_dir() and not path.is_symlink():
            try:
                return frozenset(
                    child.name.casefold() for child in path.iterdir() if child.is_file()
                )
            except OSError:
                return frozenset()
        try:
            with zipfile.ZipFile(path) as archive:
                return frozenset(
                    PurePosixPath(member.filename).name.casefold()
                    for member in archive.infolist()
                    if not member.is_dir()
                )
        except (OSError, zipfile.BadZipFile):
            return frozenset()

    def _identify_export(self, path: Path, provider: type[Any]) -> bool:
        """Recognize a provider export from its required filenames."""

        path = full_path(path)
        return provider.has_markers(self._source_names(path))

    def _call_export(
        self, path: Path, provider: type[Any]
    ) -> tuple[SessionStats, SessionFolder]:
        """Load every provider conversation from a folder or ZIP."""

        path = full_path(path)
        if not self._identify_export(path, provider):
            raise ValueError(f"{path}: {provider.name} export is not identifiable")
        signature = _signature(path.stat())
        cache_key = provider.name, path
        cached = self._llm_export_cache.get(cache_key) if path.is_file() else None
        if cached is not None and cached[0] == signature:
            return SessionStats.from_object(cached[1]), cached[1]

        files: list[SessionFile] = []
        try:
            if path.is_dir() and not path.is_symlink():
                sources = tuple(
                    child
                    for child in sorted(path.iterdir(), key=_display_order)
                    if child.is_file() and provider.conversation_file(child.name)
                )
                for source in sources:
                    with source.open("r", encoding="utf-8") as stream:
                        conversations = json.load(stream, strict=False)
                    self._append_export(
                        files,
                        source,
                        source.name,
                        conversations,
                        provider,
                    )
            else:
                with zipfile.ZipFile(path) as archive:
                    members = tuple(
                        member
                        for member in archive.infolist()
                        if not member.is_dir()
                        and provider.conversation_file(
                            PurePosixPath(member.filename).name
                        )
                    )
                    for member in members:
                        with archive.open(member) as stream:
                            conversations = json.load(stream, strict=False)
                        self._append_export(
                            files,
                            path,
                            member.filename,
                            conversations,
                            provider,
                        )
        except (
            OSError,
            UnicodeDecodeError,
            zipfile.BadZipFile,
            json.JSONDecodeError,
        ) as error:
            raise ValueError(
                f"{path}: cannot read {provider.name} export: {error}"
            ) from error
        if not files:
            raise ValueError(
                f"{path}: {provider.name} export contains no conversations"
            )
        folder = SessionFolder(path, provider.name, tuple(files))
        if path.is_file():
            self._llm_export_cache[cache_key] = signature, folder
        return SessionStats.from_object(folder), folder

    def _append_export(
        self,
        files: list[SessionFile],
        location: Path,
        member: str,
        conversations: Any,
        provider: type[Any],
    ) -> None:
        """Validate and append every conversation from one JSON source."""

        if not isinstance(conversations, list):
            raise ValueError(f"{location}::{member}: conversations are not a list")
        for conversation in conversations:
            if not isinstance(conversation, Mapping):
                raise ValueError(f"{location}::{member}: conversation is not an object")
            if not provider.identify_conversation(conversation):
                raise ValueError(
                    f"{location}::{member}: conversation format is not {provider.name}"
                )
            files.append(self._export_file(location, member, provider, conversation))

    @staticmethod
    def _export_file(
        location: Path,
        member: str,
        provider: type[Any],
        conversation: Mapping[str, Any],
    ) -> SessionFile:
        """Convert one provider conversation into a typed session file."""

        uid = next(
            (
                value.strip()
                for key in provider.id_keys
                if isinstance(value := conversation.get(key), str) and value.strip()
            ),
            None,
        )
        if uid is None:
            raise ValueError(f"{location}::{member}: conversation has no immutable id")
        turns = tuple(
            turn
            for role, content, timestamp in provider.messages(conversation)
            if (turn := SessionHandler._turn(role, content, timestamp)) is not None
        )
        timestamps = [turn.timestamp for turn in turns if turn.timestamp is not None]
        timestamps += [
            stamp
            for key in provider.time_keys
            if (stamp := valid_time(SessionHandler._stamp(conversation.get(key))))
            is not None
        ]
        return SessionFile(
            path=_record_path(member),
            harness=provider.name,
            uid=uid,
            parent_uid=None,
            subagent=False,
            records=(conversation,),
            turns=turns,
            span=(min(timestamps), max(timestamps)) if timestamps else None,
            models=SessionHandler._models((conversation,)),
            topic=SessionHandler._topic(turns),
            location=location,
        )

    def _invalidate_export(self, path: Path | None, provider: type[Any]) -> None:
        """Discard one provider's cached ZIP exports at and beneath ``path``."""

        selected = None if path is None else full_path(path)
        for key in tuple(self._llm_export_cache):
            name, cached = key
            if name == provider.name and (
                selected is None or cached == selected or selected in cached.parents
            ):
                self._llm_export_cache.pop(key, None)


class ChatGPTHandler(_LLMExportHandler):
    """Handle an extracted folder or ZIP from a ChatGPT data export.

    A folder is detected from direct files; a ZIP is detected from member
    basenames. Detection requires a case-insensitive
    ``conversations-NNN.json`` name, or both ``chat.html`` and
    ``conversations.json``. Each selected conversations file must contain a
    JSON list. Every item must be an object with string ``current_node`` and an
    object ``mapping``, plus a non-empty string ``id`` or ``conversation_id``.

    Transcript turns follow the chain from ``current_node`` through each
    node's ``parent`` and are returned in reading order. Only message objects
    whose content type is ``text`` or ``multimodal_text`` contribute turns;
    alternate mapping branches are not returned. Conversation and turn times
    accept exported ISO or Unix second/millisecond values. The complete source
    conversation remains in :attr:`SessionFile.records`.
    """

    name: Harness = "chatgpt"
    id_keys = ("id", "conversation_id")
    time_keys = ("create_time", "update_time")

    @staticmethod
    def has_markers(names: frozenset[str]) -> bool:
        """Return whether the filenames identify a ChatGPT export."""

        return any(
            re.fullmatch(r"conversations-\d+\.json", name) for name in names
        ) or {"chat.html", "conversations.json"}.issubset(names)

    @staticmethod
    def conversation_file(name: str) -> bool:
        """Return whether ``name`` is a ChatGPT conversation JSON file."""

        return EXPORT_MEMBER.fullmatch(name) is not None

    @staticmethod
    def identify_conversation(conversation: Mapping[str, Any]) -> bool:
        """Recognize the ChatGPT mapping and current-node representation."""

        return isinstance(conversation.get("mapping"), Mapping) and isinstance(
            conversation.get("current_node"), str
        )

    @sync
    async def identify(self, path: Path) -> bool:
        """Recognize a ChatGPT folder or ZIP in either call mode."""

        return await asyncio.to_thread(self._safe_identify, path, self.identify_sync)

    def identify_sync(self, path: Path) -> bool:
        """Recognize a ChatGPT folder or ZIP from its filenames."""

        return self._identify_export(path, ChatGPTHandler)

    @sync
    async def __call__(
        self,
        path: Path,
    ) -> tuple[SessionStats | None, SessionFolder | HandlerError]:
        """Load a ChatGPT folder or ZIP in either call mode."""

        return await asyncio.to_thread(self._safe_call, path, self.call_sync)

    def call_sync(self, path: Path) -> tuple[SessionStats, SessionFolder]:
        """Load all conversations from a ChatGPT folder or ZIP."""

        return self._call_export(path, ChatGPTHandler)

    def invalidate(self, path: Path | None = None) -> None:
        """Discard cached ChatGPT ZIP exports at and beneath ``path``."""

        self._invalidate_export(path, ChatGPTHandler)

    @staticmethod
    def messages(
        conversation: Mapping[str, Any],
    ) -> tuple[tuple[Any, Any, Any], ...]:
        """Return messages along the active ChatGPT branch in reading order."""

        mapping = conversation["mapping"]
        current = conversation["current_node"]
        chain: list[Mapping[str, Any]] = []
        visited: set[str] = set()
        while current is not None:
            if (
                not isinstance(current, str)
                or current not in mapping
                or current in visited
            ):
                raise ValueError(
                    "ChatGPT conversation has an invalid current-node chain"
                )
            visited.add(current)
            node = mapping[current]
            if not isinstance(node, Mapping):
                raise ValueError("ChatGPT conversation node is not an object")
            chain.append(node)
            current = node.get("parent")
        return tuple(
            (
                author.get("role"),
                content.get("parts"),
                message.get("create_time"),
            )
            for node in reversed(chain)
            if isinstance(message := node.get("message"), Mapping)
            and isinstance(author := message.get("author"), Mapping)
            and isinstance(content := message.get("content"), Mapping)
            and content.get("content_type") in ("text", "multimodal_text")
        )


class AnthropicHandler(_LLMExportHandler):
    """Handle an extracted folder or ZIP from an Anthropic Claude data export.

    A folder is detected from direct files; a ZIP is detected from member
    basenames. Detection requires case-insensitive ``conversations.json`` and
    excludes an export that also contains ``chat.html``. The file must contain
    a JSON list. Every item must be an object with a string ``uuid`` and a list
    ``chat_messages``; its immutable ID is the first non-empty ``uuid`` or
    ``id``.

    Messages retain ``chat_messages`` order. ``sender`` supplies the role,
    ``content`` supplies text or supported text blocks, and ``created_at``
    supplies the turn time. The common turn normalizer maps ``human`` to
    ``user``. Conversation ``created_at`` and ``updated_at`` values also
    contribute to the span. The complete source conversation remains in
    :attr:`SessionFile.records`.
    """

    name: Harness = "claude"
    id_keys = ("uuid", "id")
    time_keys = ("created_at", "updated_at")

    @staticmethod
    def has_markers(names: frozenset[str]) -> bool:
        """Return whether the filenames identify a Claude export."""

        return "conversations.json" in names and "chat.html" not in names

    @staticmethod
    def conversation_file(name: str) -> bool:
        """Return whether ``name`` is the Claude conversation JSON file."""

        return name.casefold() == "conversations.json"

    @staticmethod
    def identify_conversation(conversation: Mapping[str, Any]) -> bool:
        """Recognize the Claude UUID and chat-message representation."""

        return isinstance(conversation.get("chat_messages"), list) and isinstance(
            conversation.get("uuid"), str
        )

    @sync
    async def identify(self, path: Path) -> bool:
        """Recognize an Anthropic Claude folder or ZIP in either call mode."""

        return await asyncio.to_thread(self._safe_identify, path, self.identify_sync)

    def identify_sync(self, path: Path) -> bool:
        """Recognize an Anthropic Claude folder or ZIP from its filenames."""

        return self._identify_export(path, AnthropicHandler)

    @sync
    async def __call__(
        self,
        path: Path,
    ) -> tuple[SessionStats | None, SessionFolder | HandlerError]:
        """Load an Anthropic Claude folder or ZIP in either call mode."""

        return await asyncio.to_thread(self._safe_call, path, self.call_sync)

    def call_sync(self, path: Path) -> tuple[SessionStats, SessionFolder]:
        """Load all conversations from an Anthropic Claude folder or ZIP."""

        return self._call_export(path, AnthropicHandler)

    def invalidate(self, path: Path | None = None) -> None:
        """Discard cached Anthropic ZIP exports at and beneath ``path``."""

        self._invalidate_export(path, AnthropicHandler)

    @staticmethod
    def messages(
        conversation: Mapping[str, Any],
    ) -> tuple[tuple[Any, Any, Any], ...]:
        """Return Claude messages in their exported order."""

        return tuple(
            (
                message.get("sender"),
                message.get("content"),
                message.get("created_at"),
            )
            for message in conversation["chat_messages"]
            if isinstance(message, Mapping)
        )


class SessionHandler(Handler):
    """Identify, load, normalize, and cache native JSONL sessions.

    A session file has a case-insensitive ``.jsonl`` extension, is non-empty,
    and contains UTF-8 JSON Lines with at least one object. Identification
    examines at most eight leading non-empty lines; a malformed line or a JSON
    value other than an object makes that file unrecognized. Full loading
    retains every valid object, skips blank, malformed, and non-object lines,
    and returns an error only when no object remains.

    Native formats are recognized from these object fields:

    * Codex: ``type`` is ``session_meta``, ``turn_context``, ``event_msg``, or
      ``response_item`` and ``payload`` is an object.
    * Claude Code: a string ``sessionId``, ``uuid``, or ``parentUuid``, or
      ``type`` equal to ``teleported-from``.
    * OpenClaw: a string ``modelId``.
    * Agy: ``USER_INPUT`` from ``USER_EXPLICIT`` or ``PLANNER_RESPONSE`` from
      ``MODEL``, with string ``created_at``.
    * Hermes: ``role`` equal to ``session_meta`` and string ``session_id``.

    A directory is recognized from the Hermes marker ``state.db``, either Agy
    marker ``antigravity_state.pbtxt`` or ``jetski_state.pbtxt``, or an Agy UUID
    directory containing
    ``.system_generated/logs/transcript_full.jsonl`` or ``transcript.jsonl``.
    Loading a directory returns every recognized file below it. ChatGPT and
    Anthropic data exports belong to their explicit handlers.
    """

    name = "session"
    extensions = (".jsonl",)

    def __init__(
        self,
        metadata: Mapping[str, Any] | None = None,
        *,
        strict: bool = False,
    ) -> None:
        """Initialize metadata, error policy, native readers, and session cache."""

        super().__init__(metadata, strict=strict)
        self._session_cache: dict[Path, tuple[Signature, SessionObject]] = {}
        self._recognizers = (
            ("cx", self._is_codex),
            ("cc", self._is_claude_code),
            ("openclaw", self._is_openclaw),
            ("agy", self._is_agy),
            ("hermes", self._is_hermes),
        )
        self._uid_readers = {
            "cx": self._codex_uid,
            "cc": self._claude_code_uid,
            "openclaw": self._openclaw_uid,
            "agy": self._agy_uid,
            "hermes": self._hermes_uid,
        }
        self._native_turn_readers = {
            "cx": self._codex_turns,
            "cc": self._claude_code_turns,
            "openclaw": self._openclaw_turns,
            "agy": self._agy_turns,
            "hermes": self._hermes_turns,
        }

    @sync
    async def identify(self, path: Path) -> bool:
        """Recognize a session file, folder, or export in either call mode."""

        return await asyncio.to_thread(self._safe_identify, path, self.identify_sync)

    def identify_sync(self, path: Path) -> bool:
        """Recognize structural folders or non-empty native JSONL files."""

        path = full_path(path)
        if path.is_dir() and not path.is_symlink():
            return self._home_harness(path) is not None or self._agy_session_folder(
                path
            )
        return (
            self._session_candidate(path)
            and self._harness(self._head(path)) is not None
        )

    @sync
    async def __call__(
        self,
        path: Path,
    ) -> tuple[SessionStats | None, SessionObject | HandlerError]:
        """Load a session object and its derived statistics in either call mode."""

        return await asyncio.to_thread(self._safe_call, path, self.call_sync)

    def call_sync(self, path: Path) -> tuple[SessionStats, SessionObject]:
        """Load one native file or directory without entering another event loop."""

        path = full_path(path)
        if path.is_file():
            obj: SessionObject = self._file(path)
        elif path.is_dir() and not path.is_symlink():
            hint = self._home_harness(path)
            files = tuple(
                session
                for candidate in sorted(
                    path.rglob("*"), key=lambda item: str(item).casefold()
                )
                if candidate.is_file()
                for session in self._sessions(candidate)
            )
            harnesses = self._uniq(
                [file.harness for file in files] + ([hint] if hint else [])
            )
            if not harnesses:
                raise ValueError(f"{path}: session format is not identifiable")
            if len(harnesses) != 1:
                raise ValueError(f"{path}: folder contains multiple session harnesses")
            obj = SessionFolder(path, harnesses[0], files)
        else:
            raise FileNotFoundError(path)
        return SessionStats.from_object(obj), obj

    def normalize_name(self, obj: SessionObject) -> str:
        """Return the canonical name for one native session file."""

        if not isinstance(obj, SessionFile):
            raise ValueError(f"{obj.path}: normalization requires one session")
        if obj.location is not None:
            raise ValueError(f"{obj.location}: normalization requires one session file")
        if obj.uid is None:
            raise ValueError(f"{obj.path}: session has no immutable id")
        return obj.name

    def invalidate(self, path: Path | None = None) -> None:
        """Discard all cached sessions or entries at and beneath ``path``."""

        if path is None:
            self._session_cache.clear()
            return
        path = full_path(path)
        for key in tuple(self._session_cache):
            if key == path or path in key.parents:
                self._session_cache.pop(key, None)

    def _file(self, path: Path) -> SessionFile:
        """Load and cache one native JSONL session file."""

        signature = _signature(path.stat())
        cached = self._session_cache.get(path)
        if (
            cached is not None
            and cached[0] == signature
            and isinstance(cached[1], SessionFile)
        ):
            return cached[1]
        records = self._records(path)
        harness = self._harness(records[:SNIFF])
        if harness is None:
            raise ValueError(f"{path}: session format is not identifiable")
        turns = self._native_turn_readers[harness](records)
        timestamps = tuple(self._timestamps(records))
        uid = self._uid_readers[harness](records, path)
        parent_uid, subagent = self._parent(records)
        mainline = any(record.get("isSidechain") is False for record in records)
        sidechain = any(record.get("isSidechain") is True for record in records)
        item = SessionFile(
            path=path,
            harness=harness,
            uid=uid,
            parent_uid=parent_uid,
            subagent=subagent,
            records=records,
            turns=turns,
            span=(min(timestamps), max(timestamps)) if timestamps else None,
            models=self._models(records),
            topic=self._topic(turns),
            sidechain_only=sidechain and not mainline,
        )
        self._session_cache[path] = (signature, item)
        return item

    def _sessions(self, path: Path) -> tuple[SessionFile, ...]:
        """Return a native session when ``path`` has a recognized JSONL head."""

        return (
            (self._file(path),)
            if self._session_candidate(path)
            and self._harness(self._head(path)) is not None
            else ()
        )

    @staticmethod
    def _session_candidate(path: Path) -> bool:
        """Reject unsupported or empty paths without opening their contents."""

        if path.suffix.casefold() not in SessionHandler.extensions:
            return False
        try:
            status = path.stat()
        except OSError:
            return False
        return stat_module.S_ISREG(status.st_mode) and status.st_size > 0

    def _harness(
        self,
        records: Sequence[Mapping[str, Any]],
        hint: Harness | None = None,
    ) -> Harness | None:
        """Return the first native format matching ``records``, or ``hint``."""

        return next(
            (harness for harness, recognize in self._recognizers if recognize(records)),
            hint,
        )

    @staticmethod
    def _is_codex(records: Sequence[Mapping[str, Any]]) -> bool:
        """Recognize Codex lifecycle and response records."""

        return any(
            record.get("type")
            in ("session_meta", "turn_context", "event_msg", "response_item")
            and isinstance(record.get("payload"), Mapping)
            for record in records
        )

    @staticmethod
    def _is_claude_code(records: Sequence[Mapping[str, Any]]) -> bool:
        """Recognize Claude Code session identifiers and record types."""

        return any(
            isinstance(record.get("sessionId"), str)
            or record.get("type") == "teleported-from"
            or isinstance(record.get("uuid"), str)
            or isinstance(record.get("parentUuid"), str)
            for record in records
        )

    @staticmethod
    def _is_openclaw(records: Sequence[Mapping[str, Any]]) -> bool:
        """Recognize OpenClaw records from their model identifier."""

        return any(isinstance(record.get("modelId"), str) for record in records)

    @staticmethod
    def _is_agy(records: Sequence[Mapping[str, Any]]) -> bool:
        """Recognize Agy user and planner transcript records."""

        return any(
            record.get("type") in ("USER_INPUT", "PLANNER_RESPONSE")
            and record.get("source") in ("USER_EXPLICIT", "MODEL")
            and isinstance(record.get("created_at"), str)
            for record in records
        )

    @staticmethod
    def _is_hermes(records: Sequence[Mapping[str, Any]]) -> bool:
        """Recognize a Hermes session metadata record."""

        return any(
            record.get("role") == "session_meta"
            and isinstance(record.get("session_id"), str)
            for record in records
        )

    @staticmethod
    def _codex_uid(records: Sequence[Mapping[str, Any]], path: Path) -> str | None:
        """Return the immutable id from Codex session metadata."""

        for record in records:
            if record.get("type") != "session_meta" or not isinstance(
                payload := record.get("payload"), Mapping
            ):
                continue
            value = payload.get("id") or payload.get("session_id")
            return value.strip() if isinstance(value, str) and value.strip() else None
        return None

    @staticmethod
    def _agy_uid(records: Sequence[Mapping[str, Any]], path: Path) -> str | None:
        """Return the UUID-named Agy session folder beneath ``brain``."""

        return next(
            (
                parent.name
                for parent in path.parents
                if parent.parent.name == "brain" and SESSION_UID.fullmatch(parent.name)
            ),
            None,
        )

    @classmethod
    def _claude_code_uid(
        cls, records: Sequence[Mapping[str, Any]], path: Path
    ) -> str | None:
        """Return the first Claude Code session identifier."""

        return cls._record_uid(records, ID_KEYS)

    @classmethod
    def _openclaw_uid(
        cls, records: Sequence[Mapping[str, Any]], path: Path
    ) -> str | None:
        """Return the first OpenClaw session identifier."""

        return cls._record_uid(records, ("id", "session_id"))

    @classmethod
    def _hermes_uid(
        cls, records: Sequence[Mapping[str, Any]], path: Path
    ) -> str | None:
        """Return the first Hermes session identifier."""

        return cls._record_uid(records, ID_KEYS)

    @staticmethod
    def _record_uid(
        records: Sequence[Mapping[str, Any]], keys: Sequence[str]
    ) -> str | None:
        """Find the first non-empty identifier in supported record scopes."""

        for record in records:
            scopes = [record]
            scopes += [
                value
                for key in ("payload", "message", "data")
                if isinstance(value := record.get(key), Mapping)
            ]
            for key in keys:
                for scope in scopes:
                    value = scope.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        return None

    @classmethod
    def _codex_turns(
        cls, records: Sequence[Mapping[str, Any]]
    ) -> tuple[SessionTurn, ...]:
        """Extract Codex response messages, or legacy event messages when absent."""

        response = tuple(
            item
            for record in records
            if record.get("type") == "response_item"
            and isinstance(payload := record.get("payload"), Mapping)
            and payload.get("type") == "message"
            for item in [
                cls._turn(
                    payload.get("role"), payload.get("content"), record.get("timestamp")
                )
            ]
            if item is not None
        )
        if response:
            return response
        roles = {"user_message": "user", "agent_message": "assistant"}
        return tuple(
            item
            for record in records
            if record.get("type") == "event_msg"
            and isinstance(payload := record.get("payload"), Mapping)
            for item in [
                cls._turn(
                    roles.get(payload.get("type")),
                    payload.get("message"),
                    record.get("timestamp"),
                )
            ]
            if item is not None
        )

    @classmethod
    def _claude_code_turns(
        cls, records: Sequence[Mapping[str, Any]]
    ) -> tuple[SessionTurn, ...]:
        """Extract Claude Code user and assistant turns with record flags."""

        return tuple(
            item
            for record in records
            if record.get("type") in ROLES
            and isinstance(message := record.get("message"), Mapping)
            for item in [
                cls._turn(
                    message.get("role", record.get("type")),
                    message.get("content"),
                    record.get("timestamp"),
                    record.get("isMeta") is True,
                    record.get("isSidechain") is True,
                )
            ]
            if item is not None
        )

    @classmethod
    def _openclaw_turns(
        cls, records: Sequence[Mapping[str, Any]]
    ) -> tuple[SessionTurn, ...]:
        """Extract OpenClaw turns from nested message records."""

        return tuple(
            item
            for record in records
            if isinstance(message := record.get("message"), Mapping)
            for item in [
                cls._turn(
                    message.get("role"),
                    message.get("content"),
                    record.get("timestamp", record.get("ts")),
                )
            ]
            if item is not None
        )

    @classmethod
    def _agy_turns(
        cls, records: Sequence[Mapping[str, Any]]
    ) -> tuple[SessionTurn, ...]:
        """Map Agy user input and planner responses to canonical turns."""

        roles = {"USER_INPUT": "user", "PLANNER_RESPONSE": "assistant"}
        return tuple(
            item
            for record in records
            for item in [
                cls._turn(
                    roles.get(record.get("type")),
                    record.get("content"),
                    record.get("created_at"),
                )
            ]
            if item is not None
        )

    @classmethod
    def _hermes_turns(
        cls, records: Sequence[Mapping[str, Any]]
    ) -> tuple[SessionTurn, ...]:
        """Extract Hermes turns from flat role and content records."""

        return tuple(
            item
            for record in records
            for item in [
                cls._turn(
                    record.get("role"), record.get("content"), record.get("timestamp")
                )
            ]
            if item is not None
        )

    @staticmethod
    def _records(path: Path) -> tuple[Mapping[str, Any], ...]:
        """Read valid JSON objects from a JSONL session file."""

        # a writer crash or interrupted flush can leave one line truncated mid-record;
        # skip that line rather than losing every record in the file over it.
        records: list[Mapping[str, Any]] = []
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    records.append(value)
        if not records:
            raise ValueError(f"{path}: session file is empty")
        return tuple(records)

    @staticmethod
    def _head(path: Path) -> tuple[Mapping[str, Any], ...]:
        """Read up to ``SNIFF`` leading JSONL objects, or return no records."""

        found: list[Mapping[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        return ()
                    found.append(value)
                    if len(found) >= SNIFF:
                        break
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return ()
        return tuple(found)

    @classmethod
    def _walk_values(cls, value: Any) -> Iterator[tuple[str, Any]]:
        """Yield every mapping key and value recursively."""

        if isinstance(value, Mapping):
            for key, nested in value.items():
                yield str(key), nested
                yield from cls._walk_values(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from cls._walk_values(nested)

    @staticmethod
    def _stamp(value: Any) -> datetime | None:
        """Parse an ISO string or second/millisecond Unix timestamp."""

        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                return None
            return (
                parsed
                if parsed.tzinfo is not None
                else parsed.replace(tzinfo=timezone.utc)
            )
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 1_000_000_000
        ):
            seconds = value / 1000 if value > 10_000_000_000 else value
            try:
                return datetime.fromtimestamp(seconds, timezone.utc)
            except (OSError, OverflowError, ValueError):
                return None
        return None

    @classmethod
    def _timestamps(cls, records: Sequence[Mapping[str, Any]]) -> Iterator[datetime]:
        """Record times only: the record, its payload, or its message. Values quoted deeper inside content are not the session's time."""

        for record in records:
            for scope in (record, record.get("payload"), record.get("message")):
                if not isinstance(scope, Mapping):
                    continue
                for key in TIME_KEYS:
                    if (stamp := valid_time(cls._stamp(scope.get(key)))) is not None:
                        yield stamp

    @classmethod
    def _models(cls, records: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
        """Return unique model names found anywhere in the records."""

        return cls._uniq(
            value
            for record in records
            for key, value in cls._walk_values(record)
            if key in MODEL_KEYS
        )

    @staticmethod
    def _parent(records: Sequence[Mapping[str, Any]]) -> tuple[str | None, bool]:
        """Return a Codex parent session id and whether the session is a subagent."""

        for record in records:
            if record.get("type") != "session_meta":
                continue
            payload = record.get("payload")
            if not isinstance(payload, Mapping):
                return None, False
            source = payload.get("source")
            subagent = payload.get("thread_source") == "subagent" or (
                isinstance(source, Mapping) and "subagent" in source
            )
            parent = payload.get("parent_thread_id")
            if not parent and isinstance(source, Mapping):
                nested = source.get("subagent")
                spawn = (
                    nested.get("thread_spawn") if isinstance(nested, Mapping) else None
                )
                parent = (
                    spawn.get("parent_thread_id")
                    if isinstance(spawn, Mapping)
                    else None
                )
            if subagent and not parent:
                parent = payload.get("forked_from_id")
            return (str(parent) if parent else None), subagent
        return None, False

    @staticmethod
    def _content_text(content: Any) -> str:
        """Join supported string and structured text content blocks."""

        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                text = part
            elif (
                isinstance(part, Mapping)
                and part.get("type") in ("text", "input_text", "output_text")
                and isinstance(part.get("text"), str)
            ):
                text = part["text"]
            else:
                continue
            if text.strip():
                parts.append(text)
        return "\n\n".join(parts)

    @classmethod
    def _turn(
        cls,
        role: Any,
        content: Any,
        timestamp: Any,
        meta: bool = False,
        sidechain: bool = False,
    ) -> SessionTurn | None:
        """Normalize one supported role and non-empty content into a turn."""

        if isinstance(role, str) and role.casefold() == "human":
            role = "user"
        if not isinstance(role, str) or role.casefold() not in ROLES:
            return None
        text = cls._content_text(content)
        if not text.strip():
            return None
        return SessionTurn(
            role.casefold(), text, valid_time(cls._stamp(timestamp)), meta, sidechain
        )

    @staticmethod
    def _topic(messages: Sequence[SessionTurn]) -> str:
        """The first line a person typed."""
        for message in messages:
            if message.role != "user" or message.meta or message.sidechain:
                continue
            if text := typed(message.text):
                return " ".join(
                    "".join(
                        " " if char in UNSAFE else char for char in text.splitlines()[0]
                    ).split()
                )
        return ""

    @staticmethod
    def _uniq(values) -> tuple[str, ...]:
        """Return non-empty strings once, preserving their first order."""

        return tuple(
            dict.fromkeys(
                value.strip()
                for value in values
                if isinstance(value, str) and value.strip()
            )
        )

    @staticmethod
    def _home_harness(path: Path) -> Harness | None:
        """Identify a harness home directory from its required marker file."""

        return next(
            (
                harness
                for harness, markers in HOMES.items()
                if any((path / marker).exists() for marker in markers)
            ),
            None,
        )

    @staticmethod
    def _agy_session_folder(path: Path) -> bool:
        """Recognize an Agy UUID folder containing a transcript file."""

        return SESSION_UID.fullmatch(path.name) is not None and any(
            (path / ".system_generated" / "logs" / name).is_file()
            for name in ("transcript_full.jsonl", "transcript.jsonl")
        )


def valid_time(value: datetime | None) -> datetime | None:
    """A recorded time, or None. Placeholders that tools write instead of a time, anything at or before DOS zero, and future times are not times."""

    if value is None:
        return None
    fields = value.timetuple()[:6]
    utc_fields = (
        value.astimezone(timezone.utc).timetuple()[:6]
        if value.tzinfo is not None
        else fields
    )
    if (
        fields in PLACEHOLDER_TIMES
        or utc_fields in PLACEHOLDER_TIMES
        or fields <= PLACEHOLDER_TIMES[2]
    ):
        return None
    now = datetime.now(timezone.utc) if value.tzinfo is not None else datetime.now()
    if value > now + FUTURE_TOLERANCE:
        return None
    return value


def _signature(stat: os.stat_result) -> Signature:
    """Return the filesystem fields used to invalidate path caches."""

    return stat.st_mode, stat.st_size, stat.st_mtime_ns


def _display_order(path: Path) -> tuple[bool, str]:
    """Sort folders before files, then names without case sensitivity."""

    return not (path.is_dir() and not path.is_symlink()), path.name.casefold()


def _record_path(value: str) -> PurePosixPath:
    """Return a safe archive-relative path from an archive member name."""

    path = PurePosixPath(value.lstrip("/").replace("\\", "/"))
    if (
        path.is_absolute()
        or ".." in path.parts
        or (path.parts and path.parts[0].endswith(":"))
    ):
        raise ValueError(f"unsafe path inside archive: {value}")
    return PurePosixPath(*(part for part in path.parts if part not in ("", ".")))


def _archive_time(value: Any) -> datetime | None:
    """An archive member's recorded time, or None when the archiver stored a placeholder instead."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            parsed = datetime.fromtimestamp(value, timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    else:
        try:
            parsed = datetime(*value)
        except (TypeError, ValueError):
            return None
    return valid_time(parsed if parsed.tzinfo is not None else parsed.astimezone())


def _complete_archive_records(
    location: Path,
    records: Sequence[Record],
) -> tuple[Record, ...]:
    """Add missing parent folders, derive stats, and order archive records."""

    complete = {record.path: record for record in records}
    for record in records:
        for parent in record.path.parents:
            if parent != PurePosixPath("."):
                complete.setdefault(
                    parent,
                    Record(
                        path=parent,
                        is_folder=True,
                        size=0,
                        modified_at=None,
                        handlers=(),
                        location=location,
                    ),
                )

    children: dict[PurePosixPath, list[PurePosixPath]] = {}
    for path in complete:
        children.setdefault(path.parent, []).append(path)
    for path in sorted(complete, key=lambda item: len(item.parts), reverse=True):
        record = complete[path]
        if record.is_folder:
            stats = FileHandler._folder_stats(
                record, [complete[child] for child in children.get(path, ())]
            )
        else:
            stats = FileHandler._file_stats(record)
        complete[path] = replace(record, stats=stats)

    return tuple(
        sorted(
            complete.values(),
            key=lambda record: (
                len(record.path.parts),
                not record.is_folder,
                str(record.path).casefold(),
            ),
        )
    )


def _archive_stats(records: Sequence[Record]) -> FileStats:
    """Aggregate top-level archive records into complete archive statistics."""

    root = Record(PurePosixPath("."), True, 0, None, ())
    children = [
        record for record in records if record.path.parent == PurePosixPath(".")
    ]
    return FileHandler._folder_stats(root, children)


def _stats_span(stats: Any) -> Span | None:
    """Read a complete span from either supported statistics representation."""

    span = getattr(stats, "span", None)
    if isinstance(span, tuple) and len(span) == 2:
        return span
    start = getattr(stats, "span_start", None)
    end = getattr(stats, "span_end", None)
    return (
        (start, end)
        if isinstance(start, datetime) and isinstance(end, datetime)
        else None
    )


def _combine_spans(spans: Sequence[Span]) -> Span | None:
    """Return the earliest start and latest end across all spans."""

    return (
        (min(span[0] for span in spans), max(span[1] for span in spans))
        if spans
        else None
    )


def typed(text: str) -> str:
    """The text a person typed in a user message: the envelope stripped, '' when the message was generated."""
    if match := REALTIME_INPUT.search(text):
        text = match.group(1)
    text = ENVELOPE.sub("", text, count=1).strip()
    if not text or any(pattern.search(text) for pattern in NON_HUMAN):
        return ""
    first = text.splitlines()[0].strip()
    if (
        first.startswith("<")
        and first.endswith(">")
        or any(first.startswith(preamble) for preamble in PREAMBLE)
    ):
        return ""
    return text
