"""sessions-clean on gppufs: a finished Claude Code or Codex session in which no person typed anything moves into the archive,
with its subagents and the folder beside it. gppufs lists each harness's folder, its handlers reading every session, and moves
what goes; this only decides where it goes. Nothing moves without --run."""
import sys
import time
from pathlib import Path, PurePosixPath

from gppu import Env, glob
from gppu.fs.gppufs import GppuFileSystem
from gppu.fs.handlers import SessionHandler


def sessions(fs: GppuFileSystem, keep: float) -> dict[str, dict]:
    """The finished sessions in a harness's folder, each with its files and its subagents', by the session's uid. The
    listing probes, reading nothing; a session is read only from its start to the first line a person typed."""
    found = {}
    rows = {fs._key(row['name']): row for row in fs.ls('', recurse=True) if row['type'] == 'file'}
    for path, row in rows.items():
        if row['gppu']['record']['type'] != 'session':
            continue
        if any(f'{folder}.jsonl' in rows for folder in PurePosixPath(path).parents):
            continue   # in a session's own folder, which moves with it
        hours = (time.time() - row['mtime']) / 3600
        if hours < keep:
            continue
        try:
            record, unread = SessionHandler.probe(fs._path(path)), None
        except Exception as error:   # what cannot be read is a damaged session
            record, unread = None, f'{type(error).__name__}: {error}'
        subagent = record is not None and record.data['subagent']
        uid = record.meta.get('parent_uid') if subagent else (record and record.uid) or path
        session = found.setdefault(uid, {'paths': [], 'root': False, 'typed': False, 'unread': None, 'hours': hours})
        session['paths'].append(path)
        session['unread'] = session['unread'] or unread
        session['hours'] = min(session['hours'], hours)
        if record is not None and not subagent:
            session['root'] = True
            session['typed'] |= bool(record.data['topic'])
    return found


def bucket(session: dict) -> str | None:
    """Where a finished session goes, or None when a person typed in it."""
    if session['unread']:
        return 'damaged'
    if not session['root']:
        return 'orphan'
    return None if session['typed'] else 'human'


def main() -> None:
    Env.from_env(name='sessions_clean', config=Path(__file__).with_suffix('.yaml'))
    Env.from_argv(sys.argv[1:])
    run, keep = glob('run') is True, float(glob('keep_hours'))
    for folder in glob('sessions'):
        fs = GppuFileSystem(Path(glob('home')).expanduser() / folder, cache=False)   # the harness watches its folder: no index file in it
        archive = {to: GppuFileSystem(Path(glob('archive')) / glob(f'buckets/{to}') / folder) for to in ('human', 'orphan', 'damaged')}
        for uid, session in sorted(sessions(fs, keep).items()):
            if (to := bucket(session)) is None:
                continue
            print(f'{to:8} {session["hours"]:7.0f}h {folder} {uid} {session["unread"] or ""}')
            if run:
                for path in session['paths']:
                    for entry in (path, str(PurePosixPath(path).with_suffix(''))):   # Claude Code keeps a session's other files in a folder by its uid
                        if fs.exists(entry):
                            fs.move_into(archive[to], entry, entry)
    print('moved' if run else 'nothing moved: --run moves them')


if __name__ == '__main__':
    main()
