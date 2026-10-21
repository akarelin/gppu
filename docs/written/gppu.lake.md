<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/lake.py afd3cf1388c0b05d8634cdfd617a6aa139ff8188 -->
gppu.lake is the Lake, a store where an object is saved without a uri. The Lake decides where the object is kept and answers with the uri it stored it at, and an object is retrieved later by that uri. Linked Data and the Lake keep separate APIs, `/ld` and `/lake`. A UI lists the Lake through the Lake's API, never through the file system or gppufs.

The Lake's locations come from Linked Data's catalog, which `gppu.ld.gppufs.catalog()` makes. The Lake's own configuration comes from the app's Env: the uri that saved objects are stored in, and the layout templates, one for each type of record that gppu's handlers read, with `source` for any other type.

`Lake` is the class a program works with. It is built over a catalog, a store folder and the templates. `save()` reads the object with gppu's handlers, places it by the template for its record type, writes it below the store and refreshes the gppufs index of that folder. `read()` and `place()` are the two steps `save()` runs, one for the record and one for the path. `retrieve()`, `ls()`, `walk()`, `info()`, `open()` and `delete()` each take a uri, find the location that holds it and act there. `ls()` and `info()` answer a uri inside the store from its gppufs index.

`api(lake)` wraps a Lake as a FastAPI app, which an `APIApp` serves at `/lake`. It needs FastAPI, installed with the `ld` extra. POST saves the request body, GET inspects, lists, walks, retrieves or reads the bytes at a uri, and DELETE removes the object. A uri that no location holds answers 404, a save to a place another object holds answers 409, and a value the Lake refuses answers 400.

`LakeFileSystem` is the Lake through its API as an fsspec filesystem, with paths relative to a root uri, so a desktop or a UI can browse it. It is read-only. `ls`, `info` and `open` work, and opening for writing raises `PermissionError`. Saving goes through the API's POST.

## Use

```python
from gppu.fs import DataObject
from gppu.lake import Lake

lake = Lake(catalog, store, templates)   # catalog from gppu.ld.gppufs.catalog(); store and templates from the app's Env
uri = lake.save(DataObject(source, content, None, 'file', name))   # source is the uri the object came from; the answer is where the Lake stored it
obj = lake.retrieve(uri)                 # the object at uri with its content
```
