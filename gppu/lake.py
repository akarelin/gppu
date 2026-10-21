"""gppu.lake: the Lake. An object is saved to the Lake without a uri, and the Lake decides where it is stored and answers with
its uri; an object is retrieved by its uri. Linked Data is Linked Data and the Lake is the Lake: their APIs are separate, /ld and
/lake. The Lake is a catalog on gppufs: a Lake folder is listed through gppufs's GppuFileSystem, its index beside the Lake, and a
UI lists it through the Lake's API, never the file system or gppufs.

The Lake is configured in two places. Its locations are Linked Data's, a catalog made by gppu.ld.gppufs.catalog(). What the Lake
itself is configured with is the app's, in Env: the uri of the Lake saved objects are stored in, and the templates of its layout
(CRAP Systems/lake/docs/layout.md), one per type of record gppu's handlers read, `source` for any other.

  Lake(catalog, store, templates)   the Lake over catalog's locations, saving below store by templates
  api(lake)                         the Lake as a FastAPI app, which an APIApp serves at /lake among its apis()"""
import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, BinaryIO, Mapping
from urllib.parse import unquote, urlsplit

from . import handlers
from .fs import CACHE, Container, DataObject, GppuCatalog, GppuFileSystem, Location, _below
from .gppu import TemplateSet, TimeSpan, y2uri


class Lake:
    """Every location in the catalog, read by uri, and one folder, store, where saved objects go."""

    def __init__(self, catalog: GppuCatalog, store: y2uri | str, templates: Mapping[str, str]) -> None:
        self.catalog = catalog
        location, path = catalog.location_of(store)
        self.store = Container(location.provider, location.provider.join(location.uri, path))
        self.templates = TemplateSet(named={'lake': dict(templates)})
        self.root = location.provider.local(self.store.uri)   # the Lake on this host
        self.files = GppuFileSystem(str(self.root), locations={self.root.as_posix(): {'location': location.uid,
                                                                                       'canonical': str(self.store.uri)}})

    def _here(self, uri: y2uri | str) -> str | None:
        """The Lake folder or file a uri names, as gppufs takes it; none for a uri outside the Lake."""
        below = _below(str(self.store.uri), str(uri))
        return None if below is None else (self.root / unquote(below)).as_posix()

    @staticmethod
    def _row(row: dict[str, Any]) -> dict[str, Any]:
        """A gppufs row as the Lake answers it: named by its uri in the Lake."""
        return row | {'name': row['gppu']['location']['address']}

    def _at(self, uri: y2uri | str) -> tuple[Container, str]:
        location, path = self.catalog.location_of(uri)
        return location.container(), str(path)

    @staticmethod
    def read(obj: DataObject) -> handlers.Record:
        """What gppu's handlers read of obj: its content as a file under its own name, read by the handler its name and content
        call for, and by none when none does."""
        with tempfile.TemporaryDirectory(prefix='lake-', dir=CACHE) as folder:
            path = Path(folder) / obj.name
            content = obj.content.read() if hasattr(obj.content, 'read') else obj.content
            path.write_bytes(content if isinstance(content, bytes) else content.encode('utf-8') if isinstance(content, str)
                             else json.dumps(content, ensure_ascii=False).encode('utf-8'))
            found = handlers.probe(path)
            handler = handlers.HANDLERS.get((found.type, found.subtype))
            if handler is None:
                return found
            try:
                return handler.parse(path)
            except Exception as error:   # what a handler cannot read has no place in the Lake: the save is refused with its reason
                raise ValueError(f'{obj.name}: {handler.__name__} cannot read it: {type(error).__name__}: {error}') from error

    def place(self, obj: DataObject, record: handlers.Record) -> str:
        """Where obj goes in the Lake, by the template of its record's type, `source` for a type the Lake has none for: rendered
        with the record, the object's name, the date it is of (its span's start, else the date its name says) and the system,
        account and path of the uri it came from."""
        span = getattr(record, 'span', None) or handlers.Handler.named(obj.name)
        source = urlsplit(str(obj.uri))
        path = self.templates.render_template(record.type if record.type in self.templates.named else 'source',
            record=record, name=obj.name, start=span.start if span else None, system=source.scheme, account=source.netloc,
            path=unquote(source.path).strip('/'))
        path = str(path or '').strip()
        if not path:
            raise ValueError(f'{obj.name}: the Lake has no place for a {record.type} {record.subtype or ""} from {obj.uri}'.replace('  ', ' '))
        return str(Location.relative(path))

    def save(self, obj: DataObject) -> y2uri:
        """Store obj where the Lake's layout places it, by what gppu's handlers read of it, and the uri it is stored at."""
        content = obj.content.read() if hasattr(obj.content, 'read') else obj.content
        obj = DataObject(obj.uri, content, obj.identity, obj.kind, obj.name)
        path = self.place(obj, self.read(obj))
        self.store.write(path, obj)
        uri = self.store.provider.join(self.store.uri, Location.relative(path))
        self.files.info(self._here(uri), refresh=True)   # the catalog holds what was saved
        return uri

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
                             the answer is the uri the Lake stored it at
    GET    /{uri}            what the handlers found at uri; ?ls what is inside it, ?walk&level=&recursive= everything below it,
                             ?retrieve the object with its content, ?content its bytes
    DELETE /{uri}            remove the object at uri

    A uri no location holds answers 404, a save to a place another object holds 409 and a value the Lake refuses 400, each with
    its error."""
    from fastapi import FastAPI, Request, Response

    def reply(payload: Any, status: int = 200, content_type: str = 'application/json; charset=utf-8') -> Response:
        data = payload if isinstance(payload, bytes) else json.dumps(payload, default=_json, ensure_ascii=False).encode('utf-8')
        return Response(data, status_code=status, media_type=content_type)

    app = FastAPI(title='Lake')
    app.add_exception_handler(LookupError, lambda request, error: reply({'error': str(error)}, 404))
    app.add_exception_handler(FileExistsError, lambda request, error: reply({'error': str(error)}, 409))   # the place is taken
    for refused in (ValueError, TypeError):
        app.add_exception_handler(refused, lambda request, error: reply({'error': str(error)}, 400))

    @app.post('/')
    async def save(request: Request, name: str, source: str = ''):
        obj = DataObject(source, await request.body(), None, 'file', name)
        return reply({'uri': str(lake.save(obj))}, 201)

    @app.get('/{uri:path}')
    def found(uri: str, ls: str | None = None, walk: str | None = None, level: str = 'files', recursive: str | None = None,
              retrieve: str | None = None, content: str | None = None):   # a flag is there, ?ls, or not
        if ls is not None:
            return reply(lake.ls(uri))
        if walk is not None:
            return reply(lake.walk(uri, level, recursive == '1'))
        if retrieve is not None:
            return reply(lake.retrieve(uri))
        if content is not None:
            with lake.open(uri) as stream:
                return reply(stream.read(), content_type='application/octet-stream')
        return reply(lake.info(uri))

    @app.delete('/{uri:path}')
    def delete(uri: str):
        lake.delete(uri)
        return reply(b'', 204)

    return app
