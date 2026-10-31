"""gppu.fs.lake: the Lake. An object is saved to the Lake without a uri, and the Lake decides where it is stored and answers with
its uri; an object is retrieved by its uri. A client that copies an object to the Lake itself, such as a session hook growing a
session's copy as its log grows, saves it the same way, with enough of it for its handler, and the Lake answers where the client
copies it, storing nothing; the client then has the Lake index what it copied. Linked Data is Linked Data and the Lake is the
Lake: their APIs are separate, /ld and /lake. What the Lake holds is in its catalog (gppu.fs.catalog.Catalog), the one catalog: a
Lake folder is listed from there, and a UI lists it through the Lake's API, never the file system; the store is read only for the
bytes of a file saved, copied or opened.

The Lake is configured in two places. Its locations are Linked Data's, a catalog made by gppu.fs.catalog.catalog(), which reach
every uri outside the Lake. What the Lake itself is configured with is the app's, in Env: the uri of the Lake saved objects are
stored in, a folder this host reaches through gppu.fs's FileSystem, and the templates of its layout
(CRAP Systems/lake/docs/layout.md), one per type of record gppu's handlers read, `source` for any other.

  Lake(catalog, store, templates, contents)   the Lake over catalog's locations, saving below store by templates, its catalog contents
  api(lake)                         the Lake as a FastAPI app, which an APIApp serves at /lake among its apis()
  LakeFileSystem(url, root)         the Lake through its API as an fsspec filesystem, what a desktop or a UI browses it with"""
import io
import json
import shutil
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, BinaryIO, Mapping
from urllib.parse import unquote, urlsplit

from fsspec import AbstractFileSystem
from jinja2 import UndefinedError

from . import handlers
from . import CACHE, Container, DataObject, FileSystem, Location, _address, _below
from .catalog import Catalog, GppuCatalog
from ..gppu import TemplateSet, TimeSpan
from .uri import y2uri

PIECE = 1 << 20   # a download is sent a mebibyte at a time
INDEX = '.gppufs.sqlite'   # how a gppufs index's name ends

class Lake:
    """Every location in the catalog, read by uri, one folder, store, where saved objects go, and the catalog, contents, which holds
    what the Lake holds: every file the Lake saves is recorded there, every index it receives is loaded there, and a Lake folder is
    listed from there, so nothing reads the store but the bytes of a file saved, copied or opened."""

    def __init__(self, catalog: GppuCatalog, store: y2uri | str, templates: Mapping[str, str], contents: Catalog) -> None:
        self.catalog = catalog
        provider = FileSystem()   # the Lake's store is its own configuration, a folder this host reaches, not one of Linked Data's locations
        self.store = Container(provider, y2uri(store))
        self.templates = TemplateSet(named={'lake': dict(templates)})
        self.contents = contents
        self.root = provider.local(self.store.uri)   # the Lake on this host

    def _here(self, uri: y2uri | str) -> Path | None:
        """The Lake folder or file a uri names, on this host; none for a uri outside the Lake."""
        below = _below(str(self.store.uri), str(uri))
        return None if below is None else self.root / unquote(below)

    def _at(self, uri: y2uri | str) -> tuple[Container, str]:
        """The Container that reaches uri and its path there: the Lake's store for a uri in the Lake, else its location's."""
        if (below := _below(str(self.store.uri), str(uri))) is not None:
            return self.store, unquote(below)
        location, path = self.catalog.location_of(uri)
        return location.container(), str(path)

    @staticmethod
    def read(path: Path) -> handlers.Record:
        """What gppu's handlers read of the file at path: read by the handler its name and content call for, and by none when
        none does."""
        found = handlers.probe(path)
        handler = handlers.HANDLERS.get(found.type)
        if handler is None:
            return found
        try:
            return handler.parse(path)
        except Exception as error:   # what a handler cannot read has no place in the Lake: the save is refused with its reason
            raise ValueError(f'{path.name}: {handler.__name__} cannot read it: {type(error).__name__}: {error}') from error

    def place(self, obj: DataObject, record: handlers.Record, type: str) -> str:
        """Where obj goes in the Lake, by the template of its file's type, `source` for a type the Lake has none for: rendered
        with the record, the object's name, the date it is of (its span's start, else the date its name says) and the system,
        account and path of the uri it came from."""
        span = getattr(record, 'span', None) or handlers.Handler.named(obj.name)
        source = urlsplit(str(obj.uri))
        came = f' from {obj.uri}' if source.netloc or source.path else ''   # a save with no source has no uri to name
        try:
            path = self.templates.render_template(type if type in self.templates.named else 'source',
                record=record, name=obj.name, start=span.start if span else None, system=source.scheme, account=source.netloc,
                path=unquote(source.path).strip('/'))
        except UndefinedError as error:   # the template asks for what obj does not say, such as the date of a session with no time
            missing = 'what was sent of it gives no time, so it has no date to be placed by' if span is None else str(error)
            raise ValueError(f'{obj.name}: the Lake has no place for a {type}{came}: {missing}') from error
        path = str(path or '').strip()
        if not path:
            raise ValueError(f'{obj.name}: the Lake has no place for a {type}{came}')
        return str(Location.relative(path))

    def _recorded(self, uri: y2uri | str, path: Path, record: handlers.Record) -> dict[str, Any]:
        """The file the Lake holds at uri recorded in its catalog as its handler read it, from path, its copy on this host."""
        stat = path.stat()
        return self.contents.record(str(uri), record.type or 'file', {
            'kind': 'file', 'size': stat.st_size, 'modified': datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
            'created': None, 'content_type': None, 'columns': {}, 'record': json.loads(json.dumps(vars(record), default=_json))})

    def save(self, obj: DataObject, copy: bool = False) -> y2uri:
        """Store obj where the Lake's layout places it, by what gppu's handlers read of it, record it in the catalog, and the uri it
        is stored at. A gppufs index is stored as any file and received by the catalog, which load() then loads as the latest copy
        of the folder it came from, obj's uri. With copy the client copies obj there itself: obj is as much of the object as its
        handler needs, such as a session's first lines, nothing is stored or recorded, and the uri is where the client copies it
        and then has it indexed. Its content is a file under its own name in CACHE while it is read and stored, a stream copied a
        piece at a time, so a large file is never held whole."""
        with tempfile.TemporaryDirectory(prefix='lake-', dir=CACHE) as folder:
            scratch = Path(folder) / Path(obj.name).name   # its own name, never a path out of the folder
            with scratch.open('wb') as file:
                if hasattr(obj.content, 'read'):
                    shutil.copyfileobj(obj.content, file)
                else:
                    file.write(obj.content if isinstance(obj.content, bytes) else obj.content.encode('utf-8')
                               if isinstance(obj.content, str) else json.dumps(obj.content, ensure_ascii=False).encode('utf-8'))
            record = self.read(scratch)
            path = self.place(obj, record, handlers.probe(scratch).type)
            uri = self.store.provider.join(self.store.uri, Location.relative(path))
            if copy:
                return uri
            with scratch.open('rb') as stream:
                self.store.write(path, DataObject(obj.uri, stream, obj.identity, obj.kind, obj.name))
            self._recorded(uri, scratch, record)
            if obj.name.endswith(INDEX):
                self.contents.received(str(obj.uri))   # loaded after the answer, by load()
        return uri

    def load(self, uri: y2uri | str, source: str) -> None:
        """The index the Lake stored at uri, received from source, loaded into the catalog as the latest copy of its folder's: its
        bytes copied into CACHE and read there."""
        with tempfile.TemporaryDirectory(prefix='lake-', dir=CACHE) as folder:
            copy = Path(folder) / f'index{INDEX}'
            container, path = self._at(uri)
            with container.open(path, 'rb') as stream, copy.open('wb') as file:
                shutil.copyfileobj(stream, file)
            self.contents.load(source, copy)

    def index(self, uri: y2uri | str) -> dict[str, Any]:
        """The file a client copied to uri, where save told it to, read by its handlers and recorded in the catalog."""
        here = self._here(uri)
        if here is None or not here.is_file():
            raise LookupError(f'{uri}: the Lake holds no file there')
        return self._recorded(uri, here, self.read(here))

    def path(self, uri: y2uri | str) -> str:
        """Where uri is below the Lake, as a client that has the Lake mounted joins it to the mount."""
        below = _below(str(self.store.uri), str(uri))
        if below is None:
            raise LookupError(f'{uri} is not in the Lake')
        return unquote(below).strip('/')

    def retrieve(self, uri: y2uri | str) -> DataObject:
        """The object at uri with its content."""
        container, path = self._at(uri)
        return container.read(path)

    def ls(self, uri: y2uri | str) -> list[dict[str, Any]]:
        """What is directly inside uri: a Lake folder from its catalog, each entry as the catalog lists it; any other through its
        location's Container."""
        if self._here(uri) is not None:
            return list(self.contents.entries(uri=str(uri).rstrip('/')))
        container, path = self._at(uri)
        return container.ls(path)

    def walk(self, uri: y2uri | str, level: str = 'files', recursive: bool = False) -> list[tuple[dict, list[dict]]]:
        """Every folder at and below uri with what it holds, read as deep as level, through its location's Container; the Lake
        is listed from its catalog, a folder at a time (ls), never walked."""
        if self._here(uri) is not None:
            raise ValueError(f'{uri}: the Lake is listed from its catalog, a folder at a time, never walked')
        container, path = self._at(uri)
        return list(container.walk(path, level=level, recursive=recursive))

    def info(self, uri: y2uri | str) -> dict[str, Any]:
        """What is at uri, without its content: in the Lake from its catalog, else through its location's Container."""
        if self._here(uri) is not None:
            return self.contents.info(str(uri).rstrip('/'))
        container, path = self._at(uri)
        return container.info(path)

    def open(self, uri: y2uri | str, mode: str = 'rb') -> BinaryIO:
        """The bytes at uri."""
        container, path = self._at(uri)
        return container.open(path, mode)

    def delete(self, uri: y2uri | str) -> None:
        """Remove the object at uri, and from the catalog when it is in the Lake."""
        container, path = self._at(uri)
        container.delete(path)
        if self._here(uri) is not None:
            self.contents.forget(str(uri))


def _json(value: Any) -> Any:
    if isinstance(value, DataObject):
        content = value.content if not hasattr(value.content, 'read') and not isinstance(value.content, bytes) else None
        return {'uri': str(value.uri), 'identity': value.identity, 'kind': value.kind, 'name': value.name,
                'removed': value.removed, 'content': content}
    if isinstance(value, TimeSpan):
        return {'start': _json(value.start), 'end': _json(value.end)}
    if isinstance(value, handlers.Record):
        return vars(value)
    if isinstance(value, datetime):
        return (value.astimezone() if value.tzinfo is not None else value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def api(lake: Lake):
    """lake as REST resources, a FastAPI app an APIApp serves at /lake. Needs FastAPI (the `ld` extra).

    POST   /?name=&source=   save the file that is the body, by its name and the uri it came from, source, where there is one;
                             the answer is the uri the Lake stored it at; with ?copy the client copies the file itself, the body
                             as much of it as its handler needs, and the answer is the uri and the path below the Lake it copies
                             it to, nothing stored; a gppufs index is stored, answered 202, and loaded into the catalog after,
                             one at a time, its state at /lake/catalog/indexes?folder=
    POST   /{uri}            index the file a client copied to uri, after answering 202: a long session is read for seconds, and
                             no client waits for it; one file is indexed at a time, and a file copied to again while it is
                             indexed is indexed once more after
    GET    /{uri}            what the handlers found at uri, the Lake itself when no uri is given; ?ls what is inside it,
                             ?walk&level=&recursive= everything below it, ?retrieve the object with its content, ?content its bytes
    GET    /?failed          each copied file whose last index failed, and each index whose last load failed, with its error,
                             until an index or a load of it succeeds
    DELETE /{uri}            remove the object at uri

    A uri no location holds answers 404, a save to a place another object holds 409 and a value the Lake refuses 400, each with
    its error."""
    from fastapi import FastAPI, Request, Response
    from fastapi.responses import StreamingResponse
    from starlette.background import BackgroundTask

    def reply(payload: Any, status: int = 200, content_type: str = 'application/json; charset=utf-8') -> Response:
        data = payload if isinstance(payload, bytes) else json.dumps(payload, default=_json, ensure_ascii=False).encode('utf-8')
        return Response(data, status_code=status, media_type=content_type)

    app = FastAPI(title='Lake')
    app.add_exception_handler(LookupError, lambda request, error: reply({'error': str(error)}, 404))
    app.add_exception_handler(FileExistsError, lambda request, error: reply({'error': str(error)}, 409))   # the place is taken
    for refused in (ValueError, TypeError):
        app.add_exception_handler(refused, lambda request, error: reply({'error': str(error)}, 400))

    indexing: dict[str, bool] = {}   # each uri waiting or being indexed, and whether it was copied to again meanwhile
    failures: dict[str, str] = {}   # each uri whose last index or load failed, and why: the client had its 202 before, so ?failed shows it
    turn, guard = threading.Lock(), threading.Lock()   # one file indexed at a time; guard keeps indexing and failures whole
    loads = threading.Lock()   # one index loaded at a time, apart from the copies indexed, as a load takes minutes

    def load(uri: str, source: str) -> None:
        try:
            with loads:
                lake.load(uri, source)
            with guard:
                failures.pop(uri, None)
        except BaseException as error:   # kept for ?failed and the catalog's /indexes, and raised on to the server's log
            with guard:
                failures[uri] = f'{type(error).__name__}: {error}'
            raise

    @app.post('/')
    async def save(request: Request, name: str, source: str = '', copy: str | None = None):
        with tempfile.TemporaryFile(dir=CACHE) as body:   # the body streamed to a file as it arrives, never held whole
            async for chunk in request.stream():
                body.write(chunk)
            body.seek(0)
            uri = lake.save(DataObject(source, body, None, 'file', name), copy is not None)
        if copy is not None:
            return reply({'uri': str(uri), 'path': lake.path(uri)})
        if name.endswith(INDEX):   # stored and received; loaded after the answer, as a large index loads for minutes
            return Response(json.dumps({'uri': str(uri)}), status_code=202, media_type='application/json; charset=utf-8',
                            background=BackgroundTask(load, str(uri), source))
        return reply({'uri': str(uri)}, 201)

    def index(uri: str) -> None:
        try:
            while True:
                with turn:
                    lake.index(uri)
                with guard:
                    failures.pop(uri, None)
                    if not indexing[uri]:
                        del indexing[uri]
                        return
                    indexing[uri] = False
        except BaseException as error:   # kept for ?failed and raised on to the server's log, the uri free for the next copy
            with guard:
                indexing.pop(uri, None)
                failures[uri] = f'{type(error).__name__}: {error}'
            raise

    @app.post('/{uri:path}')
    def copied(uri: str):
        here = lake._here(uri)
        if here is None or not Path(here).is_file():
            raise LookupError(f'{uri}: the Lake holds no file there')
        with guard:
            waiting = uri in indexing
            indexing[uri] = waiting
        return Response(json.dumps({'uri': uri}), status_code=202, media_type='application/json; charset=utf-8',
                        background=None if waiting else BackgroundTask(index, uri))

    @app.get('/{uri:path}')
    def found(uri: str, ls: str | None = None, walk: str | None = None, level: str = 'files', recursive: str | None = None,
              retrieve: str | None = None, content: str | None = None, failed: str | None = None):   # a flag is there, ?ls, or not
        if failed is not None:
            with guard:
                return reply(dict(failures))
        uri = uri or str(lake.store.uri)
        if ls is not None:
            return reply(lake.ls(uri))
        if walk is not None:
            return reply(lake.walk(uri, level, recursive == '1'))
        if retrieve is not None:
            return reply(lake.retrieve(uri))
        if content is not None:   # streamed a piece at a time, so a large file is never held whole
            stream = lake.open(uri)
            return StreamingResponse(iter(lambda: stream.read(PIECE), b''), media_type='application/octet-stream',
                                     background=BackgroundTask(stream.close))
        return reply(lake.info(uri))

    @app.delete('/{uri:path}')
    def delete(uri: str):
        lake.delete(uri)
        return reply(b'', 204)

    return app


class LakeFileSystem(AbstractFileSystem):
    """The Lake through its API, an fsspec filesystem whose paths are relative to root, the uri of the Lake or a folder in it: ls and
    info answer what the Lake's catalog answers, open gives the bytes. Read-only; saving goes through the API's POST. client is
    the API's, made from url, or one a caller gives, such as a test's."""

    protocol = 'lake'
    cachable = False

    def __init__(self, url: str = '', root: str = '', client: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        import httpx
        self.root = root.rstrip('/')
        self.client = client or httpx.Client(base_url=url.rstrip('/'), timeout=300)   # as gppu.fs.catalog.connect gives each call

    def _uri(self, path: str) -> str:
        path = self._strip_protocol(path).strip('/')
        return f'{self.root}/{path}' if path else self.root

    def _get(self, path: str, **flags: str) -> Any:
        r = self.client.get(f'/lake/{self._uri(path)}', params=flags)
        if r.status_code == 404:
            raise FileNotFoundError(path)
        r.raise_for_status()
        return r

    @staticmethod
    def _entry(row: dict[str, Any], name: str) -> dict[str, Any]:
        """An entry of the Lake's catalog as fsspec has an entry: named by its path below root, a folder a directory."""
        folder = row['kind'] == 'folder'
        return row | {'name': name, 'type': 'directory' if folder else 'file', 'size': 0 if folder else row['size'] or 0}

    def ls(self, path: str = '', detail: bool = True, **kwargs: Any) -> list[dict[str, Any]] | list[str]:
        path = self._strip_protocol(path).strip('/')
        rows = [self._entry(row, f"{path}/{row['name']}".strip('/')) for row in self._get(path, ls='').json()]
        return rows if detail else [row['name'] for row in rows]

    def info(self, path: str = '', **kwargs: Any) -> dict[str, Any]:
        return self._entry(self._get(path).json(), self._strip_protocol(path).strip('/'))

    def _open(self, path: str, mode: str = 'rb', **kwargs: Any) -> BinaryIO:
        if mode != 'rb':
            raise PermissionError(f'{path}: the Lake is read through its API; a file is saved with POST /lake/')
        return io.BytesIO(self._get(path, content='').content)
