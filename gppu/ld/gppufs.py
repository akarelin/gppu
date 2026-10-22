r"""gppufs on Linked Data: gppu.fs as it is, what it is configured with kept by Linked Data's files API (gppu.ld.files) and reached
through it only, at the address the caller gives connect(); its files in gppufs's own index, the distributed index beside each location
(Linked Data - gppufs: "Files stay in gppufs's indexes; they are not Linked Data records"). The app using it loads its own
configuration into gppu's Env: `drives`, where a Windows host's WSL mounts its drives, is read from it (Drives).

  catalog()     gppu.fs.GppuCatalog made from GET /files' locations: every location in use, each reached over its root location's
                handler, its connection. Its Providers are gppufs's own, FileSystem for file://, and those a caller gives, as
                GppuCatalog takes them: the Locations and Containers FileIndexer and every gppufs user reach files through
  filesystem()  the GppuFileSystem of a location this host reaches, its index beside it: a listing reads the folder and keeps what
                gppufs's handlers read there, a lookup answers from it"""
import socket
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import httpx

from . import Type
from ..fs import FileSystem, GppuCatalog, GppuFileSystem
from ..app import glob
from ..gppu import full_path

client: httpx.Client   # the API, opened by connect()
NOT_IN_USE = ('discarded', 'rejected', 'archived')   # the statuses of a location not in use (# States)


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
    """gppufs's catalog of Linked Data's locations (GET /files, its fs_location records): every location in use that has a uid and a
    canonical uri, the two a gppufs Location is known and reached by, as a row of gppufs's configuration table, its data with its id,
    name, parent's uid and tags. A location in use is not discarded, rejected or archived, inside locations that are in use too, since
    a location is part of the location above it; its connection is its root location, whose data.handler holds the connection's
    parameters. location_types are the Providers a caller adds by scheme, as GppuCatalog takes them; gppufs's FileSystem reaches
    file://, and in a Windows host's WSL, Drives does."""
    records = {r['id']: r for r in api('GET', '/files', type=int(Type.FS_LOCATION))['items']
               if r['status'] not in NOT_IN_USE and r['data'].get('uid') and r['data'].get('canonical')}

    def root(r: dict) -> dict | None:
        """The root location above it; none when one above it is not in use, so it is not in use either."""
        while r['parent_id']:
            if not (r := records.get(r['parent_id'])):
                return None
        return r
    rows = [r['data'] | {'id': r['id'], 'name': r['name'], 'parent': r['parent_id'] and records[r['parent_id']]['data']['uid'],
                         'connection': top['data']['uid']} | ({'tags': r['meta']['tags']} if 'tags' in r['meta'] else {})
            for r in records.values() if (top := root(r))]
    roots = [r for r in rows if r['connection'] == r['uid']]
    if missing := [r['uid'] for r in roots if r.get('handler') is None]:
        raise ValueError(f'root locations without a handler, their connection: {", ".join(missing)}')
    return GppuCatalog({'locations': rows, 'connections': {r['uid']: r['handler'] for r in roots}}, location_types=location_types)


def here(catalog: GppuCatalog, uri: str) -> Path | None:
    """The folder on this host a location's file uri names, as the catalog's FileSystem reaches it (Drives in a Windows host's WSL);
    none when it names another host or is not a file uri. Which host is decided from the uri alone, as FileIndexer 0.1.3 decided it:
    another host's share is that host's location, and asking it from here waits out the network for every share that does not
    answer."""
    if urlsplit(uri).netloc.casefold() not in ('', socket.gethostname().split('.')[0].casefold()):
        return None
    try:
        return catalog.location_types['file']().local(uri)
    except ValueError:
        return None


def reached(catalog: GppuCatalog) -> dict[str, dict[str, str]]:
    """The folders on this host the catalog's locations are, as GppuFileSystem's locations map takes them: what addresses its entries.
    Each is looked for once, so a caller reads it once and gives it to filesystem()."""
    return {full_path(path).as_posix(): {'location': uid, 'canonical': row['canonical']}
            for uid, row in catalog.locations.items() if (path := here(catalog, row['canonical'])) and path.is_dir()}


def filesystem(catalog: GppuCatalog, uid: str, folders: dict[str, dict[str, str]]) -> GppuFileSystem:
    """The GppuFileSystem of a location this host reaches, its index beside it, `.<location-name>.gppufs.sqlite`: a listing reads the
    folder and keeps what gppufs's handlers read, a lookup answers from the index; each address its entries carry is the location's,
    from folders, what reached() found."""
    if (root := here(catalog, catalog.locations[uid]['canonical'])) is None:
        raise ValueError(f"{catalog.locations[uid]['canonical']}: {uid} is not on this host")
    return GppuFileSystem(str(root), locations=folders)
