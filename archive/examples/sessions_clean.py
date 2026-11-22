# .. archived 2026-11-22: what gppu's reduction removed from examples/sessions_clean.py, as it was last


# .. from fec31bb
def main() -> None:
    app = App(config=__file__, argv=sys.argv[1:])   # .. its own configuration is its MANIFEST, the command line over it
    run, keep = app.my('run') is True, float(app.my('keep_hours'))
    home, archive = Path(app.my('home')).expanduser(), Path(app.my('archive'))
    # .. The harnesses watch their folders and a sync client holds the archive's files: no index file in either.
    fs = GppuFileSystem(cache=[*((home / folder).as_posix() for folder in app.my('sessions')), archive.as_posix()])
    print(legend_ansi(tuple(MARKS.values())) if COLOUR else '  '.join(f'{m.symbol}={m.label}' for m in MARKS.values()))
    going = Counter()
    for folder in app.my('sessions'):
        base = (home / folder).as_posix()
        print(paint('1', base), flush=True)
        moves = asyncio.run(clean(fs, base, keep))
        going.update(to for to, _ in moves)
        if run:
            for to, path in moves:
                for entry in (path, str(PurePosixPath(path).with_suffix(''))):   # .. Claude Code keeps a session's other files in a folder by its uid
                    if fs.exists(f'{base}/{entry}'):
                        there = (archive / app.my(f'buckets/{to}') / folder / entry).as_posix()
                        fs.makedirs(str(PurePosixPath(there).parent), exist_ok=True)
                        fs.mv(f'{base}/{entry}', there, recursive=True)
    summary = ' '.join(f'{to}={going[to]}' for to in ('human', 'orphan', 'damaged'))
    print(paint('32', f'{summary}, moved into {archive}' if run else f'{summary}, nothing moved: --run moves them'))
