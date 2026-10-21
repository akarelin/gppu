# Desktop filesystem

Requirements: [SPEC_desktop.md](SPEC_desktop.md).

- Complete: recover prior work and verify fsspec and Windows integration.
- Complete: implement and prove a desktop mount using gppufs navigation and reads.
- Complete: run the Lake mount and verify desktop browsing.
- Complete: implement coexisting physical and indexed views, including direct access to deep indexed files.
- Complete: verify live indexed reads and visible Directory Opus contents; document and publish the implementation.
- In progress: Alex's acceptance of the indexed desktop view; continue corrections until Alex says it is working.
- Complete: the sources are every location Linked Data knows that this host reaches, with `desktop.yaml`'s; their indexes and those of the folders directly inside them are under `Indexed`.
- Complete: Windows lists every file an index holds: ignored files left out, an archive member named without the chain's colons and given its time in seconds, a name cut to Windows' 255 characters at the end nearest the file.
- Open: the API region, the server's index through Linked Data and the Lake's API, joined with the local one; the Lake's API is not served until its stack exists.
