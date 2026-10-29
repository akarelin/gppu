"""sessions-clean on gppufs: a finished Claude Code or Codex session in which no person typed anything moves into the archive,
with its subagents and the folder beside it. gppufs streams each harness's folder and its handlers read each session; this
decides where each goes as it arrives. Nothing moves without --run."""
import asyncio
import os
import sys
import time
from pathlib import Path, PurePosixPath

from gppu import Env, glob
from gppu.fs.gppufs import GppuFileSystem
from gppu.fs.handlers import SessionHandler

SESSION = ('session', *SessionHandler.UID)   # a session is probed as one and read as its harness's


async def clean(folder: str, keep: float) -> list[tuple[str, str]]:
    """Each session of a harness's folder as the listing gives it, and where it goes. A session changed within keep hours
    is not read and keeps its subagents; any other is read whole by its handler once, the index keeping it. A subagent
    goes where the session at the top of it went, which the listing gives before it."""
    fs = GppuFileSystem(cache=False)   # the harness watches its folder: no index file in it
    base = (Path(glob('home')).expanduser() / folder).as_posix()
    went, parent, active, moves = {}, {}, set(), []
    async for row in fs.ls_iter(base):
        if row['type'] != 'file' or row['gppu']['record']['type'] not in SESSION:
            continue
        path = row['name']
        if any(os.path.isfile(f'{base}/{above}.jsonl') for above in PurePosixPath(path).relative_to(base).parents[:-1]):
            continue   # in a session's own folder, which moves with it
        hours = (time.time() - row['mtime']) / 3600
        if hours < keep:
            active.add(PurePosixPath(path).stem)   # a harness names a session's file by its uid
            continue
        gppu = (await fs.info(path, refresh=True))['gppu']   # its handler reads it once; the index keeps what it read
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
            print(f'{to:8} {hours:7.0f}h {data.get("turns") or 0:5} turns {folder} {path} {gppu.get("unread") or ""}')
            moves.append((to, PurePosixPath(path).relative_to(base).as_posix()))
    return moves


def main() -> None:
    Env.from_env(name='sessions_clean', config=Path(__file__).with_suffix('.yaml'))
    Env.from_argv(sys.argv[1:])
    run, keep = glob('run') is True, float(glob('keep_hours'))
    for folder in glob('sessions'):
        moves = asyncio.run(clean(folder, keep))
        if run:
            fs, archive = GppuFileSystem(cache=False), GppuFileSystem()
            base = (Path(glob('home')).expanduser() / folder).as_posix()
            for to, path in moves:
                for entry in (path, str(PurePosixPath(path).with_suffix(''))):   # Claude Code keeps a session's other files in a folder by its uid
                    if fs.exists(f'{base}/{entry}'):
                        fs.move_into(archive, f'{base}/{entry}', (Path(glob('archive')) / glob(f'buckets/{to}') / folder / entry).as_posix())
    print('moved' if run else 'nothing moved: --run moves them')


if __name__ == '__main__':
    main()
