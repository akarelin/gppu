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
    listing probes, reading nothing; a session changed within keep hours is not read, and holds every session named after
    it; each other is read whole by its handler once, the index keeping it."""
    found, active, read, parent = {}, [], [], {}
    rows = {fs._key(row['name']): row for row in fs.ls('', recurse=True) if row['type'] == 'file'}
    for path, row in rows.items():
        if row['gppu']['record']['type'] not in ('session', *SessionHandler.UID):
            continue   # a session is probed as one and read as its harness's
        if any(f'{folder}.jsonl' in rows for folder in PurePosixPath(path).parents):
            continue   # in a session's own folder, which moves with it
        hours = (time.time() - row['mtime']) / 3600
        if hours < keep:
            active.append(PurePosixPath(path).stem)
            continue
        parsed = fs.info(path, refresh=True)['gppu']   # its handler reads it once; the index keeps what it read
        record, unread = parsed.get('record') or {}, parsed.get('unread')
        subagent = (record.get('data') or {}).get('subagent')
        if subagent and record.get('uid'):
            parent[record['uid']] = record['meta'].get('parent_uid')
        read.append((path, record, unread, hours, subagent))
    for path, record, unread, hours, subagent in read:
        uid = (record['meta'].get('parent_uid') if subagent else record.get('uid')) or path
        while uid in parent and parent[uid]:
            uid = parent[uid]   # a subagent's own subagents belong to the session at the top
        session = found.setdefault(uid, {'paths': [], 'root': False, 'typed': False, 'unread': None, 'hours': hours, 'turns': 0})
        session['paths'].append(path)
        session['unread'] = session['unread'] or unread
        session['hours'] = min(session['hours'], hours)
        session['turns'] += (record.get('data') or {}).get('turns') or 0
        if record.get('uid') and not subagent:
            session['root'] = True
            session['typed'] |= ' - ' in record['data']['normalized_name']   # the handler names a session by what a person typed in it, when anyone did
    return {uid: session for uid, session in found.items() if not any(stem.endswith(uid) for stem in active)}   # a harness names a session's file by its uid


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
            print(f'{to:8} {session["hours"]:7.0f}h {session["turns"]:5} turns {folder} {uid} {session["unread"] or ""}')
            if run:
                for path in session['paths']:
                    for entry in (path, str(PurePosixPath(path).with_suffix(''))):   # Claude Code keeps a session's other files in a folder by its uid
                        if fs.exists(entry):
                            fs.move_into(archive[to], entry, entry)
    print('moved' if run else 'nothing moved: --run moves them')


if __name__ == '__main__':
    main()
