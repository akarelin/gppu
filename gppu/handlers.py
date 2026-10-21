"""Handlers: a universal way to get information about a file or a folder.

Handler(path) detects what kind of handler the path needs and returns it, holding the path's information:

    info = Handler('D:/Dev/gppu/README.md')    # a MarkdownHandler
    info.title, info.tags, info.span, info.metadata

Each kind of file or folder is one class. Its `handles(path)` says whether a path is its own, and its
constructor reads it. A more specific kind is a subclass of a more general one and is asked only after the
general one handles the path, so the answer is the most specific kind. A program adds a kind by subclassing:

    class BillingCSVHandler(CSVHandler):
        time_keys = (*CSVHandler.time_keys, 'billed_at')

A handler reads the path it is given and nothing else: no index, no location, no fsspec. A read that fails
raises.
"""
from __future__ import annotations

import csv
import fnmatch
import os
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from typing import Any

import yaml

from .gppu import MY_TZ, Path, TimeSpan, full_path

# Times tools write in place of a time: Windows FILETIME zero, Unix epoch zero, DOS zero, and the constant
# Android build tools stamp on every APK member. Anything at or before DOS zero is not a time either.
PLACEHOLDER_TIMES = (
    (1601, 1, 1, 0, 0, 0),
    (1970, 1, 1, 0, 0, 0),
    (1980, 1, 1, 0, 0, 0),
    (1981, 1, 1, 1, 1, 2),
)
FUTURE_TOLERANCE = timedelta(days=1)
# The record-level time keys of the harnesses and exporters; a Gemini CLI chat's startTime and lastUpdated among them.
TIME_KEYS = ("timestamp", "ts", "started_at", "session_start", "time", "created_at", "startTime", "lastUpdated")
LOG_TIMESTAMP = re.compile(
    r"^\s*[\[(]?(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
IGNORED_NAME_PATTERNS = ("*.tmp", "*.bak", "*.swp", "~$*", "Thumbs.db", ".DS_Store", "desktop.ini")
IGNORED_FOLDER_PATTERNS = (
    ".git", ".svn", "__pycache__", ".venv", "venv", "node_modules", ".idea", ".vscode",
    ".SynologyWorking Directory", ".SynologyWorkingDirectory", "$RECYCLE.BIN", "RECYCLE.BIN",
    "System Volume Information", "OneDriveTemp", "Cache", ".cache",
)
WINDOWS_SYSTEM = 4


class Handler:
    """A file or a folder and what is known about it: its size, when it was modified, the span it covers.

    Handler(path) returns the most specific kind of handler for the path; a kind's own class, called with a
    path that is not its kind, raises ValueError.
    """

    path: Path
    size: int
    modified: datetime | None
    span: TimeSpan | None = None

    def __new__(cls, path: str | Path) -> Handler:
        path = full_path(path)
        kind = cls._kind(path)
        if kind is None:
            raise ValueError(f"{path}: not a {cls.__name__}")
        return super().__new__(kind)

    @classmethod
    def _kind(cls, path: Path) -> type[Handler] | None:
        if not cls.handles(path):
            return None
        for kind in cls.__subclasses__():
            if (found := kind._kind(path)) is not None:
                return found
        return cls

    @classmethod
    def handles(cls, path: Path) -> bool:
        """Whether this path is this kind's own."""
        return path.exists() or path.is_symlink()

    def __init__(self, path: str | Path) -> None:
        self.path = full_path(path)
        stat = self.path.stat(follow_symlinks=False)
        self.size = 0 if self.path.is_dir() and not self.path.is_symlink() else stat.st_size
        self.modified = self.valid_time(datetime.fromtimestamp(stat.st_mtime, timezone.utc))

    @property
    def kind(self) -> str:
        """The kind's name: markdown for MarkdownHandler."""
        return type(self).__name__.removesuffix("Handler").casefold()

    @property
    def metadata(self) -> dict[str, Any]:
        """What this kind knows about the path."""
        return {"kind": self.kind, "size": self.size, "modified": self.modified, "span": self.span}

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self.path)!r})"

    @staticmethod
    def valid_time(value: datetime | None) -> datetime | None:
        """A recorded time, or None for a placeholder, a time at or before DOS zero, or a future time."""
        if value is None:
            return None
        fields = value.timetuple()[:6]
        utc_fields = value.astimezone(timezone.utc).timetuple()[:6] if value.tzinfo is not None else fields
        if fields in PLACEHOLDER_TIMES or utc_fields in PLACEHOLDER_TIMES or fields <= PLACEHOLDER_TIMES[2]:
            return None
        now = datetime.now(timezone.utc) if value.tzinfo is not None else datetime.now()
        return None if value > now + FUTURE_TOLERANCE else value

    @staticmethod
    def local(value: datetime) -> datetime:
        """A time without an offset is in gppu's MY_TZ."""
        return value if value.tzinfo is not None else value.replace(tzinfo=MY_TZ)

    @staticmethod
    def spanning(times: list[datetime] | tuple[datetime, ...]) -> TimeSpan | None:
        """The earliest to the latest of times, or None when there are none."""
        return TimeSpan(start=min(times), end=max(times)) if times else None


class IgnoredHandler(Handler):
    """A file or a folder an ignore rule names; a walk shows it and never descends into it.

    The rules are FileIndexer's global ones. A folder is not ignored for starting with a dot or for being
    hidden: the named list is the whole rule. A Windows folder with the system attribute is ignored; a
    filesystem root, which has no name, never is.
    """

    name_patterns = IGNORED_NAME_PATTERNS
    folder_patterns = IGNORED_FOLDER_PATTERNS

    @classmethod
    def handles(cls, path: Path) -> bool:
        return cls.reason(path) is not None

    @classmethod
    def reason(cls, path: Path) -> str | None:
        """The rule that names this path, or None."""
        if not path.name:
            return None
        folder = path.is_dir() and not path.is_symlink()
        if not folder and not path.is_file():
            return None
        if pattern := cls.match(path.name, cls.name_patterns):
            return f"name:{pattern}"
        if not folder:
            return None
        if pattern := cls.match(path.name, cls.folder_patterns):
            return f"folder:{pattern}"
        if getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0) & WINDOWS_SYSTEM:
            return "folder:FILE_ATTRIBUTE_SYSTEM"
        return None

    @staticmethod
    def match(name: str, patterns: tuple[str, ...]) -> str | None:
        return next((pattern for pattern in patterns if fnmatch.fnmatchcase(name, pattern)), None)

    @property
    def metadata(self) -> dict[str, Any]:
        return {**super().metadata, "reason": self.reason(self.path)}


class FolderHandler(Handler):
    """A folder and what it directly holds: its files, folders and bytes, and the span of its files.

    A subfolder's modified time is when something was added to it, so the span is its files' alone.
    """

    files: int
    folders: int
    bytes: int

    @classmethod
    def handles(cls, path: Path) -> bool:
        return path.is_dir() and not path.is_symlink()

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)
        self.files = self.folders = self.bytes = 0
        times = []
        with os.scandir(self.path) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    self.folders += 1
                    continue
                stat = entry.stat(follow_symlinks=False)
                self.files += 1
                self.bytes += stat.st_size
                if (time := self.valid_time(datetime.fromtimestamp(stat.st_mtime, timezone.utc))) is not None:
                    times.append(time)
        self.span = self.spanning(times)

    @property
    def metadata(self) -> dict[str, Any]:
        return {**super().metadata, "files": self.files, "folders": self.folders, "bytes": self.bytes}


class FileHandler(Handler):
    """A file of a kind no more specific handler knows: its size and modified time."""

    @classmethod
    def handles(cls, path: Path) -> bool:
        return path.is_file()


class SqliteHandler(FileHandler):
    """A SQLite file, known by its header, and its tables with their columns.

    It is opened immutable, so SQLite writes no -wal or -shm beside it, and no row is read: what is in the
    tables is the file's content, not what the file is.
    """

    MAGIC = b"SQLite format 3\x00"

    tables: dict[str, tuple[str, ...]]

    @classmethod
    def handles(cls, path: Path) -> bool:
        with path.open("rb") as stream:
            return stream.read(len(cls.MAGIC)) == cls.MAGIC

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
            names = [name for (name,) in database.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            self.tables = {name: tuple(row[1] for row in database.execute(f'PRAGMA table_info("{name}")'))
                           for name in names}

    @property
    def metadata(self) -> dict[str, Any]:
        return {**super().metadata, "tables": {name: list(columns) for name, columns in self.tables.items()}}


class MarkdownHandler(FileHandler):
    """A .md file and its whole YAML frontmatter.

    Frontmatter is there when the first line is --- and a later line closes it with ---; it is an empty
    document or a mapping, and its timestamps stay as written. The body is not read. title and name are
    each the field of that name, then the other one, then the file's stem. tags is a list or one value.
    The span is created to updated, both required; a date starts at midnight, a time without an offset is
    in MY_TZ.
    """

    frontmatter: dict[str, Any]

    class _Loader(yaml.SafeLoader):
        """Safe YAML that keeps timestamp scalars as written."""

    _Loader.yaml_implicit_resolvers = {
        first: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:timestamp"]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    @classmethod
    def handles(cls, path: Path) -> bool:
        return path.suffix.casefold() == ".md"

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)
        self.frontmatter = self._frontmatter()
        created, updated = self._time(self.frontmatter.get("created")), self._time(self.frontmatter.get("updated"))
        if created is not None and updated is not None:
            self.span = TimeSpan(start=min(created, updated), end=max(created, updated))

    def _frontmatter(self) -> dict[str, Any]:
        with self.path.open(encoding="utf-8-sig") as stream:
            if stream.readline().strip() != "---":
                return {}
            lines = []
            for line in stream:
                if line.strip() == "---":
                    break
                lines.append(line)
            else:
                raise ValueError(f"{self.path}: YAML frontmatter has no closing ---")
        frontmatter = yaml.load("".join(lines), Loader=self._Loader)
        if frontmatter is None:
            return {}
        if not isinstance(frontmatter, dict):
            raise ValueError(f"{self.path}: YAML frontmatter must be a mapping")
        return frontmatter

    @property
    def title(self) -> str:
        value = self.frontmatter.get("title", self.frontmatter.get("name"))
        return self.path.stem if value is None else str(value)

    @property
    def name(self) -> str:
        value = self.frontmatter.get("name", self.frontmatter.get("title"))
        return self.path.stem if value is None else str(value)

    @property
    def tags(self) -> tuple[str, ...]:
        value = self.frontmatter.get("tags")
        values = [] if value is None else value if isinstance(value, list) else [value]
        return tuple(str(item) for item in values if item is not None)

    @property
    def metadata(self) -> dict[str, Any]:
        return {**super().metadata, **self.frontmatter}

    @classmethod
    def _time(cls, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return cls.local(value)
        if isinstance(value, date):
            return cls.local(datetime(value.year, value.month, value.day))
        if isinstance(value, str):
            try:
                return cls.local(datetime.fromisoformat(value.strip()))
            except ValueError:
                return None
        return None


class CSVHandler(FileHandler):
    """A .csv file: its header, its rows as text, and the span of the times in its time columns.

    The table is read strictly in the excel dialect. A time column is one whose header, stripped and in any
    case, is one of time_keys; its values are ISO dates or times, Unix seconds above 1,000,000,000 or
    milliseconds above 10,000,000,000, or one of a subclass's time_formats for strptime. A time without an
    offset is in MY_TZ; placeholders and future times do not count.
    """

    time_keys = TIME_KEYS
    time_formats: tuple[str, ...] = ()

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    @classmethod
    def handles(cls, path: Path) -> bool:
        return path.suffix.casefold() == ".csv"

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)
        with self.path.open(encoding="utf-8-sig", newline="") as stream:
            records = tuple(tuple(row) for row in csv.reader(stream, strict=True))
        self.header = records[0] if records else ()
        self.rows = records[1:]
        keys = {key.casefold() for key in self.time_keys}
        columns = [index for index, name in enumerate(self.header) if name.strip().casefold() in keys]
        self.span = self.spanning([time for row in self.rows for index in columns
                                   if index < len(row) and (time := self._time(row[index])) is not None])

    @property
    def metadata(self) -> dict[str, Any]:
        return {**super().metadata, "header": self.header, "rows": len(self.rows)}

    @classmethod
    def _time(cls, value: str) -> datetime | None:
        value = value.strip()
        if not value:
            return None
        try:
            number = float(value)
        except ValueError:
            number = 0
        if number > 1_000_000_000:
            try:
                return cls.valid_time(datetime.fromtimestamp(number / 1000 if number > 10_000_000_000 else number, timezone.utc))
            except (OSError, OverflowError, ValueError):
                return None
        try:
            return cls.valid_time(cls.local(datetime.fromisoformat(value.replace("Z", "+00:00"))))
        except ValueError:
            pass
        for time_format in cls.time_formats:
            try:
                return cls.valid_time(cls.local(datetime.strptime(value, time_format)))
            except ValueError:
                continue
        return None


class LogHandler(FileHandler):
    """A .log file: its rows, and the span of the times that begin them.

    A row's time comes after optional whitespace and one optional [ or (, as YYYY-MM-DD, T or a space,
    HH:MM:SS, an optional fraction after a dot or a comma, and an optional Z or offset. A time without an
    offset is in MY_TZ; placeholders and future times do not count.
    """

    rows: tuple[str, ...]

    @classmethod
    def handles(cls, path: Path) -> bool:
        return path.suffix.casefold() == ".log"

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)
        self.rows = tuple(self.path.read_text(encoding="utf-8-sig").splitlines())
        self.span = self.spanning([time for row in self.rows if (time := self._time(row)) is not None])

    @property
    def metadata(self) -> dict[str, Any]:
        return {**super().metadata, "rows": len(self.rows)}

    @classmethod
    def _time(cls, row: str) -> datetime | None:
        if (match := LOG_TIMESTAMP.match(row)) is None:
            return None
        try:
            return cls.valid_time(cls.local(datetime.fromisoformat(match.group("timestamp"))))
        except ValueError:
            return None


class EmailHandler(FileHandler):
    """A .msg or .eml file and what its name says: YYMMDD.HHMMSS - subject - party[ - collision].

    The message itself is not read. The time is in MY_TZ; splitting from the right lets the subject hold
    the separator. A name outside the convention leaves timestamp, subject, party and collision None.
    """

    timestamp: datetime | None = None
    subject: str | None = None
    party: str | None = None
    collision: int | None = None

    @classmethod
    def handles(cls, path: Path) -> bool:
        return path.suffix.casefold() in (".eml", ".msg")

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)
        stamp, separator, rest = self.path.stem.partition(" - ")
        content, separator2, party = rest.rpartition(" - ")
        if not (separator and separator2):
            return
        collision = None
        if party.isdecimal():
            collision = int(party)
            content, separator, party = content.rpartition(" - ")
            if not separator:
                return
        if not content.strip() or not party.strip():
            return
        try:
            timestamp = datetime.strptime(stamp, "%y%m%d.%H%M%S").replace(tzinfo=MY_TZ)
        except ValueError:
            return
        self.timestamp, self.subject, self.party, self.collision = (
            self.valid_time(timestamp), content.strip(), party.strip(), collision)
        if self.timestamp is not None:
            self.span = TimeSpan(start=self.timestamp, end=self.timestamp)

    @property
    def metadata(self) -> dict[str, Any]:
        named = {"timestamp": self.timestamp, "subject": self.subject, "party": self.party, "collision": self.collision}
        return {**super().metadata, **{key: value for key, value in named.items() if value is not None}}
