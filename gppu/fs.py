"""gppufs: DataObjects in Containers, Containers in Locations and Collections.

The stable interface. These public methods keep their names and signatures while providers.py, handlers.py and
indexing.py move into this module; the names are the ones production runs today. Two APIs are made of them: /config
is the Locations, as admin.karelin.ai/configuration/locations shows them; /lake is the Containers and the Collection,
which the Dagster jobs write into \\\\s1\\Lake.

Each method names what uses it in production: the locations page, the Dagster jobs (the M365 and Telegram exports,
plaud_import, source_markdown, index_postgres, load_locations, entities_contacts), FileIndexer, the Session Manager.

uid, Alex, 2026-09-21: "uid for an object is (path + uid)" / "uid for locaition is provider uid (dash-separated and
path)" / "m365 -child-> m365-karelin -child-> m365-karelin-graph -child-> m365-karelin-graph/alex/contacts" / "uid and
path are human readable and are used to build URIs" / "bigint ids are interna"
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO, Any, BinaryIO, Mapping

from .gppu import TimeSpan, y2path, y2uri

LEVELS = ('refresh', 'files', 'handlers', 'archives')
"""How deep Container.walk reads: folders only, files, files read by handlers, and archive members too."""


# region what is stored


@dataclass(frozen=True)
class DataObject:
  """Data and its uri, read from or written to a Container: a file, a message, a contact, a recording."""
  uri: y2uri
  """Where it came from."""
  content: dict[str, Any] | list[Any] | str | int | float | bool | None | bytes | BinaryIO
  """What it holds: JSON, text, bytes or a stream."""
  identity: str | None
  """The id its own system gives it, or None."""
  kind: str = 'object'
  """What it is to its source; the naming templates choose its path by kind."""
  name: str = ''
  """Its name, used by the naming templates."""
  parent: DataObject | None = None
  """The object it belongs to, such as the message of an attachment."""
  removed: bool = False
  """True when refresh reports it gone."""


# endregion
# region /config


class Location:
  """A configured place where data is kept: a host, a drive, a folder, a tenant's mailbox. Locations form a tree."""
  uid: str
  """Provider uid, dash-separated, then `/` and the path: `file-alex-laptop/D:/TextLake`."""
  provider: str
  """The provider uid it is reached through: `file-alex-laptop`, `m365-karelin-graph`."""
  parent: str | None
  """The uid of the Location above it, or None for a root."""
  uri: y2uri
  """Its canonical uri: `file://alex-laptop/D:/TextLake`."""
  path: y2path
  """What follows the provider uid in its uid: `D:/TextLake`."""
  name: str
  kind: str
  """`Host` or `Location`."""
  service: str
  icon: str
  tags: list[str]
  folders: dict[str, dict[str, str]]
  """Named folders inside it, each with a name and a path."""

  def ls(self) -> list[Location]:
    """The Locations directly below this one. The locations page, FileIndexer."""
    ...

  def walk(self) -> Iterator[tuple[Location, list[Location]]]:
    """This Location and every Location below it, each with the ones directly below it. load_locations."""
    ...

  def container(self, path: y2path | str = '') -> Container:
    """The Container at path below this Location. The exports, plaud_import, FileIndexer."""
    ...

  def uri_of(self, path: y2path | str = '') -> y2uri:
    """The uri of path below this Location. FileIndexer, the exports."""
    ...

  @staticmethod
  def relative(path: y2path | str) -> y2path:
    """path, checked to be relative and slash-separated, without `..`. FileIndexer."""
    ...


# endregion
# region /lake


class Container:
  """A tree of DataObjects addressed by path: a folder, a drive, a mailbox, a chat, an archive. Not storage."""
  uri: y2uri
  """The uri of its root."""

  def ls(self, path: y2path | str = '', detail: bool = True) -> list[dict[str, Any]] | list[str]:
    """What is directly inside path: name, type, size. plaud_import, index_postgres."""
    ...

  def walk(self, path: y2path | str = '', *, level: str = 'files', recursive: bool = False,
           boundaries: Iterable[y2path | str] = ()) -> Iterator[tuple[dict, list[dict]]]:
    """Every folder at and below path with what it holds, read as deep as level. FileIndexer, the Session Manager."""
    ...

  def info(self, path: y2path | str = '', refresh: bool = False) -> dict[str, Any]:
    """What is known about path without reading its content; refresh reads it again. The Session Manager."""
    ...

  def read(self, path: y2path | str | DataObject) -> DataObject:
    """The object at path, or where the naming templates put a DataObject, with its content. The exports,
    plaud_import, source_markdown."""
    ...

  def open(self, path: y2path | str, mode: str = 'rb') -> IO[bytes]:
    """The bytes at path, a member inside an archive included. plaud_import."""
    ...

  def write(self, path: y2path | str, obj: DataObject) -> None:
    """Store obj at path. The exports, plaud_import, source_markdown."""
    ...

  def delete(self, path: y2path | y2uri | str) -> None:
    """Remove the object at path or uri. The exports, plaud_import."""
    ...

  def refresh(self, state: dict[str, Any], path: y2path | str = '') -> AbstractContextManager[Iterator[DataObject]]:
    """The objects changed since state, removed ones included; state moves on only after all are consumed. The
    exports."""
    ...

  def path_of(self, obj: DataObject) -> y2path:
    """Where obj belongs by the naming templates. The exports, plaud_import."""
    ...


class Collection(Container):
  """A Container of objects from any Location, addressed by uri. The Lake is the Collection of the configured
  Locations."""
  locations: dict[str, Location]
  """Every configured Location, by uid. The locations page."""

  def location(self, uid: str) -> Location:
    """The configured Location with uid. The exports, plaud_import, FileIndexer."""
    ...

  def location_of(self, uri: y2uri | str) -> tuple[Location, y2path]:
    """The Location a uri falls under, and the path below it. index_postgres, FileIndexer."""
    ...


# endregion
# region providers: how Locations and Containers are reached


class Provider:
  """Reaches one kind of source. A provider subclasses Location and Container and registers its Location class
  under its scheme."""
  scheme: str
  """`file`, `m365`, `telegram`, `plaud`."""


class FileSystem(Provider):
  """Files on a host, read through the handlers. In gppu."""
  scheme = 'file'


class M365(Provider):
  """Microsoft 365 through Graph: calendars, contacts, to-do, SharePoint. In CRAP; the M365 exports."""
  scheme = 'm365'


class Telegram(Provider):
  """An account's chats and contacts. In CRAP; the Telegram exports."""
  scheme = 'telegram'


class Plaud(Provider):
  """Recordings, their audio and their texts. In CRAP; plaud_import."""
  scheme = 'plaud'


# endregion
# region handlers: what a file is


class Handler:
  """Recognises one kind of file and loads it into a typed object with its statistics. Handlers compose by
  multiple inheritance into FileHandler."""
  name: str
  """The key its metadata is kept under: `markdown`, `session`."""

  def identify(self, path: Path) -> bool:
    """Whether this handler reads path."""
    ...

  def load(self, path: Path) -> Any:
    """The typed object at path: a SessionFile, a MarkdownFile. The Session Manager, source_markdown."""
    ...

  def invalidate(self, path: Path | None = None) -> None:
    """Forget what was cached for path, or for everything."""
    ...


class FileHandler(Handler):
  """The composed handlers: probes a path with each and keeps what each found."""

  def probe(self, path: Path, recursive: bool = True) -> list[Record]:
    """Every entry at path read by the handlers that recognise it. index_postgres, the Session Manager."""
    ...


@dataclass(frozen=True)
class Record:
  """One file, folder or archive member and what the handlers found about it."""
  path: Path
  is_folder: bool
  size: int
  modified_at: datetime | None
  handlers: tuple[str, ...]
  span: TimeSpan | None
  """The time its content covers."""
  metadata: dict[str, Any]


class SessionFile:
  """One agent session, as the Session Manager reads it."""
  uid: str
  harness: str
  span_start: datetime | None
  span_end: datetime | None
  span: TimeSpan | None
  turns: int
  human_messages: tuple[str, ...]


class FolderHandler(Handler):
  """A folder: how many files and folders, their size, the time they span."""


class IgnoredHandler(Handler):
  """A path listed but never entered, such as a cache."""


class LocationHandler(Handler):
  """A folder that is a configured Location."""


class ArchiveHandler(Handler):
  """An archive, its members read like files."""


class GitHandler(Handler):
  """A Git repository, from its local history."""


class SqliteHandler(Handler):
  """An SQLite database."""


class MarkdownHandler(Handler):
  """Markdown: frontmatter and text."""


class CSVHandler(Handler):
  """A CSV file."""


class LogHandler(Handler):
  """A log file."""


class EmailHandler(Handler):
  """An email message."""


class BrowserHandler(Handler):
  """A browser profile and its history."""


class ImageHandler(Handler):
  """An image."""


class VideoHandler(Handler):
  """A video."""


class SessionHandler(Handler):
  """An agent session, loaded as a SessionFile."""


class ChatGPTHandler(Handler):
  """A ChatGPT export."""


class AnthropicHandler(Handler):
  """An Anthropic export."""


# endregion
# region index


class GppuIndex:
  """Where what the handlers read is kept, by uri, so it is not read again: SQLite beside the data in gppu, the
  Lake's Postgres in CRAP."""

  def entry(self, address: str) -> tuple[dict, list[dict] | None] | None:
    """What is kept for address and the listing of what is inside it, or None."""
    ...

  def put(self, entries: Mapping[str, tuple[dict | None, list[dict] | None]]) -> None:
    """Keep what the handlers read, by address."""
    ...

  def moved(self, source: str, destination: str) -> None:
    """What was kept for source, and below it, is at destination now."""
    ...


# endregion
