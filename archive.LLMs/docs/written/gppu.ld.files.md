<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/ld/files.py 0590dcfc1d39e6273e8237013121fd7407a5f7c2 -->
## Overview

`gppu.ld.files` is Linked Data's files API. It serves the file systems Alex runs as gppufs (`gppu.fs`) reads and configures them. Linked Data holds what gppufs is configured with and where its indexes are. The files themselves stay in gppufs's indexes, not in records. The API is served at `/ld/v1/files`, with its documentation at `/ld/v1/files/docs`.

## Classes and the API

The module defines four record types, each a table in Linked Data. `FSNode` is the base of every file system type. `FSLocation` is a place files are reached: a root location holds a connection and its Provider, with the connection's parameters in `data.handler`, and has no parent. Every other location sits inside the location above it. `FSFile` is one file as a single thing, wherever its copies are, and is what other records refer to. `FSIndex` is a pointer to one gppufs index, the SQLite file beside a location or inside an archive.

`app` is the API object. It is built with `api_at` and `operations` and mounted at `/files`, where each of the four types is created, read, updated and searched. gppufs builds its catalog from the locations (see `gppu.ld.gppufs`). Credentials are not stored in these records. A Provider reads them where it declares them.

## Use

A program imports the record types it works with, and the API object `app`, from the module:

```python
from gppu.ld.files import FSNode, FSLocation, FSFile, FSIndex, app

# app is the files API, served by Linked Data at /ld/v1/files
```
