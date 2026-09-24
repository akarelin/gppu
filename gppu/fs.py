"""gppufs: DataObjects in Containers, Containers in Locations and Collections.

Declarations and docstrings. providers.py, handlers.py and indexing.py become this one module. The public methods
are the API; the REST API is gppu's zero-code feature, mixin_Rest, on the app that serves the lake: it serves every
public member of a registered object and generates the manifest from the signatures and these docstrings. Nothing
here is an app, so nothing here stands on _Base; _DC is not used yet. The configuration classes live here for now.

Three first-class objects and two APIs. Location is /config, the configurable tree. Container and Collection are
/lake, what the tree holds. Each API is a REST registry: `config` holds the Locations by uid, `lake` the Containers
and Collections by uri, the global Collection at the empty key. Listing a registry is the tree; an object's public
methods are its routes, as they are.

  Container                   a tree of DataObjects: ls, walk, info, read, open, find, write, delete, refresh
    Location                  a container for alike objects: a Provider, its connection and a path    /config
    Collection                a Container of arbitrary objects: the Lake is Collection()                /lake

What they hold and what they are made of. A DataObject is a value: metadata, with content in some cases. A
Provider reaches a source; a Handler is a Provider whose source is one object's bytes; an Index holds what was
read. None of these is first class or registered: a Container is written once over a Provider and an Index, and
that is how every Provider gets ls, read and write without a Container of its own.

  DataObject                  uid, path, metadata, content, removed
  Provider                    ls, info, open, write, delete, refresh, locations, on a source's paths
    FileSystem                in gppu; M365, Telegram, Plaud in CRAP
    Handler                   + identify, probe
      FolderHandler, ArchiveHandler, MarkdownHandler, SessionHandler, ...
  Index                       entry, put, moved, find
    SqliteIndex               in gppu, beside the data; the database Index is CRAP's Lake

The graph is not here yet. Links -- annotations, a Collection's members, a span and the next, the original
Location of a Container -- will be a mixin that gives an object the property of links, over the Index. Until then
a Collection's members are what its Index holds for it.

Paths and uris. A DataObject is known by its Location and its path; a Container understands paths only. A uri
names a Location, or a member of a Collection, and only a Collection resolves one. A DataObject with its own uri
is rare. A reference, `ref`, is a path below a Container, or a uri a Collection resolves.

What is read from where: config, facts and links. Config is the configuration as Environment and State define it:
tables of rows keyed by uid, each resolved through its table's templates and built by the class its kind names.
Locations, Providers and their connections are such rows. Facts are tables of what handlers and sources said:
DataObjects as rows with a parent; folders, files, records and spans are all rows, a span's TimeSpan in its row.
Links will be the graph, edges between uris, for what no single tree can hold. A Location is read from config, a
Container reads facts, and a Collection reads its members and then the facts.

The Lake is an index and storage. gppu has no Lake: to gppu it is a Collection loaded from configuration. The upper
levels -- Locations -- come from configuration; the lower levels are loaded from the database.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import datetime
from typing import IO, Any

from .gppu import y2path, y2uri

Ref = y2path | y2uri | str
"""An object reference: a path below a Container, or a uri a Collection resolves."""


# region first-class objects


class Container:
  """A tree of DataObjects -- exactly what a zip file or a folder stores. Not storage.

  A Container is independent of Location: several Locations can reach one Container. TextLake is one Container,
  reached as `laptop-data/TextLake` and on other hosts, and known globally as `textlake` or `lake://text`. A folder
  is a DataObject in the listing that holds it, and a Container once opened; an archive is a Container whose
  Provider is its ArchiveHandler.

  A Container understands paths, never uris. It answers from its Index, so it answers with nothing online. What
  the Index lacks it reads through its Provider, and has that Provider's handlers identify; a write goes to the
  Provider and then to the Index; a delete stays in the Index with removed set. Everything below is written once,
  here, for every Provider.

  Route: /lake, by the uri of the Location it was reached through; its methods take paths below it.

  Today: providers.Container and FileContainer, CRAP's M365Container, PlaudContainer and TelegramContainer, and
  GppuFileSystem, each writing ls, read and write again. GppuFileSystem.ls and info (admin_ui's browser),
  Container.ls and read (plaud_import) and FileHandler.walk_sync (LakeFileSystem.ls, admin_ui's walk_sessions)
  become ls, info and find; probe_sync and load_sync (LakeFileSystem; admin_ui's session classify and cluster)
  and SessionHandler(path) (RAN's preserve, list-sessions, sessions-clean) become read; the FileContainer.read
  streams, PostgresFileSystem.cat, the gppu-rar cat_file and the pathlib reads in LakeFileSystem and
  TextLakeResource become open; Container.write and delete (the lake's Dagster jobs, plaud_import) stay; the
  Postgres queries FileIndexer, admin_ui and the lake run themselves become find; Container.refresh keeps its
  contract, and plaud_import's snapshot diff, SessionHandler.invalidate and FileIndexer's indexing runs move onto it.
  """
  _provider: Provider
  """The Provider it reads through: its Location's, or a Handler for an archive."""
  _index: Index
  """Where what was read is held."""

  def _resolve(self, ref: Ref) -> y2path:
    """ref as a path below this Container. A Collection overrides this, and nothing else."""
    ...

  def ls(self, ref: Ref = '') -> list[DataObject]:
    """The DataObjects held at ref; at the root when ref is empty. From the Index; a path never listed is listed
    by the Provider first, each object identified by the handlers and put in the Index."""
    ...

  def walk(self, ref: Ref = '') -> Iterator[tuple[DataObject, list[DataObject]]]:
    """Every folder below ref with what it holds, parents before children, each once. Written once over ls."""
    ...

  def info(self, ref: Ref) -> DataObject:
    """The DataObject at ref as the Index holds it: what the source supplies and what the handlers identified,
    without reading it."""
    ...

  def read(self, ref: Ref) -> DataObject:
    """The DataObject at ref, read by its handlers, with its content; put in the Index."""
    ...

  def open(self, ref: Ref, mode: str = 'rb') -> IO[bytes]:
    """The bytes at ref, from the source; a member inside an archive through its handler. Raises when the source
    cannot be reached."""
    ...

  def find(self, ref: Ref = '', criteria: dict[str, Any] | None = None) -> list[DataObject]:
    """Every DataObject below ref whose metadata matches criteria; with no criteria, all of them. What criteria are
    is open."""
    ...

  def write(self, ref: Ref, obj: DataObject) -> DataObject:
    """Store obj at ref, replacing what is there, and put it in the Index; an empty ref lets the Provider name the
    path from its templates. Returns obj as stored and indexed."""
    ...

  def delete(self, ref: Ref) -> DataObject:
    """Remove the object at ref from the source. The Index keeps it, with removed set."""
    ...

  def refresh(self, state: dict[str, Any], ref: Ref = '') -> AbstractContextManager[Iterator[DataObject]]:
    """Re-read what is below ref from live state: the DataObjects that changed since state, removed ones included.
    Consume the changes inside the context; state moves on only after every change is consumed and handled, and
    an exception leaves it where it was. Today's Container.refresh contract."""
    ...


class Location(Container):
  """A container for alike objects: a Provider, its connection and a path-to-container. The configurable structure.

  Locations form a tree, and each leaf references a Container of DataObjects. A root is a Location with no path:
  `laptop` is Alex-Laptop, the host, with the fileSystem Provider; `laptop-data` is its D: volume, a path below
  it; and `laptop-data/TextLake` is a path below that, known globally as `textlake`. A configured Location is
  written in configuration; a discovered one is found by its Provider and cached, and only discovered Locations
  are refreshed. Path-to-container and path-in-container together give the path to a DataObject. The Provider and
  the connection are part of the Location: reading an object means invoking the Location's operation on the
  object's path. A Location has a Provider; it is not one.

  Its objects are Locations: ls lists its children, configured first, then those its Provider discovers -- a
  tenant's users, a user's drives and mailboxes; walk the tree below it, which the lake's Dagster exports use to
  export each leaf; refresh re-reads the discovered ones. container opens the DataObjects below it.

  Route: /config, by uid. Listing it is the configured tree, today catalog.locations and State.locations; one
  entry is today's GppuCatalog.location(uid), called by FileIndexer, the lake's Dagster jobs and plaud_import.
  Providers and connections are read-only lists beside it.

  Today: providers.Location and FileLocation, and CRAP's M365Location, PlaudLocation and TelegramLocation. The code
  for each store moves to its Provider. GppuCatalog.ls_sync(recurse=True) becomes ls; Location.address, still
  called by FileIndexer and admin_ui's template preview, and Environment.locations.uri_of and uri_from become
  uri_of; State.connections rows become _connection; CRAP's catalog_configuration.save becomes save.
  """
  uid: str
  """Its parent's uid, `-` and its name for a configured Location, or its parent's uid, `/` and its path for one
  below a path: `laptop`, `laptop-data`, `laptop-data/TextLake`. Readable by a human."""
  name: str
  """Its display name: `Alex-Laptop`."""
  uri: y2uri
  """Canonical uri, as configuration structures it: `m365://karelin/alex/files`."""
  mirrors: tuple[y2uri, ...]
  """Its other uris: `textlake`, `lake://text`."""
  path: y2path
  """Path-to-container. Empty for a root."""
  parent: Location | None
  """The Location above it. None for a root."""
  configured: bool
  """Written in configuration, rather than discovered."""
  _connection: dict[str, Any]
  """The connection its Provider is instantiated from: an account, an endpoint and credentials. No route serves it."""

  def container(self, path: y2path | str = '') -> Container:
    """The Container of DataObjects at path below this Location, reached through its Provider."""
    ...

  def uri_of(self, path: y2path | str = '') -> y2uri:
    """Canonical uri of a path below this Location: its uri, `:`, and the escaped path."""
    ...

  def save(self) -> Location:
    """Write this Location to configuration, creating it when it is new; returns it as saved."""
    ...


class Collection(Container):
  """A Container of arbitrary objects: it refers to DataObjects anywhere rather than holding them, so it is the
  Container that understands uris: it resolves one to a Location and a path, and the rest is Container's.

  A Thread is a Collection of sessions and their spans. The Lake is a Collection loaded from configuration: its
  Locations come from configuration, and what is below them is loaded from the database. `Collection()` is that
  global Collection, the one the admin tool shows. `Collection(root)` is rooted at any Location or uri, which is
  read, indexed beside itself and browsed the same way. How members are added is the graph, later.

  Route: /lake; the global Collection is its empty key. Its inherited methods take a uri where a Container takes
  a path; location_of is its own.

  Today: handlers.GppuCatalog, the configured Locations keyed by uid; GppuFileSystem; indexing.walk_container and
  walk_files; LakeFileSystem in CRAP. Environment.locations.location_of and its three copies -- FileIndexer's
  operations.selection, LakeFileSystem.inside and of, admin_ui's Locations.owner -- become location_of.
  """
  uri: y2uri
  """The uri this Collection is: `lake://`, or a Thread's uri."""
  _locations: dict[str, Location]
  """The upper levels: Locations from configuration, by uid."""

  def __init__(self, root: Location | y2uri | None = None) -> None:
    """The global Collection of configured Locations; or, given root, the Collection of that Location or uri."""
    ...

  def _resolve(self, ref: Ref) -> y2path:
    """ref is a uri here: location_of it, and answer through that Location's Container. Empty names this
    Collection's own members."""
    ...

  def location_of(self, uri: y2uri | str) -> tuple[Location, y2path]:
    """The Location whose uri, or one of whose mirrors, begins uri for longest, and the path the rest names."""
    ...


# endregion
# region what they hold


class DataObject:
  """Metadata, with content in some cases. A file, a folder's entry, an archive, a contact and a table are all
  DataObjects.

  A file is not a DataObject without a handler: a handler returns metadata, and that metadata is stored as the
  DataObject. What the source always supplies is stored for every DataObject, whether its source is online or not:
  for a file, its type, size, times and file system attributes, in metadata; what each handler returned sits
  under the handler's name. A DataObject is a value: it is read and written through its Container, and reaches
  nothing itself.

  A part of a DataObject -- a span of a session, a passage of text -- is a DataObject too, at the whole's path with
  a fragment naming the part, which is the job RFC 3986 gives the fragment. Its metadata holds the time it covers
  as gppu's TimeSpan. Sessions, threads, the timeline and time accounting all count in these parts.

  A record is a DataObject, and there is no Record type. A record found in several places is one DataObject with
  one uid; the Index holds every place it was seen, and the DataObject in hand carries the path it was read at.
  Its uid is the id its own system gives it -- a Graph id, a Telegram id, never one minted from a name -- and any
  other system's id for it is in its metadata. It stays after every copy is gone, with removed set.

  Today: providers.DataObject and handlers.Record, with Probe, FileStats and HandlerError, become this one type.
  identity becomes uid; kind moves into metadata; the source uri becomes path; removed becomes a time. CRAP's
  span rows (fact.span) become DataObjects with a fragment; the lake's entity rows are DataObjects, instance rows
  their references and fingerprint rows their ids.
  """
  uid: str
  """Unique identifier: the one its own system gives it. An object with no identifier of its own takes the
  Index's id as its uid."""
  path: y2path
  """Path-in-container it was read at. Its last segment is its name; a fragment names a part."""
  metadata: dict[str, Any]
  """What the source supplies and, under each handler's name, what that handler returned."""
  content: Any
  """Present once a handler has read it: MarkdownFile, CSVFile, SessionFile and the other typed objects."""
  removed: datetime | None
  """When it was deleted. Its metadata stays held."""
  uri: y2uri | None
  """Its own uri, in the rare case it has one. Otherwise its Location's uri_of(path) names it."""


# endregion
# region what they are made of


class Provider:
  """Provides access to objects by references: a source on a connection, yielding DataObjects on its own paths. A
  class, instantiated from a connection; a Location has one.

  Providers are a list, not a tree: `fileSystem`, `m365`, `telegram`, `plaud`. How one reaches an object -- which
  API, which request -- is its inner working and never a uri. Configuration names the class. Its methods answer
  from the source, on paths, and a Container puts its Index in front of them.

  One Provider does what two classes do today: the Location implementations, which enumerate Locations, and the
  Container implementations with the fsspec filesystems, which enumerate DataObjects. They are one because:
  - Both use one connection and one client. Today M365Container sends its requests through M365Location.
  - Path-to-container and path-in-container are one path, and the source answers both with the same nested
    lists: Graph lists a tenant's users, then a user's drives, then a drive's folders. Where a Location ends is
    configuration; two classes would fix it in code.
  - Refresh re-reads both from the same delta state: the discovered Locations and the changed DataObjects.

  Not first class and never registered: no route serves a Provider; /config lists the ones that exist.

  Today: the reaching is spread over GppuFileSystem, SharePointFileSystem and CRAP's Location/Container pairs;
  GppuCatalog resolves the connection. No Provider for Postgres is written yet: PostgresFileSystem stays as it is.
  """
  uid: str
  """Its name in configuration: `fileSystem`, `m365`."""
  scheme: str
  """The scheme of the uris of its Locations: `file`, `m365`."""
  handlers: tuple[Handler, ...]
  """The handlers that read what it yields, in the order they identify and probe. Empty for a source whose
  objects arrive already read."""

  def __init__(self, connection: dict[str, Any]) -> None:
    """Instantiated from a Location's connection."""
    ...

  def ls(self, path: y2path) -> list[DataObject]:
    """The DataObjects held at path, with what the source always supplies."""
    ...

  def info(self, path: y2path) -> DataObject:
    """The DataObject at path: what the source supplies, without reading it."""
    ...

  def open(self, path: y2path, mode: str = 'rb') -> IO[bytes]:
    """The bytes at path. Raises when the source cannot be reached."""
    ...

  def write(self, path: y2path, obj: DataObject) -> DataObject:
    """Store obj at path, replacing what is there; an empty path names one from the Provider's templates. Returns
    obj as stored."""
    ...

  def delete(self, path: y2path) -> None:
    """Remove the object at path from the source."""
    ...

  def refresh(self, state: dict[str, Any], path: y2path) -> Iterator[DataObject]:
    """What changed below path since state, removed objects included; state moves on only after every change was
    consumed."""
    ...

  def locations(self, path: y2path) -> list[Location]:
    """The Locations below path that the source itself defines: the discovered Locations -- a tenant's users, a
    user's drives and mailboxes."""
    ...


class Handler(Provider):
  """A Provider whose source is one DataObject's bytes: an archive, a session file, a Markdown file, a folder. A
  handler returns metadata, and that metadata is stored as the DataObject; a file is not a DataObject without one.

  A handler has two ways of getting information about a DataObject: identify, from what the source always
  supplies and without reading it; and probe, reading it. It reads through the Container that holds the object,
  by path, never through a local path. What it yields is what a Provider yields: ls lists an archive's members or
  a session's spans, info and open reach them. A Provider holds its handlers in order, and that order is the
  order they identify and probe in. A failure is kept in the metadata under the handler's name, so one bad file
  does not stop a listing.

  Today: handlers.Handler with identify, __call__, identify_sync and call_sync on a local Path, returning a Record
  and a typed object; handlers.FileHandler composes them as bases, which the Provider's tuple replaces. The typed
  objects -- MarkdownFile, CSVFile, LogFile, EmailFile, BrowserProfile, SessionFile, SessionFolder, GitRepository,
  SqliteDatabase, ArchiveContents -- become the content of the DataObject.
  """
  name: str
  """The key its metadata and its failures are held under: `markdown`, `session`."""

  def identify(self, obj: DataObject, container: Container) -> bool:
    """Whether this handler recognises obj, from what the source always supplies."""
    ...

  def probe(self, obj: DataObject, container: Container) -> DataObject:
    """obj read: with this handler's metadata under its name and, where it has one, its content."""
    ...


class Index:
  """What was read, kept where retrieval is fast: referential integrity and ids.

  Two implementations answer the same questions. SqliteIndex is in the file system, beside the data it describes.
  The other is in a database: CRAP's Lake. The id is internal to the Index. It is not a pure cache: a removed
  DataObject stays, with the time it went. The database collects the SQLite indexes stored with the data. Every
  entry is named by its canonical uri, as today, so one Index can hold many Containers.

  Not first class and never registered: a Container asks these questions, and they are its inner machinery, not
  the API. Config is its own tables, not the Index. The graph, when it comes, is held here too.

  Today: handlers.GppuIndex, a Protocol with entry, put and moved on dict rows by address. CRAP's class Lake in
  lake/common/index.py implements the database side: lake.entity holds the DataObjects, lake.instance their
  references at each Location, and lake.fingerprint their ids; fact.span holds the spans.
  """

  def entry(self, uri: y2uri) -> tuple[DataObject, list[DataObject] | None] | None:
    """The DataObject at uri and what it holds, or None when neither is held. The listing is None when the Index
    was never told what it holds."""
    ...

  def put(self, uri: y2uri, obj: DataObject, listing: list[DataObject] | None = None) -> None:
    """Hold obj at uri, and what it holds when a listing is given."""
    ...

  def moved(self, source: y2uri, destination: y2uri) -> None:
    """The DataObject at source, and everything below it, is at destination now. What was said about it moves too."""
    ...

  def find(self, uri: y2uri, criteria: dict[str, Any]) -> list[DataObject]:
    """Every DataObject below uri whose metadata matches criteria."""
    ...

  def collect(self, index: Index) -> None:
    """Take in another Index's rows: data that arrives from a place never indexed here keeps what was said about it."""
    ...


# endregion
# region implementations


class FileSystem(Provider):
  """The Provider for files: fileSystem. Its Locations are hosts and their volumes and paths: `laptop`,
  `laptop-data`, `laptop-data/TextLake`. Every existing handler is its handler.

  Today: FileLocation and FileContainer with their naming templates, and the local file access inside
  GppuFileSystem through fsspec's LocalFileSystem.
  """


class M365(Provider):
  """The Provider for Microsoft 365, through Graph. Its Locations are tenants, users and their drives, mailboxes
  and contacts: `m365://karelin/alex/files`. Graph returns its objects already read, so it has no handlers. In CRAP.

  Today: SharePointFileSystem, and CRAP's M365Location and M365Container.
  """


class Telegram(Provider):
  """The Provider for Telegram: an account's chats and contacts. In CRAP.

  Today: CRAP's TelegramLocation and TelegramContainer.
  """


class Plaud(Provider):
  """The Provider for Plaud: recordings, their audio and their texts. Its root Location has no path below it. In CRAP.

  Today: CRAP's PlaudLocation and PlaudContainer, with audio and texts.
  """


class FolderHandler(Handler):
  """A folder: how many files and folders it holds, how many bytes, and the span of their times."""


class IgnoredHandler(Handler):
  """A path to report and never enter, such as a cache."""


class LocationHandler(Handler):
  """A path that is a Location: this is how a Location is detected on refresh."""


class ArchiveHandler(Handler):
  """An archive. Its ls lists the members, the DataObjects it holds, and its open reaches a member's bytes; an
  archive is a Container whose Provider is this handler.

  Today: ArchiveHandler with _RarFileSystem, and the gppu-rar cat_file admin_ui's archives use.
  """


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
  """An agent session: its turns and statistics; its ls lists its spans in order."""


class ChatGPTHandler(Handler):
  """A ChatGPT export.

  Today: shares _LLMExportHandler with AnthropicHandler.
  """


class AnthropicHandler(Handler):
  """An Anthropic export.

  Today: shares _LLMExportHandler with ChatGPTHandler.
  """


class SqliteIndex(Index):
  """The Index stored with the data: `.<name>.gppufs.sqlite` beside the path it describes. An Index named for a
  path below owns the tree under it. The database Index is CRAP's Lake.

  Today: inside GppuFileSystem.
  """


# endregion
