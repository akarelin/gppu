"""sessions-clean on gppufs: a finished Claude Code or Codex session in which no person typed anything moves into the archive,
with its subagents and the folder beside it. gppufs streams each harness's folder and its handlers read each session; this
decides where each goes as it arrives and shows it in its colour. Nothing moves without --run. The TUI launcher runs it in the
background from the manifest in sessions_clean.yaml."""
import asyncio
import os
import sys
import time
from collections import Counter
from pathlib import Path, PurePosixPath

from gppu import APP, glob
from gppu.fs.gppufs import GppuFileSystem
from gppu.fs.handlers import SessionHandler
from gppu.tui.progress import Marker, legend_ansi, marker_ansi

APP['cli'] = True
SESSION = ('session', *SessionHandler.UID)   # a session is probed as one and read as its harness's
COLOUR = sys.stdout.isatty() or bool(os.environ.get('FORCE_COLOR'))
MARKS = {   # where a session goes, as the row shows it
    'human': Marker('human', 'nothing typed by a person', '>', 'cyan', '36'),
    'orphan': Marker('orphan', 'subagents only', '?', 'magenta', '35'),
    'damaged': Marker('damaged', 'unreadable', '!', 'red', '31'),
    'active': Marker('active', 'written to within the window', '~', 'grey50', '90'),
}


def paint(code: str, text: str) -> str:
    return f'\x1b[{code}m{text}\x1b[0m' if COLOUR else text


def row(to: str, harness: str, hours: float, turns: int, text: str) -> None:
    mark = MARKS[to]
    age = f'{hours:.0f}h' if hours < 48 else f'{hours / 24:.0f}d'
    print(f'{marker_ansi(mark) if COLOUR else mark.symbol} {paint("34", harness.ljust(3))} {paint("90", f"{age:>4} {turns:>4}")} {text}', flush=True)


async def clean(fs: GppuFileSystem, base: str, keep: float) -> list[tuple[str, str]]:
    """Each session of a harness's folder as the listing gives it, and where it goes. A session changed within keep hours
    is not read and keeps its subagents; any other is read whole by its handler once, the index keeping it. A subagent
    goes where the session at the top of it went, which the listing gives before it."""
    went, parent, active, moves = {}, {}, set(), []
    async for entry in (entry async for _, _, files in fs._walk(base, detail=True) for entry in files.values()):
        if entry['type'] != 'file' or entry['gppu']['record']['type'] not in SESSION:
            continue
        path = entry['name']
        if any(os.path.isfile(f'{base}/{above}.jsonl') for above in PurePosixPath(path).relative_to(base).parents[:-1]):
            continue   # in a session's own folder, which moves with it
        hours = (time.time() - entry['mtime']) / 3600
        if hours < keep:
            active.add(PurePosixPath(path).stem)   # a harness names a session's file by its uid
            row('active', entry['gppu']['record']['type'], hours, 0, PurePosixPath(path).name)
            continue
        gppu = (await fs._info(path, refresh=True))['gppu']   # its handler reads it once; the index keeps what it read
        record = gppu.get('record') or {}
        data = record.get('data') or {}
        if gppu.get('unread'):
            to = 'damaged'
        elif data.get('subagent'):
            uid = parent[record['uid']] = record['meta'].get('parent_uid')
            while parent.get(uid):
                uid = parent[uid]   # a subagent's own subagents belong to the session at the top
            to = None if any(stem.endswith(uid or '?') for stem in active) else went.get(uid, 'orphan')
        else:
            to = went[record['uid']] = None if ' - ' in data['normalized_name'] else 'human'   # the handler names a session by what a person typed in it, when anyone did
        if to is not None:
            row(to, record['type'], hours, data.get('turns') or 0, gppu.get('unread') or data.get('normalized_name') or PurePosixPath(path).name)
            moves.append((to, PurePosixPath(path).relative_to(base).as_posix()))
    return moves


def main() -> None:
    run, keep = glob('run') is True, float(glob('keep_hours'))
    home, archive = Path(glob('home')).expanduser(), Path(glob('archive'))
    # The harnesses watch their folders and a sync client holds the archive's files: no index file in either.
    fs = GppuFileSystem(cache=[*((home / folder).as_posix() for folder in glob('sessions')), archive.as_posix()])
    print(legend_ansi(tuple(MARKS.values())) if COLOUR else '  '.join(f'{m.symbol}={m.label}' for m in MARKS.values()))
    going = Counter()
    for folder in glob('sessions'):
        base = (home / folder).as_posix()
        print(paint('1', base), flush=True)
        moves = asyncio.run(clean(fs, base, keep))
        going.update(to for to, _ in moves)
        if run:
            for to, path in moves:
                for entry in (path, str(PurePosixPath(path).with_suffix(''))):   # Claude Code keeps a session's other files in a folder by its uid
                    if fs.exists(f'{base}/{entry}'):
                        there = (archive / glob(f'buckets/{to}') / folder / entry).as_posix()
                        fs.makedirs(str(PurePosixPath(there).parent), exist_ok=True)
                        fs.mv(f'{base}/{entry}', there, recursive=True)
    summary = ' '.join(f'{to}={going[to]}' for to in ('human', 'orphan', 'damaged'))
    print(paint('32', f'{summary}, moved into {archive}' if run else f'{summary}, nothing moved: --run moves them'))


if __name__ == '__main__':
    main()
