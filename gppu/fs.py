"""gppufs: DataObjects in Containers, Containers in Locations and Collections.

Declarations and docstrings. providers.py, handlers.py and indexing.py become this one module: their code moves
into these classes, and the API and the documentation are generated from them. The configuration classes live here
for now.

  DataObject                  metadata, with content in some cases; at a path in its Container
  Location                    a Provider, its connection and a path; the configurable tree   /config
  Container                   a tree of DataObjects, by path; reached through a Location     /lake
    Collection                links arbitrary DataObjects by uri: the Lake, a Thread         /lake
  Link                        source uri, label, target uri, date: a native type, like TimeSpan
  Provider                    reaches a source; instantiated from a connection              /config, a list
    FileSystem                files; its handlers are all the existing ones
    M365, Telegram, Plaud
  Handler                     reads a DataObject for its Provider: identify, probe
    FolderHandler, ArchiveHandler, MarkdownHandler, SessionHandler, ...
  GppuIndex                   the tree and the graph, held for retrieval: SqliteIndex beside the data, a database
                              in CRAP

Routes. The API has two routes, /config and /lake, and every public method belongs to one of them as it is.
Location's belong to /config; Container's and Collection's to /lake. How a Provider or a handler reaches and reads
an object is its inner working, so those methods are protected.

Paths and uris. A DataObject is known by its Location and its path; a Container understands paths only. A uri
names a Location, or what a Link leads to, and only a Collection resolves one. A DataObject with its own uri is
rare.

The tree and the graph. Containers make a tree: every DataObject is in one place. Links make a graph over it: a
Location and the Containers it reaches, a Collection and its members, one span of a session and the next, a
session and its Thread. The graph is not held by the objects: a Link holds uris only, the whole graph is kept in
the index, and it is read around one uri at a time. The graph is what /lake adds to a file system.

The Lake is an index and storage. gppu has no Lake: to gppu it is a Collection loaded from configuration. The upper
levels -- Locations -- come from configuration; the lower levels are loaded from the database.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import IO, Any

from .gppu import y2path, y2uri


@dataclass(frozen=True)
class DataObject:
  """Metadata, with content in some cases. A file, a folder's entry, an archive, a contact and a table are all
  DataObjects.

  A file is not a DataObject without a handler: a handler returns metadata, and that metadata is stored as the
  DataObject. What the source always supplies is stored for every DataObject, whether its source is online or not.
  A DataObject is a value: it is read through its Container and saved through a Collection, and reaches nothing
  itself. It holds no Links; the index does.

  A part of a DataObject -- a span of a session, a passage of text -- is a DataObject too, at the whole's path with
  a fragment naming the part, which is the job RFC 3986 gives the fragment. Its metadata holds the time it covers
  as gppu's TimeSpan. Sessions, threads, the timeline and time accounting all count in these parts.

  A record is a DataObject: "DataObject is(?) Record that comes from handlers" is answered yes, and there is no
  Record type. A record found in several places is one DataObject at several references, a Location and a path
  for each copy. Its uid is the id its own system gives it -- a Graph id, a Telegram id, never one minted from a
  name -- and any other system's id for it is in its metadata. It stays after every copy is gone, with removed set.

  Route: /lake returns it.

  Today: providers.DataObject and handlers.Record, with Probe, FileStats and HandlerError, become this one type.
  identity becomes uid; kind and name move into metadata; the source uri becomes path; parent is the path without
  its last segment; removed becomes a time. is_folder, size and modified_at, the probes, stats and errors move into
  metadata, each under its handler's name. CRAP's span rows (fact.every_span) become DataObjects with a fragment.
  The lake's entity rows are DataObjects, instance rows their references and fingerprint rows their ids; the
  stopped textlake.record, records.record and public.files hold the same thing in older shapes.
  """
  path: y2path
  """Path-in-container. Its last segment names the object."""
  uid: str
  """Unique identifier: the one its own system gives it. It is not the Index's id, but an object with no identifier
  of its own takes that id as its uid."""
  metadata: dict[str, Any] = field(default_factory=dict)
  """What the source supplies -- for a file, its type, size, times and file system attributes -- and, under each
  handler's name, what that handler returned, such as the TimeSpan it covers."""
  content: Any = None
  """Present once a handler has read it: MarkdownFile, CSVFile, SessionFile and the other typed objects."""
  removed: datetime | None = None
  """When it was deleted. Its metadata stays held."""
  uri: y2uri | None = None
  """Its own uri, in the rare case it has one. Otherwise its Location's uri_of(path) names it."""


class Location:
  """A container for alike objects: a Provider, its connection and a path-to-container. The configurable structure.

  Locations form a tree, and each leaf references a Container. A Location with no path is a root, and its uid is its
  Provider's. A configured Location is written in configuration; a discovered one is found by its Provider and
  cached, and only discovered Locations are refreshed. Path-to-container and path-in-container together give the
  path to a DataObject. The Provider and the connection are part of the Location: reading an object means invoking
  the Location's operation on the object's path. A Location has a Provider; it is not one.

  Route: /config.

  Today: providers.Location and FileLocation, and CRAP's M365Location, PlaudLocation and TelegramLocation. The code
  for each store moves to its Provider. State.connections rows become _connection, and admin_ui's
  config_connections list goes. CRAP's catalog_configuration.save becomes save.
  """
  uid: str
  """Its Provider's uid, then `/` and the path, readable by a human: `laptop`, `laptop-data`,
  `laptop-data/TextLake`."""
  name: str
  """Its display name: `Alex-Laptop`."""
  uri: y2uri
  """Canonical uri, as configuration structures it: `m365://karelin/alex/files`."""
  mirrors: tuple[y2uri, ...]
  """Its other uris."""
  provider: Provider
  path: y2path
  """Path-to-container. Empty for a root."""
  parent: Location | None
  configured: bool
  """Written in configuration, rather than discovered."""
  _connection: dict[str, Any]
  """The connection its Provider is instantiated from: an account, an endpoint and credentials. No route serves it."""

  def ls(self) -> list[Location]:
    """Its child Locations: those configuration names under it, and those its Provider discovers -- a tenant's
    users, a user's drives and mailboxes.

    Replaces catalog.locations and GppuCatalog.ls_sync(recurse=True), read by FileIndexer's Location tree and the
    lake's lineage assets.
    """
    ...

  def walk(self) -> Iterator[tuple[Location, list[Location]]]:
    """This Location and every Location below it, each with its children.

    Used by the lake's Dagster exports, which export each leaf.
    """
    ...

  def container(self, path: y2path | str = '') -> Container:
    """The Container at path below this Location, reached through its Provider.

    Used by FileIndexer, the lake's Dagster jobs and plaud_import, as catalog.location(uid).container(path) today.
    """
    ...

  def uri_of(self, path: y2path | str = '') -> y2uri:
    """Canonical uri of a path below this Location: its uri, `:`, and the escaped path.

    Replaces Location.address, still called by FileIndexer and admin_ui's template preview, and
    Environment.locations.uri_of and uri_from.
    """
    ...

  def save(self) -> Location:
    """Write this Location to configuration, creating it when it is new. Returns it as saved.

    Replaces CRAP's catalog_configuration.save behind /config/location, and locations.save_location and
    add_location, which raise.
    """
    ...


class Container:
  """A tree of DataObjects -- exactly what a zip file or a folder stores. Not storage.

  A Container is independent of Location: several Locations can reach one Container. TextLake is one Container,
  reached as `laptop-data/TextLake` and on other hosts, and known globally as `textlake` or `lake://text`. Which
  Location is the original is an annotation: a Link labelled `original`. The others are manifestations. A folder
  is a DataObject in the listing that holds it, and a Container once opened.

  A Container understands paths, never uris, and never writes. It answers from its index, so it answers with
  nothing online. What the index lacks it reads through the Provider of the Location it was reached through, and
  has that Provider's handlers identify.

  Route: /lake.

  Today: providers.Container and FileContainer, CRAP's M365Container, PlaudContainer and TelegramContainer, and
  GppuFileSystem. ls returns DataObjects instead of fsspec rows; walk becomes find; read runs the handlers; write
  moves to Collection; delete goes, because a write replaces and refresh reports what is gone.
  """
  _location: Location
  """The Location it was reached through."""
  _index: GppuIndex
  """Where its tree is held."""

  def ls(self, path: y2path | str = '') -> list[DataObject]:
    """The DataObjects held at path; at the root when path is empty.

    Answered from the index. A path the index has never listed is listed by the Provider first, and each DataObject
    is identified by the handlers and put into the index.

    Replaces GppuFileSystem.ls (admin_ui's browser), Container.ls (plaud_import) and FileHandler.walk_sync with
    recursive=False (LakeFileSystem.ls).
    """
    ...

  def info(self, path: y2path | str) -> DataObject:
    """The DataObject at path as the index holds it: what the source supplies and what the handlers identified,
    without reading it.

    Replaces GppuFileSystem.info (admin_ui's browser) and SessionHandler.identify (RAN preserve).
    """
    ...

  def read(self, path: y2path | str) -> DataObject:
    """The DataObject at path, read by its handlers, with its content.

    Replaces probe_sync and load_sync (LakeFileSystem; admin_ui's session classify and cluster), SessionHandler(path)
    (RAN preserve, list-sessions, sessions-clean) and Container.read (plaud_import).
    """
    ...

  def open(self, path: y2path | str, mode: str = 'rb') -> IO[bytes]:
    """The bytes at path, from the source. Raises when the source cannot be reached.

    Replaces the FileContainer.read streams (plaud hashing), PostgresFileSystem.cat (postgres_catalog), the gppu-rar
    cat_file (admin_ui's archives), and the pathlib reads in LakeFileSystem and TextLakeResource.
    """
    ...

  def find(self, path: y2path | str = '', criteria: dict[str, Any] | None = None) -> list[DataObject]:
    """Every DataObject below path whose metadata matches criteria; with no criteria, all of them.

    The catalog gives the simple recursive list; the Index gives anything beyond it.

    Replaces Container.walk (FileIndexer), FileHandler.walk_sync with recursive=True (admin_ui's walk_sessions,
    LakeFileSystem's reindex), and the Postgres queries FileIndexer, admin_ui and the lake run themselves.
    """
    ...

  def refresh(self, state: dict[str, Any], path: y2path | str = '') -> AbstractContextManager[Iterator[DataObject]]:
    """Re-read what is below path from live state: the DataObjects that changed since state, removed ones
    included, and the discovered Locations below it.

    state moves on only after every change is consumed and handled; an exception leaves it where it was.

    The contract of Container.refresh stays (the lake's Dagster exports and Markdown rendering). plaud_import's own
    snapshot diff, SessionHandler.invalidate and FileIndexer's indexing runs move onto it.
    """
    ...


class Collection(Container):
  """A Container that links arbitrary DataObjects rather than holding them. Its links are uris, so it is the
  Container that understands uris: it resolves one to a Location and a path.

  A Collection is a form of annotation: its members are the DataObjects linked to it, and a Link to it adds one.
  A Thread is a Collection of sessions and their spans.

  The Lake is a Collection loaded from configuration. Its Locations come from configuration, and what is below them
  is loaded from the database. `Collection()` is that global Collection, the one the admin tool shows.
  `Collection(root)` is rooted at any path or Location, which is read, indexed beside itself and browsed the same
  way. Objects are saved and linked by uri, so saving and linking are here.

  Route: /lake. Its ls, info, read, open, find and refresh take a uri where a Container takes a path.

  Today: handlers.GppuCatalog, the configured Locations keyed by uid; GppuFileSystem; indexing.walk_container and
  walk_files; LakeFileSystem in CRAP.
  """
  _locations: dict[str, Location]
  """The upper levels: Locations from configuration, by uid."""

  def __init__(self, root: y2uri | None = None) -> None:
    """The global Collection of configured Locations; or, given root, the Collection of that path or Location."""
    ...

  def write(self, uri: y2uri, obj: DataObject) -> DataObject:
    """Save obj at uri. The Provider of the Location uri falls in writes it; given a Location's own uri, that
    Provider names the path from its templates. Returns it as the index now holds it.

    Replaces Container.write, called with one argument by the lake's Dagster jobs and plaud_import, their
    delete-then-write on FileExistsError, and the pathlib writes in LakeFileSystem and TextLakeResource.
    """
    ...

  def link(self, source: y2uri, label: str, target: y2uri) -> Link:
    """Link source to target under label: a session to its Thread, a span to the next, an object to a tag.

    This is how people make Links; handlers make theirs while reading. Neither end has to exist: a uri names what
    it leads to without knowing anything about it. The caller is who made the Link. Returns it as held.

    Replaces admin_ui's say, annotate and verify.
    """
    ...

  def links(self, uri: y2uri) -> list[Link]:
    """The Links from and to uri: the part of the graph around one DataObject.

    Replaces admin_ui's graph node, neighbors and topology reads, and its spans, chains and threads.
    """
    ...

  def location_of(self, uri: y2uri) -> Location:
    """The Location uri falls in: the one whose uri, or one of its mirrors, begins it for longest.

    Replaces Environment.locations.location_of (admin_ui's inventory) and three copies of it: FileIndexer's
    operations.selection, LakeFileSystem.inside and of, and admin_ui's Locations.owner.
    """
    ...


@dataclass(frozen=True)
class Link:
  """A graph link: a source uri, a label, a target uri and a date. A native type, like TimeSpan.

  Annotations, a Collection's members and the original Location of a Container are all Links. The index keeps
  them, and who made each: a handler or a person.
  """
  source: y2uri
  label: str
  target: y2uri
  date: datetime
  """A link needs a label and a date, and nothing else."""


class Provider:
  """Provides access to objects by references. A class, instantiated from a connection; a Location has one.

  A Provider lists, opens and writes what its source holds, on its own paths, and reads what it reaches with its
  handlers. Provider instances form a hierarchy, encoded in the uid as a dash-separated path: `laptop` above
  `laptop-data`, and `m365` above `m365-karelin` above `m365-karelin-graph`. How it reaches an object -- which API,
  which request -- is its inner working and never a uri. Configuration names the class.

  One Provider does what two classes do today: the Location implementations, which enumerate Locations, and the
  Container implementations with the fsspec filesystems, which enumerate DataObjects. They are one because:
  - Both use one connection and one client. Today M365Container sends its requests through M365Location.
  - Path-to-container and path-in-container are one path, and the source answers both with the same nested
    lists: Graph lists a tenant's users, then a user's drives, then a drive's folders. Where a Location ends is
    configuration; two classes would fix it in code.
  - Refresh re-reads both from the same delta state: the discovered Locations and the changed DataObjects.

  Route: /config, a list, read only. Its methods are protected: how it reaches its source is its inner working.

  Today: the reaching is spread over GppuFileSystem, SharePointFileSystem and CRAP's Location/Container pairs;
  GppuCatalog resolves the connection. One Provider class per provider takes it over. No Provider for Postgres is
  written yet: PostgresFileSystem stays as it is.
  """
  uid: str
  parent: Provider | None
  scheme: str
  authority: str | None
  handlers: FileHandler | None
  """The handlers that read what it reaches, as one set."""

  def __init__(self, connection: dict[str, Any]) -> None:
    """Instantiated from a Location's connection."""
    ...

  def _locations(self, path: y2path) -> list[Location]:
    """The Locations below path that the source itself defines: the discovered Locations."""
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

  def _refresh(self, path: y2path, state: dict[str, Any]) -> Iterator[DataObject]:
    """What changed below path since state, removed objects included. state moves on only after every change
    was consumed."""
    ...


class FileSystem(Provider):
  """The Provider for files: fileSystem. One instance per host or volume: `laptop`, `laptop-data`. Every existing
  handler is its handler.

  Today: FileLocation and FileContainer with their naming templates, and the local file access inside
  GppuFileSystem through fsspec's LocalFileSystem.
  """


class M365(Provider):
  """The Provider for Microsoft 365, through Graph: `m365`, `m365-karelin`, `m365-karelin-graph`. Graph returns its
  objects already read, so it has no handlers.

  Today: SharePointFileSystem, and CRAP's M365Location and M365Container.
  """


class Telegram(Provider):
  """The Provider for Telegram: an account's chats and contacts.

  Today: CRAP's TelegramLocation and TelegramContainer.
  """


class Plaud(Provider):
  """The Provider for Plaud: recordings, their audio and their texts. Its root Location has no path below it.

  Today: CRAP's PlaudLocation and PlaudContainer, with audio and texts.
  """


class Handler:
  """Reads a DataObject for its Provider. A handler returns metadata, and that metadata is stored as the DataObject.

  A handler has two ways of getting information about a DataObject: identify, from what the source always
  supplies and without reading it; and probe, reading it. It reads through the Container that holds the object,
  by path, never through a local path. Handlers are mixins: a subclass of FileHandler lists them as its bases, and
  that order is the order they identify and probe in. A failure is kept in the metadata under the handler's name,
  so one bad file does not stop a listing.

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

  def _links(self, obj: DataObject, container: Container) -> list[Link]:
    """The Links this handler finds from obj as it reads it -- a session's spans and their order. Most find none.
    They go to the index, not onto obj."""
    ...


class FileHandler(Handler):
  """The set of handlers: a subclass lists them as its bases, and their order is the order they run in.

  Today: FileHandler also walks trees and caches signatures; walking moves to Container.find and refresh, and the
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
  """An agent session: its turns and statistics, its spans and their order."""


class ChatGPTHandler(Handler):
  """A ChatGPT export.

  Today: shares _LLMExportHandler with AnthropicHandler.
  """


class AnthropicHandler(Handler):
  """An Anthropic export.

  Today: shares _LLMExportHandler with ChatGPTHandler.
  """


class GppuIndex:
  """The tree of DataObjects and the graph of Links, kept where retrieval is fast: referential integrity and ids.

  Two implementations answer the same questions. SqliteIndex is in the file system, beside the data it describes.
  The other is in a database: CRAP's Lake. The id is internal to the index. It is not a pure cache: a removed
  DataObject stays, with the time it went. The database collects the SQLite indexes stored with the data.

  Its methods are protected: an index is the inner working of a Container.

  Today: handlers.GppuIndex, a Protocol with entry, put and moved on dict rows. CRAP's class Lake in
  lake/common/index.py implements the database side: lake.entity holds the DataObjects, lake.instance their
  references at each Location, and lake.fingerprint their ids.
  """

  def _entry(self, path: y2path) -> tuple[DataObject, list[DataObject] | None] | None:
    """The DataObject at path and what it holds, or None when neither is held. The listing is None when the index
    was never told what it holds."""
    ...

  def _put(self, obj: DataObject, listing: list[DataObject] | None = None) -> None:
    ...

  def _moved(self, source: y2path, destination: y2path) -> None:
    """The DataObject at source, and everything below it, is at destination now. What was said about it moves too."""
    ...

  def _find(self, path: y2path, criteria: dict[str, Any]) -> list[DataObject]:
    ...

  def _link(self, link: Link) -> None:
    ...

  def _links(self, uri: y2uri) -> list[Link]:
    """The Links from and to uri."""
    ...

  def _collect(self, index: GppuIndex) -> None:
    """Take in another index's rows: data that arrives from a place never indexed here keeps what was said about it."""
    ...


class SqliteIndex(GppuIndex):
  """The index stored with the data: `.<name>.gppufs.sqlite` beside the path it describes. An index named for a
  path below owns the tree under it.

  Today: inside GppuFileSystem.
  """
