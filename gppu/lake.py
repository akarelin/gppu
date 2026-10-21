"""gppu.lake: the Lake. An object is saved to the Lake without a uri, and the Lake decides where it is stored and answers with
its uri; an object is retrieved by its uri. Linked Data is Linked Data and the Lake is the Lake: their APIs are separate, /ld and
/lake.

The Lake is configured in two places. Its locations are Linked Data's, a catalog made by gppu.ld.gppufs.catalog(). What the Lake
itself is configured with is the app's, in Env: the uri of the folder saved objects are stored in, and the naming templates
that place each object in it (Container.path_of).

  Lake(catalog, store, templates)   the Lake over catalog's locations, saving below store by templates
  api(lake)                         the Lake as a FastAPI app, which an APIApp serves at /lake among its apis()"""
import json
from datetime import date, datetime
from typing import Any, BinaryIO, Mapping

from . import handlers
from .fs import Container, DataObject, GppuCatalog, Location
from .gppu import TimeSpan, y2uri


class Lake:
    """Every location in the catalog, read by uri, and one folder, store, where saved objects go."""

    def __init__(self, catalog: GppuCatalog, store: y2uri | str, templates: Mapping[str, str]) -> None:
        self.catalog = catalog
        location, path = catalog.location_of(store)
        self.store = Container(location.provider, location.provider.join(location.uri, path), templates=templates)

    def _at(self, uri: y2uri | str) -> tuple[Container, str]:
        location, path = self.catalog.location_of(uri)
        return location.container(), str(path)

    def save(self, obj: DataObject) -> y2uri:
        """Store obj where the Lake's naming templates place it, and the uri it is stored at."""
        path = self.store.path_of(obj)
        self.store.write(path, obj)
        return self.store.provider.join(self.store.uri, Location.relative(path))

    def retrieve(self, uri: y2uri | str) -> DataObject:
        """The object at uri with its content."""
        container, path = self._at(uri)
        return container.read(path)

    def ls(self, uri: y2uri | str) -> list[dict[str, Any]]:
        """What is directly inside uri."""
        container, path = self._at(uri)
        return container.ls(path)

    def walk(self, uri: y2uri | str, level: str = 'files', recursive: bool = False) -> list[tuple[dict, list[dict]]]:
        """Every folder at and below uri with what it holds, read as deep as level."""
        container, path = self._at(uri)
        return list(container.walk(path, level=level, recursive=recursive))

    def info(self, uri: y2uri | str) -> dict[str, Any]:
        """What the handlers found at uri, without its content."""
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

    POST   /                 save the object in the body, content, name, kind, identity and the uri it came from, source; the
                             answer is the uri the Lake stored it at
    GET    /{uri}            what the handlers found at uri; ?ls what is inside it, ?walk&level=&recursive= everything below it,
                             ?retrieve the object with its content, ?content its bytes
    DELETE /{uri}            remove the object at uri

    A uri no location holds answers 404 and a value the Lake refuses 400, each with its error."""
    from fastapi import Body, FastAPI, Response

    def reply(payload: Any, status: int = 200, content_type: str = 'application/json; charset=utf-8') -> Response:
        data = payload if isinstance(payload, bytes) else json.dumps(payload, default=_json, ensure_ascii=False).encode('utf-8')
        return Response(data, status_code=status, media_type=content_type)

    app = FastAPI(title='Lake')
    app.add_exception_handler(LookupError, lambda request, error: reply({'error': str(error)}, 404))
    for refused in (ValueError, TypeError):
        app.add_exception_handler(refused, lambda request, error: reply({'error': str(error)}, 400))

    @app.post('/')
    def save(body: dict = Body(...)):
        obj = DataObject(body.get('source', ''), body['content'], body.get('identity'), body.get('kind', 'object'), body.get('name', ''))
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
