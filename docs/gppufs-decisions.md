# gppufs: rulings it is built on

Alex's rulings that the gppufs rework rests on, each with where he said it. The questions this file used to ask were withdrawn: they were already answered in his sessions, and they rested on the agent's own unverified statements.

- **gppufs reaches the catalog.** With a catalog, gppufs lists and opens through it what it holds no index for, SharePoint and archives among them; without it, `ls` and the desktop never reach them. (This session, 2026-10-28.)
- **Writes go through the APIs.** All writes to Linked Data records, from FileIndexer, gppufs, Session Manager and importers, go through the REST API's structured CRUD, never direct database writes; bulk needs are met by how the API is designed. "I don't like the idea of direct database writes. Only structured CRUD." (2026-10-10.)
- **Objects are saved by uri.** "Containers do not write digital objects. Objects are retrieved and saved by uri." (2026-09-23.) The Lake decides where an object goes and answers with its uri; a program that copies an object itself, as the session hook does, asks the Lake where it goes and has the Lake index it.
- **Do not pollute the Lake.** The Lake holds only session copies that match their transcripts byte for byte. (2026-10-01.)
- **Refresh is gppufs's own.** It is not a question for Alex: gppufs re-reads what is not read as it is now, never follows a link or a junction, lists an ignored folder without entering it, and enters an archive only when the archive itself is refreshed.

## The Lake after this rework

- The Lake service reads Linked Data's location records and gives them to the catalog: `catalog(records)` for the locations, `Catalog(dsn, records)` for the Lake catalog behind `/lake/catalog`.
- The Lake names its rows by its own uris and lists through the process's one gppufs.
- How each user of gppufs moves is in [gppufs-users.md](gppufs-users.md).
