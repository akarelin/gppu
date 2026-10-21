"""Archived from gppu/fs.py, 2026-10-21: the Lake as gppu.fs.Collection over a configuration loaded and stored as tables,
its /config and /lake API and serve(). The Lake is gppu.lake; its locations are Linked Data's."""

class Collection:
  """The Lake: every configured Location, and whatever they hold, addressed by uri.

  Its methods take a uri where a Container takes a path. A uri resolves to the configured Location whose uri begins
  it for longest, and the rest is the path inside that Location's Container.
  """

  def __init__(self, load: Callable[[], GppuCatalog], store: Callable[[Location | None, str, dict[str, Any]], None]) -> None:
    """The Lake of the Locations load reads from where the configuration is kept; store writes a Location's
    configuration row there, a new row when the Location is None, and the configuration is read again after it."""
    self._load, self._store_row = load, store
    self._catalog = load()

  def _store(self, location: Location | None, who: str, fields: dict[str, Any]) -> None:
    self._store_row(location, who, fields)
    self._catalog = self._load()

  def add(self, who: str, **fields: Any) -> None:
    """Write a new Location's configuration row as who: provider, uid, name, path, service, kind, icon, tags, folders."""
    self._store(None, who, fields)

  @property
  def locations(self) -> dict[str, Location]:
    """Every configured Location, by uid."""
    return {uid: self.location(uid) for uid in self._catalog.locations}

  def location(self, uid: str) -> Location:
    """The configured Location with uid."""
    location = self._catalog.location(uid)
    location._store = self._store
    return location

  def location_of(self, uri: y2uri | str) -> tuple[Location, y2path]:
    """The Location a uri falls under, and the path below it."""
    return self._catalog.location_of(uri)

  def config(self, table: str | None = None) -> list[str] | dict[str, dict[str, Any]]:
    """The configuration, before templates resolve it: the names of its tables, or one table's rows by uid.

    A table is what the configuration was loaded with, never the objects built from it. Locations are listed with
    the rest; /config/locations adds and changes them.
    """
    tables = {name: rows for name, rows in self._catalog._config.items() if isinstance(rows, Mapping)}
    if table is None:
      return sorted(tables)
    return {uid: deepcopy(row) for uid, row in tables[table].items() if isinstance(row, Mapping)}

  def _at(self, uri: y2uri | str) -> tuple[Container, y2path]:
    location, path = self.location_of(uri)
    return location.container(), path

  def ls(self, uri: y2uri | str, detail: bool = True) -> list[dict[str, Any]] | list[str]:
    """What is directly inside uri."""
    container, path = self._at(uri)
    return container.ls(path, detail)

  def walk(self, uri: y2uri | str, level: str = 'files', recursive: bool = False) -> list[tuple[dict, list[dict]]]:
    """Every folder at and below uri with what it holds, read as deep as level."""
    container, path = self._at(uri)
    return list(container.walk(path, level=level, recursive=recursive))

  def info(self, uri: y2uri | str) -> dict[str, Any]:
    """What the handlers found at uri, without its content."""
    container, path = self._at(uri)
    return container.info(path)

  def read(self, uri: y2uri | str) -> DataObject:
    """The object at uri with its content."""
    container, path = self._at(uri)
    return container.read(path)

  def open(self, uri: y2uri | str, mode: str = 'rb') -> BinaryIO:
    """The bytes at uri."""
    container, path = self._at(uri)
    return container.open(path, mode)

  def write(self, uri: y2uri | str, obj: DataObject) -> None:
    """Store obj at uri."""
    container, path = self._at(uri)
    container.write(path, obj)

  def delete(self, uri: y2uri | str) -> None:
    """Remove the object at uri."""
    container, path = self._at(uri)
    container.delete(path)

def _json(value: Any) -> Any:
  if isinstance(value, Location):
    return value.uid
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


def api(lake: Collection):
  """lake's configuration and content as REST resources, a FastAPI app: an APIApp serves it among its apis(), serve() alone.
  A write to the configuration carries its author as who. Needs FastAPI (the `ld` extra).

  GET    /config                    the names of the configuration's tables
  GET    /config/{table}[/{uid}]    a table's rows as configured, or one row
  GET    /config/locations          every Location's configuration
  GET    /config/locations/{uid}    one Location's configuration; the uid is URL-encoded, a generated one has slashes
  POST   /config/locations          add a Location: who, provider, uid, name, path, service, kind, icon, tags, folders
  PATCH  /config/locations/{uid}    change a Location's fields as who; a new configured uid goes in the body
  GET    /lake/{uri}                what the handlers found at uri; ?ls what is inside it, ?walk&level=&recursive=
                                    everything below it, ?read the object with its content, ?content its bytes
  PUT    /lake/{uri}                store the object in the body: content, identity, kind, name
  DELETE /lake/{uri}                remove the object at uri

  An unknown name answers 404 and a value lake refuses 400, each with its error.
  """
  from fastapi import Body, FastAPI, Response

  def reply(payload: Any, status: int = 200, content_type: str = 'application/json; charset=utf-8') -> Response:
    data = payload if isinstance(payload, bytes) else json.dumps(payload, default=_json, ensure_ascii=False).encode('utf-8')
    return Response(data, status_code=status, media_type=content_type)

  app = FastAPI(title='gppufs')
  app.add_exception_handler(LookupError, lambda request, error: reply({'error': str(error)}, 404))
  for refused in (ValueError, TypeError):
    app.add_exception_handler(refused, lambda request, error: reply({'error': str(error)}, 400))

  @app.get('/config/locations')
  def locations(): return reply([location.data for location in lake.locations.values()])

  @app.get('/config/locations/{uid:path}')
  def location(uid: str): return reply(lake.location(uid).data)

  @app.post('/config/locations')
  def add(body: dict = Body(...)):
    lake.add(**body)
    return reply(lake.location(body.get('uid') or body['provider'] + ('/' + body['path'] if body.get('path') else '')).data, 201)

  @app.patch('/config/locations/{uid:path}')
  def change(uid: str, body: dict = Body(...)):
    id = lake.location(uid).data['id']
    lake.location(uid).save(**body)
    return reply(next(location.data for location in lake.locations.values() if location.data['id'] == id))

  @app.get('/config')
  def tables(): return reply(lake.config())

  @app.get('/config/{name:path}')
  def table(name: str):
    table, _, uid = name.partition('/')
    rows = lake.config(table)
    return reply(rows[uid] if uid else rows)

  @app.get('/lake')
  @app.get('/lake/{uri:path}')
  def found(uri: str | None = None, ls: str | None = None, walk: str | None = None, level: str = 'files', recursive: str | None = None,
           read: str | None = None, content: str | None = None):   # a flag is there, ?ls, or not
    if ls is not None:
      return reply(lake.ls(uri))
    if walk is not None:
      return reply(lake.walk(uri, level, recursive == '1'))
    if read is not None:
      return reply(lake.read(uri))
    if content is not None:
      with lake.open(uri) as stream:
        return reply(stream.read(), content_type='application/octet-stream')
    return reply(lake.info(uri))

  @app.put('/lake/{uri:path}')
  def write(uri: str, body: dict = Body(...)):
    lake.write(uri, DataObject(uri, body['content'], body.get('identity'), body.get('kind', 'object'), body.get('name', '')))
    return reply(b'', 204)

  @app.delete('/lake/{uri:path}')
  def delete(uri: str):
    lake.delete(uri)
    return reply(b'', 204)

  return app


def serve(lake: Collection, host: str, port: int) -> None:
  """api(lake) on uvicorn at host and port, for a program that serves the Lake alone."""
  import uvicorn
  uvicorn.run(api(lake), host=host, port=port)

  def save(self, who: str, **fields: Any) -> None:
    """Write fields into this Location's configuration row as who: uid, name, path, service, kind, icon, tags, folders.

    Args:
      who (str): Author identity written with the configuration change.
      fields (Any): Named configuration changes: uid, name, path, service, kind, icon, tags or folders; null removes a field in the REST merge patch.

    Returns:
      None: The configured store writes the change; read the Location from its Collection again for updated values.
    """
    if self._store is None:
      raise ValueError(f'{self.uid}: this Location was not loaded from a configuration it can write to')
    self._store(self, who, fields)
