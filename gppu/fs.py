"""gppufs: DataObjects in Containers, Containers in Locations and Collections.

Two APIs, made of the public methods of these classes. They take over the routes admin_ui serves in production.

/config: the configuration, as admin.karelin.ai/configuration/locations shows it today.
  GET  /config/locations            every Location, one row each, parent by uid:
         {"uid": "laptop-data/TextLake", "parent": "laptop-data", "provider": "file://",
          "uri": "file://alex-laptop/D:/TextLake", "name": "TextLake", "kind": "Location", "path": "D:/TextLake",
          "service": "file", "icon": "/machine.svg", "tags": [], "folders": {}}
  GET  /config/locations/{uid}      one Location, the same row
  POST /config/locations/{uid}/save write it to configuration                          Location.save
  GET  /config/locations/{uid}/ls   the Locations directly below it                    Location.ls
  GET  /config/providers            Providers, by uri: `file://`, `m365://`, `telegram://`, `plaud://`
  GET  /config/connections          connection names, without credentials
  POST /config/locations/{uid}/uri_of, container, path_of   used by FileIndexer, Dagster and the template preview

/lake: what the Locations hold, by uri; the Lake is the Collection at lake://.
  GET  /records/browse              children within a Location      /lake/{uri}/ls, walk            Container
  GET  /records/record              one record and its spans        /lake/{uri}/read                Container
  GET  /records                     search by text, Location, kind  /lake/lake://find               Collection
  GET  /sources/resolve             the owner of a source reference /lake/lake://location_of        Collection
  GET  /sources/record              a source object as fetched      /lake/{uri}/info, open          Container
  Dagster, Plaud import             write, delete, refresh          /lake/{uri}/write, delete, refresh

Spans, annotations and threads are links between objects, and come later with the graph. /sources/query runs
registered SQL and stays in admin_ui. The Lake stores what it fetched at sources/<Location uid>/<path> and
renditions under text/.

Provider, Handler and GppuIndex are what a Container is built on. This module replaces providers.py, handlers.py
and indexing.py.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import IO, Any

from .gppu import y2path, y2uri


# region /config


class Location:
  """A configured place where data is kept: a host, a volume, a folder, a tenant, a mailbox.

  Locations form a tree. Each one reaches its data through a Provider and opens Containers below itself. State
  builds a Location from each row of the locations table.
  """
  uid: str
  """Its key in configuration, readable by a person. A dash steps down the configured tree to a named Location, a
  slash to a path below one: `laptop` is Alex-Laptop, `laptop-data` its D: volume, `laptop-data/TextLake` a folder
  on it. The Provider is not part of it."""
  parent: Location | None
  """The Location above it, or None for a root."""
  provider: Provider
  """The Provider that reaches its data, by its uri: `file://` for every Location made of files, local, on smb or
  on Synology Drive; `m365://` for Microsoft 365."""
  uri: y2uri
  """Its canonical uri: `file://alex-laptop/D:/TextLake`, `m365://karelin/alex/onedrive`."""
  name: str
  """Its display name: `Alex-Laptop`, `TextLake`."""
  kind: str
  """What it is: `Host` or `Location`."""
  path: y2path
  """Its path on its Provider: `D:/TextLake`; empty for a root."""
  service: str
  """How its Provider reaches it: `file` on the host itself, `smb` over a share, `sd` through Synology Drive."""
  icon: str
  """The icon admin_ui shows for it."""
  tags: list[str]
  """Tags from the vocabulary."""
  folders: dict[str, dict[str, str]]
  """Named folders inside it, each with a name and a path: `inbox`."""
  index: GppuIndex
  """Where what is read below it is kept."""

  def __init__(self, data: dict[str, Any]) -> None:
    """Built by State from a row of the locations table."""
    ...

  def ls(self) -> list[Location]:
    """The Locations directly below this one: the configured ones, then the ones its Provider finds."""
    ...

  def walk(self) -> Iterator[tuple[Location, list[Location]]]:
    """This Location and every Location below it, each paired with the Locations directly below it."""
    ...

  def container(self, path: y2path | str = '') -> Container:
    """The Container at path below this Location."""
    ...

  def uri_of(self, path: y2path | str = '') -> y2uri:
    """The uri of path below this Location: its uri, a colon, and the path."""
    ...

  def save(self) -> Location:
    """Write this Location to configuration, creating it when it is new, and return it as saved."""
    ...

  @staticmethod
  def relative(path: y2path | str) -> y2path:
    """path checked to be relative, slash-separated and without `..`."""
    ...


# endregion
# region /lake


@dataclass
class DataObject:
  """Metadata about one thing, and its content once a handler has read it: a file, a folder, a message, a record.

  A file is a DataObject only after a handler has read it. A part of one, such as a span of a session, is a
  DataObject at the same path with a fragment.
  """
  path: y2path
  """Where it is in its Container. The last segment is its name."""
  identity: str | None = None
  """The id its own system gives it, such as a Graph id or a Telegram id; None when it has none."""
  kind: str = 'object'
  """What it is to its source: `file`, `folder`, `message`, `contact`."""
  metadata: dict[str, Any] = field(default_factory=dict)
  """What the source says about it, such as size, times and attributes, and what each handler found, under the
  handler's name."""
  content: Any = None
  """What a handler read: a parsed document, a session, JSON, bytes or a stream."""
  parent: DataObject | None = None
  """The object it belongs to, such as the message of an attachment; None for most objects."""
  removed: bool = False
  """True when it is gone from the source. The index keeps it."""


class Container:
  """A tree of DataObjects, addressed by path: a folder, a drive, a mailbox, an archive.

  A Container is not storage. It reads through its Location's Provider and keeps what it read in its index, so it
  can answer when the source is offline.
  """
  uri: y2uri
  """Its own uri: the uri of its root below its Location."""
  index: GppuIndex
  """Where it keeps what it read: its Location's index, or the one a Collection is given."""

  def __init__(self, location: Location, root: y2path | str = '') -> None:
    """The Container at root below location."""
    ...

  def ls(self, path: y2path | str = '') -> list[DataObject]:
    """The DataObjects directly inside path."""
    ...

  def walk(self, path: y2path | str = '', *, level: str = 'files', recursive: bool = False,
           boundaries: Iterable[y2path | str] = ()) -> Iterator[tuple[DataObject, list[DataObject]]]:
    """Every folder at and below path, with the DataObjects inside it, reading as deep as level asks."""
    ...

  def info(self, path: y2path | str) -> DataObject:
    """The DataObject at path, without its content."""
    ...

  def read(self, path: y2path | str) -> DataObject:
    """The DataObject at path, read by its handlers, with its content."""
    ...

  def open(self, path: y2path | str, mode: str = 'rb') -> IO[bytes]:
    """The bytes at path, including a member inside an archive."""
    ...

  def write(self, path: y2path | str, obj: DataObject) -> DataObject:
    """Store obj at path, replacing what is there, and return it as stored."""
    ...

  def delete(self, path: y2path | str) -> None:
    """Remove the object at path from the source. The index keeps it, marked removed."""
    ...

  def refresh(self, state: dict[str, Any], path: y2path | str = '') -> AbstractContextManager[Iterator[DataObject]]:
    """The DataObjects at or below path that changed since state, including removed ones.

    state moves forward only when every change was consumed inside the context without an error.
    """
    ...

  def path_of(self, obj: DataObject) -> y2path:
    """The path where obj belongs in this Container, from its Location's naming templates."""
    ...


class Collection(Container):
  """A Container of DataObjects from any Location, addressed by uri instead of path.

  Its methods take a uri wherever a Container takes a path. The Lake is the Collection of the configured Locations
  and of everything the index holds below them; its uri is `lake://`.
  """

  def __init__(self, index: GppuIndex, uri: y2uri | str = 'lake://') -> None:
    """The Collection of the configured Locations, over index."""
    ...

  def find(self, text: str = '', location: str = '', kind: str = '', parent: str = '') -> list[DataObject]:
    """The DataObjects the index holds that match text in their name or path, under location, of kind, in parent."""
    ...

  def location_of(self, uri: y2uri | str) -> tuple[Location, y2path]:
    """The Location a uri falls under, and the path below it."""
    ...


# endregion
# region machinery


class Provider:
  """Reaches one kind of source through its client: files, Microsoft 365, Telegram, Plaud.

  One Provider both finds Locations and reads the Containers below them, because both go through the same
  connection and the same client. Paths are below the Provider's Location.
  """
  uri: y2uri
  """Its uri: `file://`, `m365://`. It is not per host or per account; hosts, tenants and accounts are Locations,
  and each carries the connection its Provider uses to reach it."""
  handlers: tuple[Handler, ...]
  """The handlers that read what it lists, in the order they are tried. Empty when the source returns objects
  already read."""

  def __init__(self, location: Location) -> None:
    """Connects with the connection configured for location."""
    ...

  def locations(self) -> list[Location]:
    """The Locations the source defines below this Provider's Location, such as a tenant's users and drives."""
    ...

  def ls(self, path: y2path) -> list[DataObject]:
    """The DataObjects directly inside path, with what the source says about each."""
    ...

  def info(self, path: y2path) -> DataObject:
    """The DataObject at path, with what the source says about it."""
    ...

  def open(self, path: y2path, mode: str = 'rb') -> IO[bytes]:
    """The bytes at path."""
    ...

  def write(self, path: y2path, obj: DataObject) -> None:
    """Store obj at path, replacing what is there."""
    ...

  def delete(self, path: y2path) -> None:
    """Remove the object at path."""
    ...

  def refresh(self, state: dict[str, Any], path: y2path) -> AbstractContextManager[tuple[Iterator[DataObject], Callable[[], None]]]:
    """The objects that changed below path since state, and the call that moves state forward."""
    ...


class Handler:
  """Recognises one kind of object and reads it into metadata and content."""
  name: str
  """The key its metadata and its errors are kept under: `markdown`, `session`."""

  def identify(self, obj: DataObject, container: Container) -> bool:
    """Whether this handler reads obj, judged without opening it."""
    ...

  def probe(self, obj: DataObject, container: Container) -> DataObject:
    """obj with this handler's metadata under its name and, when it has one, its content. An error is kept in the
    metadata, so one bad file does not stop a listing."""
    ...


class GppuIndex:
  """Keeps what was read from Containers, by uri, so they can be listed without reaching the source."""

  def entry(self, uri: y2uri) -> tuple[DataObject, list[DataObject] | None] | None:
    """The DataObject at uri and the ones inside it, or None when it holds nothing there. The list is None when it
    was never listed."""
    ...

  def put(self, uri: y2uri, obj: DataObject, listing: list[DataObject] | None = None) -> None:
    """Keep obj at uri, and the DataObjects inside it when listing is given."""
    ...


# endregion
# region implementations in gppu; M365, Telegram, Plaud and the Lake's Postgres index are in CRAP


class FileSystem(Provider):
  """Files on a host. Its Locations are hosts, their volumes and folders. Every handler below is its handler."""


class SqliteIndex(GppuIndex):
  """An index kept beside the data it describes, in `.<name>.gppufs.sqlite`."""


class FolderHandler(Handler):
  """A folder: how many files and folders it holds, their size, and the time they span."""


class IgnoredHandler(Handler):
  """A path that is listed but never entered, such as a cache."""


class LocationHandler(Handler):
  """A folder that is a configured Location of its own."""


class ArchiveHandler(Handler):
  """An archive. Its members are listed and opened by path, as if the archive were a folder."""


class GitHandler(Handler):
  """A Git repository, read from its local history and configuration."""


class SqliteHandler(Handler):
  """An SQLite database."""


class MarkdownHandler(Handler):
  """A Markdown file: its frontmatter and text."""


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
  """An agent session: its turns, its messages and the time it spans."""


class LLMExportHandler(Handler):
  """A conversation export from an LLM service."""


class ChatGPTHandler(LLMExportHandler):
  """A ChatGPT export."""


class AnthropicHandler(LLMExportHandler):
  """An Anthropic export."""


# endregion
