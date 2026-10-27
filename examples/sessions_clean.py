"""sessions-clean on gppufs: a finished Claude Code or Codex session in which no person typed anything moves into the archive,
with its subagents and the folder beside it. gppufs lists each harness's folder, its handlers reading every session, and moves
what goes; this only decides where it goes. Nothing moves without --run."""
import sys
import time
from pathlib import Path, PurePosixPath

from gppu import Env, glob
from gppu.fs.gppufs import GppuFileSystem


def sessions(fs: GppuFileSystem) -> dict[str, dict]:
    """The sessions gppufs lists in a harness's folder, each with its own entries and its subagents', by the session's uid."""
    found = {}
    for row in fs.ls('', recurse=True, refresh=True):
        record = row['gppu'].get('record') or {}
        if record.get('uid') is None and not row['gppu'].get('unread') or row['type'] != 'file':
            continue
        path = fs._key(row['name'])
        subagent = (record.get('data') or {}).get('subagent')
        uid = record['meta'].get('parent_uid') if subagent else record.get('uid') or PurePosixPath(path).stem
        session = found.setdefault(uid, {'paths': [], 'root': False, 'typed': False, 'unread': None, 'modified': 0.0})
        session['paths'].append(path)
        session['unread'] = session['unread'] or row['gppu'].get('unread')
        session['modified'] = max(session['modified'], row['mtime'])
        if not subagent and record.get('uid'):
            session['root'] = True
            session['typed'] |= ' - ' in record['data']['normalized_name']   # the handler names a session by what a person typed in it, when anyone did
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
        fs = GppuFileSystem(Path(glob('home')).expanduser() / folder)
        archive = {to: GppuFileSystem(Path(glob('archive')) / glob(f'buckets/{to}') / folder) for to in ('human', 'orphan', 'damaged')}
        for uid, session in sorted(sessions(fs).items()):
            hours = (time.time() - session['modified']) / 3600
            if (to := bucket(session)) is None or hours < keep:
                continue
            print(f'{to:8} {hours:7.0f}h {folder} {uid} {session["unread"] or ""}')
            if run:
                for path in session['paths']:
                    for entry in (path, str(PurePosixPath(path).with_suffix(''))):   # Claude Code keeps a session's other files in a folder by its uid
                        if fs.exists(entry):
                            fs.move_into(archive[to], entry, entry)
    print('moved' if run else 'nothing moved: --run moves them')


if __name__ == '__main__':
    main()
