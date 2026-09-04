r"""Typed handlers for files, folders, and sessions.

``FileHandler`` identifies, probes, normalizes, caches, and navigates a file
hierarchy. A domain handler receives one ``Path`` and returns
``(stats, obj)``; stats are derived from the complete typed object.

  2DO:
  - [x] Add support for git repos. Span should come from .git folder, but .git itself should not be included when exporting/copying
  - [x] Add support for tar.gz archives
  - [x] Extract datetime from filename when {ts} is present
  - [x] Harnesses should use Decisions\001 - Sessions - file naming convention
    - `{model|harness}` - short slug representing harness OR model:
      - chatgpt | cx
      - claude | cc
      - gemini | agy
      - hermes
      - openclaw
      - manus
  - [x] Extract timespans from filenames/foldernames like:
    - 260619-260513 five - langfuse
    - report-511833076877-2026-06-21-to-2026-07-22
    - Garage_Large_NVR_NVR_20250508202204_20250508204259_1053962
    - 10.172.105.54_01_20260721191520979_TIMING
    - Rabbit mom-1777250940-1777251900
    - Camera 10-21-2023, 07.00.00 GMT+3 - 10-21-2023, 08.00.00 GMT+3
    - 241020-2257 Alex fall (140s)

  Big tasks:
  - [x] Add support for export files from LLMs.
    - [x] OpenAi. Example: D:\SD.archive\Sessions\a60608bb38ceb475551dff9ce52432d8c1b885fea57ee517ab7f1f534ff10778-2026-08-27-03-46-09-3fab63159d564b92abd68e599a3facd9.zip
    - [x] Anthropic. Example: \\s1\Everything\Sessions\*.zip
  - [x] Refactor code so harness specific code is not in big if else blocks.
  - [x] Refactor code to have fewer functions that do not belong to classes
  - [x] Make handlers support async (gppu async)
  - [x] extract spans from git history (local, no upstreams)
    - [x] Folders that are git-tracked - extract spans from
    - [x] files that are git-tracked - codex memories folder

  In consideration
  - [ ] file/folder history from SynologyDrive history
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tarfile
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol, TypeVar, runtime_checkable

import rarfile

from .gppu import sync

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

HOMES: dict[Harness, tuple[str, ...]] = {
    "hermes": ("state.db",),
    "agy": ("antigravity_state.pbtxt", "jetski_state.pbtxt"),
}
SESSION_UID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
EXPORT_MEMBER = re.compile(r"conversations(?:-\d+)?\.json", re.I)


@runtime_checkable
class Handler(Protocol[ObjectT, StatsT]):
    """One configured domain handler."""

    name: str

    def identify(self, path: Path) -> bool: ...
    def __call__(self, path: Path) -> tuple[StatsT, ObjectT]: ...


@runtime_checkable
class _SyncHandler(Protocol[ObjectT, StatsT]):
    """Synchronous implementation used while a handler runs in a worker thread."""

    def identify_sync(self, path: Path) -> bool: ...
    def call_sync(self, path: Path) -> tuple[StatsT, ObjectT]: ...


@dataclass(frozen=True)
class Probe:
    """One handler's result for a file or folder."""

    handler: str
    stats: Any
    obj: Any = field(repr=False, compare=False)


@dataclass(frozen=True)
class FileStats:
    """Recursive statistics displayed for one hierarchy record."""

    files: int
    folders: int
    bytes: int
    span: Span | None


@dataclass(frozen=True)
class Record:
    """One file or folder and the handlers that matched it."""

    path: Path | PurePosixPath
    is_folder: bool
    size: int
    modified_at: datetime | None
    handlers: tuple[str, ...]
    location: str | Path | None = None
    probes: tuple[Probe, ...] = ()
    stats: FileStats | None = None

    @property
    def name(self) -> str:
        return self.path.name or str(self.path)

    @property
    def label(self) -> str:
        return self.name + ("/" if self.is_folder else "")

    @property
    def display_path(self) -> str:
        if self.location is None:
            return str(self.path)
        return f"{self.location}::{self.path.as_posix()}"

    @property
    def span(self) -> Span | None:
        return self.stats.span if self.stats is not None else None

    @property
    def metadata(self) -> dict[str, Any]:
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
        return value


class FileHandler:
    """Access point for one cached hierarchy and its domain handlers."""

    def __init__(self, *configured: Handler[Any, Any]) -> None:
        names = [handler.name for handler in configured]
        if len(names) != len(set(names)):
            raise ValueError("handler names must be unique")
        self.configured = tuple(configured)
        self._identified: dict[Path, tuple[Signature, tuple[str, ...]]] = {}
        self._probed: dict[Path, tuple[Signature, tuple[Probe, ...]]] = {}
        self._children: dict[Path, tuple[Signature, tuple[Path, ...]]] = {}

    @sync
    async def identify(self, path: Path, recursive: bool = True) -> list[Record]:
        return await asyncio.to_thread(self.identify_sync, path, recursive)

    def identify_sync(self, path: Path, recursive: bool = True) -> list[Record]:
        """Return metadata and matching handler names without probing objects."""

        return [self.record(found) for found in self._walk(path, recursive)]

    @sync
    async def probe(self, path: Path, recursive: bool = True) -> list[Record]:
        return await asyncio.to_thread(self.probe_sync, path, recursive)

    def probe_sync(self, path: Path, recursive: bool = True) -> list[Record]:
        """Probe matching handlers and derive recursive folder statistics."""

        paths = list(self._walk(path, recursive))
        records = {found: self._probe_record(found) for found in paths}
        child_paths: dict[Path, list[Path]] = {}
        for found in paths[1:]:
            child_paths.setdefault(found.parent, []).append(found)

        for found in reversed(paths):
            record = records[found]
            if record.is_folder:
                children = [records[child] for child in child_paths.get(found, ())]
                record = replace(record, stats=self._folder_stats(record, children))
            else:
                record = replace(record, stats=self._file_stats(record))
            records[found] = record
        return [records[found] for found in paths]

    def record(self, path: Path) -> Record:
        """Return one cached identification record."""

        path = _absolute(path)
        stat = path.stat()
        signature = _signature(stat)
        cached = self._identified.get(path)
        if cached is None or cached[0] != signature:
            names = tuple(
                handler.name
                for handler in self.configured
                if self._handler_identify(handler, path)
            )
            self._identified[path] = (signature, names)
            self._probed.pop(path, None)
        else:
            names = cached[1]
            if any(handler.name == "git" for handler in self.configured):
                names = tuple(
                    handler.name
                    for handler in self.configured
                    if (
                        self._handler_identify(handler, path)
                        if handler.name == "git"
                        else handler.name in names
                    )
                )
                self._identified[path] = (signature, names)
        is_folder = path.is_dir() and not path.is_symlink()
        return Record(
            path=path,
            is_folder=is_folder,
            size=0 if is_folder else stat.st_size,
            modified_at=valid_time(datetime.fromtimestamp(stat.st_mtime, timezone.utc)),
            handlers=names,
        )

    def children(self, path: Path | Record) -> tuple[Record, ...]:
        """Return direct children in display order from the hierarchy cache."""

        if isinstance(path, Record):
            if path.location is not None:
                if not path.is_folder or not isinstance(path.location, Path):
                    return ()
                return self._archive_children(path.location, path.path)
            if "archive" in path.handlers:
                return self._archive_children(Path(path.path), PurePosixPath("."))
            path = Path(path.path)
        path = _absolute(path)
        if not path.is_dir() or path.is_symlink():
            return ()
        signature = _signature(path.stat())
        cached = self._children.get(path)
        if cached is None or cached[0] != signature:
            paths = tuple(
                sorted(
                    (
                        child
                        for child in path.iterdir()
                        if child.name.casefold() != ".git"
                    ),
                    key=_display_order,
                )
            )
            self._children[path] = (signature, paths)
        else:
            paths = cached[1]
        return tuple(
            record for child in paths if (record := self._child(child)) is not None
        )

    def _child(self, path: Path) -> Record | None:
        """One child, or None when it is gone. A listing and the reading of it are two moments, and on a tree being
        written the thing named in the first can be absent by the second. It is not a child then.
        """
        try:
            return self.record(path)
        except FileNotFoundError:
            return None

    def _archive_children(
        self,
        archive: Path,
        parent: Path | PurePosixPath,
    ) -> tuple[Record, ...]:
        record = self._probe_record(_absolute(archive))
        probe = next(
            (probe for probe in record.probes if probe.handler == "archive"), None
        )
        if probe is None:
            raise ValueError(f"{archive}: archive handler did not return records")
        parent = PurePosixPath(parent.as_posix())
        return tuple(child for child in probe.obj if child.path.parent == parent)

    @sync
    async def load(self, path: Path) -> Any:
        return await asyncio.to_thread(self.load_sync, path)

    def load_sync(self, path: Path) -> Any:
        """Return the first matching typed object, or ``None`` when unrecognized."""

        result = self._probe_record(_absolute(path))
        return result.probes[0].obj if result.probes else None

    @sync
    async def normalize(
        self,
        source: Path,
        destination: Path | None = None,
        recursive: bool = True,
        exclude_handlers: Sequence[str] = (),
    ) -> Path:
        return await asyncio.to_thread(
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
    ) -> Path:
        """Rename by handler naming or copy to an exact destination hierarchy."""

        source = _absolute(source)
        if destination is None:
            result = self._probe_record(source)
            selected = next(
                (
                    (probe, handler)
                    for probe in result.probes
                    for handler in self.configured
                    if probe.handler == handler.name
                    and probe.handler not in exclude_handlers
                    and callable(getattr(handler, "normalize_name", None))
                ),
                None,
            )
            if selected is None:
                raise ValueError(f"{source}: no naming handler")
            probe, handler = selected
            destination = source.with_name(handler.normalize_name(probe.obj))
            if destination == source:
                return source
            if destination.exists():
                raise FileExistsError(destination)
            source.rename(destination)
        else:
            destination = _absolute(destination)
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
        return await asyncio.to_thread(
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

        root = self.probe_sync(source)[0]
        if root.span is None:
            raise ValueError(f"{source}: hierarchy has no span")
        return _absolute(destination) / ArchiveHandler.archive_name(
            root.span,
            name,
            extension,
            local_time,
        )

    @sync
    async def invalidate(self, path: Path | None = None) -> None:
        await asyncio.to_thread(self.invalidate_sync, path)

    def invalidate_sync(self, path: Path | None = None) -> None:
        """Discard one cached branch, or the complete hierarchy cache."""

        if path is None:
            self._identified.clear()
            self._probed.clear()
            self._children.clear()
            for handler in self.configured:
                invalidate = getattr(handler, "invalidate", None)
                if invalidate is not None:
                    invalidate()
            return
        path = _absolute(path)
        for cache in (self._identified, self._probed, self._children):
            for cached in tuple(cache):
                if cached == path or path in cached.parents:
                    cache.pop(cached, None)
        for handler in self.configured:
            invalidate = getattr(handler, "invalidate", None)
            if invalidate is not None:
                invalidate(path)

    def _walk(self, path: Path, recursive: bool) -> Iterator[Path]:
        path = _absolute(path)
        path.stat()
        yield path
        if recursive and path.is_dir() and not path.is_symlink():
            for child in self.children(path):
                yield from self._walk(child.path, True)

    def _probe_record(self, path: Path) -> Record:
        record = self.record(path)
        signature = _signature(path.stat())
        cached = self._probed.get(path)
        if cached is None or cached[0] != signature or "git" in record.handlers:
            selected = {handler.name: handler for handler in self.configured}
            probes = tuple(
                Probe(name, *self._handler_call(selected[name], path))
                for name in record.handlers
            )
            self._probed[path] = (signature, probes)
        else:
            probes = cached[1]
        return replace(record, probes=probes)

    @staticmethod
    def _handler_identify(handler: Handler[Any, Any], path: Path) -> bool:
        if isinstance(handler, _SyncHandler):
            return handler.identify_sync(path)
        return handler.identify(path)

    @staticmethod
    def _handler_call(handler: Handler[Any, Any], path: Path) -> tuple[Any, Any]:
        if isinstance(handler, _SyncHandler):
            return handler.call_sync(path)
        return handler(path)

    @staticmethod
    def _file_stats(record: Record) -> FileStats:
        spans = [span for probe in record.probes if (span := _stats_span(probe.stats))]
        span = _combine_spans(spans) or FileHandler._name_span(record.name)
        modified = (
            (record.modified_at, record.modified_at) if record.modified_at else None
        )
        return FileStats(1, 0, record.size, span or modified)

    @staticmethod
    def _folder_stats(record: Record, children: Sequence[Record]) -> FileStats:
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
            spans += [
                child.stats.span
                for child in children
                if child.stats and child.stats.span
            ]
        files = sum(child.stats.files for child in children if child.stats)
        folders = sum(
            child.stats.folders + int(child.is_folder)
            for child in children
            if child.stats
        )
        size = sum(child.stats.bytes for child in children if child.stats)
        modified = (
            (record.modified_at, record.modified_at) if record.modified_at else None
        )
        return FileStats(files, folders, size, _combine_spans(spans) or modified)

    @classmethod
    def _name_span(cls, name: str) -> Span | None:
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
        try:
            parsed = datetime.strptime(value, format_string)
        except ValueError:
            return None
        parsed = (
            parsed.replace(tzinfo=zone) if zone is not None else parsed.astimezone()
        )
        return valid_time(parsed)


class GitHandler:
    """Identify Git-tracked paths and derive their spans from local history."""

    name = "git"

    def __init__(self) -> None:
        self._cache: dict[
            Path,
            tuple[tuple[Any, ...], frozenset[Path], dict[Path, Span]],
        ] = {}

    @sync
    async def identify(self, path: Path) -> bool:
        return await asyncio.to_thread(self.identify_sync, path)

    def identify_sync(self, path: Path) -> bool:
        repository = self._repository(path)
        if repository is None:
            return False
        tracked, _ = self._history(*repository)
        return _absolute(path) in tracked

    @sync
    async def __call__(self, path: Path) -> tuple[FileStats, Path]:
        return await asyncio.to_thread(self.call_sync, path)

    def call_sync(self, path: Path) -> tuple[FileStats, Path]:
        path = _absolute(path)
        repository = self._repository(path)
        if repository is None:
            raise ValueError(f"{path}: Git repository is not identifiable")
        tracked, spans = self._history(*repository)
        if path not in tracked:
            raise ValueError(f"{path}: path is not Git-tracked")
        return FileStats(0, 0, 0, spans.get(path)), repository[1]

    def invalidate(self, path: Path | None = None) -> None:
        if path is None:
            self._cache.clear()
            return
        repository = self._repository(path)
        if repository is not None:
            self._cache.pop(repository[0], None)

    @classmethod
    def _repository(cls, path: Path) -> tuple[Path, Path] | None:
        path = _absolute(path)
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
        state = self._state(metadata)
        cached = self._cache.get(root)
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
        self._cache[root] = state, frozen, spans
        return frozen, spans

    @staticmethod
    def _git(root: Path, *arguments: str) -> bytes:
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
    def _relative(value: bytes) -> PurePosixPath:
        path = PurePosixPath(value.decode("utf-8"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe path in Git history: {path}")
        return path

    @staticmethod
    def _add_span(spans: dict[Path, Span], path: Path, moment: datetime) -> None:
        if span := spans.get(path):
            spans[path] = min(span[0], moment), max(span[1], moment)
        else:
            spans[path] = moment, moment

    @classmethod
    def _state(cls, metadata: Path) -> tuple[Any, ...]:
        common = metadata
        commondir = metadata / "commondir"
        if commondir.is_file():
            common = _absolute(metadata / commondir.read_text(encoding="utf-8").strip())
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
                common / "packed-refs",
            )
            if path.is_file()
        )
        return head_value, ref_value, signatures

    @staticmethod
    def _metadata(path: Path) -> Path | None:
        if not path.is_dir() or path.is_symlink():
            return None
        marker = path / ".git"
        if marker.is_dir():
            return marker
        if not marker.is_file():
            return None
        try:
            target = marker.read_text(encoding="utf-8").strip()
        except OSError, UnicodeDecodeError:
            return None
        prefix = "gitdir:"
        if not target.casefold().startswith(prefix):
            return None
        metadata = Path(target[len(prefix) :].strip())
        if not metadata.is_absolute():
            metadata = path / metadata
        metadata = _absolute(metadata)
        return metadata if metadata.is_dir() else None


class ArchiveHandler:
    """Identify and load ZIP, RAR, and TAR.GZ hierarchies from their contents."""

    name = "archive"
    extensions = (".rar", ".tar.gz", ".zip")

    @sync
    async def identify(self, path: Path) -> bool:
        return await asyncio.to_thread(self.identify_sync, path)

    def identify_sync(self, path: Path) -> bool:
        return path.is_file() and (
            zipfile.is_zipfile(path)
            or rarfile.is_rarfile(path)
            or self._is_tar_gz(path)
        )

    @sync
    async def __call__(self, path: Path) -> tuple[FileStats, tuple[Record, ...]]:
        return await asyncio.to_thread(self.call_sync, path)

    def call_sync(self, path: Path) -> tuple[FileStats, tuple[Record, ...]]:
        path = _absolute(path)
        if zipfile.is_zipfile(path):
            records = self._zip_records(path)
        elif rarfile.is_rarfile(path):
            records = self._rar_records(path)
        elif self._is_tar_gz(path):
            records = self._tar_records(path)
        else:
            raise ValueError(f"{path}: unsupported archive")
        return _archive_stats(records), records

    @staticmethod
    def _is_tar_gz(path: Path) -> bool:
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

    @staticmethod
    def _rar_records(path: Path) -> tuple[Record, ...]:
        try:
            with rarfile.RarFile(path) as archive:
                return _complete_archive_records(
                    path,
                    tuple(
                        Record(
                            path=_record_path(info.filename),
                            is_folder=info.isdir(),
                            size=info.file_size,
                            modified_at=_archive_time(info.mtime or info.date_time),
                            handlers=(),
                            location=path,
                        )
                        for info in archive.infolist()
                        if _record_path(info.filename) != PurePosixPath(".")
                    ),
                )
        except (OSError, rarfile.Error) as error:
            raise ValueError(f"{path}: cannot read RAR: {error}") from error

    @staticmethod
    def _tar_records(path: Path) -> tuple[Record, ...]:
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


@dataclass(frozen=True)
class SessionTurn:
    """One user or assistant message."""

    role: str
    text: str
    timestamp: datetime | None
    meta: bool = False
    sidechain: bool = False


@dataclass(frozen=True)
class SessionFile:
    """One complete session log."""

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
        return self.span[0] if self.span else None

    @property
    def span_end(self) -> datetime | None:
        return self.span[1] if self.span else None

    @property
    def user_messages(self) -> tuple[str, ...]:
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
        if self.span is None:
            return ""
        seconds = round((self.span[1] - self.span[0]).total_seconds())
        if not seconds:
            return ""
        unit, size = next(pair for pair in UNITS if seconds >= pair[1])
        return f"~{round(seconds / size)}{unit}"

    @property
    def label(self) -> str:
        start = f"{self.span[0].astimezone():%y%m%d-%H%M} " if self.span else ""
        topic = f" - {self.topic}" if self.topic else ""
        return f"{start}{len(self.turns)}{self.length}{topic}"

    @property
    def name(self) -> str:
        tail = (f".{self.uid}" if self.uid else "") + self.path.suffix
        label = self.label
        if len(label) + len(tail) > NAME_LIMIT:
            label = label[: NAME_LIMIT - len(tail)].rstrip()
        return f"{label}{tail}"


@dataclass(frozen=True)
class SessionFolder:
    """Session files held by one folder."""

    path: Path
    harness: Harness
    files: tuple[SessionFile, ...]

    @property
    def uid(self) -> str | None:
        values = {file.uid for file in self.files if file.uid}
        return values.pop() if len(values) == 1 else None


SessionObject = SessionFile | SessionFolder


@dataclass(frozen=True)
class SessionStats:
    """Statistics derived only from a session file or folder."""

    files: int
    sessions: int
    turns: int
    bytes: int
    span_start: datetime | None
    span_end: datetime | None
    models: tuple[str, ...]

    @property
    def span(self) -> Span | None:
        return (
            (self.span_start, self.span_end)
            if self.span_start is not None and self.span_end is not None
            else None
        )

    @classmethod
    def from_object(cls, obj: SessionObject) -> SessionStats:
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


class SessionHandler:
    """Identify and load Claude, Codex, OpenClaw, Hermes, and Agy sessions."""

    name = "session"

    def __init__(self) -> None:
        self._cache: dict[Path, tuple[Signature, SessionObject]] = {}
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
        self._turn_readers = {
            "cx": self._codex_turns,
            "cc": self._claude_code_turns,
            "openclaw": self._openclaw_turns,
            "agy": self._agy_turns,
            "hermes": self._hermes_turns,
        }
        self._export_recognizers = (
            ("chatgpt", self._is_chatgpt),
            ("claude", self._is_claude),
        )
        self._export_ids = {
            "chatgpt": ("id", "conversation_id"),
            "claude": ("uuid", "id"),
        }
        self._export_times = {
            "chatgpt": ("create_time", "update_time"),
            "claude": ("created_at", "updated_at"),
        }
        self._export_turn_readers = {
            "chatgpt": self._chatgpt_turns,
            "claude": self._claude_turns,
        }

    @sync
    async def identify(self, path: Path) -> bool:
        return await asyncio.to_thread(self.identify_sync, path)

    def identify_sync(self, path: Path) -> bool:
        path = _absolute(path)
        if path.is_dir() and not path.is_symlink():
            if self._home_harness(path) is not None or self._agy_session_folder(path):
                return True
            try:
                children = tuple(path.iterdir())
            except OSError:
                return False  # a folder that will not be listed holds no session that can be read
            return any(
                child.is_file()
                and (
                    self._export_members(child)
                    or self._harness(self._head(child)) is not None
                )
                for child in children
            )
        return path.is_file() and (
            bool(self._export_members(path))
            or self._harness(self._head(path)) is not None
        )

    @sync
    async def __call__(self, path: Path) -> tuple[SessionStats, SessionObject]:
        return await asyncio.to_thread(self.call_sync, path)

    def call_sync(self, path: Path) -> tuple[SessionStats, SessionObject]:
        path = _absolute(path)
        if path.is_file():
            if members := self._export_members(path):
                obj: SessionObject = self._export(path, members)
            else:
                obj = self._file(path)
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
        if not isinstance(obj, SessionFile):
            raise ValueError(f"{obj.path}: normalization requires one session")
        if obj.location is not None:
            raise ValueError(f"{obj.location}: normalization requires one session file")
        if obj.uid is None:
            raise ValueError(f"{obj.path}: session has no immutable id")
        return obj.name

    def invalidate(self, path: Path | None = None) -> None:
        if path is None:
            self._cache.clear()
            return
        path = _absolute(path)
        for key in tuple(self._cache):
            if key == path or path in key.parents:
                self._cache.pop(key, None)

    def _file(self, path: Path) -> SessionFile:
        signature = _signature(path.stat())
        cached = self._cache.get(path)
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
        turns = self._turn_readers[harness](records)
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
        self._cache[path] = (signature, item)
        return item

    def _sessions(self, path: Path) -> tuple[SessionFile, ...]:
        if members := self._export_members(path):
            return self._export(path, members).files
        return (
            (self._file(path),) if self._harness(self._head(path)) is not None else ()
        )

    def _export(
        self,
        path: Path,
        members: Sequence[zipfile.ZipInfo],
    ) -> SessionFolder:
        signature = _signature(path.stat())
        cached = self._cache.get(path)
        if (
            cached is not None
            and cached[0] == signature
            and isinstance(cached[1], SessionFolder)
        ):
            return cached[1]
        files: list[SessionFile] = []
        try:
            with zipfile.ZipFile(path) as archive:
                for member in members:
                    with archive.open(member) as stream:
                        conversations = json.load(stream, strict=False)
                    if not isinstance(conversations, list):
                        raise ValueError(
                            f"{path}::{member.filename}: conversations are not a list"
                        )
                    for conversation in conversations:
                        if not isinstance(conversation, Mapping):
                            raise ValueError(
                                f"{path}::{member.filename}: conversation is not an object"
                            )
                        harness = self._export_harness(conversation)
                        if harness is None:
                            raise ValueError(
                                f"{path}::{member.filename}: conversation format is not identifiable"
                            )
                        files.append(
                            self._export_file(
                                path, member.filename, harness, conversation
                            )
                        )
        except (
            OSError,
            UnicodeDecodeError,
            zipfile.BadZipFile,
            json.JSONDecodeError,
        ) as error:
            raise ValueError(
                f"{path}: cannot read session export ZIP: {error}"
            ) from error
        if not files:
            raise ValueError(f"{path}: session export contains no conversations")
        item = SessionFolder(path, self._one_harness(path, files), tuple(files))
        self._cache[path] = (signature, item)
        return item

    def _export_file(
        self,
        location: Path,
        member: str,
        harness: Harness,
        conversation: Mapping[str, Any],
    ) -> SessionFile:
        uid = next(
            (
                value.strip()
                for key in self._export_ids[harness]
                if isinstance(value := conversation.get(key), str) and value.strip()
            ),
            None,
        )
        if uid is None:
            raise ValueError(f"{location}::{member}: conversation has no immutable id")
        turns = self._export_turn_readers[harness](conversation)
        timestamps = [turn.timestamp for turn in turns if turn.timestamp is not None]
        timestamps += [
            stamp
            for key in self._export_times[harness]
            if (stamp := valid_time(self._stamp(conversation.get(key)))) is not None
        ]
        return SessionFile(
            path=_record_path(member),
            harness=harness,
            uid=uid,
            parent_uid=None,
            subagent=False,
            records=(conversation,),
            turns=turns,
            span=(min(timestamps), max(timestamps)) if timestamps else None,
            models=self._models((conversation,)),
            topic=self._topic(turns),
            location=location,
        )

    @staticmethod
    def _export_members(path: Path) -> tuple[zipfile.ZipInfo, ...]:
        try:
            with zipfile.ZipFile(path) as archive:
                return tuple(
                    sorted(
                        (
                            member
                            for member in archive.infolist()
                            if not member.is_dir()
                            and EXPORT_MEMBER.fullmatch(
                                PurePosixPath(member.filename).name
                            )
                        ),
                        key=lambda member: member.filename.casefold(),
                    )
                )
        except OSError, zipfile.BadZipFile:
            return ()

    def _export_harness(self, conversation: Mapping[str, Any]) -> Harness | None:
        matches = tuple(
            harness
            for harness, recognize in self._export_recognizers
            if recognize(conversation)
        )
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _one_harness(path: Path, files: Sequence[SessionFile]) -> Harness:
        harnesses = tuple(dict.fromkeys(file.harness for file in files))
        if len(harnesses) != 1:
            raise ValueError(f"{path}: contains multiple session harnesses")
        return harnesses[0]

    def _harness(
        self,
        records: Sequence[Mapping[str, Any]],
        hint: Harness | None = None,
    ) -> Harness | None:
        return next(
            (harness for harness, recognize in self._recognizers if recognize(records)),
            hint,
        )

    @staticmethod
    def _is_codex(records: Sequence[Mapping[str, Any]]) -> bool:
        return any(
            record.get("type")
            in ("session_meta", "turn_context", "event_msg", "response_item")
            and isinstance(record.get("payload"), Mapping)
            for record in records
        )

    @staticmethod
    def _is_claude_code(records: Sequence[Mapping[str, Any]]) -> bool:
        return any(
            isinstance(record.get("sessionId"), str)
            or record.get("type") == "teleported-from"
            or isinstance(record.get("uuid"), str)
            or isinstance(record.get("parentUuid"), str)
            for record in records
        )

    @staticmethod
    def _is_openclaw(records: Sequence[Mapping[str, Any]]) -> bool:
        return any(isinstance(record.get("modelId"), str) for record in records)

    @staticmethod
    def _is_agy(records: Sequence[Mapping[str, Any]]) -> bool:
        return any(
            record.get("type") in ("USER_INPUT", "PLANNER_RESPONSE")
            and record.get("source") in ("USER_EXPLICIT", "MODEL")
            and isinstance(record.get("created_at"), str)
            for record in records
        )

    @staticmethod
    def _is_hermes(records: Sequence[Mapping[str, Any]]) -> bool:
        return any(
            record.get("role") == "session_meta"
            and isinstance(record.get("session_id"), str)
            for record in records
        )

    @staticmethod
    def _is_chatgpt(conversation: Mapping[str, Any]) -> bool:
        return isinstance(conversation.get("mapping"), Mapping) and isinstance(
            conversation.get("current_node"), str
        )

    @staticmethod
    def _is_claude(conversation: Mapping[str, Any]) -> bool:
        return isinstance(conversation.get("chat_messages"), list) and isinstance(
            conversation.get("uuid"), str
        )

    @staticmethod
    def _codex_uid(records: Sequence[Mapping[str, Any]], path: Path) -> str | None:
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
        return cls._record_uid(records, ID_KEYS)

    @classmethod
    def _openclaw_uid(
        cls, records: Sequence[Mapping[str, Any]], path: Path
    ) -> str | None:
        return cls._record_uid(records, ("id", "session_id"))

    @classmethod
    def _hermes_uid(
        cls, records: Sequence[Mapping[str, Any]], path: Path
    ) -> str | None:
        return cls._record_uid(records, ID_KEYS)

    @staticmethod
    def _record_uid(
        records: Sequence[Mapping[str, Any]], keys: Sequence[str]
    ) -> str | None:
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

    @classmethod
    def _chatgpt_turns(cls, conversation: Mapping[str, Any]) -> tuple[SessionTurn, ...]:
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
            item
            for node in reversed(chain)
            if isinstance(message := node.get("message"), Mapping)
            and isinstance(author := message.get("author"), Mapping)
            and isinstance(content := message.get("content"), Mapping)
            and content.get("content_type") in ("text", "multimodal_text")
            for item in [
                cls._turn(
                    author.get("role"),
                    content.get("parts"),
                    message.get("create_time"),
                )
            ]
            if item is not None
        )

    @classmethod
    def _claude_turns(cls, conversation: Mapping[str, Any]) -> tuple[SessionTurn, ...]:
        return tuple(
            item
            for message in conversation["chat_messages"]
            if isinstance(message, Mapping)
            for item in [
                cls._turn(
                    message.get("sender"),
                    message.get("content"),
                    message.get("created_at"),
                )
            ]
            if item is not None
        )

    @staticmethod
    def _records(path: Path) -> tuple[Mapping[str, Any], ...]:
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
        except OSError, UnicodeDecodeError, json.JSONDecodeError:
            return ()
        return tuple(found)

    @classmethod
    def _walk_values(cls, value: Any) -> Iterator[tuple[str, Any]]:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                yield str(key), nested
                yield from cls._walk_values(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from cls._walk_values(nested)

    @staticmethod
    def _stamp(value: Any) -> datetime | None:
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
            except OSError, OverflowError, ValueError:
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
        return cls._uniq(
            value
            for record in records
            for key, value in cls._walk_values(record)
            if key in MODEL_KEYS
        )

    @staticmethod
    def _parent(records: Sequence[Mapping[str, Any]]) -> tuple[str | None, bool]:
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
        return tuple(
            dict.fromkeys(
                value.strip()
                for value in values
                if isinstance(value, str) and value.strip()
            )
        )

    @staticmethod
    def _home_harness(path: Path) -> Harness | None:
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


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _signature(stat: os.stat_result) -> Signature:
    return stat.st_mode, stat.st_size, stat.st_mtime_ns


def _display_order(path: Path) -> tuple[bool, str]:
    return not (path.is_dir() and not path.is_symlink()), path.name.casefold()


def _record_path(value: str) -> PurePosixPath:
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
        except OSError, OverflowError, ValueError:
            return None
    else:
        try:
            parsed = datetime(*value)
        except TypeError, ValueError:
            return None
    return valid_time(parsed if parsed.tzinfo is not None else parsed.astimezone())


def _complete_archive_records(
    location: Path,
    records: Sequence[Record],
) -> tuple[Record, ...]:
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
    root = Record(PurePosixPath("."), True, 0, None, ())
    children = [
        record for record in records if record.path.parent == PurePosixPath(".")
    ]
    return FileHandler._folder_stats(root, children)


def _stats_span(stats: Any) -> Span | None:
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


session_handler = SessionHandler()
archive_handler = ArchiveHandler()
git_handler = GitHandler()
file_handler = FileHandler(session_handler, archive_handler, git_handler)
