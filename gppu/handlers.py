"""Handlers: a universal way to get information about a file or a folder.

There is a handler for every type of data, and probe, which knows every handler there is (HANDLERS) and, given a
path whose type is not known in advance, which handler to call:

    handler = probe('D:/Dev/gppu/README.md')            # MarkdownHandler; await probe(...) in an event loop
    record = handler.parse('D:/Dev/gppu/README.md')     # await handler.parse(...) in an event loop

A handler is a class of class methods. `identify(path, stat, head)` says whether the path is of its type from what
probe gives it: the path, its stat, and `head(n)`, the file's first n bytes. A handler does no I/O of its own there,
so probing a path takes one stat and at most one read of the most bytes a handler asks for: a suffix needs none, a
SQLite file's header 16 once its suffix says SQLite, a session's first lines up to SESSION_HEAD once its suffix
says .jsonl. probe and parse are asynchronous, awaited inside an event loop and returned directly outside one.
`parse(path)` reads the path into a record, what
Linked Data holds of the thing: its type, subtype, name, span, data and, in meta, the path it was read from; a
session's record also has its messages. A subtype is a subclass of its type: it identifies a path only where its
type does, and its parse adds to its type's. probe returns the most specific handler that identifies the path. A
program adds a handler by subclassing and appending it to HANDLERS:

    class BillingCSVHandler(CSVHandler):
        time_keys = (*CSVHandler.time_keys, 'billed_at')

    HANDLERS.append(BillingCSVHandler)

A handler reads the path it is given and nothing else: no index, no location, no fsspec. A read that fails raises.
"""
from __future__ import annotations

import asyncio
import csv
import html
import json
import fnmatch
import os
import re
import sqlite3
import stat as stat_module
from collections.abc import Iterator, Mapping
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID, uuid5

import yaml

from .gppu import MY_TZ, Path, full_path, sync

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
Harness = Literal[
    "chatgpt",
    "cx",
    "claude",
    "cc",
    "gemini",
    "copilot",
    "agy",
    "hermes",
    "openclaw",
    "manus",
]
MODEL_KEYS = ("model", "modelId", "model_slug", "default_model_slug")
ID_KEYS = ("sessionId", "session_id", "id", "remoteSessionId")
ROLES = ("user", "assistant")
SNIFF = 8
UNITS = (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))
UNSAFE = '\\/:*?"<>|\r\n\t'
NAME_LIMIT = 254
PREAMBLE = ("# AGENTS.md instructions",)
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
ENVELOPE = re.compile(r"\A.*?^##\s*My request for Codex:[^\S\n]*$", re.S | re.M)
REALTIME_INPUT = re.compile(
    r"<realtime_delegation>\s*<input>(.*?)</input>", re.I | re.S
)
HOMES: dict[Harness, tuple[str, ...]] = {
    "hermes": ("state.db",),
    "agy": ("antigravity_state.pbtxt", "jetski_state.pbtxt"),
}
# Linked Data's sessions (RAN Projects/ld/sessions.py): a name is the first line of a text, clipped; the lines of Claude
# Code that name its session and the key each holds the name in; the Codex payloads that are messages and the roles of its
# messages; how Codex opens the AGENTS.md it reads into a session; the namespace of a Codex message's id; and the tags a
# prompt is wrapped in.
NAME_LEN = 120
TITLES = {"ai-title": "aiTitle", "agent-name": "agentName", "custom-title": "customTitle"}
CODEX_MESSAGES = {"message", "function_call", "custom_tool_call", "function_call_output", "custom_tool_call_output", "agent_message"}
CODEX_ROLES = {"user": "user", "assistant": "agent", "developer": "user"}
CODEX_INSTRUCTIONS = "# AGENTS.md instructions"
NAMESPACE = UUID("4936da84-fd80-59f2-90ef-1d5b9672ceb6")
OPENING = re.compile(r"\s*<([\w:-]+)([^>]*)>")
SUMMARY = re.compile(r'\bsummary="([^"]*)"')
ELEMENT = re.compile(r"<([\w:-]+)[^>]*>.*?</\1>", re.S)
TAGS = re.compile(r"</?[\w:-]+[^>]*>")
# The most a session's identification reads: the first SNIFF objects of 5,385 real sessions identified their harness
# within 434 KB, half of them within 4 KB.
SESSION_HEAD = 512 * 1024
SESSION_UID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


class Head:
    """A file's first bytes, read once for probing: head(n) is the first n, read again only when a handler asks for
    more than it holds. A folder has none."""

    def __init__(self, path: Path, stat: os.stat_result) -> None:
        self.path, self.file, self.data = path, stat_module.S_ISREG(stat.st_mode), b""

    def __call__(self, n: int) -> bytes:
        if self.file and n > len(self.data):
            with self.path.open("rb") as stream:
                self.data = stream.read(n)
        return self.data[:n]


class Handler:
    """The base of every handler: a file or a folder, its size and when it was modified.

    `type` is the class below Handler a handler descends from, file, folder or ignored, unless the handler names
    its own; `subtype` is the handler's own name, markdown for MarkdownHandler, None for a type itself.
    """

    type: str
    subtype: str | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        top = next(base for base in reversed(cls.__mro__) if issubclass(base, Handler) and base is not Handler)
        if "type" not in cls.__dict__:
            cls.type = top.type if "type" in top.__dict__ else top.__name__.removesuffix("Handler").casefold()
        name = cls.__name__.removesuffix("Handler").casefold()
        if "subtype" not in cls.__dict__:
            cls.subtype = None if cls is top else name

    @classmethod
    def identify(cls, path: Path, stat: os.stat_result, head: Head) -> bool:
        """Whether the path is of this handler's type: anything that is there is."""
        return True

    @classmethod
    @sync
    async def parse(cls, path: str | Path) -> dict[str, Any]:
        """The path as a Linked Data record: its size and modified time as its stat gives them. A handler's parse adds
        to its type's; what it reads, it reads in a thread. Awaited inside an event loop, returned directly outside
        one."""
        path = full_path(path)
        stat = await asyncio.to_thread(path.stat, follow_symlinks=False)
        return {"type": cls.type, "subtype": cls.subtype, "name": path.name or str(path), "span": None,
                "data": {"size": stat.st_size, "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc)},
                "meta": {"source": str(path)}}

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
    def spanning(times: list[datetime] | tuple[datetime, ...]) -> dict[str, datetime] | None:
        """The span from the earliest to the latest of times, or None when there are none."""
        return {"start": min(times), "end": max(times)} if times else None


class IgnoredHandler(Handler):
    """A file or a folder an ignore rule names; a walk shows it and never descends into it.

    The rules are FileIndexer's global ones. A folder is not ignored for starting with a dot or for being
    hidden: the named list is the whole rule. A Windows folder with the system attribute is ignored; a
    filesystem root, which has no name, never is.
    """

    name_patterns = IGNORED_NAME_PATTERNS
    folder_patterns = IGNORED_FOLDER_PATTERNS

    @classmethod
    def identify(cls, path: Path, stat: os.stat_result, head: Head) -> bool:
        return cls.reason(path, stat) is not None

    @classmethod
    @sync
    async def parse(cls, path: str | Path) -> dict[str, Any]:
        record = await super().parse(path)
        path = full_path(path)
        record["data"]["reason"] = cls.reason(path, await asyncio.to_thread(path.stat, follow_symlinks=False))
        return record

    @classmethod
    def reason(cls, path: Path, stat: os.stat_result) -> str | None:
        """The rule that names this path, or None."""
        if not path.name:
            return None
        folder = stat_module.S_ISDIR(stat.st_mode)
        if not folder and not stat_module.S_ISREG(stat.st_mode):
            return None
        if pattern := cls.match(path.name, cls.name_patterns):
            return f"name:{pattern}"
        if not folder:
            return None
        if pattern := cls.match(path.name, cls.folder_patterns):
            return f"folder:{pattern}"
        if getattr(stat, "st_file_attributes", 0) & WINDOWS_SYSTEM:
            return "folder:FILE_ATTRIBUTE_SYSTEM"
        return None

    @staticmethod
    def match(name: str, patterns: tuple[str, ...]) -> str | None:
        return next((pattern for pattern in patterns if fnmatch.fnmatchcase(name, pattern)), None)


class SymlinkHandler(Handler):
    """A symbolic link, as stat gives it, and the path it points to; what is there is the target's own, probed at
    the target."""

    @classmethod
    def identify(cls, path: Path, stat: os.stat_result, head: Head) -> bool:
        return stat_module.S_ISLNK(stat.st_mode)

    @classmethod
    @sync
    async def parse(cls, path: str | Path) -> dict[str, Any]:
        record = await super().parse(path)
        record["data"]["target"] = await asyncio.to_thread(os.readlink, path)
        return record


class JunctionHandler(Handler):
    """A Windows junction, as stat gives it, and the folder it points to; what is there is the target's own, probed
    at the target."""

    @classmethod
    def identify(cls, path: Path, stat: os.stat_result, head: Head) -> bool:
        return getattr(stat, "st_reparse_tag", 0) == getattr(stat_module, "IO_REPARSE_TAG_MOUNT_POINT", None)

    @classmethod
    @sync
    async def parse(cls, path: str | Path) -> dict[str, Any]:
        record = await super().parse(path)
        record["data"]["target"] = await asyncio.to_thread(os.readlink, path)
        return record


class FolderHandler(Handler):
    """A folder and what it directly holds: its files, folders and bytes, and the span of its files.

    A subfolder's modified time is when something was added to it, so the span is its files' alone.
    """

    @classmethod
    def identify(cls, path: Path, stat: os.stat_result, head: Head) -> bool:
        return stat_module.S_ISDIR(stat.st_mode)

    @classmethod
    @sync
    async def parse(cls, path: str | Path) -> dict[str, Any]:
        record = await super().parse(path)
        entries = await asyncio.to_thread(cls._entries, full_path(path))
        files = [stat for folder, stat in entries if not folder]
        times = [time for stat in files if (time := cls.valid_time(datetime.fromtimestamp(stat.st_mtime, timezone.utc)))]
        record["data"].update(files=len(files), folders=len(entries) - len(files), bytes=sum(stat.st_size for stat in files))
        record["span"] = cls.spanning(times)
        return record

    @staticmethod
    def _entries(path: Path) -> list[tuple[bool, os.stat_result | None]]:
        """Each entry the folder directly holds: whether it is a folder, and a file's stat."""
        with os.scandir(path) as entries:
            return [(True, None) if entry.is_dir(follow_symlinks=False) else (False, entry.stat(follow_symlinks=False))
                    for entry in entries]


class FileHandler(Handler):
    """A file of a type no more specific handler identifies: its size and modified time."""

    @classmethod
    def identify(cls, path: Path, stat: os.stat_result, head: Head) -> bool:
        return stat_module.S_ISREG(stat.st_mode)


class SqliteHandler(FileHandler):
    """A SQLite file, known by its extension and its header, and its tables with their columns.

    It is opened immutable, so SQLite writes no -wal or -shm beside it, and no row is read: what is in the
    tables is the file's content, not what the file is.
    """

    MAGIC = b"SQLite format 3\x00"
    extensions = (".sqlite", ".sqlite3", ".db")

    @classmethod
    def identify(cls, path: Path, stat: os.stat_result, head: Head) -> bool:
        return (super().identify(path, stat, head) and path.suffix.casefold() in cls.extensions
                and head(len(cls.MAGIC)) == cls.MAGIC)

    @classmethod
    @sync
    async def parse(cls, path: str | Path) -> dict[str, Any]:
        record = await super().parse(path)
        record["data"]["tables"] = await asyncio.to_thread(cls._tables, full_path(path))
        return record

    @staticmethod
    def _tables(path: Path) -> dict[str, list[str]]:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
            names = [name for (name,) in database.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            return {name: [row[1] for row in database.execute(f'PRAGMA table_info("{name}")')] for name in names}


class MarkdownHandler(FileHandler):
    """A .md file and its whole YAML frontmatter.

    Frontmatter is there when the first line is --- and a later line closes it with ---; it is an empty
    document or a mapping, and its timestamps stay as written. The body is not read. The record's name is the
    frontmatter's name, then its title, then the file's stem; data.title is its title, then its name, then the
    stem. data.tags is a list or one value. The span is created to updated, both required; a date starts at
    midnight, a time without an offset is in MY_TZ.
    """

    class _Loader(yaml.SafeLoader):
        """Safe YAML that keeps timestamp scalars as written."""

    _Loader.yaml_implicit_resolvers = {
        first: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:timestamp"]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    @classmethod
    def identify(cls, path: Path, stat: os.stat_result, head: Head) -> bool:
        return super().identify(path, stat, head) and path.suffix.casefold() == ".md"

    @classmethod
    @sync
    async def parse(cls, path: str | Path) -> dict[str, Any]:
        record = await super().parse(path)
        path = full_path(path)
        frontmatter = await asyncio.to_thread(cls._frontmatter, path)
        name, title = frontmatter.get("name", frontmatter.get("title")), frontmatter.get("title", frontmatter.get("name"))
        tags = frontmatter.get("tags")
        tags = [] if tags is None else tags if isinstance(tags, list) else [tags]
        record["name"] = path.stem if name is None else str(name)
        record["data"].update(title=path.stem if title is None else str(title),
                              tags=[str(tag) for tag in tags if tag is not None], frontmatter=frontmatter)
        created, updated = cls._time(frontmatter.get("created")), cls._time(frontmatter.get("updated"))
        if created is not None and updated is not None:
            record["span"] = cls.spanning([created, updated])
        return record

    @classmethod
    def _frontmatter(cls, path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8-sig") as stream:
            if stream.readline().strip() != "---":
                return {}
            lines = []
            for line in stream:
                if line.strip() == "---":
                    break
                lines.append(line)
            else:
                raise ValueError(f"{path}: YAML frontmatter has no closing ---")
        frontmatter = yaml.load("".join(lines), Loader=cls._Loader)
        if frontmatter is None:
            return {}
        if not isinstance(frontmatter, dict):
            raise ValueError(f"{path}: YAML frontmatter must be a mapping")
        return frontmatter

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
    """A .csv file: its header, how many rows it has, and the span of the times in its time columns.

    The table is read strictly in the excel dialect. A time column is one whose header, stripped and in any
    case, is one of time_keys; its values are ISO dates or times, Unix seconds above 1,000,000,000 or
    milliseconds above 10,000,000,000, or one of a subclass's time_formats for strptime. A time without an
    offset is in MY_TZ; placeholders and future times do not count.
    """

    time_keys = TIME_KEYS
    time_formats: tuple[str, ...] = ()

    @classmethod
    def identify(cls, path: Path, stat: os.stat_result, head: Head) -> bool:
        return super().identify(path, stat, head) and path.suffix.casefold() == ".csv"

    @classmethod
    @sync
    async def parse(cls, path: str | Path) -> dict[str, Any]:
        record = await super().parse(path)
        rows = await asyncio.to_thread(cls._rows, full_path(path))
        header, rows = (rows[0], rows[1:]) if rows else ((), [])
        keys = {key.casefold() for key in cls.time_keys}
        columns = [index for index, name in enumerate(header) if name.strip().casefold() in keys]
        record["data"].update(header=list(header), rows=len(rows))
        record["span"] = cls.spanning([time for row in rows for index in columns
                                       if index < len(row) and (time := cls._time(row[index])) is not None])
        return record

    @staticmethod
    def _rows(path: Path) -> list[tuple[str, ...]]:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return [tuple(row) for row in csv.reader(stream, strict=True)]

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
    """A .log file: how many rows it has, and the span of the times that begin them.

    A row's time comes after optional whitespace and one optional [ or (, as YYYY-MM-DD, T or a space,
    HH:MM:SS, an optional fraction after a dot or a comma, and an optional Z or offset. A time without an
    offset is in MY_TZ; placeholders and future times do not count.
    """

    @classmethod
    def identify(cls, path: Path, stat: os.stat_result, head: Head) -> bool:
        return super().identify(path, stat, head) and path.suffix.casefold() == ".log"

    @classmethod
    @sync
    async def parse(cls, path: str | Path) -> dict[str, Any]:
        record = await super().parse(path)
        rows = (await asyncio.to_thread(full_path(path).read_text, encoding="utf-8-sig")).splitlines()
        record["data"]["rows"] = len(rows)
        record["span"] = cls.spanning([time for row in rows if (time := cls._time(row)) is not None])
        return record

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
    the separator. A name outside the convention says nothing, and the record has no timestamp, subject,
    party or collision.
    """

    @classmethod
    def identify(cls, path: Path, stat: os.stat_result, head: Head) -> bool:
        return super().identify(path, stat, head) and path.suffix.casefold() in (".eml", ".msg")

    @classmethod
    @sync
    async def parse(cls, path: str | Path) -> dict[str, Any]:
        record = await super().parse(path)
        stamp, separator, rest = full_path(path).stem.partition(" - ")
        content, separator2, party = rest.rpartition(" - ")
        if not (separator and separator2):
            return record
        collision = None
        if party.isdecimal():
            collision = int(party)
            content, separator, party = content.rpartition(" - ")
            if not separator:
                return record
        if not content.strip() or not party.strip():
            return record
        try:
            timestamp = cls.valid_time(datetime.strptime(stamp, "%y%m%d.%H%M%S").replace(tzinfo=MY_TZ))
        except ValueError:
            return record
        named = {"timestamp": timestamp, "subject": content.strip(), "party": party.strip(), "collision": collision}
        record["data"].update({key: value for key, value in named.items() if value is not None})
        if timestamp is not None:
            record["span"] = cls.spanning([timestamp])
        return record


@dataclass(frozen=True)
class SessionTurn:
    """One user or assistant message of a session, and whether it was meta or on a sidechain."""

    role: str
    text: str
    timestamp: datetime | None
    meta: bool = False
    sidechain: bool = False


class SessionHandler(FileHandler):
    """A native session: a non-empty .jsonl whose first eight objects say which harness wrote it.

    The harness is told by its records, never by the file's name or folder:

    * Codex (cx): type is session_meta, turn_context, event_msg or response_item, with an object payload.
    * Copilot: a VS Code append log opening with sessionId, requests and responderUsername GitHub Copilot.
    * Gemini CLI: a header with sessionId, projectHash and startTime.
    * Claude Code (cc): a string sessionId, uuid or parentUuid, or type teleported-from.
    * OpenClaw: a string modelId.
    * Agy: USER_INPUT from USER_EXPLICIT or PLANNER_RESPONSE from MODEL, with a string created_at.
    * Hermes: role session_meta with a string session_id.

    Its record is a session, its subtype the harness. Every object of the file is read; a blank, truncated or
    non-object line is skipped. The lines of cc and cx are read as Linked Data reads them (parse_lines): the
    uid, the name, the span from the first message to the last, data.title, topic, cwd and models, meta.parent_uid,
    and the record's messages. For the other harnesses the record has the uid its harness gives, the span from
    the first record time to the last, the models named anywhere in its lines, and no messages. data.normalized_name is the file's name from its start,
    turns, duration and the first line a person typed.
    """

    type = "session"

    RECOGNIZERS = (
        ("cx", "_is_codex"), ("copilot", "_is_copilot"), ("gemini", "_is_gemini"), ("cc", "_is_claude_code"),
        ("openclaw", "_is_openclaw"), ("agy", "_is_agy"), ("hermes", "_is_hermes"),
    )
    UID = {"cx": "_codex_uid", "copilot": "_copilot_uid", "gemini": "_gemini_uid", "cc": "_claude_code_uid",
           "openclaw": "_openclaw_uid", "agy": "_agy_uid", "hermes": "_hermes_uid"}
    # What a file says of the conversation above it: Codex names a parent thread, Claude Code the session
    # that spawned the subagent. The other harnesses name none.
    PARENT = {"cx": "_parent", "cc": "_claude_code_parent"}
    TURNS = {"cx": "_codex_turns", "copilot": "_copilot_turns", "gemini": "_gemini_turns",
             "cc": "_claude_code_turns", "openclaw": "_openclaw_turns", "agy": "_agy_turns",
             "hermes": "_hermes_turns"}

    @classmethod
    def identify(cls, path: Path, stat: os.stat_result, head: Head) -> bool:
        return (super().identify(path, stat, head) and path.suffix.casefold() == ".jsonl" and stat.st_size > 0
                and cls._harness(cls._head(head(SESSION_HEAD), stat.st_size)) is not None)

    @classmethod
    @sync
    async def parse(cls, path: str | Path) -> dict[str, Any]:
        record = await super().parse(path)
        path = full_path(path)
        records = await asyncio.to_thread(cls._records, path)
        harness = cls._harness(records[:SNIFF])
        turns = getattr(cls, cls.TURNS[harness])(records)
        times = tuple(cls._timestamps(records))
        if harness == "copilot":
            created = cls.valid_time(cls._stamp(records[0]["v"].get("creationDate")))
            times = tuple(time for time in (created, *(turn.timestamp for turn in turns)) if time is not None)
        uid = getattr(cls, cls.UID[harness])(records, path)
        parent = cls.PARENT.get(harness)
        parent_uid, subagent = getattr(cls, parent)(records) if parent else (None, False)
        mainline = any(line.get("isSidechain") is False for line in records)
        sidechain = any(line.get("isSidechain") is True for line in records)
        span = cls.spanning(times)
        record["subtype"], record["uid"], record["name"], record["span"] = harness, uid, cls._topic(turns) or uid, span
        record["data"].update(subagent=subagent, sidechain_only=sidechain and not mainline, turns=len(turns),
                              normalized_name=cls.normalized_name(path, uid, turns, span))
        if parent_uid:
            record["meta"]["parent_uid"] = parent_uid
        if harness in ("cc", "cx"):
            session, messages = cls.parse_lines(harness, records)
            data = {"title": session["title"], "topic": session["topic"], "cwd": session["cwd"],
                    "models": sorted(session["models"]) or None}
            record["uid"] = session["uid"]
            record["name"] = (cls.first_line(session["title"] or "") or cls.first_line(session["name"] or "")
                              or session["uid"])
            record["span"] = cls.spanning(session["times"])
            record["data"].update({key: value for key, value in data.items() if value is not None})
            record["meta"].pop("parent_uid", None)
            if session["parent_uid"]:
                record["meta"]["parent_uid"] = session["parent_uid"]
            record["messages"] = messages
        else:
            record["data"]["models"] = list(cls._models(records))
        return record

    @classmethod
    def human_messages(cls, turns: tuple[SessionTurn, ...]) -> tuple[str, ...]:
        """What a person typed: the mainline user messages that are not meta, without their envelopes, leaving
        out generated ones."""
        return tuple(text for turn in turns if turn.role == "user" and not turn.meta and not turn.sidechain
                     and (text := cls.typed(turn.text)))

    @classmethod
    def normalized_name(cls, path: Path, uid: str | None, turns: tuple[SessionTurn, ...],
                        span: dict[str, datetime] | None) -> str:
        """The file's name from its start, turn count, duration and topic, its uid and its suffix, within
        NAME_LIMIT: 261020-1412 42~3h - the topic.<uid>.jsonl."""
        length = ""
        if span is not None and (seconds := round((span["end"] - span["start"]).total_seconds())):
            unit, size = next(pair for pair in UNITS if seconds >= pair[1])
            length = f"~{round(seconds / size)}{unit}"
        topic = cls._topic(turns)
        label = (f"{span['start'].astimezone():%y%m%d-%H%M} " if span else "") + f"{len(turns)}{length}" + (f" - {topic}" if topic else "")
        tail = (f".{uid}" if uid else "") + path.suffix
        if len(label) + len(tail) > NAME_LIMIT:
            label = label[: NAME_LIMIT - len(tail)].rstrip()
        return f"{label}{tail}"

    @classmethod
    def parse_lines(cls, harness: str, lines: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...], offset: int = 0,
              uid: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """The session and the messages a harness's lines say: the whole file, or the lines after the offset lines read
        before, each numbered by its place in the file, counted from 1. A Codex delta names no session, so its uid is
        given. The session's times are its messages' first and last (a resumed session's copied lines are out of time
        order); with none, its lines', a moment when they are one (a Codex session opened and left). Linked Data's
        sessions API reads what a session hook sends through this, as SessionHandler.parse reads its file."""
        if harness == "cc":
            session, messages = cls._claude_lines(lines, offset, uid)
        elif harness == "cx":
            session, messages = cls._codex_lines(lines, offset, uid)
        else:
            raise NotImplementedError(f"the lines of cc and cx are read into messages, not those of {harness}")
        times = [message["ts"] for message in messages] or [
            datetime.fromisoformat(line["timestamp"]) for line in lines if line.get("timestamp")]
        session["times"] = [min(times), max(times)] if times else []
        return session, messages

    @staticmethod
    def first_line(text: str) -> str:
        """The first line of a text, clipped to NAME_LEN: a name."""
        return next((line.strip()[:NAME_LEN] for line in text.replace(chr(0), "").splitlines() if line.strip()), "")

    @classmethod
    def _text_of(cls, content: Any, keys: tuple[str, ...] = ("text", "thinking", "content", "output")) -> str:
        """The text a line carries: a string, or the text of its blocks, each block's under the first of keys it has."""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            return cls._text_of(next((content[key] for key in keys if content.get(key)), ""), keys)
        if isinstance(content, list):
            return "\n".join(filter(None, (cls._text_of(item, keys) for item in content)))
        return ""

    @classmethod
    def _readable(cls, text: str) -> str:
        """A prompt as a person reads it: one opening with a tag reads as the tag's summary, else the text outside the
        tags, else the text inside them."""
        opening = OPENING.match(text)
        if not opening:
            return text
        if (summary := SUMMARY.search(opening[2])) and summary[1].strip():
            return html.unescape(summary[1])
        return cls.first_line(TAGS.sub("", ELEMENT.sub("", text))) or TAGS.sub("", text)

    @classmethod
    def _prompted(cls, session: dict[str, Any], text: str) -> None:
        """The first prompt a person typed is the session's topic, and its name as a person reads it; one opening with a
        tag gives way to the first that does not."""
        prompt = cls.first_line(text)
        if prompt and (not session["topic"] or session["topic"].startswith("<") and not prompt.startswith("<")):
            session["topic"], session["name"] = prompt, cls.first_line(cls._readable(text))

    @classmethod
    def _message(cls, uid: str, line: Mapping[str, Any], n: int, subtype: str, text: str) -> dict[str, Any]:
        return {"uid": uid, "ts": datetime.fromisoformat(line["timestamp"]), "subtype": subtype,
                "name": cls.first_line(text) or subtype, "data": line, "line": n}

    @classmethod
    def _claude_lines(cls, lines, offset: int, uid: str | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Each user or assistant line is a message, its id the line's uuid. A subagent run's lines name the run, agentId,
        and the session that spawned it, sessionId. A line marked isMeta is not a prompt. An ai-title, agent-name or
        custom-title line names the session."""
        session = {"uid": uid, "parent_uid": None, "title": None, "topic": None, "name": None, "cwd": None, "models": set()}
        messages = []
        for n, line in enumerate(lines, offset + 1):
            kind = line.get("type")
            if kind in TITLES:
                session["title"] = line.get(TITLES[kind]) or session["title"]
            if kind not in ("user", "assistant"):
                continue
            if line.get("agentId"):
                session["uid"], session["parent_uid"] = line["agentId"], line.get("sessionId")
            else:
                session["uid"] = line.get("sessionId") or session["uid"]
            session["cwd"] = line.get("cwd") or session["cwd"]
            message = line.get("message") or {}
            if message.get("model"):
                session["models"].add(message["model"])
            content = message.get("content")
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
            types = {block.get("type") for block in blocks}
            if kind == "user" and not line.get("isMeta") and "text" in types:
                cls._prompted(session, cls._text_of(blocks, ("text",)))
            subtype = ("tool_result" if "tool_result" in types else "user" if kind == "user"
                       else "tool_use" if "tool_use" in types else "agent" if "text" in types else "thinking")
            text = (" ".join(block.get("name", "") for block in blocks if block.get("type") == "tool_use")
                    if subtype == "tool_use" else cls._text_of(blocks))
            messages.append(cls._message(line["uuid"], line, n, subtype, text))
        return session, messages

    @classmethod
    def _codex_lines(cls, lines, offset: int, uid: str | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """The first session_meta line names the session, its folder and the session that spawned it. A response_item of
        a message, a tool call or a tool's output is a message, its id made from the session's uid and the line. The
        AGENTS.md Codex reads into a session is not a prompt."""
        session = {"uid": uid, "parent_uid": None, "title": None, "topic": None, "name": None, "cwd": None, "models": set()}
        messages, named = [], False
        for n, line in enumerate(lines, offset + 1):
            payload = line.get("payload") or {}
            if line.get("type") == "session_meta" and not named:
                named = True
                source = payload.get("source")
                session["uid"] = session["uid"] or payload.get("id") or payload.get("session_id")
                session["parent_uid"] = (((source.get("subagent") or {}).get("thread_spawn") or {}).get("parent_thread_id")
                                         if isinstance(source, dict) else None)
                session["cwd"] = payload.get("cwd")
            if line.get("type") != "response_item" or payload.get("type") not in CODEX_MESSAGES:
                continue
            if payload["type"] == "message":
                subtype, text = CODEX_ROLES[payload["role"]], cls._text_of(payload.get("content"))
                if payload["role"] == "user" and not text.startswith(CODEX_INSTRUCTIONS):
                    cls._prompted(session, cls._text_of(payload.get("content"), ("text",)))
            elif payload["type"].endswith("_output"):
                subtype, text = "tool_result", cls._text_of(payload.get("output"))
            elif payload["type"] == "agent_message":
                subtype, text = "agent", cls._text_of(payload.get("content") or payload.get("text"))
            else:
                subtype, text = "tool_use", payload.get("name") or ""
            messages.append(cls._message(str(uuid5(NAMESPACE, f"{session['uid']}/{line.get('ordinal', n)}")), line, n, subtype, text))
        return session, messages

    @classmethod
    def _harness(cls, records: tuple[Mapping[str, Any], ...]) -> Harness | None:
        return next((harness for harness, recognize in cls.RECOGNIZERS if getattr(cls, recognize)(records)), None)

    @staticmethod
    def _is_codex(records: tuple[Mapping[str, Any], ...]) -> bool:
        """Recognize Codex lifecycle and response records."""

        return any(
            record.get("type")
            in ("session_meta", "turn_context", "event_msg", "response_item")
            and isinstance(record.get("payload"), Mapping)
            for record in records
        )

    @staticmethod
    def _is_copilot(records: tuple[Mapping[str, Any], ...]) -> bool:
        """Recognize the native VS Code Copilot append-log header."""
        if not records or records[0].get("kind") != 0:
            return False
        body = records[0].get("v")
        return (isinstance(body, Mapping) and isinstance(body.get("sessionId"), str)
                and isinstance(body.get("requests"), list)
                and body.get("responderUsername") == "GitHub Copilot")

    @staticmethod
    def _copilot_state(records: tuple[Mapping[str, Any], ...]) -> dict:
        """Replay VS Code objectMutationLog entries without changing raw records.

        Kind 2 replaces the array tail at ``i`` and then appends ``v``. Request
        and response patches belong to the same conversation; they are not turns.
        """
        if not SessionHandler._is_copilot(records):
            raise ValueError("Copilot append log has no initial session object")
        body = deepcopy(records[0]["v"])
        uid = body["sessionId"]
        for record in records[1:]:
            kind, path = record.get("kind"), record.get("k")
            if type(kind) is not int or kind not in (1, 2, 3) or not isinstance(path, list) or not path:
                raise ValueError("Copilot append log has an invalid mutation")
            target = body
            for key in path[:-1]:
                if (isinstance(target, dict) and key in target
                    or isinstance(target, list) and type(key) is int and 0 <= key < len(target)):
                    target = target[key]
                else:
                    raise ValueError("Copilot append log mutation has no parent")
            key = path[-1]
            if not (isinstance(target, dict) and isinstance(key, str)
                    or isinstance(target, list) and type(key) is int and 0 <= key < len(target)):
                raise ValueError("Copilot append log mutation has an invalid target")
            if kind == 1:
                target[key] = deepcopy(record["v"])
            elif kind == 3:
                if not isinstance(target, dict):
                    raise ValueError("Copilot deletion requires an object property")
                target.pop(key, None)
            else:
                if isinstance(target, dict) and key not in target:
                    target[key] = []  # Native Push initializes an absent array.
                values = target[key]
                if not isinstance(values, list):
                    raise ValueError("Copilot Push target is not an array")
                if "i" in record:
                    index = record["i"]
                    if type(index) is not int or not 0 <= index <= len(values):
                        raise ValueError("Copilot Push index is outside its array")
                    del values[index:]
                if "v" in record:
                    if not isinstance(record["v"], list):
                        raise ValueError("Copilot Push values are not an array")
                    values.extend(deepcopy(record["v"]))
        if body["sessionId"] != uid or not isinstance(body["requests"], list):
            raise ValueError("Copilot append log changed its session identity or requests type")
        return body

    @classmethod
    def _copilot_uid(cls, records: tuple[Mapping[str, Any], ...], path: Path) -> str:
        """Return the sessionId recorded in the native initial object."""
        return records[0]["v"]["sessionId"]

    @classmethod
    def _copilot_turns(cls, records: tuple[Mapping[str, Any], ...]) -> tuple[SessionTurn, ...]:
        """Read final messages and their explicitly recorded response completion times."""
        turns = []
        for request in cls._copilot_state(records)["requests"]:
            if (not isinstance(request, Mapping) or not isinstance(request.get("message"), Mapping)
                or not isinstance(request["message"].get("text"), str) or "timestamp" not in request):
                raise ValueError("Copilot request requires its original message and timestamp")
            if turn := cls._turn("user", request["message"]["text"], request["timestamp"]):
                turns.append(turn)
            response = request.get("response", [])
            if not isinstance(response, list):
                raise ValueError("Copilot response must be an array")
            parts = []
            for part in response:
                if not isinstance(part, Mapping):
                    continue
                if isinstance(part.get("value"), str):
                    parts.append(part["value"])
                elif part.get("kind") == "inlineReference" and isinstance(part.get("name"), str):
                    parts.append(part["name"])
            text = "".join(parts)
            state = request.get("modelState")
            completed = state.get("completedAt") if isinstance(state, Mapping) else None
            if completed is not None and (state.get("value") not in (1, 2, 3)
                or type(completed) not in (int, float) or Handler.valid_time(cls._stamp(completed)) is None
                or completed < request["timestamp"]):
                raise ValueError("Copilot completion requires a terminal state and a valid recorded time")
            if turn := cls._turn("assistant", text, completed):
                turns.append(turn)
        return tuple(turns)

    @staticmethod
    def _is_claude_code(records: tuple[Mapping[str, Any], ...]) -> bool:
        """Recognize Claude Code session identifiers and record types."""

        return any(
            isinstance(record.get("sessionId"), str)
            or record.get("type") == "teleported-from"
            or isinstance(record.get("uuid"), str)
            or isinstance(record.get("parentUuid"), str)
            for record in records
        )

    @staticmethod
    def _is_gemini(records: tuple[Mapping[str, Any], ...]) -> bool:
        """Recognize a Gemini CLI chat log by the header it opens with.

        Its first record is the chat's own header — a session id, the hash of the project it was
        opened in, when it started and what kind it is — and its turns arrive as one ``$set`` of
        messages. Claude Code is recognized by a ``sessionId`` alone, so without this the Gemini CLI
        is read as Claude Code, its turns are not found and every chat of one service shares that
        service's id.
        """

        return any(
            isinstance(record.get("sessionId"), str)
            and isinstance(record.get("projectHash"), str)
            and isinstance(record.get("startTime"), str)
            for record in records
        )

    @staticmethod
    def _is_openclaw(records: tuple[Mapping[str, Any], ...]) -> bool:
        """Recognize OpenClaw records from their model identifier."""

        return any(isinstance(record.get("modelId"), str) for record in records)

    @staticmethod
    def _is_agy(records: tuple[Mapping[str, Any], ...]) -> bool:
        """Recognize Agy user and planner transcript records."""

        return any(
            record.get("type") in ("USER_INPUT", "PLANNER_RESPONSE")
            and record.get("source") in ("USER_EXPLICIT", "MODEL")
            and isinstance(record.get("created_at"), str)
            for record in records
        )

    @staticmethod
    def _is_hermes(records: tuple[Mapping[str, Any], ...]) -> bool:
        """Recognize a Hermes session metadata record."""

        return any(
            record.get("role") == "session_meta"
            and isinstance(record.get("session_id"), str)
            for record in records
        )

    @staticmethod
    def _codex_uid(records: tuple[Mapping[str, Any], ...], path: Path) -> str | None:
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
    def _agy_uid(records: tuple[Mapping[str, Any], ...], path: Path) -> str | None:
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
        cls, records: tuple[Mapping[str, Any], ...], path: Path
    ) -> str | None:
        """Return the identifier of the conversation this file holds.

        A subagent transcript carries its parent's ``sessionId`` on every record and its own
        ``agentId``, which is also what the file is named after. The agent id identifies the
        conversation in the file; the session id identifies its parent.
        """

        return cls._record_uid(records, ("agentId",)) or cls._record_uid(records, ID_KEYS)

    @classmethod
    def _gemini_uid(
        cls, records: tuple[Mapping[str, Any], ...], path: Path
    ) -> str | None:
        """Return the identifier of the chat this file holds: its session id and when it started.

        The Gemini CLI reuses one session id for a service it runs — every chat of its a2a server is
        logged under ``a2a-server`` — so the id alone names the service and not the conversation. The
        start moment is in the header of every chat and is what tells one from another.
        """

        header = next(
            (
                record
                for record in records
                if isinstance(record.get("sessionId"), str)
                and isinstance(record.get("startTime"), str)
            ),
            None,
        )
        if header is None:
            return cls._record_uid(records, ID_KEYS)
        return f"{header['sessionId']}/{header['startTime']}"

    @classmethod
    def _gemini_turns(
        cls, records: tuple[Mapping[str, Any], ...]
    ) -> tuple[SessionTurn, ...]:
        """Read the messages a Gemini CLI chat sets, in the order it sets them.

        Its content blocks carry the text and no label, where the shared reader wants a block that
        says it is text, so the text is joined here and handed over as one string.
        """

        return tuple(
            item
            for record in records
            for changed in [record.get("$set")]
            if isinstance(changed, Mapping)
            for message in changed.get("messages") or ()
            if isinstance(message, Mapping)
            for item in [
                cls._turn(
                    message.get("type"),
                    cls._gemini_text(message.get("content")),
                    message.get("timestamp"),
                )
            ]
            if item is not None
        )

    @staticmethod
    def _gemini_text(content: Any) -> str:
        """Join the text of a Gemini CLI message's blocks."""

        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        return "\n\n".join(
            part["text"]
            for part in content
            if isinstance(part, Mapping)
            and isinstance(part.get("text"), str)
            and part["text"].strip()
        )

    @classmethod
    def _openclaw_uid(
        cls, records: tuple[Mapping[str, Any], ...], path: Path
    ) -> str | None:
        """Return the first OpenClaw session identifier."""

        return cls._record_uid(records, ("id", "session_id"))

    @classmethod
    def _hermes_uid(
        cls, records: tuple[Mapping[str, Any], ...], path: Path
    ) -> str | None:
        """Return the first Hermes session identifier."""

        return cls._record_uid(records, ID_KEYS)

    @staticmethod
    def _record_uid(
        records: tuple[Mapping[str, Any], ...], keys: tuple[str]
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
        cls, records: tuple[Mapping[str, Any], ...]
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
        cls, records: tuple[Mapping[str, Any], ...]
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
        cls, records: tuple[Mapping[str, Any], ...]
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
        cls, records: tuple[Mapping[str, Any], ...]
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
        cls, records: tuple[Mapping[str, Any], ...]
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
    def _head(data: bytes, size: int) -> tuple[Mapping[str, Any], ...]:
        """Up to SNIFF leading JSONL objects of a file's first bytes, its last line left out when the bytes end
        inside it; none when a line is not an object."""

        if len(data) < size:
            data = data[: data.rfind(b"\n") + 1]
        found: list[Mapping[str, Any]] = []
        try:
            for line in data.decode("utf-8").splitlines():
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    return ()
                found.append(value)
                if len(found) >= SNIFF:
                    break
        except (UnicodeDecodeError, json.JSONDecodeError):
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
    def _timestamps(cls, records: tuple[Mapping[str, Any], ...]) -> Iterator[datetime]:
        """Record times only: the record, its payload, or its message. Values quoted deeper inside content are not the session's time."""

        for record in records:
            for scope in (record, record.get("payload"), record.get("message")):
                if not isinstance(scope, Mapping):
                    continue
                for key in TIME_KEYS:
                    if (stamp := Handler.valid_time(cls._stamp(scope.get(key)))) is not None:
                        yield stamp

    @classmethod
    def _models(cls, records: tuple[Mapping[str, Any], ...]) -> tuple[str, ...]:
        """Return unique model names found anywhere in the records."""

        return cls._uniq(
            value
            for record in records
            for key, value in cls._walk_values(record)
            if key in MODEL_KEYS
        )

    @classmethod
    def _claude_code_parent(
        cls, records: tuple[Mapping[str, Any], ...]
    ) -> tuple[str | None, bool]:
        """Return a Claude Code parent session id and whether the file is a subagent's.

        A file carrying an ``agentId`` is a subagent's transcript, and the ``sessionId`` every
        record carries is the session that spawned it.
        """

        if cls._record_uid(records, ("agentId",)) is None:
            return None, False
        return cls._record_uid(records, ID_KEYS), True

    @staticmethod
    def _parent(records: tuple[Mapping[str, Any], ...]) -> tuple[str | None, bool]:
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
            role.casefold(), text, Handler.valid_time(cls._stamp(timestamp)), meta, sidechain
        )

    @staticmethod
    def _topic(messages: tuple[SessionTurn]) -> str:
        """The first line a person typed."""
        for message in messages:
            if message.role != "user" or message.meta or message.sidechain:
                continue
            if text := SessionHandler.typed(message.text):
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

    @staticmethod
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



class SessionFolderHandler(FolderHandler):
    """A harness's session folder: a Hermes home (state.db), an Agy home (antigravity_state.pbtxt or
    jetski_state.pbtxt), or an Agy session folder named by its UUID with a transcript under
    .system_generated/logs. Its sessions are every session file below it, all of one harness: their harness, their
    uid when they agree on one, how many there are and their span are its data.
    """

    @classmethod
    def identify(cls, path: Path, stat: os.stat_result, head: Head) -> bool:
        return super().identify(path, stat, head) and (SessionHandler._home_harness(path) is not None
                                                       or SessionHandler._agy_session_folder(path))

    @classmethod
    @sync
    async def parse(cls, path: str | Path) -> dict[str, Any]:
        record = await super().parse(path)
        path = full_path(path)
        files = await asyncio.to_thread(lambda: sorted(path.rglob("*.jsonl"), key=lambda item: str(item).casefold()))
        files = [file for file, handler in zip(files, await asyncio.gather(*(probe(file) for file in files)))
                 if handler is SessionHandler]
        sessions = list(await asyncio.gather(*(SessionHandler.parse(file) for file in files)))
        harnesses = SessionHandler._uniq([session["subtype"] for session in sessions] + [SessionHandler._home_harness(path)])
        if len(harnesses) != 1:
            raise ValueError(f"{path}: a session folder holds one harness, not {harnesses}")
        uids = {session["uid"] for session in sessions if session["uid"]}
        record["data"].update(harness=harnesses[0], sessions=len(sessions))
        if len(uids) == 1:
            record["data"]["uid"] = uids.pop()
        record["span"] = cls.spanning([time for session in sessions if session["span"] for time in session["span"].values()])
        return record


# The handlers probe knows, every type and subtype there is; a program adds its own by appending it.
HANDLERS: list[type[Handler]] = [
    IgnoredHandler, SymlinkHandler, JunctionHandler, FolderHandler, SessionFolderHandler, FileHandler, SqliteHandler, MarkdownHandler, CSVHandler,
    LogHandler, EmailHandler, SessionHandler,
]


@sync
async def probe(path: str | Path) -> type[Handler]:
    """The handler to call for a path whose type is not known: the most specific of HANDLERS that identifies it, one
    no other identifying handler is a subtype of; of two alike, the first. Probing does no more than that takes: the
    path is stat'ed once and its first bytes are read at most once, as many as the handler asking for most asks, in a
    thread, since on a file share a stat alone can take seconds. Awaited inside an event loop, returned directly
    outside one. The path is taken as given, a link as the link."""

    def which() -> type[Handler]:
        given = Path(path)
        stat = given.stat(follow_symlinks=False)
        head = Head(given, stat)
        found = [handler for handler in HANDLERS if handler.identify(given, stat, head)]
        specific = [handler for handler in found if not any(other is not handler and issubclass(other, handler) for other in found)]
        if not specific:
            raise ValueError(f"{given}: no handler identifies it")
        return specific[0]

    return await asyncio.to_thread(which)
