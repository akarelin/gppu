"""gppu.fs.lake: the Lake. An object is saved to the Lake without a uri, and the Lake decides where it is stored and answers with
its uri; an object is retrieved by its uri. A client that copies an object to the Lake itself, such as a session hook growing a
session's copy as its log grows, saves it the same way, with enough of it for its handler, and the Lake answers where the client
copies it, storing nothing; the client then has the Lake index what it copied. Linked Data is Linked Data and the Lake is the Lake: their APIs are separate, /ld and
/lake. The Lake is a catalog on gppufs: a Lake folder is listed through gppufs's GppuFileSystem, its index beside the Lake, and a
UI lists it through the Lake's API, never the file system or gppufs.

The Lake is configured in two places. Its locations are Linked Data's, a catalog made by gppu.fs.catalog.catalog(). What the Lake
itself is configured with is the app's, in Env: the uri of the Lake saved objects are stored in, and the templates of its layout
(CRAP Systems/lake/docs/layout.md), one per type of record gppu's handlers read, `source` for any other.

  Lake(catalog, store, templates)   the Lake over catalog's locations, saving below store by templates
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
from . import CACHE, Container, DataObject, Location, _address, _below
from .catalog import GppuCatalog
from .gppufs import GppuFileSystem
from ..gppu import TemplateSet, TimeSpan, y2uri

PIECE = 1 << 20   # a download is sent a mebibyte at a time

class Lake:
    """Every location in the catalog, read by uri, and one folder, store, where saved objects go."""

    def __init__(self, catalog: GppuCatalog, store: y2uri | str, templates: Mapping[str, str]) -> None:
        self.catalog = catalog
        location, path = catalog.location_of(store)
        self.store = Container(location.provider, location.provider.join(location.uri, path))
        self.templates = TemplateSet(named={'lake': dict(templates)})
        self.files = GppuFileSystem()
        self.root = self.files._key(location.provider.local(self.store.uri).as_posix())   # the Lake on this host, as gppufs names it
        self.files.ls(self.root)   # the Lake's index is at its root, so what it saves is indexed there and never beside a day folder

    def _here(self, uri: y2uri | str) -> str | None:
        """The Lake folder or file a uri names, as gppufs takes it; none for a uri outside the Lake."""
        below = _below(str(self.store.uri), str(uri))
        return None if below is None else f'{self.root}/{unquote(below)}'.rstrip('/')

    def _row(self, row: dict[str, Any]) -> dict[str, Any]:
        """A gppufs row as the Lake answers it: named by its uri in the Lake."""
        return row | {'name': _address(str(self.store.uri), row['name'][len(self.root):].strip('/'))}

    def _at(self, uri: y2uri | str) -> tuple[Container, str]:
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
        try:
            path = self.templates.render_template(type if type in self.templates.named else 'source',
                record=record, name=obj.name, start=span.start if span else None, system=source.scheme, account=source.netloc,
                path=unquote(source.path).strip('/'))
        except UndefinedError as error:   # the template asks for what obj does not say, such as the date of a session with no time
            raise ValueError(f'{obj.name}: the Lake has no place for a {type} from {obj.uri}: {error}') from error
        path = str(path or '').strip()
        if not path:
            raise ValueError(f'{obj.name}: the Lake has no place for a {type} from {obj.uri}')
        return str(Location.relative(path))

    def save(self, obj: DataObject, copy: bool = False) -> y2uri:
        """Store obj where the Lake's layout places it, by what gppu's handlers read of it, and the uri it is stored at. With
        copy the client copies it there itself: obj is as much of the object as its handler needs, such as a session's first
        lines, nothing is stored, and the uri is where the client copies it and then has it indexed. Its content is a file under
        its own name in CACHE while it is read and stored, a stream copied a piece at a time, so a large file is never held
        whole."""
        with tempfile.TemporaryDirectory(prefix='lake-', dir=CACHE) as folder:
            scratch = Path(folder) / Path(obj.name).name   # its own name, never a path out of the folder
            with scratch.open('wb') as file:
                if hasattr(obj.content, 'read'):
                    shutil.copyfileobj(obj.content, file)
                else:
                    file.write(obj.content if isinstance(obj.content, bytes) else obj.content.encode('utf-8')
                               if isinstance(obj.content, str) else json.dumps(obj.content, ensure_ascii=False).encode('utf-8'))
            path = self.place(obj, self.read(scratch), handlers.probe(scratch).type)
            if copy:
                return self.store.provider.join(self.store.uri, Location.relative(path))
            with scratch.open('rb') as stream:
                self.store.write(path, DataObject(obj.uri, stream, obj.identity, obj.kind, obj.name))
        uri = self.store.provider.join(self.store.uri, Location.relative(path))
        self.index(uri)   # the catalog holds what was saved
        return uri

    def index(self, uri: y2uri | str) -> dict[str, Any]:
        """The file at uri read again by its handlers into the Lake's catalog, gppufs: what save stored, or what a client copied
        where save told it to."""
        here = self._here(uri)
        if here is None or not Path(here).is_file():
            raise LookupError(f'{uri}: the Lake holds no file there')
        return self._row(self.files.info(here, refresh=True))   # plainly, as an async route calls save too

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
        """What is directly inside uri: a Lake folder from its catalog, gppufs, each entry with what its handlers read; any other
        through its location's Container."""
        if (here := self._here(uri)) is not None:
            return [self._row(row) for row in self.files.ls(here, detail=True)]
        container, path = self._at(uri)
        return container.ls(path)

    def walk(self, uri: y2uri | str, level: str = 'files', recursive: bool = False) -> list[tuple[dict, list[dict]]]:
        """Every folder at and below uri with what it holds, read as deep as level."""
        container, path = self._at(uri)
        return list(container.walk(path, level=level, recursive=recursive))

    def info(self, uri: y2uri | str) -> dict[str, Any]:
        """What the handlers found at uri, without its content: in the Lake from its catalog, gppufs."""
        if (here := self._here(uri)) is not None:
            return self._row(self.files.info(here))
        container, path = self._at(uri)
        return container.info(path)

    def open(self, uri: y2uri | str, mode: str = 'rb') -> BinaryIO:
        """The bytes at uri."""
        container, path = self._at(uri)
        return container.open(path, mode)

    def delete(self, uri: y2uri | str) -> None:
        """Remove the object at uri."""
        container, path = self._at(uri)
        container.delete(path)


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
                             it to, nothing stored
    POST   /{uri}            index the file a client copied to uri, after answering 202: a long session is read for seconds, and
                             no client waits for it; one file is indexed at a time, and a file copied to again while it is
                             indexed is indexed once more after
    GET    /{uri}            what the handlers found at uri, the Lake itself when no uri is given; ?ls what is inside it,
                             ?walk&level=&recursive= everything below it, ?retrieve the object with its content, ?content its bytes
    GET    /?failed          each copied file whose last index failed, with its error, until an index of it succeeds
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

    @app.post('/')
    async def save(request: Request, name: str, source: str = '', copy: str | None = None):
        with tempfile.TemporaryFile(dir=CACHE) as body:   # the body streamed to a file as it arrives, never held whole
            async for chunk in request.stream():
                body.write(chunk)
            body.seek(0)
            uri = lake.save(DataObject(source, body, None, 'file', name), copy is not None)
        if copy is not None:
            return reply({'uri': str(uri), 'path': lake.path(uri)})
        return reply({'uri': str(uri)}, 201)

    indexing: dict[str, bool] = {}   # each uri waiting or being indexed, and whether it was copied to again meanwhile
    failures: dict[str, str] = {}   # each uri whose last index failed, and why: the client had its 202 before, so ?failed shows it
    turn, guard = threading.Lock(), threading.Lock()   # one file indexed at a time; guard keeps indexing and failures whole

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

    def _entry(self, row: dict[str, Any]) -> dict[str, Any]:
        """A Lake row as fsspec has an entry: named by its path below root."""
        return row | {'name': row['name'][len(self.root):].strip('/')}

    def ls(self, path: str = '', detail: bool = True, **kwargs: Any) -> list[dict[str, Any]] | list[str]:
        rows = [self._entry(row) for row in self._get(path, ls='').json()]
        return rows if detail else [row['name'] for row in rows]

    def info(self, path: str = '', **kwargs: Any) -> dict[str, Any]:
        return self._entry(self._get(path).json())

    def _open(self, path: str, mode: str = 'rb', **kwargs: Any) -> BinaryIO:
        if mode != 'rb':
            raise PermissionError(f'{path}: the Lake is read through its API; a file is saved with POST /lake/')
        return io.BytesIO(self._get(path, content='').content)
