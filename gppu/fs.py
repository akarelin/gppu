"""gppufs: DataObjects in Containers, Containers in Locations and Collections.

Declarations and docstrings. providers.py, handlers.py and indexing.py become this one module. The public methods
are the API; the REST API is gppu's zero-code feature, mixin_Rest, which serves every public member of a
registered object and generates the manifest from the signatures and these docstrings. The configuration classes
live here for now.

  _Tree                       a node that lists its children; walk is written once here
    Location                  a Provider, its connection and a path; the configurable tree   config/<uid>
    Container                 a tree of DataObjects, by path; reached through a Location     lake/<uri>
      Collection              links arbitrary DataObjects by uri: the Lake, a Thread         lake/<uri>
  DataObject                  metadata, with content in some cases; at a path in its Container
  Link                        source uri, label, target uri, date: a native type, like TimeSpan
  Provider                    protocol: reaches a source; a Container's methods are written once over it
    FileSystem                files, in gppu; its handlers are all the existing ones
    M365, Telegram, Plaud     in CRAP
  Handler                     protocol: reads a DataObject for its Provider: identify, probe
    FolderHandler, ArchiveHandler, MarkdownHandler, SessionHandler, ...
  GppuIndex                   protocol: the facts and the links, held for retrieval
    SqliteIndex               beside the data, in gppu; the database index is CRAP's Lake

Code reuse. Container implements ls, info, read, open, find, write, delete and refresh once, over any Provider
and any GppuIndex: no Provider has a Container of its own, where today FileContainer, M365Container,
PlaudContainer and TelegramContainer each write them again. Collection inherits all eight and overrides only how a
reference resolves: a Container takes a path below itself, a Collection a uri. Location and Container are both
trees, and _Tree walks them with one method.

Routes. The API has two routes, and they are the two REST registries: `config` holds the Locations by uid, the
configured tree; `lake` holds the Collections and Containers by uri, the global Collection at the empty key.
Listing a registry is the tree; an object's public methods are its routes, as they are. Providers, Handlers and
indexes are protocols, never registered: their methods are what the objects call, not routes.

Paths and uris. A DataObject is known by its Location and its path; a Container understands paths only. A uri
names a Location, or what a Link leads to, and only a Collection resolves one. A DataObject with its own uri is
rare.

The tree and the graph. Containers make a tree: every DataObject is in one place. Links make a graph over it: a
Location and the Containers it reaches, a Collection and its members, one span of a session and the next, a
session and its Thread. The graph is not held by the objects: a Link holds uris only, the whole graph is kept in
the index, and it is read around one uri at a time. The graph is what /lake adds to a file system.

What is read from where: config, facts and links. Three stores, and every object is read from one of them.
Config is the configuration as Environment and State define it: tables of rows keyed by uid, each resolved through
its table's templates and built by the class its kind names. Locations, Providers and their connections are such
rows. Facts are tables of what handlers and sources said: DataObjects as rows with a parent; folders, files,
records and spans are all rows, a span's TimeSpan in its row. Links are the graph: edges between uris, for what no
single tree can hold -- one Container under two Locations, a member of a Collection, a span and the next, an
annotation on an object. A graph is not needed where there is a single tree, so the graph holds edges only; a
node is a uri, and what it names is a config row or a fact row. A Location is read from config, a Container reads
facts only, and a Collection is a uri whose links lead to facts. The index holds facts and links.

The Lake is an index and storage. gppu has no Lake: to gppu it is a Collection loaded from configuration. The upper
levels -- Locations -- come from configuration; the lower levels are loaded from the database.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import IO, Any, Protocol, Self

from .gppu import _Base, y2path, y2uri

Ref = y2path | y2uri | str
"""An object reference: a path below a Container, or a uri a Collection resolves."""


@dataclass(frozen=True)
class DataObject:
  """Metadata, with content in some cases. A file, a folder's entry, an archive, a contact and a table are all
  DataObjects.

  A file is not a DataObject without a handler: a handler returns metadata, and that metadata is stored as the
  DataObject. What the source always supplies is stored for every DataObject, whether its source is online or not.
  A DataObject is a value: it is read and written through its Container, and reaches nothing itself. It holds no
  Links; the index does.

  A part of a DataObject -- a span of a session, a passage of text -- is a DataObject too, at the whole's path with
  a fragment naming the part, which is the job RFC 3986 gives the fragment. Its metadata holds the time it covers
  as gppu's TimeSpan. Sessions, threads, the timeline and time accounting all count in these parts.

  A record is a DataObject, and there is no Record type. A record found in several places is one DataObject with
  one uid; the index holds every place it was seen, and the DataObject in hand carries the path it was read at.
  Its uid is the id its own system gives it -- a Graph id, a Telegram id, never one minted from a name -- and any
  other system's id for it is in its metadata. It stays after every copy is gone, with removed set.

  Today: providers.DataObject and handlers.Record, with Probe, FileStats and HandlerError, become this one type.
  identity becomes uid; kind and name move into metadata; the source uri becomes path; removed becomes a time.
  is_folder, size and modified_at, the probes, stats and errors move into metadata, each under its handler's
  name. CRAP's span rows (fact.span) become DataObjects with a fragment; the lake's entity rows are DataObjects,
  instance rows their references and fingerprint rows their ids.
  """
  path: y2path
  """Path-in-container it was read at. Its last segment names the object; a fragment names a part."""
  uid: str
  """Unique identifier: the one its own system gives it. An object with no identifier of its own takes the
  index's id as its uid."""
  metadata: dict[str, Any] = field(default_factory=dict)
  """What the source supplies -- for a file, its type, size, times and file system attributes -- and, under each
  handler's name, what that handler returned, such as the TimeSpan it covers."""
  content: Any = None
  """Present once a handler has read it: MarkdownFile, CSVFile, SessionFile and the other typed objects."""
  removed: datetime | None = None
  """When it was deleted. Its metadata stays held."""
  uri: y2uri | None = None
  """Its own uri, in the rare case it has one. Otherwise its Location's uri_of(path) names it."""


@dataclass(frozen=True)
class Link:
  """A graph link: a source uri, a label, a target uri and a date. A native type, like TimeSpan. A link needs a label
  and a date, and nothing else.

  Annotations, a Collection's members and the original Location of a Container are all Links. The index keeps them.
  """
  source: y2uri
  """The uri the Link goes from."""
  label: str
  """What the Link says: `original`, `member`, `next`, a tag."""
  target: y2uri
  """The uri the Link leads to."""
  date: datetime
  """When the Link was made."""


class _Tree(_Base):
  """A node that lists its children. Location and Container are both trees, and walk is written once here."""

  def ls(self, ref: Ref = '') -> list[Self] | list[DataObject]:
    """The children of the node ref names; of this node when ref is empty."""
    ...

  def walk(self, ref: Ref = '') -> Iterator[tuple[Self | DataObject, list]]:
    """Every node below ref with its children, parents before children, each node once. Written once over ls.

    Used by the lake's Dagster exports on a Location, and by find on a Container.
    """
    ...


class Location(_Tree):
  """A container for alike objects: a Provider, its connection and a path-to-container. The configurable structure.

  Locations form a tree, and each leaf references a Container. A root is a Location with no path: `laptop` is
  Alex-Laptop, the host, with the fileSystem Provider; `laptop-data` is its D: volume, a path below it; and
  `laptop-data/TextLake` is a path below that, known globally as `textlake`. A configured Location is written in
  configuration; a discovered one is found by its Provider -- a tenant's users, a user's drives -- and cached, and
  only discovered Locations are refreshed. Path-to-container and path-in-container together give the path to a
  DataObject. The Provider and the connection are part of the Location: reading an object means invoking the
  Location's operation on the object's path. A Location has a Provider; it is not one.

  Route: the `config` registry, by uid. Listing it is the configured tree, today catalog.locations and
  State.locations; one entry is today's GppuCatalog.location(uid), called by FileIndexer, the lake's Dagster jobs
  and plaud_import. Providers and connections are read-only lists beside it.

  Today: providers.Location and FileLocation, and CRAP's M365Location, PlaudLocation and TelegramLocation. The code
  for each store moves to its Provider. State.connections rows become _connection. CRAP's
  catalog_configuration.save becomes save.
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
  provider: Provider
  """The Provider that reaches it, instantiated from its connection."""
  path: y2path
  """Path-to-container. Empty for a root."""
  parent: Location | None
  """The Location above it. None for a root."""
  configured: bool
  """Written in configuration, rather than discovered."""
  _connection: dict[str, Any]
  """The connection its Provider is instantiated from: an account, an endpoint and credentials. No route serves it."""

  def ls(self, ref: Ref = '') -> list[Location]:
    """Its child Locations: those configuration names under it, and those its Provider discovers -- a tenant's
    users, a user's drives and mailboxes. ref names a Location below it; empty for this one.

    Replaces GppuCatalog.ls_sync(recurse=True), read by FileIndexer's Location tree and the lake's lineage assets.
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
    """Write this Location to configuration, creating it when it is new; returns it as saved.

    Replaces CRAP's catalog_configuration.save behind /config/location, and locations.save_location and
    add_location, which raise.
    """
    ...


class Container(_Tree):
  """A tree of DataObjects -- exactly what a zip file or a folder stores. Not storage.

  A Container is independent of Location: several Locations can reach one Container. TextLake is one Container,
  reached as `laptop-data/TextLake` and on other hosts, and known globally as `textlake` or `lake://text`. Which
  Location is the original is an annotation: a Link labelled `original`. The others are manifestations. A folder
  is a DataObject in the listing that holds it, and a Container once opened.

  A Container understands paths, never uris. It answers from its index, so it answers with nothing online. What
  the index lacks it reads through the Provider of the Location it was reached through, and has that Provider's
  handlers identify. Its methods are written once, here, over the Provider and GppuIndex protocols; a Provider
  brings no Container of its own.

  Route: the `lake` registry, by the uri of the Location it was reached through; its methods take paths below it.

  Today: providers.Container and FileContainer, CRAP's M365Container, PlaudContainer and TelegramContainer, and
  GppuFileSystem. ls returns DataObjects instead of fsspec rows; walk becomes find; read runs the handlers.
  """
  _location: Location
  """The Location it was reached through."""
  _index: GppuIndex
  """Where its facts and links are held."""

  def _resolve(self, ref: Ref) -> tuple[Location, y2path]:
    """ref as this Container's Location and a path below it. A Collection overrides this and nothing else."""
    ...

  def ls(self, ref: Ref = '') -> list[DataObject]:
    """The DataObjects held at ref; at the root when ref is empty.

    Answered from the index. A path the index has never listed is listed by the Provider first, and each DataObject
    is identified by the handlers and put into the index.

    Replaces GppuFileSystem.ls (admin_ui's browser), Container.ls (plaud_import) and FileHandler.walk_sync with
    recursive=False (LakeFileSystem.ls).
    """
    ...

  def info(self, ref: Ref) -> DataObject:
    """The DataObject at ref as the index holds it: what the source supplies and what the handlers identified,
    without reading it.

    Replaces GppuFileSystem.info (admin_ui's browser) and SessionHandler.identify (RAN preserve).
    """
    ...

  def read(self, ref: Ref) -> DataObject:
    """The DataObject at ref, read by its handlers, with its content.

    Replaces probe_sync and load_sync (LakeFileSystem; admin_ui's session classify and cluster), SessionHandler(path)
    (RAN preserve, list-sessions, sessions-clean) and Container.read (plaud_import).
    """
    ...

  def open(self, ref: Ref, mode: str = 'rb') -> IO[bytes]:
    """The bytes at ref, from the source; a member inside an archive through its handler. Raises when the source
    cannot be reached.

    Replaces the FileContainer.read streams (plaud hashing), PostgresFileSystem.cat (postgres_catalog), the gppu-rar
    cat_file (admin_ui's archives), and the pathlib reads in LakeFileSystem and TextLakeResource.
    """
    ...

  def find(self, ref: Ref = '', criteria: dict[str, Any] | None = None) -> list[DataObject]:
    """Every DataObject below ref whose metadata matches criteria; with no criteria, all of them. What criteria are
    is open.

    Replaces Container.walk (FileIndexer), FileHandler.walk_sync with recursive=True (admin_ui's walk_sessions,
    LakeFileSystem's reindex), and the Postgres queries FileIndexer, admin_ui and the lake run themselves.
    """
    ...

  def write(self, ref: Ref, obj: DataObject) -> DataObject:
    """Store obj at ref, replacing what is there, and put it in the index; an empty ref lets the Provider name the
    path from its templates. Returns obj as stored and indexed.

    Replaces Container.write, called by the lake's Dagster jobs and plaud_import, their delete-then-write on
    FileExistsError, and the pathlib writes in LakeFileSystem and TextLakeResource.
    """
    ...

  def delete(self, ref: Ref) -> DataObject:
    """Remove the object at ref from the source. The index keeps it, with removed set.

    Replaces Container.delete, called by the lake's Dagster jobs and plaud_import.
    """
    ...

  def refresh(self, state: dict[str, Any], ref: Ref = '') -> AbstractContextManager[Iterator[DataObject]]:
    """Re-read what is below ref from live state: the DataObjects that changed since state, removed ones included.

    The contract of Container.refresh stays: consume the changes inside the context, and state moves on only after
    every change is consumed and handled; an exception leaves it where it was. Used by the lake's Dagster exports
    and Markdown rendering; plaud_import's own snapshot diff, SessionHandler.invalidate and FileIndexer's indexing
    runs move onto it.
    """
    ...


class Collection(Container):
  """A Container that links arbitrary DataObjects rather than holding them. Its members are Links, and a Link holds
  uris, so it is the Container that understands uris: it resolves one to a Location and a path, and the rest is
  Container's.

  A Collection is a form of annotation: its members are the DataObjects linked to it, and a Link to it adds one.
  A Thread is a Collection of sessions and their spans. A Collection is a uri, and its members are the links that
  lead to it, each from a fact; a Container reads the facts only.

  The Lake is a Collection loaded from configuration. Its Locations come from configuration, and what is below them
  is loaded from the database. `Collection()` is that global Collection, the one the admin tool shows.
  `Collection(root)` is rooted at any Location or uri, which is read, indexed beside itself and browsed the same
  way.

  Route: the `lake` registry; the global Collection is its empty key. Its inherited methods take a uri where a
  Container takes a path; link, links and location_of are its own.

  Today: handlers.GppuCatalog, the configured Locations keyed by uid; GppuFileSystem; indexing.walk_container and
  walk_files; LakeFileSystem in CRAP.
  """
  uri: y2uri
  """The uri this Collection is: `lake://`, or a Thread's uri."""
  _locations: dict[str, Location]
  """The upper levels: Locations from configuration, by uid."""

  def __init__(self, root: Location | y2uri | None = None) -> None:
    """The global Collection of configured Locations; or, given root, the Collection of that Location or uri."""
    ...

  def _resolve(self, ref: Ref) -> tuple[Location, y2path]:
    """ref is a uri here: location_of it. Empty names this Collection's own members."""
    ...

  def location_of(self, uri: y2uri | str) -> tuple[Location, y2path]:
    """The Location uri falls in -- the one whose uri, or one of its mirrors, begins it for longest -- and the path
    below it.

    Replaces Environment.locations.location_of (admin_ui's inventory) and three copies of it: FileIndexer's
    operations.selection, LakeFileSystem.inside and of, and admin_ui's Locations.owner.
    """
    ...

  def link(self, source: y2uri | str, label: str, target: y2uri | str) -> Link:
    """Link source to target under label: a session to its Thread, a span to the next, an object to a tag. Returns
    the Link as held, dated now.

    This is how people make Links; handlers make theirs while reading. Neither end has to exist: a uri names what
    it leads to without knowing anything about it.

    Replaces admin_ui's say, annotate and verify.
    """
    ...

  def links(self, uri: y2uri | str) -> list[Link]:
    """The Links from and to uri: the part of the graph around one DataObject, oldest first.

    Replaces admin_ui's graph node, neighbors and topology reads, and its spans, chains and threads.
    """
    ...


class Provider(Protocol):
  """Provides access to objects by references. A class, instantiated from a connection; a Location has one.

  A Provider lists, opens, writes and deletes what its source holds, on its own paths, and reads what it reaches
  with its handlers. Providers are a list, not a tree: `fileSystem`, `m365`, `telegram`, `plaud`. How one reaches
  an object -- which API, which request -- is its inner working and never a uri. Configuration names the class.

  One Provider does what two classes do today: the Location implementations, which enumerate Locations, and the
  Container implementations with the fsspec filesystems, which enumerate DataObjects. They are one because:
  - Both use one connection and one client. Today M365Container sends its requests through M365Location.
  - Path-to-container and path-in-container are one path, and the source answers both with the same nested
    lists: Graph lists a tenant's users, then a user's drives, then a drive's folders. Where a Location ends is
    configuration; two classes would fix it in code.
  - Refresh re-reads both from the same delta state: the discovered Locations and the changed DataObjects.

  A protocol: Location and Container call these methods, and an implementation provides them. Never registered,
  so no route serves them; the `config` registry lists the Providers that exist.

  Today: the reaching is spread over GppuFileSystem, SharePointFileSystem and CRAP's Location/Container pairs;
  GppuCatalog resolves the connection. One Provider class per provider takes it over. No Provider for Postgres is
  written yet: PostgresFileSystem stays as it is.
  """
  uid: str
  """Its name in configuration: `fileSystem`, `m365`."""
  scheme: str
  """The scheme of the uris of its Locations: `file`, `m365`."""
  handlers: tuple[Handler, ...]
  """The handlers that read what it reaches, in the order they identify and probe. Empty for a source whose
  objects arrive already read."""

  def __init__(self, connection: dict[str, Any]) -> None:
    """Instantiated from a Location's connection."""
    ...

  def locations(self, path: y2path) -> list[Location]:
    """The Locations below path that the source itself defines: the discovered Locations. Called by Location.ls.

    Today: the ls() of CRAP's M365Location, PlaudLocation and TelegramLocation.
    """
    ...

  def ls(self, path: y2path) -> list[DataObject]:
    """What the Container at path holds, with what the source always supplies. Called by Container.ls for a path
    the index has never listed.

    Today: FileContainer.ls through fsspec, and the ls of CRAP's M365Container, PlaudContainer and TelegramContainer.
    """
    ...

  def info(self, path: y2path) -> DataObject:
    """The DataObject at path, from the source. Called by Container.info for a path the index does not hold.

    Today: fsspec's info inside GppuFileSystem.
    """
    ...

  def open(self, path: y2path, mode: str = 'rb') -> IO[bytes]:
    """The bytes at path. Called by Container.open, and by the handlers as they probe.

    Today: fsspec's open inside GppuFileSystem, and the read streams of FileContainer and PlaudContainer.
    """
    ...

  def path_of(self, obj: DataObject) -> y2path:
    """The path this Provider stores obj at, named from its templates. Called by Container.write given no path.

    Today: FileContainer._object_file, which admin_ui's template preview and plaud_import reach into.
    """
    ...

  def write(self, path: y2path, obj: DataObject) -> DataObject:
    """Store obj at path, replacing what is there. Called by Container.write.

    Today: FileContainer.write; M365Container, PlaudContainer and TelegramContainer raise.
    """
    ...

  def delete(self, path: y2path) -> None:
    """Remove the object at path from the source. Called by Container.delete.

    Today: FileContainer.delete; M365Container, PlaudContainer and TelegramContainer raise.
    """
    ...

  def refresh(self, path: y2path, state: dict[str, Any]) -> Iterator[DataObject]:
    """What changed below path since state, removed objects included; state moves on only after every change was
    consumed. Called by Container.refresh.

    Today: the _refresh of CRAP's M365Container, PlaudContainer and TelegramContainer.
    """
    ...


class Handler(Protocol):
  """Reads a DataObject for its Provider. A handler returns metadata, and that metadata is stored as the DataObject.

  A handler has two ways of getting information about a DataObject: identify, from what the source always
  supplies and without reading it; and probe, reading it. It reads through the Container that holds the object,
  by path, never through a local path. A Provider holds its handlers in order, and that order is the order they
  identify and probe in. A failure is kept in the metadata under the handler's name, so one bad file does not stop
  a listing.

  A protocol: a Container calls these methods as it lists and reads, and each handler provides them.

  Today: handlers.Handler with identify, __call__, identify_sync and call_sync on a local Path, returning a Record
  and a typed object; handlers.FileHandler composes them as bases, which the Provider's tuple replaces. The typed
  objects -- MarkdownFile, CSVFile, LogFile, EmailFile, BrowserProfile, SessionFile, SessionFolder, GitRepository,
  SqliteDatabase, ArchiveContents -- become the content of the DataObject.
  """
  name: str
  """The key its metadata and its failures are held under: `markdown`, `session`."""

  def identify(self, obj: DataObject, container: Container) -> bool:
    """Whether this handler recognises obj, from what the source always supplies. Called by Container.ls and info.

    Today: Handler.identify and identify_sync, called on a path by RAN's preserve.
    """
    ...

  def probe(self, obj: DataObject, container: Container) -> DataObject:
    """obj read: with this handler's metadata under its name and, where it has one, its content. Called by
    Container.read.

    Today: Handler.__call__ and call_sync, reached as probe_sync and load_sync by LakeFileSystem and admin_ui's
    session classify and cluster, and as SessionHandler(path) by RAN's preserve, list-sessions and sessions-clean.
    """
    ...

  def links(self, obj: DataObject, uri: y2uri) -> list[Link]:
    """The Links this handler finds from obj as it reads it -- a session's spans and their order. Most find none.
    Called by Container.read, which names obj by its Location's uri_of and hands the Links to the index.
    """
    ...


class GppuIndex(Protocol):
  """The facts and the links, kept where retrieval is fast: referential integrity and ids.

  Two implementations answer the same questions. SqliteIndex is in the file system, beside the data it describes.
  The other is in a database: CRAP's Lake. The id is internal to the index. It is not a pure cache: a removed
  DataObject stays, with the time it went. The database collects the SQLite indexes stored with the data. Every
  entry is named by its canonical uri, as today, so one index can hold many Containers.

  A protocol: Container asks these questions, and SqliteIndex and CRAP's Lake answer them. It is the inner
  machinery of a Container, not the API. entry, put, moved and find are the facts; link and links are the links.
  A fact is never a link and a link never a fact; the two meet only in a Collection, which follows links to facts.
  Config is its own tables, not the index.

  Today: handlers.GppuIndex, a Protocol with entry, put and moved on dict rows by address. CRAP's class Lake in
  lake/common/index.py implements the database side: lake.entity holds the DataObjects, lake.instance their
  references at each Location, and lake.fingerprint their ids; fact.span holds the spans. The Links are the
  edges of the AGE graph meta: IS_PART_OF, ALTERNATE_OF and TAGGED_AS.
  """

  def entry(self, uri: y2uri) -> tuple[DataObject, list[DataObject] | None] | None:
    """The DataObject at uri and what it holds, or None when neither is held. The listing is None when the index
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

  def link(self, link: Link) -> None:
    """Hold link."""
    ...

  def links(self, uri: y2uri) -> list[Link]:
    """The Links from and to uri."""
    ...

  def collect(self, index: GppuIndex) -> None:
    """Take in another index's rows: data that arrives from a place never indexed here keeps what was said about it."""
    ...


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
  """An archive. Its probe lists the members; the members are the DataObjects it holds, and Container.open reaches
  a member's bytes through it.

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
  """An agent session: its turns and statistics, its spans and their order."""


class ChatGPTHandler(Handler):
  """A ChatGPT export.

  Today: shares _LLMExportHandler with AnthropicHandler.
  """


class AnthropicHandler(Handler):
  """An Anthropic export.

  Today: shares _LLMExportHandler with ChatGPTHandler.
  """


class SqliteIndex(GppuIndex):
  """The index stored with the data: `.<name>.gppufs.sqlite` beside the path it describes. An index named for a
  path below owns the tree under it. The database index is CRAP's Lake.

  Today: inside GppuFileSystem.
  """
