"""gppufs: DataObjects in Containers, Containers in Locations and Collections.

Declarations and docstrings. providers.py, handlers.py and indexing.py become this one module: their code moves
into these classes, and the API and the documentation are generated from them. The configuration classes live here
for now.

  DataObject                  metadata, with content in some cases                         /lake
    Span                      a part of a DataObject: a stretch of a session, a passage     /lake
    Container                 holds DataObjects: a folder, an archive                       /lake
      Location                a Provider and a path-to-container                            /config
      Collection              a Container that links arbitrary DataObjects                  /lake
  Link                        a labelled edge between two uris                              /lake
  Annotation                  a statement about a DataObject, with evidence and author      /lake
  Handler                     where DataObjects come from: identify, probe
    Provider                  a Handler instantiated from a connection                      /config, a list
      FileSystem, M365, Postgres
    FolderHandler, ArchiveHandler, MarkdownHandler, SessionHandler, ...
  GppuIndex                   the tree: SqliteIndex beside the data, a database in CRAP

Routes. The API has two routes, /config and /lake, and every public method belongs to one of them as it is. A
Location's own members serve /config; the Container methods it inherits serve /lake. How a Provider or a handler
reaches and reads an object is its inner working, so those methods are protected.

The tree and the graph. Containers make a tree: every DataObject is in one place. Links and Annotations make a
graph over it: a Location and the Containers it reaches, a Collection and what it links, one Span and the next,
a session and the Thread it belongs to. The graph is what /lake adds to a file system.

The Lake is an index and storage. gppu has no Lake: to gppu it is a Collection loaded from configuration. The upper
levels -- Locations -- come from configuration; the lower levels are loaded from the database.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import IO, Any

from .gppu import y2path, y2uri


@dataclass(frozen=True)
class DataObject:
  """Metadata, with content in some cases. A file, a folder, an archive, a contact and a table are all DataObjects.

  A file is not a DataObject without a handler: a handler returns metadata, and that metadata is stored as the
  DataObject. What the source always supplies is stored for every DataObject, whether its source is online or not.
  A DataObject is a value. It reaches nothing itself: it is retrieved by uri through the Container that holds it,
  and saved by uri through a Collection.

  Route: /lake returns it.

  Today: providers.DataObject and handlers.Record, with Probe, FileStats and HandlerError, become this one type.
  identity becomes uid; kind and name move into metadata; parent is the uri without its last segment; removed
  becomes a time. is_folder, size and modified_at, the probes, stats and errors move into
  metadata, each under its handler's name.
  """
  uri: y2uri
  """Canonical uri: the Location's uri, `:`, and the path inside the Container, as in
  `m365://karelin/alex/files:Contact%20Photos`. Its last segment names the object. It can have other uris."""
  uid: str
  """Unique identifier: the one its own system gives it. It is not the Index's id, but an object with no identifier
  of its own takes that id as its uid."""
  metadata: dict[str, Any] = field(default_factory=dict)
  """What the source supplies -- for a file, its type, size, times and file system attributes -- and, under each
  handler's name, what that handler returned."""
  content: Any = None
  """Present once a handler has read it: MarkdownFile, CSVFile, SessionFile and the other typed objects."""
  removed: datetime | None = None
  """When it was deleted. Its metadata stays held."""
  links: tuple[Link, ...] = ()
  """The Links from it: its edges in the graph."""
  annotations: tuple[Annotation, ...] = ()
  """What has been said about it."""


class Span(DataObject):
  """A part of a DataObject: a stretch of time in a session, a passage of text. The unit that sessions, threads,
  the timeline and time accounting all count in.

  Its uri is the uri of the DataObject it is part of, with a fragment naming the part: RFC 3986 gives the fragment
  exactly this job. Spans follow one another by Links, and belong to a Thread by a Link to it.

  Route: /lake.

  Today: CRAP's span rows (fact.every_span, `pg://pg.karel.in/files/lake/span`), read and written by admin_ui's
  spans, fact_spans and chains.
  """


class Container(DataObject):
  """A DataObject that holds DataObjects -- exactly what a zip file or a folder stores. Not storage.

  A Container is independent of Location: several Locations can reach one Container. TextLake is one Container,
  reached as `laptop-data/TextLake` and on other hosts, and known globally as `textlake` or `lake://text`. One
  Location is the original; the others are manifestations. A Container retrieves by uri and never writes.

  Route: /lake.

  Today: providers.Container with ls, walk, read, write, delete and refresh, over FileContainer and CRAP's
  M365Container, PlaudContainer and TelegramContainer. ls returns DataObjects instead of fsspec rows; walk goes;
  read runs the handlers; write, delete and refresh move to Collection; the code for each store moves to its
  Provider.
  """
  _index: GppuIndex
  """Where its tree is held."""
  _source: Handler
  """What reaches the DataObjects it holds: its Location's Provider, or the handler of an archive."""

  def ls(self, uri: y2uri) -> list[DataObject]:
    """The DataObjects that the Container at uri holds.

    ls takes the uri because a DataObject is a value and cannot list itself. It is answered from the Index, so it
    works with nothing online. A Container the Index has never listed is listed through its Provider, and each
    DataObject is identified by the handlers and put into the Index first.
    """
    ...

  def info(self, uri: y2uri) -> DataObject:
    """The DataObject at uri, as the Index holds it: what the source supplies and what the handlers identified."""
    ...

  def read(self, uri: y2uri) -> DataObject:
    """The DataObject at uri, read by its handlers, with its content."""
    ...

  def open(self, uri: y2uri, mode: str = 'rb') -> IO[bytes]:
    """The bytes of the DataObject at uri, from its source. Raises when the source cannot be reached."""
    ...


class Location(Container):
  """A container for alike objects: a Provider and a path-to-container. The configurable structure.

  Locations form a tree through parent. A Location with no path is a root, and its uid is its Provider's. A
  configured Location is written in configuration. A discovered Location is detected on refresh and cached, and
  only discovered Locations are refreshed. Path-to-container and path-in-container together give the path to a
  DataObject.

  Route: /config for its own members; the Container methods it inherits serve /lake.

  Today: providers.Location, a _Base that hands out a separate Container and whose ls and walk list child
  Locations; FileLocation; and CRAP's M365Location, PlaudLocation and TelegramLocation. The subclasses for each
  store give way to Providers. A Location's children are the Locations naming it as parent. CRAP's
  catalog_configuration.save becomes save. The rows of State.connections become _connection, and admin_ui's
  config_connections list goes.
  """
  uid: str
  """Its Provider's uid, then `/` and the path, readable by a human: `laptop`, `laptop-data`,
  `laptop-data/TextLake`."""
  name: str
  """Its display name: `Alex-Laptop`."""
  provider: Provider
  path: y2path
  """Path-to-container. Empty for a root."""
  parent: Location | None
  mirrors: tuple[y2uri, ...]
  """Its other uris. uri is the canonical one."""
  configured: bool
  """Written in configuration, rather than discovered."""
  _connection: dict[str, Any]
  """The connection its Provider is instantiated from: an account, an endpoint and credentials. Internal to the
  Location; no route serves it."""

  def uri_of(self, path: y2path) -> y2uri:
    """Canonical uri of a path inside this Location: its uri, `:`, and the escaped path.

    Configuration defines how canonical uris are structured.
    """
    ...

  def save(self) -> Location:
    """Write this Location to configuration, creating it when it is new. Returns it as saved."""
    ...


class Collection(Container):
  """A Container that links arbitrary DataObjects by uri, rather than holding them.

  A Collection is loaded from configuration: its Locations come from configuration, and what is below them is
  loaded from the database. `Collection()` is the global Collection of configured Locations that the admin tool
  shows: the Lake. `Collection(root)` is rooted at any path or Location, which is read, indexed beside itself and
  then browsed the same way. A uri resolves to the Location whose uri begins it; the rest of the uri is the path
  inside. Objects are saved by uri, so saving is here and not on Container.

  Route: /lake.

  Today: handlers.GppuCatalog, the configured Locations keyed by uid with location(uid) and filesystem(uid);
  GppuFileSystem, the listing with handlers and the SQLite index; indexing.walk_container and walk_files.
  Container.write and Container.delete move here.
  """
  _locations: dict[str, Location]
  """The upper levels: Locations from configuration, by uid."""
  _handler: FileHandler
  """The handlers that identify and read what is below the Locations."""

  def __init__(self, root: y2uri | None = None) -> None:
    """The global Collection of configured Locations; or, given root, the Collection of that path or Location."""
    ...

  def find(self, criteria: dict[str, Any]) -> list[DataObject]:
    """DataObjects in the Index whose metadata matches criteria: anything beyond a simple recursive list."""
    ...

  def write(self, uri: y2uri, obj: DataObject) -> DataObject:
    """Save obj at uri, through the Provider of the Location that uri falls in. Returns it as the Index now holds it."""
    ...

  def delete(self, uri: y2uri) -> None:
    """Delete the DataObject at uri from its source. The Index keeps it, with removed set."""
    ...

  def refresh(self, uri: y2uri) -> list[DataObject]:
    """Re-read what is at uri from live state: the DataObjects that changed, removed ones included.

    Discovered Locations below uri are detected again. The Index keeps where the last refresh ended, and moves
    it on only once every change is held.
    """
    ...

  def link(self, source: y2uri, target: y2uri, label: str) -> Link:
    """Link the DataObject at source to the one at target. Neither has to exist: a uri names what it leads to
    without knowing anything about it."""
    ...

  def annotate(self, uri: y2uri, annotation: Annotation) -> Annotation:
    """Say something about the DataObject at uri. Returns the annotation as held, with its uid."""
    ...


@dataclass(frozen=True)
class Link:
  """A labelled, dated edge from one uri to another: the graph over the tree.

  Links join a Location and a Container where a single tree cannot hold them -- one label value, `original`,
  marks the source and every other label is for display -- a Collection and what it links, one Span and the next,
  and a session and its Thread.

  Route: /lake, in the links of a DataObject.

  Today: the typed edges of the graph database, and the annotations whose predicate is declared a link in
  admin_ui's model.
  """
  source: y2uri
  target: y2uri
  label: str
  date: datetime


@dataclass(frozen=True)
class Annotation:
  """A statement about a DataObject: a predicate and a value, with the evidence for it and who said it.

  A statement that points at another DataObject is a Link instead.

  Route: /lake, in the annotations of a DataObject.

  Today: CRAP's annotation rows (`pg://pg.karel.in/files/lake/annotation`), written by admin_ui's say, annotate
  and verify.
  """
  uid: str
  predicate: str
  value: str
  evidence: str
  who: str
  date: datetime


class Handler:
  """What DataObjects come from. A handler returns metadata, and that metadata is stored as the DataObject.

  A handler has two ways of getting information about a DataObject: identify, from what the source always
  supplies and without reading it; and probe, reading it. It reads through the Container that holds the object,
  by uri, never through a local path, so one handler serves every Provider. Handlers are mixins: a subclass of
  FileHandler lists them as its bases, and that order is the order they identify and probe in. A failure is kept
  in the metadata under the handler's name, so one bad file does not stop a listing.

  Its methods are protected: how a handler reads is its inner working.

  Today: handlers.Handler with identify, __call__, identify_sync and call_sync on a local Path, returning a Record
  and a typed object. The typed objects -- MarkdownFile, CSVFile, LogFile, EmailFile, BrowserProfile, SessionFile,
  SessionFolder, GitRepository, SqliteDatabase, ArchiveContents -- become the content of the DataObject.
  """
  name: str

  def _identify(self, obj: DataObject, container: Container) -> bool:
    """Whether this handler recognises obj, from what the source always supplies."""
    ...

  def _probe(self, obj: DataObject, container: Container) -> DataObject:
    """obj read: with this handler's metadata and, where it has one, its content."""
    ...


class Provider(Handler):
  """Provides access to objects by references. A Handler instantiated from a connection.

  A Provider identifies and probes what it reaches, as any handler does, and it also lists, opens, writes and
  deletes there. It works on its own paths; the Location turns them into uris. Provider instances form a
  hierarchy, encoded in the uid as a dash-separated path: `laptop` above `laptop-data`, and `m365` above
  `m365-karelin` above `m365-karelin-graph`. How it reaches an object -- which API, which request -- is its inner
  working and never a uri. Outside gppu, CRAP declares Plaud and Telegram the same way, and configuration names
  the class.

  Route: /config, a list, read only.

  Today: the reaching is spread over GppuFileSystem, SharePointFileSystem, PostgresFileSystem and CRAP's
  Location/Container pairs; GppuCatalog resolves the connection. One Provider class per provider takes it over.
  """
  uid: str
  parent: Provider | None
  scheme: str
  authority: str | None

  def __init__(self, connection: dict[str, Any]) -> None:
    """Instantiated from a Location's connection."""
    ...

  def _ls(self, path: y2path) -> list[DataObject]:
    """What the Container at path holds, with what the source always supplies."""
    ...

  def _info(self, path: y2path) -> DataObject:
    """The DataObject at path, from the source."""
    ...

  def _open(self, path: y2path, mode: str = 'rb') -> IO[bytes]:
    ...

  def _write(self, path: y2path, obj: DataObject) -> DataObject:
    ...

  def _delete(self, path: y2path) -> None:
    ...

  def _refresh(self, path: y2path, state: dict[str, Any]) -> Iterator[DataObject]:
    """What changed below path since state, removed objects included. state moves on only after every change
    was consumed."""
    ...


class FileSystem(Provider):
  """The Provider for files: fileSystem. One instance per host or volume: `laptop`, `laptop-data`.

  Today: FileLocation and FileContainer, and the local file access inside GppuFileSystem through fsspec's
  LocalFileSystem.
  """


class M365(Provider):
  """The Provider for Microsoft 365, through Graph: `m365`, `m365-karelin`, `m365-karelin-graph`.

  Today: SharePointFileSystem, and CRAP's M365Location and M365Container.
  """


class Postgres(Provider):
  """The Provider for a Postgres database: its tables are Containers, their rows DataObjects.

  Today: PostgresFileSystem.
  """


class FileHandler(Handler):
  """The set of handlers: a subclass lists them as its bases, and their order is the order they run in.

  Today: FileHandler also walks trees and caches signatures; walking moves to Collection.refresh, and the
  signatures to the metadata.
  """


class FolderHandler(Handler):
  """A folder: how many files and folders it holds, how many bytes, and the span of their times."""


class IgnoredHandler(Handler):
  """A path to report and never enter, such as a cache."""


class LocationHandler(Handler):
  """A path that is a Location: this is how a Location is detected on refresh."""


class ArchiveHandler(Handler):
  """An archive. Its probe lists the members; the members are the DataObjects it holds.

  Today: ArchiveHandler with _RarFileSystem.
  """

  def _open(self, obj: DataObject, container: Container, path: y2path, mode: str = 'rb') -> IO[bytes]:
    """The bytes of the member at path inside the archive obj."""
    ...


class GitHandler(Handler):
  """A Git repository."""


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
  """A browser profile."""


class ImageHandler(Handler):
  """An image."""


class VideoHandler(Handler):
  """A video."""


class SessionHandler(Handler):
  """An agent session: its turns and statistics."""


class ChatGPTHandler(Handler):
  """A ChatGPT export.

  Today: shares _LLMExportHandler with AnthropicHandler.
  """


class AnthropicHandler(Handler):
  """An Anthropic export.

  Today: shares _LLMExportHandler with ChatGPTHandler.
  """


class GppuIndex:
  """The tree of DataObjects, kept where retrieval is fast: referential integrity and ids.

  Two implementations answer the same questions. SqliteIndex is in the file system, beside the data it describes.
  The other is in a database: CRAP's Lake. The id is internal to the index. It is not a pure cache: a removed
  DataObject stays, with the time it went. The database collects the SQLite indexes stored with the data.

  Its methods are protected: an index is the inner working of a Container.

  Today: handlers.GppuIndex, a Protocol with entry, put and moved on dict rows. CRAP's class Lake in
  lake/common/index.py implements the database side.
  """

  def _entry(self, uri: y2uri) -> tuple[DataObject, list[DataObject] | None] | None:
    """The DataObject at uri and what it holds, or None when neither is held. The listing is None when the index was
    never told what it holds."""
    ...

  def _put(self, obj: DataObject, listing: list[DataObject] | None = None) -> None:
    ...

  def _moved(self, source: y2uri, destination: y2uri) -> None:
    """The DataObject at source, and everything below it, is at destination now. What was said about it moves too."""
    ...

  def _find(self, criteria: dict[str, Any]) -> list[DataObject]:
    ...

  def _collect(self, index: GppuIndex) -> None:
    """Take in another index's rows: data that arrives from a place never indexed here keeps what was said about it."""
    ...


class SqliteIndex(GppuIndex):
  """The index stored with the data: `.<name>.gppufs.sqlite` beside the path it describes. An index named for a
  path below owns the tree under it.

  Today: inside GppuFileSystem.
  """
