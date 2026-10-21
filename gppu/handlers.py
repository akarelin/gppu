"""Handlers: a universal way to get information about a file or a folder.

There is a handler for every type of data that is read, and probe, which, given a path, a file's or a folder's,
whose type is not known in advance, gives what info gives of it, its record from its stat and its name; the record's
type and subtype say which handler reads it:

    record = probe('D:/Dev/gppu/README.md')                  # await probe(...) in an event loop
    handler = HANDLERS[record.type, record.subtype]          # MarkdownHandler
    record = handler.parse('D:/Dev/gppu/README.md')          # await handler.parse(...) in an event loop

Probing starts from the path's stat, and nothing is read: a file's handler is its suffix's in SUFFIXES. A link, a junction, an ignored path and an offline file are what probe gives; no handler
reads them. A handler is a class of class methods, and `parse(path)` reads the path into a Record, what Linked Data
holds of the thing: its type, subtype, name, created, updated, span, data, meta, and the records it holds;
each handler says what it returns. A subtype is a subclass of its type, and its parse adds to its type's. probe and parse are
asynchronous, awaited inside an event loop and returned directly outside one. A program adds a handler by
subclassing and adding its suffix:

    class TSVHandler(CSVHandler):
        ...

    SUFFIXES['.tsv'] = TSVHandler
    HANDLERS[TSVHandler.type, TSVHandler.subtype] = TSVHandler

A handler reads the path it is given and nothing else: no index, no location, no fsspec. A read that fails raises.
"""
from __future__ import annotations

import csv
import html
import json
import os
import re
import sqlite3
import stat as stat_module
from collections.abc import Iterator, Mapping
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, BinaryIO, Literal
from uuid import UUID, uuid5

import yaml

from .gppu import Path, TimeSpan, sync

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
LOG_BLOCK = 65536   # how much of a log's tail is read at a time
LOG_TIMESTAMP = re.compile(
    r"^\s*[\[(]?(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
IGNORED_SUFFIXES = (".tmp", ".bak", ".swp")
IGNORED_PREFIX = "~$"
IGNORED_NAMES = ("Thumbs.db", ".DS_Store", "desktop.ini")
IGNORED_FOLDERS = (
    ".git", ".svn", "__pycache__", ".venv", "venv", "node_modules", ".idea", ".vscode",
    ".SynologyWorking Directory", ".SynologyWorkingDirectory", "$RECYCLE.BIN", "RECYCLE.BIN",
    "System Volume Information", "OneDriveTemp", "Cache", ".cache",
)
WINDOWS_SYSTEM = 4
# Windows' FILE_ATTRIBUTE_OFFLINE and FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS: a file whose bytes are not on this host.
OFFLINE = 0x1000 | 0x400000
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
# Linked Data's sessions (RAN Projects/ld/sessions.py): a name is the first line of a text, clipped; the messages of Claude
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
MESSAGE_SUBTYPES = ("user", "agent", "thinking", "tool_use", "tool_result")
SESSION_UID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


@dataclass
class Record:
    """A record as Linked Data holds it: gppu.ld's _Record without what Postgres fills, its id, created, updated and the
    code of its type, kept to that one shape on purpose; handlers import neither Postgres nor gppu.ld. A file's
    `created` and `updated` are its own, as stat gives them. `type` is the
    handler's type and `subtype` its own; `uid` is a session's own id in its harness, as Linked Data's sessions hold it;
    `ts` is when a message happened and `span` when a thing went on; `contents` are the records it holds, a folder's
    and a session's, which Linked Data gives a parent_id instead."""

    type: str | None = None
    subtype: str | None = None
    name: str | None = None
    created: datetime | None = None
    updated: datetime | None = None
    uid: str | None = None
    ts: datetime | None = None
    span: TimeSpan | None = None
    data: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    contents: list[Record] = field(default_factory=list)


class Handler:
    """The base of every handler: a handler reads a file or a folder, and its parse is what it reads.

    `type` is the class below Handler a handler descends from, file or folder, unless the handler names its own;
    `subtype` is the handler's own name, markdown for MarkdownHandler, None for a type itself, one that names its type
    as SessionHandler does.
    """

    type: str
    subtype: str | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        top = next(base for base in reversed(cls.__mro__) if issubclass(base, Handler) and base is not Handler)
        names_type = "type" in cls.__dict__
        if not names_type:
            cls.type = top.type if "type" in top.__dict__ else top.__name__.removesuffix("Handler").casefold()
        name = cls.__name__.removesuffix("Handler").casefold()
        if "subtype" not in cls.__dict__:
            cls.subtype = None if cls is top or names_type else name
        if "parse" in cls.__dict__:
            cls.parse = classmethod(sync(cls.__dict__["parse"].__func__))

    @classmethod
    @sync
    async def parse(cls, path: str | Path) -> Record:
        """The record of the path: what probe gives, with the handler's type and subtype, and what the handler
        reads. A handler's parse adds to its type's; Handler makes every handler's parse gppu's sync, awaited inside
        an event loop and returned directly outside one.

        Returns: type, subtype, name the path's name, created and updated as stat gives them, meta.size its size."""
        record = await probe(path)
        record.type, record.subtype = cls.type, cls.subtype
        return record

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

    @classmethod
    def time(cls, value: Any) -> datetime | None:
        """A recorded time from what a file writes: a datetime, a date, which starts at midnight, an ISO string, or Unix
        seconds above 1,000,000,000 or milliseconds above 10,000,000,000. A time without an offset is local. None for
        anything else, and for what valid_time refuses."""
        if isinstance(value, str):
            value = value.strip()
            try:
                value = float(value) if value[:1].isdigit() and value.replace(".", "", 1).isdigit() else value
            except ValueError:
                pass
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value <= 1_000_000_000:
                return None
            try:
                value = datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value)
            except (OSError, OverflowError, ValueError):
                return None
        elif isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        elif isinstance(value, date) and not isinstance(value, datetime):
            value = datetime(value.year, value.month, value.day)
        elif not isinstance(value, datetime):
            return None
        return cls.valid_time(value.astimezone())

    @staticmethod
    def spanning(times: list[datetime] | tuple[datetime, ...]) -> TimeSpan | None:
        """The span from the earliest to the latest of times, or None when there are none."""
        return TimeSpan(min(times), max(times)) if times else None


class FolderHandler(Handler):
    """A folder: a loop over what it holds. Each is probed, and one a handler reads is parsed by it, so a folder in it
    loops over its own; an ignored one, a link, a junction or an offline file is what probe gives. A subfolder's
    modified time is when something was added to it, so the span is its files' alone.

    Returns: Handler's record, with data.files, data.folders and data.bytes, what the folder directly holds; span from
    its files' earliest updated time to their latest; contents, the record of each thing it holds.
    """

    @classmethod
    async def parse(cls, path: str | Path) -> Record:
        record = await super().parse(path)
        path = Path(path).absolute()
        for member in sorted(path.iterdir()):
            found = await probe(member)
            handler = HANDLERS.get((found.type, found.subtype))
            record.contents.append(found if handler is None else await handler.parse(member))
        files = [member for member in record.contents if "folder" not in (member.type, member.subtype)]
        record.data.update(files=len(files), folders=len(record.contents) - len(files),
                           bytes=sum(member.meta["size"] for member in files))
        record.span = cls.spanning([time for member in files if (time := cls.valid_time(member.updated))])
        return record


class FileHandler(Handler):
    """A file of a type no more specific handler reads.

    Returns: Handler's record.
    """


class SqliteHandler(FileHandler):
    """A SQLite file and its tables with their columns.

    It is opened immutable, so SQLite writes no -wal or -shm beside it, and no row is read: what is in the
    tables is the file's content, not what the file is.

    Returns: Handler's record, with data.tables, each table's name and the names of its columns in order, the
    tables in name order and SQLite's own left out.
    """

    @classmethod
    async def parse(cls, path: str | Path) -> Record:
        record = await super().parse(path)
        with closing(sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
            names = [name for (name,) in database.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            record.data["tables"] = {name: [row[1] for row in database.execute(f'PRAGMA table_info("{name}")')]
                                        for name in names}
        return record


class MarkdownHandler(FileHandler):
    """A .md file and its whole YAML frontmatter.

    Frontmatter is there when the first line is --- and a later line closes it with ---; it is an empty
    document or a mapping, and its timestamps stay as written. The body is not read. The record's name is the
    frontmatter's name, then its title, then the file's stem; data.title is its title, then its name, then the
    stem. data.tags is a list or one value. The span is created to updated, both required; a date starts at
    midnight, a time without an offset is local.

    Returns: Handler's record, with name; data.title, data.tags, a list of strings, and data.frontmatter, the whole
    mapping, {} when there is none; span from created to updated, or None.
    """

    class _Loader(yaml.SafeLoader):
        """Safe YAML that keeps timestamp scalars as written."""

    _Loader.yaml_implicit_resolvers = {
        first: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:timestamp"]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    @classmethod
    async def parse(cls, path: str | Path) -> Record:
        record = await super().parse(path)
        path = Path(path).absolute()
        frontmatter = cls._frontmatter(path)
        name, title = frontmatter.get("name", frontmatter.get("title")), frontmatter.get("title", frontmatter.get("name"))
        tags = frontmatter.get("tags")
        tags = [] if tags is None else tags if isinstance(tags, list) else [tags]
        record.name = path.stem if name is None else str(name)
        record.data.update(title=path.stem if title is None else str(title),
                              tags=[str(tag) for tag in tags if tag is not None], frontmatter=frontmatter)
        created, updated = cls.time(frontmatter.get("created")), cls.time(frontmatter.get("updated"))
        if created is not None and updated is not None:
            record.span = cls.spanning([created, updated])
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



class CSVHandler(FileHandler):
    """A .csv file: its header, how many rows it has, and the span of the times in its time columns.

    The table is read strictly in the excel dialect. A time column is one whose header, stripped and in any
    case, is one of time_keys; its values are ISO dates or times, Unix seconds above 1,000,000,000 or
    milliseconds above 10,000,000,000, or one of a subclass's time_formats for strptime. A time without an
    offset is local; placeholders and future times do not count.

    Returns: Handler's record, with data.header, the first row's names, and data.rows, how many rows follow it; span
    from the earliest time in the time columns to the latest, or None.
    """

    time_keys = TIME_KEYS
    time_formats: tuple[str, ...] = ()

    @classmethod
    async def parse(cls, path: str | Path) -> Record:
        record = await super().parse(path)
        with Path(path).absolute().open(encoding="utf-8-sig", newline="") as stream:
            rows = [tuple(row) for row in csv.reader(stream, strict=True)]
        header, rows = (rows[0], rows[1:]) if rows else ((), [])
        keys = {key.casefold() for key in cls.time_keys}
        columns = [index for index, name in enumerate(header) if name.strip().casefold() in keys]
        record.data.update(header=list(header), rows=len(rows))
        record.span = cls.spanning([time for row in rows for index in columns
                                       if index < len(row) and (time := cls._time(row[index])) is not None])
        return record

    @classmethod
    def _time(cls, value: str) -> datetime | None:
        """Handler.time, else one of time_formats."""
        if (time := cls.time(value)) is not None:
            return time
        for time_format in cls.time_formats:
            try:
                return cls.valid_time(datetime.strptime(value.strip(), time_format).astimezone())
            except ValueError:
                continue
        return None


class LogHandler(FileHandler):
    """A .log file: when it starts and when it ends, from the times that begin its lines.

    A line's time comes after optional whitespace and one optional [ or (, as YYYY-MM-DD, T or a space, HH:MM:SS, an
    optional fraction after a dot or a comma, and an optional Z or offset. A time without an offset is local;
    placeholders and future times do not count. A log is written in order, so its start is the first line from its
    head that has a time and its end the first from its tail: it is read from both ends until each is found, LOG_BLOCK
    bytes at a time, and never whole unless no line has a time.

    Returns: Handler's record, with span from the time of the first line that has one to the time of the last, or None.
    """

    @classmethod
    async def parse(cls, path: str | Path) -> Record:
        record = await super().parse(path)
        with Path(path).absolute().open("rb") as stream:
            start = next((time for line in cls._head(stream) if (time := cls._line_time(line)) is not None), None)
            end = next((time for line in cls._tail(stream) if (time := cls._line_time(line)) is not None), None)
        if start is not None and end is not None:
            record.span = TimeSpan(start, max(start, end))
        return record

    @staticmethod
    def _head(stream: BinaryIO) -> Iterator[bytes]:
        """The lines from the start of the file."""
        stream.seek(0)
        yield from stream

    @staticmethod
    def _tail(stream: BinaryIO) -> Iterator[bytes]:
        """The lines from the end of the file, last first, read LOG_BLOCK bytes at a time."""
        position, rest = stream.seek(0, os.SEEK_END), b""
        while position > 0:
            size = min(LOG_BLOCK, position)
            position -= size
            stream.seek(position)
            lines = (stream.read(size) + rest).split(b"\n")
            rest = lines.pop(0)
            yield from reversed(lines)
        yield rest

    @classmethod
    def _line_time(cls, line: bytes) -> datetime | None:
        match = LOG_TIMESTAMP.match(line.decode("utf-8-sig", errors="replace"))
        return None if match is None else cls.time(match.group("timestamp").replace(",", "."))


class EmailHandler(FileHandler):
    """A .msg or .eml file and what its name says: YYMMDD.HHMMSS - subject - party[ - collision].

    The message itself is not read. The time is local; splitting from the right lets the subject hold
    the separator. A name outside the convention says nothing, and the record has no timestamp, subject,
    party or collision.

    Returns: Handler's record, with data.timestamp, data.subject, data.party and data.collision, each where the name
    gives it; span the timestamp, or None.
    """

    @classmethod
    async def parse(cls, path: str | Path) -> Record:
        record = await super().parse(path)
        stamp, separator, rest = Path(path).absolute().stem.partition(" - ")
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
            timestamp = cls.valid_time(datetime.strptime(stamp, "%y%m%d.%H%M%S").astimezone())
        except ValueError:
            return record
        named = {"timestamp": timestamp, "subject": content.strip(), "party": party.strip(), "collision": collision}
        record.data.update({key: value for key, value in named.items() if value is not None})
        if timestamp is not None:
            record.span = cls.spanning([timestamp])
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
    """A native session: a .jsonl a harness wrote, its first eight messages saying which harness.

    Probing takes a .jsonl that is not empty by its suffix; the harness is told by its messages when it is parsed, never by the
    file's name or folder:

    * Codex (cx): type is session_meta, turn_context, event_msg or response_item, with an object payload.
    * Copilot: a VS Code append log opening with sessionId, requests and responderUsername GitHub Copilot.
    * Gemini CLI: a header with sessionId, projectHash and startTime.
    * Claude Code (cc): a type and a string sessionId, uuid or parentUuid, or type teleported-from.
    * OpenClaw: a string modelId.
    * Agy: USER_INPUT from USER_EXPLICIT or PLANNER_RESPONSE from MODEL, with a string created_at.
    * Hermes: role session_meta with a string session_id.

    Its record is a session, its subtype the harness; a .jsonl whose messages name no harness raises. Its messages
    are every message of the file, in order, as session messages in its contents; a blank, truncated or non-object line
    of the file is skipped. A session message's subtype is user, agent, thinking, tool_use or tool_result as Linked Data reads
    the messages of cc and cx (parse_messages), else the type its harness gives it. For cc and cx the record has the
    uid, the name, the span from the first session message of Linked Data's subtypes to the last, data.title, topic,
    cwd and models, and meta.parent_uid, as Linked Data reads them. For the other harnesses it has the uid its
    harness gives, the span from the first time in its messages to the last, and the models named anywhere in them.
    data.turns counts its turns, and data.normalized_name is the file's name from its start, turns, duration and the
    first line a person typed.

    Returns: Handler's record, with subtype the harness; uid; name; span; data.subagent, data.sidechain_only,
    data.turns, data.normalized_name and data.models, and for cc and cx data.title, data.topic and data.cwd where the
    session gives them; meta.parent_uid where it names one; contents, every message as a session message record:
    type session_message, subtype, ts, name, data the message as the harness wrote it, meta.uid and meta.line.
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
    async def parse(cls, path: str | Path) -> Record:
        record = await super().parse(path)
        path = Path(path).absolute()
        messages = cls._messages(path)
        harness = cls._harness(messages[:SNIFF])
        if harness is None:
            raise ValueError(f"{path}: its messages name no harness")
        turns = getattr(cls, cls.TURNS[harness])(messages)
        times = tuple(cls._timestamps(messages))
        if harness == "copilot":
            created = cls.valid_time(cls._stamp(messages[0]["v"].get("creationDate")))
            times = tuple(time for time in (created, *(turn.timestamp for turn in turns)) if time is not None)
        uid = getattr(cls, cls.UID[harness])(messages, path)
        parent = cls.PARENT.get(harness)
        parent_uid, subagent = getattr(cls, parent)(messages) if parent else (None, False)
        mainline = any(message.get("isSidechain") is False for message in messages)
        sidechain = any(message.get("isSidechain") is True for message in messages)
        span = cls.spanning(times)
        record.subtype, record.uid, record.name, record.span = harness, uid, cls._topic(turns) or uid, span
        record.data.update(subagent=subagent, sidechain_only=sidechain and not mainline, turns=len(turns),
                              normalized_name=cls.normalized_name(path, uid, turns, span))
        if parent_uid:
            record.meta["parent_uid"] = parent_uid
        if harness in ("cc", "cx"):
            session, session_messages = cls.parse_messages(harness, messages)
            data = {"title": session["title"], "topic": session["topic"], "cwd": session["cwd"],
                    "models": sorted(session["models"]) or None}
            record.uid = session["uid"]
            record.name = (cls.first_line(session["title"] or "") or cls.first_line(session["name"] or "")
                              or session["uid"])
            record.span = cls.spanning(session["times"])
            record.data.update({key: value for key, value in data.items() if value is not None})
            record.meta.pop("parent_uid", None)
            if session["parent_uid"]:
                record.meta["parent_uid"] = session["parent_uid"]
        else:
            record.data["models"] = list(cls._models(messages))
            session_messages = [cls._session_message(None, message, n, cls._own_type(message), "") for n, message in enumerate(messages, 1)]
        record.contents = session_messages
        return record

    @classmethod
    def human_messages(cls, turns: tuple[SessionTurn, ...]) -> tuple[str, ...]:
        """What a person typed: the mainline user messages that are not meta, without their envelopes, leaving
        out generated ones."""
        return tuple(text for turn in turns if turn.role == "user" and not turn.meta and not turn.sidechain
                     and (text := cls.typed(turn.text)))

    @classmethod
    def normalized_name(cls, path: Path, uid: str | None, turns: tuple[SessionTurn, ...],
                        span: TimeSpan | None) -> str:
        """The file's name from its start, turn count, duration and topic, its uid and its suffix, within
        NAME_LIMIT: 261020-1412 42~3h - the topic.<uid>.jsonl."""
        length = ""
        if span is not None and (seconds := round((span.end - span.start).total_seconds())):
            unit, size = next(pair for pair in UNITS if seconds >= pair[1])
            length = f"~{round(seconds / size)}{unit}"
        topic = cls._topic(turns)
        label = (f"{span.start.astimezone():%y%m%d-%H%M} " if span else "") + f"{len(turns)}{length}" + (f" - {topic}" if topic else "")
        tail = (f".{uid}" if uid else "") + path.suffix
        if len(label) + len(tail) > NAME_LIMIT:
            label = label[: NAME_LIMIT - len(tail)].rstrip()
        return f"{label}{tail}"

    @classmethod
    def parse_messages(cls, harness: str, messages: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
                       offset: int = 0, uid: str | None = None) -> tuple[dict[str, Any], list[Record]]:
        """The session and its session messages from the messages a harness wrote: the whole file, or the messages
        after the offset ones read before, each numbered by its place in the file, counted from 1. Every message is a
        session message: user, agent, thinking, tool_use or tool_result as Linked Data reads them, else the type its
        harness gives it, such as system, attachment or ai-title. A Codex delta names no session, so its uid is given. The session's times are the first and last of its
        session messages of Linked Data's subtypes (a resumed session's copied messages are out of time order); with none, its
        messages', a moment when they are one (a Codex session opened and left). Linked Data's sessions API reads
        what a session hook sends through this, as SessionHandler.parse reads its file."""
        if harness == "cc":
            session, session_messages = cls._claude_messages(messages, offset, uid)
        elif harness == "cx":
            session, session_messages = cls._codex_messages(messages, offset, uid)
        else:
            raise NotImplementedError(f"the messages of cc and cx are read into session messages, not those of {harness}")
        times = [message.ts for message in session_messages if message.subtype in MESSAGE_SUBTYPES] or [
            datetime.fromisoformat(message["timestamp"]) for message in messages if message.get("timestamp")]
        session["times"] = [min(times), max(times)] if times else []
        return session, session_messages

    @staticmethod
    def first_line(text: str) -> str:
        """The first line of a text, clipped to NAME_LEN: a name."""
        return next((line.strip()[:NAME_LEN] for line in text.replace(chr(0), "").splitlines() if line.strip()), "")

    @classmethod
    def _text_of(cls, content: Any, keys: tuple[str, ...] = ("text", "thinking", "content", "output")) -> str:
        """The text a message carries: a string, or the text of its blocks, each block's under the first of keys it has."""
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

    @staticmethod
    def _own_type(message: Mapping[str, Any]) -> str | None:
        """The type a harness gives its message, or its role; None only where it gives neither."""
        value = message.get("type") or message.get("role")
        return value if isinstance(value, str) else None

    @classmethod
    def _session_message(cls, uid: str | None, message: Mapping[str, Any], n: int, subtype: str | None,
                         text: str) -> Record:
        """A session message as Linked Data holds it: its subtype, its time, its name the first line of its text, the
        message as its data, and in meta its id in its harness and its place in the file."""
        return Record(type="session_message", subtype=subtype,
                      ts=datetime.fromisoformat(message["timestamp"]) if message.get("timestamp") else None,
                      name=cls.first_line(text) or subtype, data=dict(message), meta={"uid": uid, "line": n})

    @classmethod
    def _claude_messages(cls, messages, offset: int, uid: str | None) -> tuple[dict[str, Any], list[Record]]:
        """A user or an assistant message has a subtype, its id its uuid. A subagent run's messages name the run,
        agentId, and the session that spawned it, sessionId. A message marked isMeta is not a prompt. An ai-title,
        agent-name or custom-title message names the session."""
        session = {"uid": uid, "parent_uid": None, "title": None, "topic": None, "name": None, "cwd": None, "models": set()}
        session_messages = []
        for n, message in enumerate(messages, offset + 1):
            kind = message.get("type")
            if kind in TITLES:
                session["title"] = message.get(TITLES[kind]) or session["title"]
            if kind not in ("user", "assistant"):
                session_messages.append(cls._session_message(message.get("uuid"), message, n, kind, ""))
                continue
            if message.get("agentId"):
                session["uid"], session["parent_uid"] = message["agentId"], message.get("sessionId")
            else:
                session["uid"] = message.get("sessionId") or session["uid"]
            session["cwd"] = message.get("cwd") or session["cwd"]
            body = message.get("message") or {}
            if body.get("model"):
                session["models"].add(body["model"])
            content = body.get("content")
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
            types = {block.get("type") for block in blocks}
            if kind == "user" and not message.get("isMeta") and "text" in types:
                cls._prompted(session, cls._text_of(blocks, ("text",)))
            subtype = ("tool_result" if "tool_result" in types else "user" if kind == "user"
                       else "tool_use" if "tool_use" in types else "agent" if "text" in types else "thinking")
            text = (" ".join(block.get("name", "") for block in blocks if block.get("type") == "tool_use")
                    if subtype == "tool_use" else cls._text_of(blocks))
            session_messages.append(cls._session_message(message["uuid"], message, n, subtype, text))
        return session, session_messages

    @classmethod
    def _codex_messages(cls, messages, offset: int, uid: str | None) -> tuple[dict[str, Any], list[Record]]:
        """The first session_meta message names the session, its folder and the session that spawned it. A
        response_item of a message, a tool call or a tool's output has a subtype. Codex gives a message no id, so its
        id is made from the session's uid and its place. The AGENTS.md Codex reads into a session is not a prompt."""
        session = {"uid": uid, "parent_uid": None, "title": None, "topic": None, "name": None, "cwd": None, "models": set()}
        session_messages, named = [], False
        for n, message in enumerate(messages, offset + 1):
            payload = message.get("payload") or {}
            if message.get("type") == "session_meta" and not named:
                named = True
                source = payload.get("source")
                session["uid"] = session["uid"] or payload.get("id") or payload.get("session_id")
                session["parent_uid"] = (((source.get("subagent") or {}).get("thread_spawn") or {}).get("parent_thread_id")
                                         if isinstance(source, dict) else None)
                session["cwd"] = payload.get("cwd")
            message_uid = str(uuid5(NAMESPACE, f"{session['uid']}/{message.get('ordinal', n)}"))
            if message.get("type") != "response_item" or payload.get("type") not in CODEX_MESSAGES:
                own = payload.get("type") if message.get("type") == "response_item" else message.get("type")
                session_messages.append(cls._session_message(message_uid, message, n, own, ""))
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
            session_messages.append(cls._session_message(message_uid, message, n, subtype, text))
        return session, session_messages

    @classmethod
    def _harness(cls, messages: tuple[Mapping[str, Any], ...]) -> Harness | None:
        return next((harness for harness, recognize in cls.RECOGNIZERS if getattr(cls, recognize)(messages)), None)

    @staticmethod
    def _is_codex(messages: tuple[Mapping[str, Any], ...]) -> bool:
        """Recognize Codex lifecycle and response messages."""

        return any(
            message.get("type")
            in ("session_meta", "turn_context", "event_msg", "response_item")
            and isinstance(message.get("payload"), Mapping)
            for message in messages
        )

    @staticmethod
    def _is_copilot(messages: tuple[Mapping[str, Any], ...]) -> bool:
        """Recognize the native VS Code Copilot append-log header."""
        if not messages or messages[0].get("kind") != 0:
            return False
        body = messages[0].get("v")
        return (isinstance(body, Mapping) and isinstance(body.get("sessionId"), str)
                and isinstance(body.get("requests"), list)
                and body.get("responderUsername") == "GitHub Copilot")

    @staticmethod
    def _copilot_state(messages: tuple[Mapping[str, Any], ...]) -> dict:
        """Replay VS Code objectMutationLog entries without changing raw messages.

        Kind 2 replaces the array tail at ``i`` and then appends ``v``. Request
        and response patches belong to the same conversation; they are not turns.
        """
        if not SessionHandler._is_copilot(messages):
            raise ValueError("Copilot append log has no initial session object")
        body = deepcopy(messages[0]["v"])
        uid = body["sessionId"]
        for message in messages[1:]:
            kind, path = message.get("kind"), message.get("k")
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
                target[key] = deepcopy(message["v"])
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
                if "i" in message:
                    index = message["i"]
                    if type(index) is not int or not 0 <= index <= len(values):
                        raise ValueError("Copilot Push index is outside its array")
                    del values[index:]
                if "v" in message:
                    if not isinstance(message["v"], list):
                        raise ValueError("Copilot Push values are not an array")
                    values.extend(deepcopy(message["v"]))
        if body["sessionId"] != uid or not isinstance(body["requests"], list):
            raise ValueError("Copilot append log changed its session identity or requests type")
        return body

    @classmethod
    def _copilot_uid(cls, messages: tuple[Mapping[str, Any], ...], path: Path) -> str:
        """Return the sessionId recorded in the native initial object."""
        return messages[0]["v"]["sessionId"]

    @classmethod
    def _copilot_turns(cls, messages: tuple[Mapping[str, Any], ...]) -> tuple[SessionTurn, ...]:
        """Read final messages and their explicitly recorded response completion times."""
        turns = []
        for request in cls._copilot_state(messages)["requests"]:
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
    def _is_claude_code(messages: tuple[Mapping[str, Any], ...]) -> bool:
        """Recognize Claude Code session messages: each has a type, and a sessionId, a uuid or a parentUuid, or is
        teleported-from. Claude Code's prompt history, history.jsonl, has a sessionId and no type."""

        return any(
            message.get("type") == "teleported-from"
            or isinstance(message.get("type"), str)
            and (isinstance(message.get("sessionId"), str)
                 or isinstance(message.get("uuid"), str)
                 or isinstance(message.get("parentUuid"), str))
            for message in messages
        )

    @staticmethod
    def _is_gemini(messages: tuple[Mapping[str, Any], ...]) -> bool:
        """Recognize a Gemini CLI chat log by the header it opens with.

        Its first message is the chat's own header — a session id, the hash of the project it was
        opened in, when it started and what kind it is — and its turns arrive as one ``$set`` of
        messages. Claude Code is recognized by a ``sessionId`` alone, so without this the Gemini CLI
        is read as Claude Code, its turns are not found and every chat of one service shares that
        service's id.
        """

        return any(
            isinstance(message.get("sessionId"), str)
            and isinstance(message.get("projectHash"), str)
            and isinstance(message.get("startTime"), str)
            for message in messages
        )

    @staticmethod
    def _is_openclaw(messages: tuple[Mapping[str, Any], ...]) -> bool:
        """Recognize OpenClaw messages from their model identifier."""

        return any(isinstance(message.get("modelId"), str) for message in messages)

    @staticmethod
    def _is_agy(messages: tuple[Mapping[str, Any], ...]) -> bool:
        """Recognize Agy user and planner transcript messages."""

        return any(
            message.get("type") in ("USER_INPUT", "PLANNER_RESPONSE")
            and message.get("source") in ("USER_EXPLICIT", "MODEL")
            and isinstance(message.get("created_at"), str)
            for message in messages
        )

    @staticmethod
    def _is_hermes(messages: tuple[Mapping[str, Any], ...]) -> bool:
        """Recognize a Hermes session metadata message."""

        return any(
            message.get("role") == "session_meta"
            and isinstance(message.get("session_id"), str)
            for message in messages
        )

    @staticmethod
    def _codex_uid(messages: tuple[Mapping[str, Any], ...], path: Path) -> str | None:
        """Return the immutable id from Codex session metadata."""

        for message in messages:
            if message.get("type") != "session_meta" or not isinstance(
                payload := message.get("payload"), Mapping
            ):
                continue
            value = payload.get("id") or payload.get("session_id")
            return value.strip() if isinstance(value, str) and value.strip() else None
        return None

    @staticmethod
    def _agy_uid(messages: tuple[Mapping[str, Any], ...], path: Path) -> str | None:
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
        cls, messages: tuple[Mapping[str, Any], ...], path: Path
    ) -> str | None:
        """Return the identifier of the conversation this file holds.

        A subagent transcript carries its parent's ``sessionId`` on every message and its own
        ``agentId``, which is also what the file is named after. The agent id identifies the
        conversation in the file; the session id identifies its parent.
        """

        return cls._message_uid(messages, ("agentId",)) or cls._message_uid(messages, ID_KEYS)

    @classmethod
    def _gemini_uid(
        cls, messages: tuple[Mapping[str, Any], ...], path: Path
    ) -> str | None:
        """Return the identifier of the chat this file holds: its session id and when it started.

        The Gemini CLI reuses one session id for a service it runs — every chat of its a2a server is
        logged under ``a2a-server`` — so the id alone names the service and not the conversation. The
        start moment is in the header of every chat and is what tells one from another.
        """

        header = next(
            (
                message
                for message in messages
                if isinstance(message.get("sessionId"), str)
                and isinstance(message.get("startTime"), str)
            ),
            None,
        )
        if header is None:
            return cls._message_uid(messages, ID_KEYS)
        return f"{header['sessionId']}/{header['startTime']}"

    @classmethod
    def _gemini_turns(
        cls, messages: tuple[Mapping[str, Any], ...]
    ) -> tuple[SessionTurn, ...]:
        """Read the messages a Gemini CLI chat sets, in the order it sets them.

        Its content blocks carry the text and no label, where the shared reader wants a block that
        says it is text, so the text is joined here and handed over as one string.
        """

        return tuple(
            item
            for message in messages
            for changed in [message.get("$set")]
            if isinstance(changed, Mapping)
            for body in changed.get("messages") or ()
            if isinstance(body, Mapping)
            for item in [
                cls._turn(
                    body.get("type"),
                    cls._gemini_text(body.get("content")),
                    body.get("timestamp"),
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
        cls, messages: tuple[Mapping[str, Any], ...], path: Path
    ) -> str | None:
        """Return the first OpenClaw session identifier."""

        return cls._message_uid(messages, ("id", "session_id"))

    @classmethod
    def _hermes_uid(
        cls, messages: tuple[Mapping[str, Any], ...], path: Path
    ) -> str | None:
        """Return the first Hermes session identifier."""

        return cls._message_uid(messages, ID_KEYS)

    @staticmethod
    def _message_uid(
        messages: tuple[Mapping[str, Any], ...], keys: tuple[str]
    ) -> str | None:
        """Find the first non-empty identifier in supported message scopes."""

        for message in messages:
            scopes = [message]
            scopes += [
                value
                for key in ("payload", "message", "data")
                if isinstance(value := message.get(key), Mapping)
            ]
            for key in keys:
                for scope in scopes:
                    value = scope.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        return None

    @classmethod
    def _codex_turns(
        cls, messages: tuple[Mapping[str, Any], ...]
    ) -> tuple[SessionTurn, ...]:
        """Extract Codex response messages, or legacy event messages when absent."""

        response = tuple(
            item
            for message in messages
            if message.get("type") == "response_item"
            and isinstance(payload := message.get("payload"), Mapping)
            and payload.get("type") == "message"
            for item in [
                cls._turn(
                    payload.get("role"), payload.get("content"), message.get("timestamp")
                )
            ]
            if item is not None
        )
        if response:
            return response
        roles = {"user_message": "user", "agent_message": "assistant"}
        return tuple(
            item
            for message in messages
            if message.get("type") == "event_msg"
            and isinstance(payload := message.get("payload"), Mapping)
            for item in [
                cls._turn(
                    roles.get(payload.get("type")),
                    payload.get("message"),
                    message.get("timestamp"),
                )
            ]
            if item is not None
        )

    @classmethod
    def _claude_code_turns(
        cls, messages: tuple[Mapping[str, Any], ...]
    ) -> tuple[SessionTurn, ...]:
        """Extract Claude Code user and assistant turns with message flags."""

        return tuple(
            item
            for message in messages
            if message.get("type") in ROLES
            and isinstance(body := message.get("message"), Mapping)
            for item in [
                cls._turn(
                    body.get("role", message.get("type")),
                    body.get("content"),
                    message.get("timestamp"),
                    message.get("isMeta") is True,
                    message.get("isSidechain") is True,
                )
            ]
            if item is not None
        )

    @classmethod
    def _openclaw_turns(
        cls, messages: tuple[Mapping[str, Any], ...]
    ) -> tuple[SessionTurn, ...]:
        """Extract OpenClaw turns from nested message messages."""

        return tuple(
            item
            for message in messages
            if isinstance(body := message.get("message"), Mapping)
            for item in [
                cls._turn(
                    body.get("role"),
                    body.get("content"),
                    message.get("timestamp", message.get("ts")),
                )
            ]
            if item is not None
        )

    @classmethod
    def _agy_turns(
        cls, messages: tuple[Mapping[str, Any], ...]
    ) -> tuple[SessionTurn, ...]:
        """Map Agy user input and planner responses to canonical turns."""

        roles = {"USER_INPUT": "user", "PLANNER_RESPONSE": "assistant"}
        return tuple(
            item
            for message in messages
            for item in [
                cls._turn(
                    roles.get(message.get("type")),
                    message.get("content"),
                    message.get("created_at"),
                )
            ]
            if item is not None
        )

    @classmethod
    def _hermes_turns(
        cls, messages: tuple[Mapping[str, Any], ...]
    ) -> tuple[SessionTurn, ...]:
        """Extract Hermes turns from flat role and content messages."""

        return tuple(
            item
            for message in messages
            for item in [
                cls._turn(
                    message.get("role"), message.get("content"), message.get("timestamp")
                )
            ]
            if item is not None
        )

    @staticmethod
    def _messages(path: Path) -> tuple[Mapping[str, Any], ...]:
        """Read valid JSON objects from a JSONL session file."""

        # a writer crash or interrupted flush can leave one line truncated mid-message;
        # skip that line rather than losing every message in the file over it.
        messages: list[Mapping[str, Any]] = []
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    messages.append(value)
        if not messages:
            raise ValueError(f"{path}: session file is empty")
        return tuple(messages)

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
        """A harness's time, as Handler.time reads it, but for an ISO string without an offset, which a harness writes
        in UTC."""
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                return Handler.valid_time(parsed.replace(tzinfo=timezone.utc).astimezone())
        return Handler.time(value)

    @classmethod
    def _timestamps(cls, messages: tuple[Mapping[str, Any], ...]) -> Iterator[datetime]:
        """Record times only: the message, its payload, or its message. Values quoted deeper inside content are not the session's time."""

        for message in messages:
            for scope in (message, message.get("payload"), message.get("message")):
                if not isinstance(scope, Mapping):
                    continue
                for key in TIME_KEYS:
                    if (stamp := Handler.valid_time(cls._stamp(scope.get(key)))) is not None:
                        yield stamp

    @classmethod
    def _models(cls, messages: tuple[Mapping[str, Any], ...]) -> tuple[str, ...]:
        """Return unique model names found anywhere in the messages."""

        return cls._uniq(
            value
            for message in messages
            for key, value in cls._walk_values(message)
            if key in MODEL_KEYS
        )

    @classmethod
    def _claude_code_parent(
        cls, messages: tuple[Mapping[str, Any], ...]
    ) -> tuple[str | None, bool]:
        """Return a Claude Code parent session id and whether the file is a subagent's.

        A file carrying an ``agentId`` is a subagent's transcript, and the ``sessionId`` every
        message carries is the session that spawned it.
        """

        if cls._message_uid(messages, ("agentId",)) is None:
            return None, False
        return cls._message_uid(messages, ID_KEYS), True

    @staticmethod
    def _parent(messages: tuple[Mapping[str, Any], ...]) -> tuple[str | None, bool]:
        """Return a Codex parent session id and whether the session is a subagent."""

        for message in messages:
            if message.get("type") != "session_meta":
                continue
            payload = message.get("payload")
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
    def _topic(turns: tuple[SessionTurn, ...]) -> str:
        """The first line a person typed."""
        for turn in turns:
            if turn.role != "user" or turn.meta or turn.sidechain:
                continue
            if text := SessionHandler.typed(turn.text):
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
    """A harness's session folder, which probe tells by its path: a Hermes home, .hermes; an Agy home,
    .gemini/antigravity or .gemini/antigravity-cli, with antigravity_state.pbtxt or jetski_state.pbtxt; or an Agy
    session folder in .gemini/antigravity-cli/brain. It is a folder, so its members are parsed as any folder's; its sessions are the session
    records among them at any depth, all of one harness: their harness, their uid when they agree on one, how many
    there are and their span are its data.

    Returns: FolderHandler's record, with subtype sessionfolder; data.harness, data.sessions, how many, and data.uid
    where they agree on one; span from the first of its sessions to the last.
    """

    @classmethod
    async def parse(cls, path: str | Path) -> Record:
        record = await super().parse(path)
        path = Path(path).absolute()
        sessions = list(cls._sessions(record))
        harnesses = SessionHandler._uniq([session.subtype for session in sessions] + [SessionHandler._home_harness(path)])
        if len(harnesses) != 1:
            raise ValueError(f"{path}: a session folder holds one harness, not {harnesses}")
        uids = {session.uid for session in sessions if session.uid}
        record.data.update(harness=harnesses[0], sessions=len(sessions))
        if len(uids) == 1:
            record.data["uid"] = uids.pop()
        record.span = cls.spanning([time for session in sessions if session.span for time in (session.span.start, session.span.end)])
        return record

    @classmethod
    def _sessions(cls, record: Record) -> Iterator[Record]:
        """The session records among what a folder holds, at any depth; a session's own contents are its messages."""
        for member in record.contents:
            if member.type == "session":
                yield member
            elif member.type == "folder":
                yield from cls._sessions(member)


# What probe reads off a path: a file's handler by its suffix, a folder's by its path; a program adds its own.
SUFFIXES: dict[str, type[Handler]] = {
    ".sqlite": SqliteHandler, ".sqlite3": SqliteHandler, ".db": SqliteHandler, ".md": MarkdownHandler,
    ".csv": CSVHandler, ".log": LogHandler, ".eml": EmailHandler, ".msg": EmailHandler, ".jsonl": SessionHandler,
}
FOLDERS: dict[str, type[Handler]] = {
    ".hermes": SessionFolderHandler, ".gemini/antigravity": SessionFolderHandler,
    ".gemini/antigravity-cli": SessionFolderHandler, ".gemini/antigravity-cli/brain/*": SessionFolderHandler,
}
# The handler that reads a record of a type and subtype; a link, a junction, an offline file or an ignored path has none.
HANDLERS: dict[tuple[str, str | None], type[Handler]] = {
    (handler.type, handler.subtype): handler
    for handler in (FolderHandler, FileHandler, *SUFFIXES.values(), *FOLDERS.values())
}


def kind(stat: os.stat_result) -> str:
    """What the stat says a path is: a symlink, a junction, an offline file, a folder or a file."""
    if stat_module.S_ISLNK(stat.st_mode):
        return "symlink"
    if getattr(stat, "st_reparse_tag", 0) == getattr(stat_module, "IO_REPARSE_TAG_MOUNT_POINT", None):
        return "junction"
    if getattr(stat, "st_file_attributes", 0) & OFFLINE:
        return "offline"
    if stat_module.S_ISDIR(stat.st_mode):
        return "folder"
    if stat_module.S_ISREG(stat.st_mode):
        return "file"
    raise ValueError("neither a folder nor a file")


def ignored(path: Path, stat: os.stat_result) -> bool:
    """FileIndexer's global ignore rules: a name, a suffix or a prefix, and a folder's name or its Windows system
    attribute. A folder is not ignored for starting with a dot or for being hidden; a root, with no name, never is."""
    folder = stat_module.S_ISDIR(stat.st_mode)
    return bool(path.name) and (path.name in IGNORED_NAMES or path.suffix in IGNORED_SUFFIXES
                                or path.name.startswith(IGNORED_PREFIX)
                                or folder and (path.name in IGNORED_FOLDERS
                                               or bool(getattr(stat, "st_file_attributes", 0) & WINDOWS_SYSTEM)))


@sync
async def probe(path: str | Path) -> Record:
    """What info gives of a path: its record from its stat and its name, nothing read. The stat says what the path
    is; a link or a junction is that and its target, an offline file is a file whose bytes are not on this host, and
    an ignored path is ignored. A folder's handler is the one FOLDERS gives its path, a file's the one SUFFIXES gives
    its suffix. Awaited inside an event loop, returned directly outside one.

    Returns: type and subtype, which say the handler that reads it: symlink or junction, with data.target; file and
    offline; ignored, with subtype folder or file; else the handler's. name the path's name; created and updated as
    stat gives them; meta.size."""
    path = Path(path).absolute()
    stat = path.stat(follow_symlinks=False)
    record = Record(name=path.name or str(path), meta={"size": stat.st_size},
                    created=datetime.fromtimestamp(getattr(stat, "st_birthtime", stat.st_ctime)).astimezone(),
                    updated=datetime.fromtimestamp(stat.st_mtime).astimezone())
    match kind(stat):
        case "symlink" | "junction" as link:
            record.type, record.data["target"] = link, os.readlink(path)
        case "offline":
            record.type, record.subtype = "file", "offline"
        case found if ignored(path, stat):
            record.type, record.subtype = "ignored", found
        case "folder":
            handler = next((handler for pattern, handler in FOLDERS.items() if path.match(pattern)), FolderHandler)
            record.type, record.subtype = handler.type, handler.subtype
        case "file":
            handler = SUFFIXES.get(path.suffix.casefold(), FileHandler)
            record.type, record.subtype = handler.type, handler.subtype
    return record
