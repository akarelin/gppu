r"""gppufs on Linked Data: gppu.fs as it is, what it is configured with kept by Linked Data's files API (gppu.ld.files) and reached
through it only, at the address the caller gives connect(); its files in gppufs's own index, the distributed index beside each location
(Linked Data - gppufs: "Files stay in gppufs's indexes; they are not Linked Data records"). The app using it loads its own
configuration into gppu's Env: `drives`, where a Windows host's WSL mounts its drives, is read from it (Drives).

  catalog()     gppu.fs.GppuCatalog made from GET /files/locations: every location in use, each reached over its root location's
                handler, its connection. Its Providers are gppufs's own, FileSystem for file://, and those a caller gives, as
                GppuCatalog takes them: the Locations and Containers FileIndexer and every gppufs user reach files through
  collection()  gppu.fs.Collection, the Lake, over the catalog, a Location's configuration written back by store()
  filesystem()  the GppuFileSystem of a location this host reaches, its index beside it: a listing reads the folder and keeps what
                gppufs's handlers read there, a lookup answers from it"""
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import httpx

from . import Type
from ..fs import Collection, FileSystem, GppuCatalog, GppuFileSystem, Location
from ..gppu import full_path, glob

client: httpx.Client   # the API, opened by connect()


def connect(url: str) -> None:
    """Open Linked Data's API at url. One connection serves every call: a connection a call left 11,811 sockets waiting after one walk
    and ran this host out of ports (WinError 10048)."""
    global client
    if not url:
        raise ValueError("Linked Data's API address is required")
    client = httpx.Client(base_url=url, timeout=300)


def api(method: str, path: str, body: Any = None, **params: Any) -> Any:
    """One call to the API, its answer as JSON; a refusal raises with what the API said (a 422 carries Postgres' reason), a 404 as LookupError."""
    r = client.request(method, path, json=body, params=params)
    if r.is_error:
        raise (LookupError if r.status_code == 404 else ValueError)(f'{method} {path}: {r.status_code} {r.text}')
    return r.json()


class Drives(FileSystem):
    """gppufs's FileSystem in a Windows host's WSL: a file uri naming a drive, file://alex-pc/D:/Dev, is that drive as WSL mounts it,
    /mnt/d/Dev (`drives` in the app's configuration), so a location configured on the host is walked from its WSL as it is configured."""

    def local(self, uri: Any) -> Path:
        parsed = urlsplit(str(uri))
        path = unquote(parsed.path)
        if len(path) >= 3 and path[0] == '/' and path[2] == ':':
            if not (drives := glob('drives')):
                raise ValueError("`drives`, where WSL mounts this host's drives, is not in the app's configuration")
            uri = urlunsplit(parsed._replace(path=quote(f"{drives}/{path[1].casefold()}{path[3:]}")))
        return super().local(uri)


def catalog(**location_types: Any) -> GppuCatalog:
    """gppufs's catalog of Linked Data's locations: the rows of GET /files/locations, each over its connection, the handler of the root
    location it names. location_types are the Providers a caller adds by scheme, as GppuCatalog takes them; gppufs's FileSystem reaches
    file://, and in a Windows host's WSL, Drives does."""
    rows = api('GET', '/files/locations')
    roots = [r for r in rows if r['connection'] == r['uid']]
    if missing := [r['uid'] for r in roots if r['handler'] is None]:
        raise ValueError(f'root locations without a handler, their connection: {", ".join(missing)}')
    return GppuCatalog({'locations': rows, 'connections': {r['uid']: r['handler'] for r in roots}}, location_types=location_types)


def store(location: Location | None, who: str, fields: dict[str, Any]) -> None:
    """A Location's configuration written as who, as gppufs's Collection stores it: into the location's record, a new fs_location when
    location is None. Its name is the record's, its tags meta.tags, its parent the location with that uid, the rest its data; meta.generated
    says who wrote it and when (Alex's provenance, generated: {by, at}). A null removes a field."""
    if not who:
        raise ValueError('configuration author is required')
    fields, record = dict(fields), {'meta': {'generated': {'by': who, 'at': datetime.now().astimezone().isoformat()}}}
    if 'name' in fields:
        record['name'] = fields.pop('name')
    if 'tags' in fields:
        record['meta']['tags'] = fields.pop('tags')
    if 'parent' in fields:
        parent = fields.pop('parent')
        record['parent_id'] = parent and next(r['id'] for r in api('GET', '/files/locations') if r['uid'] == parent)
    record['data'] = fields
    if location is None:
        api('POST', '/files', record, type=int(Type.FS_LOCATION))
    else:
        api('PUT', f"/files/{location.data['id']}", record)


def collection(**location_types: Any) -> Collection:
    """gppufs's Collection, the Lake, over Linked Data: its Locations read from it (catalog()) and their configuration written back
    into it (store()); gppu.fs.api serves it as /config and /lake."""
    return Collection(lambda: catalog(**location_types), store)


def here(catalog: GppuCatalog, uri: str) -> Path | None:
    """The folder on this host a location's file uri names, as the catalog's FileSystem reaches it (Drives in a Windows host's WSL);
    none when it names another host or is not a file uri."""
    try:
        return catalog.location_types['file']().local(uri)
    except ValueError:
        return None


def reached(catalog: GppuCatalog) -> dict[str, dict[str, str]]:
    """The folders on this host the catalog's locations are, as GppuFileSystem's locations map takes them: what addresses its entries."""
    return {full_path(path).as_posix(): {'location': uid, 'canonical': row['canonical']}
            for uid, row in catalog.locations.items() if (path := here(catalog, row['canonical'])) and path.is_dir()}


def filesystem(catalog: GppuCatalog, uid: str) -> GppuFileSystem:
    """The GppuFileSystem of a location this host reaches, its index beside it, `.<location-name>.gppufs.sqlite`: a listing reads the
    folder and keeps what gppufs's handlers read, a lookup answers from the index; each address its entries carry is the location's."""
    if (root := here(catalog, catalog.locations[uid]['canonical'])) is None:
        raise ValueError(f"{catalog.locations[uid]['canonical']}: {uid} is not on this host")
    return GppuFileSystem(str(root), locations=reached(catalog))
