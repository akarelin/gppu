"""gppu.fs — provider: gppufs. Moves here unchanged from gppu/fs.py: DataObject, Container, Location, Collection,
FileSystem, the Handlers, GppuFileSystem, GppuCatalog, PostgresFileSystem, SharePointFileSystem.

One change: its Provider subclasses core ``gppu.Provider``, which now holds only what every Connection has (scheme,
uid, parameters, close). The object methods — ls, info, open, read, write, delete, walk, refresh, locations — stay
here on the fs Provider. GppuCatalog reads its connections through ``gppu.connections`` instead of resolving the
``connections`` table itself, so a Location's Connection and an app's Connection are the same instance.
"""
