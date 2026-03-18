"""
OneDrive for Business Sync Diagnostics TUI.

Reads SyncDiagnostics.log, the sync engine database, and download queue
to surface stuck files, postponed changes, and overall sync health.
Supports multiple accounts/tenants with tabbed view.
Uses gppu Env for configuration.

Usage:
    python w11-onedrive.py                     # interactive mode selector
    python w11-onedrive.py diag                # sync diagnostics
    python w11-onedrive.py diag --watch        # auto-refresh
    python w11-onedrive.py conflicts           # conflict analysis
    python w11-onedrive.py conflicts --hostname Mailstore
    python w11-onedrive.py dbexplore           # explore sync DB, dump report
    python w11-onedrive.py dbexplore --output . # save report to current dir
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import struct
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from gppu import Env
from gppu.tui import TUIApp, StatusHeader
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.binding import Binding
from textual.widgets import (
    Button, Checkbox, DataTable, Footer, Input, RichLog, Static,
    TabbedContent, TabPane,
)


# ── Paths ────────────────────────────────────────────────────────────────────

def od_base() -> Path:
    return Path(os.environ['LOCALAPPDATA']) / 'Microsoft' / 'OneDrive'


def logs_dir(account: str) -> Path:
    return od_base() / 'logs' / account


def settings_dir(account: str) -> Path:
    return od_base() / 'settings' / account


def sync_diag_path(account: str) -> Path:
    return logs_dir(account) / 'SyncDiagnostics.log'


def discover_accounts() -> list[str]:
    """Find all account folders that have a SyncDiagnostics.log."""
    logs = od_base() / 'logs'
    if not logs.exists():
        return []
    accounts = []
    for p in sorted(logs.iterdir()):
        if p.is_dir() and (p / 'SyncDiagnostics.log').exists():
            accounts.append(p.name)
    return accounts


def user_folder(account: str) -> str | None:
    """Read OneDrive sync root from registry."""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             rf'Software\Microsoft\OneDrive\Accounts\{account}')
        val, _ = winreg.QueryValueEx(key, 'UserFolder')
        return val
    except OSError:
        return None


def user_email(account: str) -> str | None:
    """Read account email from registry."""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             rf'Software\Microsoft\OneDrive\Accounts\{account}')
        val, _ = winreg.QueryValueEx(key, 'UserEmail')
        return val
    except OSError:
        return None


def onedrive_exe_path() -> str | None:
    """Find OneDrive.exe path from registry or known locations."""
    import winreg
    # Try registry first
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r'Software\Microsoft\OneDrive')
        val, _ = winreg.QueryValueEx(key, 'OneDriveTrigger')
        if os.path.exists(val):
            return val
    except OSError:
        pass
    # Known paths
    for candidate in [
        r'C:\Program Files\Microsoft OneDrive\OneDrive.exe',
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'OneDrive', 'OneDrive.exe'),
    ]:
        if os.path.exists(candidate):
            return candidate
    return None


# ── SyncDiagnostics parser ───────────────────────────────────────────────────

HEALTH_FIELDS = {
    'syncStallDetected':      ('Sync stall detected',       '0'),
    'scanStateStallDetected': ('Scan stall detected',       '0'),
    'numFileFailedDownloads': ('Failed downloads',          '0'),
    'numFileFailedUploads':   ('Failed uploads',            '0'),
    'conflictsFailed':        ('Failed conflicts',          '0'),
    'numResyncs':             ('Resyncs',                   '0'),
}

PROGRESS_FIELDS = [
    'ChangesToProcess', 'ChangesToSend',
    'FilesToDownload', 'FilesToUpload',
    'BytesToDownload', 'BytesDownloaded',
    'BytesToUpload', 'BytesUploaded',
    'DownloadSpeedBytesPerSec', 'UploadSpeedBytesPerSec',
    'EstTimeRemainingInSec', 'SyncProgressState',
    'scanState', 'drivesChangeEnumPending',
]

INFO_FIELDS = [
    'files', 'folders', 'uptimeSecs', 'placeholdersEnabled',
    'clientVersion', 'pid', 'numDrives',
    'bytesAvailableOnDiskDrive', 'totalSizeOfDiskDrive',
]


def parse_sync_diag(account: str) -> dict:
    """Parse SyncDiagnostics.log into a flat dict."""
    path = sync_diag_path(account)
    if not path.exists():
        return {}
    data = {}
    try:
        text = path.read_text(encoding='utf-8-sig')
    except OSError:
        return {}
    for line in text.splitlines():
        if '=' in line:
            key, _, val = line.partition('=')
            data[key.strip()] = val.strip()
    return data


# ── Downloads queue parser ───────────────────────────────────────────────────

def parse_downloads_queue(account: str) -> list[str]:
    """Read file IDs from downloads3.txt (UTF-16LE, locked by OneDrive)."""
    src = settings_dir(account) / 'downloads3.txt'
    if not src.exists():
        return []
    tmp = Path(os.environ['TEMP']) / f'od_downloads3_{account}_copy.txt'
    try:
        shutil.copy2(src, tmp)
    except OSError:
        # File locked — try reading with shared access
        try:
            import ctypes
            import ctypes.wintypes as wt
            GENERIC_READ = 0x80000000
            FILE_SHARE_READ = 1
            FILE_SHARE_WRITE = 2
            FILE_SHARE_DELETE = 4
            OPEN_EXISTING = 3
            h = ctypes.windll.kernel32.CreateFileW(
                str(src), GENERIC_READ,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                None, OPEN_EXISTING, 0, None)
            if h == -1:
                return []
            size = os.path.getsize(src)
            buf = ctypes.create_string_buffer(size)
            read = wt.DWORD()
            ctypes.windll.kernel32.ReadFile(h, buf, size, ctypes.byref(read), None)
            ctypes.windll.kernel32.CloseHandle(h)
            content = buf.raw[:read.value].decode('utf-16-le', errors='replace')
        except Exception:
            return []
    else:
        try:
            raw = tmp.read_bytes()
            # Strip BOM if present
            if raw[:2] == b'\xff\xfe':
                raw = raw[2:]
            content = raw.decode('utf-16-le', errors='replace')
        except OSError:
            return []

    lines = [l.strip() for l in content.splitlines() if l.strip()]
    return lines


# ── Sync database queries ────────────────────────────────────────────────────

def copy_sync_db(account: str) -> Path | None:
    """Copy SyncEngineDatabase.db (+wal/shm) to temp for safe reading."""
    src = settings_dir(account) / 'SyncEngineDatabase.db'
    if not src.exists():
        return None
    dst = Path(os.environ['TEMP']) / f'od_SyncEngineDB_{account}_copy.db'
    try:
        shutil.copy2(src, dst)
        for ext in ('-wal', '-shm'):
            s = Path(str(src) + ext)
            if s.exists():
                shutil.copy2(s, Path(str(dst) + ext))
    except OSError:
        return None
    return dst


def query_stuck_downloads(db_path: Path, download_ids: list[str]) -> list[dict]:
    """Look up download queue IDs in ClientFile_Records."""
    if not download_ids or not db_path:
        return []
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    results = []
    for raw_id in download_ids:
        # Extract the file resource ID (first hex block before any URL/suffix)
        parts = raw_id.split()
        if not parts:
            continue
        file_id = parts[0].rstrip('+0123456789')
        if len(file_id) < 20:
            # Might be a scope ID line, skip
            continue
        try:
            cur.execute(
                'SELECT resourceID, fileName, parentResourceID, size '
                'FROM od_ClientFile_Records WHERE resourceID LIKE ?',
                (file_id + '%',))
            for row in cur.fetchall():
                folder = resolve_folder(cur, row[2])
                results.append({
                    'resourceID': row[0],
                    'fileName': row[1],
                    'folder': folder,
                    'size': row[3] or 0,
                    'raw_queue': raw_id[:80],
                })
        except sqlite3.Error:
            pass
    conn.close()
    return results


def query_postponed_changes(db_path: Path) -> list[dict]:
    """Get postponed file changes sorted by retry count."""
    if not db_path:
        return []
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    results = []
    try:
        cur.execute(
            'SELECT resourceID, fileName, changeType, postponedCount, '
            'flags, parentResourceID, size '
            'FROM od_ClientFilePostponedChange_Records '
            'ORDER BY postponedCount DESC')
        for row in cur.fetchall():
            folder = resolve_folder(cur, row[5])
            results.append({
                'resourceID': row[0],
                'fileName': row[1],
                'changeType': row[2],
                'postponedCount': row[3],
                'flags': row[4],
                'folder': folder,
                'size': row[6] or 0,
            })
    except sqlite3.Error:
        pass
    conn.close()
    return results


def query_hydration_data(db_path: Path) -> list[dict]:
    """Get active hydrations."""
    if not db_path:
        return []
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    results = []
    try:
        cur.execute(
            'SELECT resourceID, firstHydrationTime, lastHydrationTime, '
            'hydrationCount, lastHydrationType FROM od_HydrationData')
        for row in cur.fetchall():
            # Try to resolve file name
            rid = row[0]
            name = ''
            try:
                cur.execute(
                    'SELECT fileName FROM od_ClientFile_Records '
                    'WHERE resourceID = ?', (rid,))
                r2 = cur.fetchone()
                if r2:
                    name = r2[0]
            except sqlite3.Error:
                pass
            results.append({
                'resourceID': rid,
                'fileName': name,
                'firstHydration': format_epoch(row[1]),
                'lastHydration': format_epoch(row[2]),
                'count': row[3],
                'type': row[4],
            })
    except sqlite3.Error:
        pass
    conn.close()
    return results


def resolve_folder(cur: sqlite3.Cursor, resource_id: str | None) -> str:
    """Walk parent chain in ClientFolder_Records to build path."""
    parts = []
    current = resource_id
    seen = set()
    while current and current not in seen:
        seen.add(current)
        try:
            cur.execute(
                'SELECT folderName, parentResourceID '
                'FROM od_ClientFolder_Records WHERE resourceID = ?',
                (current,))
            row = cur.fetchone()
            if row and row[0]:
                parts.insert(0, row[0])
                current = row[1]
            else:
                break
        except sqlite3.Error:
            break
    return '/'.join(parts) if parts else '(unknown folder)'


def query_scope_info(db_path: Path) -> list[dict]:
    """Get all synced scopes (libraries) with URLs and types."""
    if not db_path:
        return []
    LIBRARY_TYPES = {0: 'Personal', 1: 'SharedWithMe', 2: 'ODB', 4: 'SPDocLib'}
    SCOPE_TYPES = {3: 'ODB root', 6: 'SPO library'}
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    results = []
    try:
        cur.execute(
            'SELECT scopeID, scopeType, libraryType, webURL, '
            'selectiveSyncEnabled, lastProcessedChange '
            'FROM od_ScopeInfo_Records')
        for row in cur.fetchall():
            # Resolve library name from URL path
            url = row[3] or ''
            lib_name = url.rstrip('/').rsplit('/', 1)[-1] if url else ''
            results.append({
                'scopeID': row[0],
                'scopeType': SCOPE_TYPES.get(row[1], str(row[1])),
                'libraryType': LIBRARY_TYPES.get(row[2], str(row[2])),
                'webURL': url,
                'libName': lib_name,
                'selectiveSync': bool(row[4]) if row[4] is not None else None,
                'lastProcessedChange': row[5] or '',
            })
    except sqlite3.Error:
        pass
    conn.close()
    return results


def query_service_history(db_path: Path, limit: int = 30) -> list[dict]:
    """Get recent service operations, especially errors."""
    if not db_path:
        return []
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    results = []
    try:
        cur.execute(
            'SELECT timestamp, scopeId, operationName, resultCode, '
            'sizeInBytes, scenarioName '
            'FROM od_ServiceOperationHistory ORDER BY id DESC LIMIT ?',
            (limit,))
        for row in cur.fetchall():
            results.append({
                'time': format_epoch(row[0]),
                'scopeID': row[1],
                'operation': row[2],
                'resultCode': row[3],
                'size': int(row[4]) if row[4] else 0,
                'scenario': row[5] or '',
            })
    except sqlite3.Error:
        pass
    conn.close()
    return results


def query_file_folder_counts(db_path: Path) -> tuple[int, int]:
    """Get total file and folder counts from the database."""
    if not db_path:
        return 0, 0
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    files = folders = 0
    try:
        cur.execute('SELECT COUNT(*) FROM od_ClientFile_Records')
        files = cur.fetchone()[0]
    except sqlite3.Error:
        pass
    try:
        cur.execute('SELECT COUNT(*) FROM od_ClientFolder_Records')
        folders = cur.fetchone()[0]
    except sqlite3.Error:
        pass
    conn.close()
    return files, folders


def query_postponed_folder_changes(db_path: Path) -> list[dict]:
    """Get postponed folder changes."""
    if not db_path:
        return []
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    results = []
    try:
        cur.execute(
            'SELECT resourceID, folderName, changeType, postponedCount, '
            'flags, parentResourceID '
            'FROM od_ClientFolderPostponedChange_Records '
            'ORDER BY postponedCount DESC')
        for row in cur.fetchall():
            folder = resolve_folder(cur, row[5])
            results.append({
                'resourceID': row[0],
                'folderName': row[1],
                'changeType': row[2],
                'postponedCount': row[3],
                'flags': row[4],
                'parentFolder': folder,
            })
    except sqlite3.Error:
        pass
    conn.close()
    return results


SYNC_PROGRESS_BITS = {
    0: 'Syncing',
    16: 'ScanInProgress',
    24: 'Hydration',
}


def decode_sync_progress(state: int) -> list[str]:
    """Decode syncProgressState bitfield into human-readable flags."""
    if state == 0:
        return ['Idle']
    flags = []
    for bit, name in SYNC_PROGRESS_BITS.items():
        if state & (1 << bit):
            flags.append(name)
    if not flags:
        flags.append(f'Unknown(0x{state:x})')
    return flags


def format_epoch(ts: int | None) -> str:
    if not ts:
        return '?'
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime('%Y-%m-%d %H:%M UTC')
    except (OSError, ValueError):
        return str(ts)


# ── Health assessment ────────────────────────────────────────────────────────

def assess_health(diag: dict, stuck_dl: list, postponed: list) -> tuple[str, str]:
    """Return (status_text, status_style)."""
    if not diag:
        return 'NO DATA', 'bold red'

    stall = diag.get('syncStallDetected', '0')
    scan_stall = diag.get('scanStateStallDetected', '0')
    failed_dl = int(diag.get('numFileFailedDownloads', '0'))
    failed_ul = int(diag.get('numFileFailedUploads', '0'))
    files_dl = int(diag.get('FilesToDownload', diag.get('filesToDownload', '0')))
    files_ul = int(diag.get('FilesToUpload', '0'))
    bytes_to_dl = int(diag.get('BytesToDownload', '0'))
    bytes_dled = int(diag.get('BytesDownloaded', '0'))
    changes = int(diag.get('ChangesToProcess', '0'))
    progress = int(diag.get('SyncProgressState', diag.get('syncProgressState', '0')))

    if stall == '1' or scan_stall == '1':
        return 'STALL DETECTED', 'bold red'
    if failed_dl > 0 or failed_ul > 0:
        return f'ERRORS (dl:{failed_dl} ul:{failed_ul})', 'bold red'
    if bytes_dled == bytes_to_dl and bytes_to_dl > 0 and files_dl > 0:
        return f'STUCK FINALIZING ({files_dl} files)', 'bold yellow'
    if len(postponed) > 0 and all(p['postponedCount'] > 50 for p in postponed):
        return f'STUCK CHANGES ({len(postponed)} files, {postponed[0]["postponedCount"]}x retried)', 'bold yellow'
    if files_dl > 0 or files_ul > 0 or changes > 0:
        return 'SYNCING', 'bold cyan'
    if progress == 0:
        return 'IDLE (healthy)', 'bold green'
    return f'ACTIVE (state={progress})', 'cyan'


def format_bytes(n: int) -> str:
    if n < 1024:
        return f'{n} B'
    if n < 1024 * 1024:
        return f'{n / 1024:.1f} KB'
    if n < 1024 * 1024 * 1024:
        return f'{n / 1024 / 1024:.1f} MB'
    return f'{n / 1024 / 1024 / 1024:.1f} GB'


def format_uptime(secs: int) -> str:
    if secs < 60:
        return f'{secs}s'
    if secs < 3600:
        return f'{secs // 60}m {secs % 60}s'
    h = secs // 3600
    m = (secs % 3600) // 60
    return f'{h}h {m}m'


# ── Filename issue detection ─────────────────────────────────────────────────

def detect_filename_issues(name: str) -> list[str]:
    """Flag known problematic filename patterns on Windows."""
    issues = []
    if name != name.rstrip():
        issues.append('trailing whitespace')
    if name != name.lstrip():
        issues.append('leading whitespace')
    # Space before extension
    stem, _, ext = name.rpartition('.')
    if stem and stem.endswith(' '):
        issues.append(f'space before .{ext}')
    if len(name) > 200:
        issues.append(f'long name ({len(name)} chars)')
    # Characters illegal on Windows
    illegal = set(name) & set('<>:"/\\|?*')
    if illegal:
        issues.append(f'illegal chars: {"".join(illegal)}')
    return issues


def normalize_filename(name: str) -> str:
    """Return a cleaned filename that won't upset Windows/OneDrive."""
    # Strip leading/trailing whitespace
    name = name.strip()
    # Fix space(s) before extension: "file .docx" -> "file.docx"
    name = re.sub(r'\s+\.(\w+)$', r'.\1', name)
    # Replace illegal Windows characters
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Collapse runs of spaces/underscores
    name = re.sub(r'_{2,}', '_', name)
    # Strip trailing dots/spaces from stem (Windows silently strips these)
    stem, dot, ext = name.rpartition('.')
    if dot:
        name = stem.rstrip('. ') + '.' + ext
    return name


def local_path_for_item(od_folder: str, item: dict) -> str | None:
    """Build the full local path for a stuck-file item, or None if unknown."""
    folder = item.get('folder', '')
    fname = item.get('file', '')
    if not folder or folder == '(unknown folder)' or not fname:
        return None
    return os.path.join(od_folder, folder.replace('/', os.sep), fname)


# ── Per-account data container ───────────────────────────────────────────────

class AccountData:
    """Holds all diagnostic data for one OneDrive account."""

    def __init__(self, account: str):
        self.account = account
        self.od_folder = user_folder(account) or '?'
        self.email = user_email(account) or ''
        self.diag: dict = {}
        self.stuck_downloads: list[dict] = []
        self.postponed: list[dict] = []
        self.hydrations: list[dict] = []
        self.all_issues: list[dict] = []

    @property
    def tab_label(self) -> str:
        if self.email:
            return f'{self.account} ({self.email})'
        return self.account

    def load(self) -> None:
        self.diag = parse_sync_diag(self.account)

        dl_lines = parse_downloads_queue(self.account)
        db_path = copy_sync_db(self.account)

        self.stuck_downloads = query_stuck_downloads(db_path, dl_lines) if db_path else []
        self.postponed = query_postponed_changes(db_path) if db_path else []
        self.hydrations = query_hydration_data(db_path) if db_path else []

        self.all_issues = []
        for d in self.stuck_downloads:
            issues = detect_filename_issues(d['fileName'])
            self.all_issues.append({
                'type': 'Download',
                'file': d['fileName'],
                'folder': d['folder'],
                'size': d['size'],
                'retries': '-',
                'issues': ', '.join(issues) if issues else '',
                'detail': d,
            })
        for p in self.postponed:
            issues = detect_filename_issues(p['fileName'])
            self.all_issues.append({
                'type': f'Postponed (ct={p["changeType"]})',
                'file': p['fileName'],
                'folder': p['folder'],
                'size': p['size'],
                'retries': str(p['postponedCount']),
                'issues': ', '.join(issues) if issues else '',
                'detail': p,
            })
        for h in self.hydrations:
            self.all_issues.append({
                'type': 'Hydration',
                'file': h['fileName'] or h['resourceID'][:20],
                'folder': '',
                'size': 0,
                'retries': str(h['count']),
                'issues': f"type={h['type']} last={h['lastHydration']}",
                'detail': h,
            })

    def refresh_diag(self) -> None:
        """Light refresh — re-read SyncDiagnostics.log only."""
        self.diag = parse_sync_diag(self.account)


# ── TUI ──────────────────────────────────────────────────────────────────────

def _escape(text: str) -> str:
    """Escape Rich markup characters."""
    return text.replace('[', '\\[').replace(']', '\\]')


class OneDriveDiagApp(TUIApp):
    CSS = """
    #main-layout { height: 1fr; }
    #tabs { height: 1fr; }
    .account-tab { height: 1fr; }
    .health-panel {
        border: solid $accent;
        height: auto;
        max-height: 12;
    }
    .stuck-panel {
        border: solid $error;
        height: 2fr;
    }
    .stuck-table { height: 1fr; }
    .bottom-split { height: 1fr; }
    .progress-panel {
        border: solid $warning;
        width: 2fr;
        height: 1fr;
    }
    .detail-panel {
        border: solid $success;
        width: 3fr;
        height: 1fr;
    }
    .panel-label {
        dock: top;
        color: $text;
        text-align: center;
        padding: 0 1;
        height: 1;
    }
    .health-label  { background: $accent-darken-2; }
    .stuck-label   { background: $error-darken-2; }
    .progress-label { background: $warning-darken-2; }
    .detail-label  { background: $success-darken-2; }
    .health-log, .progress-log, .detail-log {
        height: 1fr;
        max-height: 100%;
    }
    """

    BINDINGS = [
        ('q', 'quit', 'Quit'),
        ('d', 'toggle_dark', 'Dark/Light'),
        ('r', 'refresh', 'Refresh'),
        ('n', 'normalize', 'Fix Name'),
        ('x', 'reset_onedrive', 'Reset OD'),
        ('escape', 'clear_detail', 'Clear Detail'),
    ]

    def __init__(self, accounts: list[str], watch: bool = False):
        super().__init__()
        self.accounts_data: dict[str, AccountData] = {
            acc: AccountData(acc) for acc in accounts
        }
        self.watch = watch
        self._watch_stop = threading.Event()
        self._reset_armed = False  # two-step confirmation for reset

    @property
    def _current_account(self) -> str | None:
        """Return the currently active tab's account name."""
        try:
            tabs = self.query_one('#tabs', TabbedContent)
            active = tabs.active
            # active is the tab pane ID like "tab-Business1"
            if active and active.startswith('tab-'):
                return active[4:]
        except Exception:
            pass
        # Fallback to first account
        if self.accounts_data:
            return next(iter(self.accounts_data))
        return None

    @property
    def _current_data(self) -> AccountData | None:
        acc = self._current_account
        return self.accounts_data.get(acc) if acc else None

    def _wid(self, account: str, name: str) -> str:
        """Generate a widget ID unique per account."""
        return f'{name}-{account}'

    def compose(self) -> ComposeResult:
        yield StatusHeader()
        with TabbedContent(id='tabs'):
            for acc, data in self.accounts_data.items():
                with TabPane(data.tab_label, id=f'tab-{acc}'):
                    with Vertical(classes='account-tab'):
                        with Vertical(classes='health-panel'):
                            yield Static('Sync Health', id=self._wid(acc, 'health-label'),
                                         classes='panel-label health-label')
                            yield RichLog(id=self._wid(acc, 'health-log'),
                                          classes='health-log', highlight=True, markup=True, wrap=False)
                        with Vertical(classes='stuck-panel'):
                            yield Static('Stuck / Errored Files', id=self._wid(acc, 'stuck-label'),
                                         classes='panel-label stuck-label')
                            yield DataTable(id=self._wid(acc, 'stuck-table'),
                                            classes='stuck-table', cursor_type='row', zebra_stripes=True)
                        with Horizontal(classes='bottom-split'):
                            with Vertical(classes='progress-panel'):
                                yield Static('Sync Progress', id=self._wid(acc, 'progress-label'),
                                             classes='panel-label progress-label')
                                yield RichLog(id=self._wid(acc, 'progress-log'),
                                              classes='progress-log', highlight=True, markup=True, wrap=False)
                            with Vertical(classes='detail-panel'):
                                yield Static('Detail — select a row above',
                                             id=self._wid(acc, 'detail-label'),
                                             classes='panel-label detail-label')
                                yield RichLog(id=self._wid(acc, 'detail-log'),
                                              classes='detail-log', highlight=True, markup=True, wrap=False)
        yield Footer()

    def on_mount(self) -> None:
        for acc in self.accounts_data:
            table = self.query_one(f'#{self._wid(acc, "stuck-table")}', DataTable)
            table.add_columns('Type', 'File', 'Folder', 'Size', 'Retries', 'Issues')
        self.title = 'OneDrive Diagnostics'
        self.load_all_data()

    @work(thread=True)
    def load_all_data(self) -> None:
        for acc, data in self.accounts_data.items():
            self.call_from_thread(setattr, self, 'sub_title', f'Loading {acc}...')
            data.load()
            self.call_from_thread(self._render_account, acc)

        self.call_from_thread(setattr, self, 'sub_title',
                              f'{len(self.accounts_data)} accounts — {datetime.now().strftime("%H:%M:%S")}')

        if self.watch and not self._watch_stop.is_set():
            self._watch_loop()

    def _watch_loop(self) -> None:
        while not self._watch_stop.is_set():
            time.sleep(10)
            if self._watch_stop.is_set():
                break
            for acc, data in self.accounts_data.items():
                data.refresh_diag()
                self.call_from_thread(self._render_health, acc)
                self.call_from_thread(self._render_progress, acc)
            self.call_from_thread(setattr, self, 'sub_title',
                                  f'{len(self.accounts_data)} accounts — {datetime.now().strftime("%H:%M:%S")}')

    def _render_account(self, acc: str) -> None:
        self._render_health(acc)
        self._render_stuck_table(acc)
        self._render_progress(acc)

    def _render_health(self, acc: str) -> None:
        data = self.accounts_data[acc]
        log = self.query_one(f'#{self._wid(acc, "health-log")}', RichLog)
        log.clear()
        label = self.query_one(f'#{self._wid(acc, "health-label")}', Static)

        if not data.diag:
            label.update(f'Sync Health — NO DATA  [{acc}]')
            log.write('[bold red]SyncDiagnostics.log not found or empty[/]')
            return

        status_text, status_style = assess_health(
            data.diag, data.stuck_downloads, data.postponed)
        label.update(f'Sync Health — [{status_style}]{status_text}[/]  [{acc}  {data.od_folder}]')

        # Health indicators row
        parts = []
        for field, (display, healthy) in HEALTH_FIELDS.items():
            val = data.diag.get(field, '?')
            style = 'green' if val == healthy else 'bold red'
            parts.append(f'{display}: [{style}]{val}[/]')
        log.write('  '.join(parts))

        # Key info
        uptime = int(data.diag.get('uptimeSecs', '0'))
        files = data.diag.get('files', '?')
        folders = data.diag.get('folders', '?')
        version = data.diag.get('clientVersion', '?')
        pid = data.diag.get('pid', '?')
        placeholder = 'Yes' if data.diag.get('placeholdersEnabled') == '1' else 'No'
        disk_free = int(data.diag.get('bytesAvailableOnDiskDrive', '0'))

        log.write(
            f'Uptime: {format_uptime(uptime)}  '
            f'Files: {files}  Folders: {folders}  '
            f'FOD: {placeholder}  '
            f'Disk free: {format_bytes(disk_free)}  '
            f'PID: {pid}  v{version}'
        )

        # Stuck finalizing warning
        bytes_to_dl = int(data.diag.get('BytesToDownload', '0'))
        bytes_dled = int(data.diag.get('BytesDownloaded', '0'))
        files_dl = int(data.diag.get('FilesToDownload',
                       data.diag.get('filesToDownload', '0')))
        if bytes_dled == bytes_to_dl and bytes_to_dl > 0 and files_dl > 0:
            log.write(
                f'[bold yellow]STUCK FINALIZING: {files_dl} files, '
                f'{format_bytes(bytes_to_dl)} downloaded (100%) but not finalized[/]'
            )

    def _render_stuck_table(self, acc: str) -> None:
        data = self.accounts_data[acc]
        table = self.query_one(f'#{self._wid(acc, "stuck-table")}', DataTable)
        label = self.query_one(f'#{self._wid(acc, "stuck-label")}', Static)
        table.clear()

        if not data.all_issues:
            label.update('Stuck / Errored Files — [green]none[/]')
            return

        label.update(f'Stuck / Errored Files — [bold red]{len(data.all_issues)}[/]')
        for item in data.all_issues:
            fname = item['file']
            if len(fname) > 60:
                fname = '...' + fname[-57:]
            folder = item['folder']
            if len(folder) > 40:
                folder = '...' + folder[-37:]
            size_str = format_bytes(item['size']) if item['size'] else '-'
            table.add_row(
                item['type'],
                fname,
                folder,
                size_str,
                item['retries'],
                item['issues'] or '-',
            )

    def _render_progress(self, acc: str) -> None:
        data = self.accounts_data[acc]
        log = self.query_one(f'#{self._wid(acc, "progress-log")}', RichLog)
        log.clear()
        label = self.query_one(f'#{self._wid(acc, "progress-label")}', Static)

        if not data.diag:
            label.update('Sync Progress — no data')
            return

        changes = int(data.diag.get('ChangesToProcess', '0'))
        sends = int(data.diag.get('ChangesToSend', '0'))
        label.update(f'Sync Progress — changes:{changes} pending_send:{sends}')

        for field in PROGRESS_FIELDS:
            val = data.diag.get(field, data.diag.get(field[0].lower() + field[1:], '?'))
            if val == '?':
                continue
            style = ''
            if field in ('FilesToDownload', 'FilesToUpload', 'ChangesToProcess',
                         'ChangesToSend') and val != '0':
                style = '[bold yellow]'
            elif field in ('DownloadSpeedBytesPerSec', 'UploadSpeedBytesPerSec') and val != '0':
                style = '[cyan]'

            display_val = val
            if 'Bytes' in field and val.isdigit():
                display_val = f'{val} ({format_bytes(int(val))})'
            elif 'Speed' in field and val.isdigit():
                display_val = f'{format_bytes(int(val))}/s'

            close = '[/]' if style else ''
            log.write(f'  {style}{field}: {display_val}{close}')

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        data = self._current_data
        if not data:
            return
        idx = event.cursor_row
        if 0 <= idx < len(data.all_issues):
            self._show_detail(data, data.all_issues[idx])

    def _detail_log_for(self, acc: str) -> RichLog:
        return self.query_one(f'#{self._wid(acc, "detail-log")}', RichLog)

    def _detail_label_for(self, acc: str) -> Static:
        return self.query_one(f'#{self._wid(acc, "detail-label")}', Static)

    def _show_detail(self, data: AccountData, item: dict) -> None:
        log = self._detail_log_for(data.account)
        log.clear()
        label = self._detail_label_for(data.account)
        label.update(f'Detail — {_escape(item["file"][:60])}')

        log.write(f'[bold]Type:[/]   {item["type"]}')
        log.write(f'[bold]File:[/]   {_escape(item["file"])}')
        log.write(f'[bold]Folder:[/] {_escape(item["folder"])}')
        if item['size']:
            log.write(f'[bold]Size:[/]   {format_bytes(item["size"])}')
        if item['retries'] != '-':
            log.write(f'[bold]Retries:[/] {item["retries"]}')

        issues = item.get('issues')
        if issues:
            log.write('')
            log.write(f'[bold yellow]Issues: {_escape(issues)}[/]')

        detail = item.get('detail', {})
        if detail:
            log.write('')
            log.write('[bold]Raw fields:[/]')
            for k, v in detail.items():
                if k == 'detail':
                    continue
                log.write(f'  {k}: {_escape(str(v)[:200])}')

        # Show full local path if folder is known
        folder = item['folder']
        fname = item['file']
        if folder and folder != '(unknown folder)':
            full = f'{data.od_folder}\\{folder}\\{fname}'.replace('/', '\\')
            log.write('')
            exists = Path(full).exists() if len(full) < 260 else False
            status = '[green]exists locally[/]' if exists else '[red]NOT found locally[/]'
            log.write(f'[bold]Local path:[/] {_escape(full)}')
            log.write(f'  {status}')

        # Recommendations
        log.write('')
        log.write('[bold]Recommendations:[/]')
        if issues:
            new_name = normalize_filename(item['file'])
            if new_name != item['file']:
                log.write(f'  [bold cyan]Press "n" to auto-fix: {_escape(item["file"])} -> {_escape(new_name)}[/]')
        if 'space before' in (issues or ''):
            log.write('  [yellow]Or rename on SharePoint web to remove trailing space[/]')
        if item['type'] == 'Download':
            log.write('  [yellow]1. Check if file is locked by another process[/]')
            log.write('  [yellow]2. Try: Pause sync > Resume sync (tray icon)[/]')
            log.write('  [yellow]3. Press "x" for OneDrive reset[/]')
        elif 'Postponed' in item['type']:
            retries = int(item['retries']) if item['retries'].isdigit() else 0
            if retries > 100:
                log.write('  [yellow]1. These changes have been retried 100+ times[/]')
                log.write('  [yellow]2. Parent folder may be missing from sync scope[/]')
                log.write('  [yellow]3. Press "x" for OneDrive reset[/]')
            else:
                log.write('  [yellow]1. Wait — OneDrive will retry automatically[/]')

    def action_normalize(self) -> None:
        """Rename the selected file to fix filename issues (n key)."""
        data = self._current_data
        if not data:
            return
        detail_log = self._detail_log_for(data.account)
        try:
            table = self.query_one(f'#{self._wid(data.account, "stuck-table")}', DataTable)
        except Exception:
            return
        idx = table.cursor_row
        if idx < 0 or idx >= len(data.all_issues):
            detail_log.clear()
            detail_log.write('[bold red]Select a row first[/]')
            return

        item = data.all_issues[idx]
        issues = item.get('issues', '')
        if not issues:
            detail_log.clear()
            detail_log.write('[yellow]No filename issues detected for this file[/]')
            return

        old_name = item['file']
        new_name = normalize_filename(old_name)
        if new_name == old_name:
            detail_log.clear()
            detail_log.write('[yellow]Name is already normalized (issues may be non-renameable)[/]')
            return

        old_path = local_path_for_item(data.od_folder, item)
        if not old_path:
            detail_log.clear()
            detail_log.write('[bold red]Cannot resolve local path (folder unknown)[/]')
            return

        new_path = os.path.join(os.path.dirname(old_path), new_name)

        detail_log.clear()
        detail_log.write('[bold]Normalize Filename[/]')
        detail_log.write('')
        detail_log.write(f'[bold]Old:[/] {_escape(old_name)}')
        detail_log.write(f'[bold]New:[/] {_escape(new_name)}')
        detail_log.write(f'[bold]Issues fixed:[/] {_escape(issues)}')
        detail_log.write('')
        detail_log.write(f'[bold]Path:[/] {_escape(old_path)}')
        detail_log.write('')

        if not os.path.exists(old_path):
            detail_log.write('[bold red]File not found locally — cannot rename[/]')
            detail_log.write('[dim]File may be cloud-only or path exceeds 260 chars[/]')
            return

        if os.path.exists(new_path):
            detail_log.write(f'[bold red]Target already exists: {_escape(new_name)}[/]')
            detail_log.write('[dim]Rename manually to avoid overwriting[/]')
            return

        try:
            os.rename(old_path, new_path)
        except OSError as e:
            detail_log.write(f'[bold red]Rename failed: {_escape(str(e))}[/]')
            detail_log.write('')
            detail_log.write('[dim]Try closing any app that has the file open,[/]')
            detail_log.write('[dim]or rename via SharePoint web UI.[/]')
            return

        detail_log.write('[bold green]Renamed successfully[/]')
        detail_log.write('[dim]OneDrive will sync the rename to SharePoint.[/]')
        detail_log.write('[dim]Press "r" to refresh diagnostics.[/]')

        item['file'] = new_name
        item['issues'] = ''
        self._render_stuck_table(data.account)

    def action_reset_onedrive(self) -> None:
        """Two-step OneDrive reset: first press arms, second press executes."""
        data = self._current_data
        acc = data.account if data else (next(iter(self.accounts_data)) if self.accounts_data else None)
        if not acc:
            return
        detail_log = self._detail_log_for(acc)
        detail_log.clear()

        exe = onedrive_exe_path()
        if not exe:
            detail_log.write('[bold red]OneDrive.exe not found[/]')
            detail_log.write('[dim]Check registry HKCU\\Software\\Microsoft\\OneDrive\\OneDriveTrigger[/]')
            return

        if not self._reset_armed:
            # First press — arm and show warning
            self._reset_armed = True
            detail_log.write('[bold red]OneDrive Reset[/]')
            detail_log.write('')
            detail_log.write(f'[bold]Executable:[/] {_escape(exe)}')
            detail_log.write('')
            detail_log.write('[bold yellow]This will:[/]')
            detail_log.write('  - Kill the OneDrive process')
            detail_log.write('  - Clear the local sync database')
            detail_log.write('  - Re-enumerate all files (may take minutes)')
            detail_log.write('  - NOT delete any files')
            detail_log.write('')
            affected = ', '.join(self.accounts_data.keys())
            detail_log.write(f'[bold]Affected accounts:[/] {affected}')
            detail_log.write('')
            detail_log.write('[bold red]>>> Press "x" again to confirm, Esc to cancel <<<[/]')
        else:
            # Second press — execute reset
            self._reset_armed = False
            detail_log.write('[bold]Executing OneDrive reset...[/]')
            detail_log.write(f'[dim]{_escape(exe)} /reset[/]')
            detail_log.write('')

            try:
                # /reset kills OneDrive then relaunches it
                result = subprocess.run(
                    [exe, '/reset'],
                    capture_output=True, text=True, timeout=30,
                    encoding='utf-8', errors='replace',
                )
                detail_log.write('[bold green]Reset command sent[/]')
                if result.returncode != 0:
                    detail_log.write(f'[yellow]Return code: {result.returncode}[/]')
                if result.stderr:
                    detail_log.write(f'[dim]{_escape(result.stderr[:200])}[/]')
            except subprocess.TimeoutExpired:
                detail_log.write('[bold green]Reset in progress (process is restarting)[/]')
            except OSError as e:
                detail_log.write(f'[bold red]Failed: {_escape(str(e))}[/]')
                return

            detail_log.write('')
            detail_log.write('[bold]What happens now:[/]')
            detail_log.write('  1. OneDrive will relaunch automatically')
            detail_log.write('  2. It will show "Processing N changes" in the tray')
            detail_log.write('  3. SyncDiagnostics.log will be empty until reset completes')
            detail_log.write('  4. Press "r" to refresh after OneDrive restarts')
            detail_log.write('')
            detail_log.write('[dim]This TUI will continue running. Refresh when ready.[/]')

    def action_refresh(self) -> None:
        self._reset_armed = False
        self.load_all_data()

    def action_clear_detail(self) -> None:
        self._reset_armed = False
        data = self._current_data
        if not data:
            return
        log = self._detail_log_for(data.account)
        log.clear()
        label = self._detail_label_for(data.account)
        label.update('Detail — select a row above')

    def on_unmount(self) -> None:
        self._watch_stop.set()


# ── Conflict analysis ────────────────────────────────────────────────────────

def discover_hostnames(od_folder: str, sample_limit: int = 5000,
                       extra_stopwords: list[str] | None = None,
                       exclude_dirs: list[str] | None = None) -> list[str]:
    """Scan OneDrive folder to discover hostname suffixes in conflict files.

    OneDrive conflict pattern: {name}-{hostname}.{ext}
    Returns sorted list of detected hostnames with file counts.
    """
    _STOP_WORDS = {
        'alt', 'copy', 'old', 'new', 'backup', 'original', 'temp',
        'final', 'draft', 'test', 'prod', 'dev', 'raw', 'min', 'max',
        'small', 'large', 'medium', 'thumb', 'thumbs', 'preview',
        'full', 'high', 'low', 'journal', 'outline', 'variant',
        'flattened', 'compressed', 'cropped', 'resized', 'scaled',
        'edited', 'modified', 'signed', 'unsigned', 'encrypted',
        'Images', 'Pictures', 'Documents', 'Downloads',
    }
    if extra_stopwords:
        _STOP_WORDS.update(extra_stopwords)
        _STOP_WORDS.update(w.lower() for w in extra_stopwords)

    exclude_set = set(exclude_dirs or [])

    hostname_counts: dict[str, int] = {}
    count = 0
    for root, dirs, files in os.walk(od_folder):
        # Prune excluded directories
        dirs[:] = [d for d in dirs if d not in exclude_set]
        for fname in files:
            count += 1
            if count > sample_limit * 10:
                break
            m = re.match(r'^.+-([A-Za-z][A-Za-z0-9_-]*[A-Za-z0-9])(\.\w+)$', fname)
            if not m:
                m = re.match(r'^.+-([A-Za-z][A-Za-z0-9_-]*[A-Za-z0-9])$', fname)
            if m:
                candidate = m.group(1)
                if (len(candidate) >= 3
                    and candidate not in _STOP_WORDS
                    and candidate.lower() not in _STOP_WORDS
                    and candidate[0].isupper()):
                    if fname.count('.') > 0:
                        base = fname.replace(f'-{candidate}.', '.', 1)
                    else:
                        base = fname.replace(f'-{candidate}', '', 1)
                    base_path = os.path.join(root, base)
                    if os.path.exists(base_path) and base != fname:
                        hostname_counts[candidate] = hostname_counts.get(candidate, 0) + 1
    # Filter to hostnames with 2+ conflicts
    return sorted(
        [h for h, c in hostname_counts.items() if c >= 2],
        key=lambda h: hostname_counts[h],
        reverse=True,
    )


def scan_conflicts(od_folder: str, hostnames: list[str],
                   exclude_dirs: list[str] | None = None) -> list[dict]:
    """Find all conflict file pairs for given hostnames."""
    exclude_set = set(exclude_dirs or [])
    # Build suffix lookup
    suffixes = [(h, f'-{h}.', f'-{h}') for h in hostnames]
    results = []

    for root, dirs, files in os.walk(od_folder):
        dirs[:] = [d for d in dirs if d not in exclude_set]
        for fname in files:
            matched_host = None
            base = None
            for hostname, suffix_dot, suffix_bare in suffixes:
                idx = fname.find(suffix_dot)
                if idx > 0:
                    base = fname[:idx] + fname[idx + len(suffix_bare):]
                    matched_host = hostname
                    break
                elif fname.endswith(suffix_bare):
                    base = fname[:-len(suffix_bare)]
                    matched_host = hostname
                    break

            if not matched_host or not base or base == fname:
                continue

            rel_dir = os.path.relpath(root, od_folder)
            if rel_dir == '.':
                rel_dir = ''

            conflict_path = os.path.join(root, fname)
            base_path = os.path.join(root, base)
            base_exists = os.path.exists(base_path)

            try:
                cstat = os.stat(conflict_path)
                conflict_size = cstat.st_size
                conflict_mtime = datetime.fromtimestamp(cstat.st_mtime)
            except OSError:
                conflict_size = 0
                conflict_mtime = None

            base_size = 0
            base_mtime = None
            if base_exists:
                try:
                    bstat = os.stat(base_path)
                    base_size = bstat.st_size
                    base_mtime = datetime.fromtimestamp(bstat.st_mtime)
                except OSError:
                    pass

            results.append({
                'base_name': base,
                'conflict_name': fname,
                'hostname': matched_host,
                'folder': rel_dir,
                'base_path': base_path,
                'conflict_path': conflict_path,
                'base_exists': base_exists,
                'base_size': base_size,
                'base_mtime': base_mtime,
                'conflict_size': conflict_size,
                'conflict_mtime': conflict_mtime,
                'size_diff': conflict_size - base_size if base_exists else 0,
            })

    results.sort(key=lambda r: (r['folder'], r['base_name']))
    return results


class HostnamePicker(App):
    """TUI checkbox picker for conflict hostnames."""

    CSS = """
    Screen { align: center middle; }
    #picker {
        width: 60;
        max-height: 20;
        border: solid $primary;
        padding: 1 2;
    }
    #picker-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }
    #custom-input {
        margin-top: 1;
    }
    #start-btn {
        margin-top: 1;
        width: 100%;
    }
    """
    BINDINGS = [
        Binding('escape', 'quit', 'Cancel'),
        Binding('enter', 'confirm', 'Confirm'),
    ]

    def __init__(self, cfg_hostnames: list[str], discovered: list[str]):
        super().__init__()
        self._cfg = cfg_hostnames
        self._discovered = [h for h in discovered if h not in cfg_hostnames]

    def compose(self) -> ComposeResult:
        yield StatusHeader()
        with Vertical(id='picker'):
            yield Static('Select hostnames  [dim]Enter=Confirm  Esc=Cancel[/dim]',
                          id='picker-title')
            for h in self._cfg:
                yield Checkbox(f'{h}  [dim](config)[/dim]', value=True, id=f'host-{h}')
            for h in self._discovered:
                yield Checkbox(f'{h}  [dim](discovered)[/dim]', value=False, id=f'host-{h}')
            yield Input(placeholder='Custom hostname (optional)', id='custom-input')
            yield Button('Start', variant='success', id='start-btn')
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'start-btn':
            self.action_confirm()

    def action_confirm(self) -> None:
        selected = []
        all_hosts = self._cfg + self._discovered
        for h in all_hosts:
            try:
                cb = self.query_one(f'#host-{h}', Checkbox)
                if cb.value:
                    selected.append(h)
            except Exception:
                pass
        custom = self.query_one('#custom-input', Input).value.strip()
        if custom and custom not in selected:
            selected.append(custom)
        self.exit(result=selected)

    def action_quit(self) -> None:
        self.exit(result=[])


class ConflictApp(TUIApp):
    CSS = """
    #main-layout {
        height: 1fr;
        overflow: hidden;
    }
    #summary-panel {
        border: solid $accent;
        height: auto;
        max-height: 6;
    }
    #conflict-panel {
        border: solid $error;
        height: 2fr;
        min-height: 8;
    }
    #conflict-table { height: 1fr; }
    #detail-panel {
        border: solid $success;
        height: 1fr;
        min-height: 6;
    }
    .panel-label {
        dock: top;
        color: $text;
        text-align: center;
        padding: 0 1;
        height: 1;
    }
    #summary-label { background: $accent-darken-2; }
    #conflict-label { background: $error-darken-2; }
    #cdetail-label { background: $success-darken-2; }
    #summary-log {
        height: auto;
        max-height: 3;
    }
    #cdetail-log {
        height: 1fr;
    }
    """

    BINDINGS = [
        ('q', 'quit', 'Quit'),
        ('d', 'toggle_dark', 'Dark/Light'),
        ('r', 'refresh', 'Refresh'),
        ('delete', 'delete_conflict', 'Delete Conflict'),
        ('a', 'delete_all', 'Delete All'),
        ('escape', 'clear_detail', 'Clear Detail'),
    ]

    def __init__(self, od_folder: str, hostnames: list[str],
                 exclude_dirs: list[str] | None = None):
        super().__init__()
        self.od_folder = od_folder
        self.hostnames = hostnames
        self.exclude_dirs = exclude_dirs or []
        self._conflicts: list[dict] = []
        self._delete_all_armed = False

    def compose(self) -> ComposeResult:
        yield StatusHeader()
        with Vertical(id='main-layout'):
            with Vertical(id='summary-panel'):
                yield Static('Conflict Summary', id='summary-label', classes='panel-label')
                yield RichLog(id='summary-log', highlight=True, markup=True, wrap=False)
            with Vertical(id='conflict-panel'):
                yield Static('Conflict Files', id='conflict-label', classes='panel-label')
                yield DataTable(id='conflict-table', cursor_type='row', zebra_stripes=True)
            with Vertical(id='detail-panel'):
                yield Static('Detail — select a row', id='cdetail-label', classes='panel-label')
                yield RichLog(id='cdetail-log', highlight=True, markup=True, wrap=False)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one('#conflict-table', DataTable)
        table.add_columns('Base File', 'Conflict File', 'Host', 'Folder',
                          'Base Date', 'Conflict Date', 'Base Size', 'Conflict Size')
        self.title = f'Conflict Analysis — {", ".join(self.hostnames)}'
        self.scan()

    @work(thread=True)
    def scan(self) -> None:
        self.call_from_thread(setattr, self, 'sub_title', f'Scanning {self.od_folder}...')
        self._conflicts = scan_conflicts(self.od_folder, self.hostnames,
                                         exclude_dirs=self.exclude_dirs)
        self.call_from_thread(self._render_all)
        self.call_from_thread(setattr, self, 'sub_title',
                              f'{len(self._conflicts)} conflicts — {datetime.now().strftime("%H:%M:%S")}')

    def _render_all(self) -> None:
        self._render_summary()
        self._render_table()

    def _render_summary(self) -> None:
        log = self.query_one('#summary-log', RichLog)
        log.clear()
        label = self.query_one('#summary-label', Static)

        n = len(self._conflicts)
        total_bytes = sum(c['conflict_size'] for c in self._conflicts)
        with_base = sum(1 for c in self._conflicts if c['base_exists'])
        orphans = n - with_base

        hosts_str = ', '.join(self.hostnames)
        if n == 0:
            label.update(f'Conflict Summary — [green]no conflicts for {hosts_str}[/]')
            return

        label.update(f'Conflict Summary — [bold yellow]{n} conflicts[/] for [bold]{hosts_str}[/]')
        log.write(
            f'Total: {n} conflict files  '
            f'Size: {format_bytes(total_bytes)}  '
            f'With base: {with_base}  '
            f'Orphaned (no base): {orphans}'
        )

        # Group by hostname
        by_host: dict[str, int] = {}
        for c in self._conflicts:
            h = c.get('hostname', '?')
            by_host[h] = by_host.get(h, 0) + 1
        if len(by_host) > 1:
            host_str = '  '.join(f'{h}:{count}' for h, count in
                                 sorted(by_host.items(), key=lambda x: x[1], reverse=True))
            log.write(f'By host: {host_str}')

        # Group by extension
        by_ext: dict[str, int] = {}
        for c in self._conflicts:
            _, _, ext = c['conflict_name'].rpartition('.')
            by_ext[f'.{ext}'] = by_ext.get(f'.{ext}', 0) + 1
        ext_str = '  '.join(f'{ext}:{count}' for ext, count in
                            sorted(by_ext.items(), key=lambda x: x[1], reverse=True))
        log.write(f'By type: {ext_str}')

    def _render_table(self) -> None:
        table = self.query_one('#conflict-table', DataTable)
        label = self.query_one('#conflict-label', Static)
        table.clear()

        if not self._conflicts:
            label.update('Conflict Files — [green]none[/]')
            return

        label.update(f'Conflict Files — [bold red]{len(self._conflicts)}[/]  '
                     f'(Del=remove selected, a=remove all)')

        for c in self._conflicts:
            base = c['base_name']
            if len(base) > 40:
                base = '...' + base[-37:]
            conflict = c['conflict_name']
            if len(conflict) > 45:
                conflict = '...' + conflict[-42:]
            folder = c['folder']
            if len(folder) > 30:
                folder = '...' + folder[-27:]
            host = c.get('hostname', '?')

            base_date = c['base_mtime'].strftime('%Y-%m-%d %H:%M') if c['base_mtime'] else '-'
            conf_date = c['conflict_mtime'].strftime('%Y-%m-%d %H:%M') if c['conflict_mtime'] else '-'

            base_size = format_bytes(c['base_size']) if c['base_exists'] else '-'
            conf_size = format_bytes(c['conflict_size'])

            table.add_row(base, conflict, host, folder, base_date, conf_date, base_size, conf_size)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self._conflicts):
            self._show_conflict_detail(self._conflicts[idx])

    def _show_conflict_detail(self, c: dict) -> None:
        log = self.query_one('#cdetail-log', RichLog)
        log.clear()
        label = self.query_one('#cdetail-label', Static)
        label.update(f'Detail — {_escape(c["base_name"][:50])}')

        log.write(f'[bold]Base file:[/]     {_escape(c["base_name"])}')
        log.write(f'[bold]Conflict file:[/] {_escape(c["conflict_name"])}')
        log.write(f'[bold]Folder:[/]        {_escape(c["folder"])}')
        log.write('')

        if c['base_exists']:
            log.write(f'[bold]Base:[/]     {format_bytes(c["base_size"])}  '
                      f'{c["base_mtime"].strftime("%Y-%m-%d %H:%M:%S") if c["base_mtime"] else "?"}')
        else:
            log.write('[bold red]Base file does NOT exist (orphaned conflict)[/]')

        log.write(f'[bold]Conflict:[/] {format_bytes(c["conflict_size"])}  '
                  f'{c["conflict_mtime"].strftime("%Y-%m-%d %H:%M:%S") if c["conflict_mtime"] else "?"}')

        if c['base_exists'] and c['base_mtime'] and c['conflict_mtime']:
            if c['conflict_mtime'] > c['base_mtime']:
                log.write('[yellow]Conflict is NEWER than base[/]')
            elif c['conflict_mtime'] < c['base_mtime']:
                log.write('[green]Base is newer (conflict is stale)[/]')
            else:
                log.write('[dim]Same modification time[/]')

            if c['size_diff'] != 0:
                log.write(f'Size difference: {format_bytes(abs(c["size_diff"]))} '
                          f'({"conflict larger" if c["size_diff"] > 0 else "base larger"})')
            elif c['base_size'] == c['conflict_size']:
                log.write('[green]Same size — likely identical content[/]')

        log.write('')
        log.write(f'[bold]Conflict path:[/] {_escape(c["conflict_path"])}')
        log.write('')
        log.write('[bold cyan]Press Delete to remove the conflict file[/]')

    def action_delete_conflict(self) -> None:
        """Delete the selected conflict file."""
        log = self.query_one('#cdetail-log', RichLog)
        table = self.query_one('#conflict-table', DataTable)
        idx = table.cursor_row
        if idx < 0 or idx >= len(self._conflicts):
            log.clear()
            log.write('[bold red]Select a conflict row first[/]')
            return

        c = self._conflicts[idx]
        path = c['conflict_path']

        log.clear()
        try:
            os.remove(path)
        except OSError as e:
            log.write(f'[bold red]Delete failed: {_escape(str(e))}[/]')
            return

        log.write(f'[bold green]Deleted: {_escape(c["conflict_name"])}[/]')
        self._conflicts.pop(idx)
        self._render_table()
        self._render_summary()

    def action_delete_all(self) -> None:
        """Two-step: arm on first press, delete all on second."""
        log = self.query_one('#cdetail-log', RichLog)

        if not self._conflicts:
            log.clear()
            log.write('[green]No conflicts to delete[/]')
            return

        if not self._delete_all_armed:
            self._delete_all_armed = True
            log.clear()
            log.write('[bold red]Delete ALL conflict files?[/]')
            log.write('')
            log.write(f'This will delete {len(self._conflicts)} files '
                      f'({format_bytes(sum(c["conflict_size"] for c in self._conflicts))})')
            log.write('')
            log.write('[bold red]>>> Press "a" again to confirm, Esc to cancel <<<[/]')
        else:
            self._delete_all_armed = False
            log.clear()
            deleted = 0
            failed = 0
            for c in list(self._conflicts):
                try:
                    os.remove(c['conflict_path'])
                    deleted += 1
                except OSError:
                    failed += 1

            log.write(f'[bold green]Deleted {deleted} conflict files[/]')
            if failed:
                log.write(f'[bold red]Failed to delete {failed} files[/]')

            self._conflicts = [c for c in self._conflicts if os.path.exists(c['conflict_path'])]
            self._render_table()
            self._render_summary()

    def action_refresh(self) -> None:
        self._delete_all_armed = False
        self.scan()

    def action_clear_detail(self) -> None:
        self._delete_all_armed = False
        log = self.query_one('#cdetail-log', RichLog)
        log.clear()
        label = self.query_one('#cdetail-label', Static)
        label.update('Detail — select a row')


# ── DB Explorer (non-TUI report) ────────────────────────────────────────────

def db_explore(accounts: list[str], output_dir: str | None = None) -> str | None:
    """Explore sync databases for all accounts and dump a diagnostic report.

    Returns the output file path, or None if no output was written.
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    lines: list[str] = []

    def out(text: str = '') -> None:
        print(text)
        lines.append(text)

    out(f'OneDrive DB Explorer — {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    out('=' * 72)

    issues_found = 0

    for acc in accounts:
        out('')
        out(f'Account: {acc}')
        out('-' * 72)

        email = user_email(acc) or '(unknown)'
        od_folder = user_folder(acc) or '(unknown)'
        out(f'  Email:  {email}')
        out(f'  Folder: {od_folder}')

        # SyncDiagnostics.log summary
        diag = parse_sync_diag(acc)
        if diag:
            progress_state = int(diag.get('SyncProgressState',
                                          diag.get('syncProgressState', '0')))
            progress_flags = decode_sync_progress(progress_state)
            uptime = int(diag.get('uptimeSecs', '0'))
            out(f'  Uptime: {format_uptime(uptime)}  '
                f'PID: {diag.get("pid", "?")}  '
                f'v{diag.get("clientVersion", "?")}')
            out(f'  SyncProgressState: {progress_state} '
                f'({", ".join(progress_flags)})')

            # Key counters
            counters = {}
            for field in ['ChangesToProcess', 'ChangesToSend',
                          'FilesToDownload', 'FilesToUpload',
                          'numFileFailedDownloads', 'numFileFailedUploads',
                          'syncStallDetected', 'scanStateStallDetected']:
                val = diag.get(field, diag.get(
                    field[0].lower() + field[1:], '0'))
                counters[field] = val
            nonzero = {k: v for k, v in counters.items() if v != '0'}
            if nonzero:
                out(f'  Active counters: {nonzero}')
                issues_found += len(nonzero)
            else:
                out('  All sync counters: 0 (healthy)')
        else:
            out('  SyncDiagnostics.log: NOT FOUND')
            issues_found += 1

        # Database queries
        db_path = copy_sync_db(acc)
        if not db_path:
            out('  SyncEngineDatabase.db: NOT FOUND or locked')
            issues_found += 1
            continue

        # Scope info
        scopes = query_scope_info(db_path)
        out(f'  Scopes (synced libraries): {len(scopes)}')
        for s in scopes:
            out(f'    [{s["scopeType"]}] {s["webURL"] or "(no URL)"}'
                f'  type={s["libraryType"]}')

        # File/folder counts
        files, folders = query_file_folder_counts(db_path)
        out(f'  Database records: {files} files, {folders} folders')

        # Active hydrations
        hydrations = query_hydration_data(db_path)
        if hydrations:
            out(f'  Active hydrations: {len(hydrations)}  *** ISSUE ***')
            issues_found += len(hydrations)
            for h in hydrations:
                name = h['fileName'] or h['resourceID'][:30]
                out(f'    {name}  '
                    f'type={h["type"]}  count={h["count"]}  '
                    f'last={h["lastHydration"]}')
                # Resolve folder for hydration items
                conn = sqlite3.connect(str(db_path))
                cur = conn.cursor()
                try:
                    rid = h['resourceID'].split('+')[0]
                    cur.execute(
                        'SELECT parentResourceID, size '
                        'FROM od_ClientFile_Records WHERE resourceID LIKE ?',
                        (rid + '%',))
                    row = cur.fetchone()
                    if row:
                        folder = resolve_folder(cur, row[0])
                        out(f'      folder: {folder}  '
                            f'size: {format_bytes(row[1] or 0)}')
                except sqlite3.Error:
                    pass
                conn.close()
        else:
            out('  Active hydrations: 0')

        # Postponed file changes
        postponed = query_postponed_changes(db_path)
        if postponed:
            out(f'  Postponed file changes: {len(postponed)}  *** ISSUE ***')
            issues_found += len(postponed)
            for p in postponed:
                out(f'    {p["fileName"]}  '
                    f'type={p["changeType"]}  '
                    f'retries={p["postponedCount"]}  '
                    f'folder={p["folder"]}')
        else:
            out('  Postponed file changes: 0')

        # Postponed folder changes
        postponed_folders = query_postponed_folder_changes(db_path)
        if postponed_folders:
            out(f'  Postponed folder changes: {len(postponed_folders)}'
                f'  *** ISSUE ***')
            issues_found += len(postponed_folders)
            for p in postponed_folders:
                out(f'    {p["folderName"]}  '
                    f'type={p["changeType"]}  '
                    f'retries={p["postponedCount"]}  '
                    f'parent={p["parentFolder"]}')
        else:
            out('  Postponed folder changes: 0')

        # Service operation history
        history = query_service_history(db_path, limit=30)
        errors = [h for h in history
                  if h['resultCode'] not in (200, 206, 304, None)]
        if errors:
            out(f'  Recent service errors: {len(errors)}  *** ISSUE ***')
            issues_found += len(errors)
            for e in errors:
                scope_url = ''
                for s in scopes:
                    if s['scopeID'] == e['scopeID']:
                        scope_url = s['webURL']
                        break
                scope_label = scope_url or e['scopeID'][:16]
                out(f'    [{e["time"]}] {e["operation"]} -> '
                    f'{e["resultCode"]}  '
                    f'scope={scope_label}  '
                    f'{e["scenario"][:60]}')
        else:
            out(f'  Recent service operations: {len(history)} (all OK)')

        # Health assessment
        postponed_for_health = query_postponed_changes(db_path)
        dl_lines = parse_downloads_queue(acc)
        stuck_dl = query_stuck_downloads(db_path, dl_lines)
        status_text, _ = assess_health(diag, stuck_dl, postponed_for_health)
        out(f'  Health: {status_text}')

    # Summary
    out('')
    out('=' * 72)
    if issues_found:
        out(f'Total issues found: {issues_found}')
    else:
        out('No issues found — all accounts healthy.')

    # Write report file
    if output_dir is None:
        output_dir = os.environ.get('TEMP', '.')
    out_path = os.path.join(output_dir, f'onedrive-dbexplore-{timestamp}.txt')
    try:
        Path(out_path).write_text('\n'.join(lines), encoding='utf-8')
        print(f'\nReport saved: {out_path}')
        return out_path
    except OSError as e:
        print(f'\nFailed to save report: {e}')
        return None


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    import argparse

    from w11 import resolve_app_dir
    app_dir = resolve_app_dir()
    Env(name='w11-onedrive', app_path=app_dir)
    Env.load()

    parser = argparse.ArgumentParser(description='OneDrive Sync Diagnostics TUI')
    parser.add_argument('mode', nargs='?',
                        choices=['diag', 'conflicts', 'reset', 'dbexplore'],
                        help='Mode: diag, conflicts, or reset')
    parser.add_argument('--account', action='append', default=None,
                        help='Account folder name(s). Repeatable. Default: all detected.')
    parser.add_argument('--hostname', default=None,
                        help='Hostname suffix to analyze conflicts for (e.g., Mailstore)')
    parser.add_argument('--watch', action='store_true',
                        help='Auto-refresh health every 10s')
    parser.add_argument('--output', default=None,
                        help='Output directory for report files (dbexplore mode)')
    args = parser.parse_args()

    # Config values
    cfg_accounts = Env.glob_list('accounts', default=[])
    cfg_hostnames = Env.glob_list('hostnames', default=[])
    cfg_stopwords = Env.glob_list('hostname_stopwords', default=[])
    cfg_exclude = Env.glob_list('conflict_scan_exclude', default=['.git', 'node_modules', '__pycache__'])
    cfg_watch_interval = Env.glob_int('watch_interval', default=10)

    # Read manifest modes from config for interactive menu
    manifest = Env.glob_dict('manifest') or {}
    modes = manifest.get('modes') or {}

    mode = args.mode or Env.glob('mode', default=None)
    if not mode:
        app_name = manifest.get('name', 'OneDrive Diagnostics')
        icon = manifest.get('icon', '')
        print(f'{icon}  {app_name}' if icon else app_name)
        print('')
        mode_keys = list(modes.keys()) if modes else ['diag', 'conflicts']
        for i, key in enumerate(mode_keys, 1):
            info = modes.get(key, {})
            name = info.get('name', key) if isinstance(info, dict) else key
            print(f'  {i}. {name}')
        print('')
        try:
            idx = int(input(f'Select mode [1-{len(mode_keys)}]: ').strip()) - 1
            selected_key = mode_keys[idx]
        except (ValueError, IndexError):
            selected_key = mode_keys[0]

        # Apply manifest args for the selected mode
        info = modes.get(selected_key, {})
        manifest_args = info.get('args', []) if isinstance(info, dict) else []
        if manifest_args:
            # Re-parse with manifest args prepended
            args = parser.parse_args(manifest_args)
        mode = args.mode or selected_key.split('-')[0]  # "diag-watch" -> "diag"

    if mode == 'diag':
        if args.account:
            accounts = args.account
        elif cfg_accounts:
            accounts = cfg_accounts
        else:
            accounts = discover_accounts()

        if not accounts:
            print('No OneDrive accounts found with SyncDiagnostics.log.')
            logs = od_base() / 'logs'
            if logs.exists():
                available = [p.name for p in logs.iterdir() if p.is_dir()]
                print(f'Log directories found: {", ".join(available)}')
            return

        for acc in accounts:
            if not logs_dir(acc).exists():
                available = [p.name for p in (od_base() / 'logs').iterdir() if p.is_dir()]
                print(f'Account "{acc}" not found. Available: {", ".join(available)}')
                return

        watch = args.watch or cfg_watch_interval > 0
        app = OneDriveDiagApp(accounts=accounts, watch=watch)
        app.run()

    elif mode == 'conflicts':
        accounts = args.account or cfg_accounts or discover_accounts()
        if not accounts:
            print('No OneDrive accounts found.')
            return

        if len(accounts) == 1:
            od_folder = user_folder(accounts[0])
        else:
            print('')
            print('Select account to scan for conflicts:')
            for i, acc in enumerate(accounts, 1):
                folder = user_folder(acc)
                email = user_email(acc) or ''
                print(f'  {i}. {acc} ({email}) — {folder}')
            print('')
            try:
                idx = int(input(f'Select [1-{len(accounts)}]: ').strip()) - 1
                od_folder = user_folder(accounts[idx])
            except (ValueError, IndexError):
                od_folder = user_folder(accounts[0])

        if not od_folder or not os.path.isdir(od_folder):
            print(f'OneDrive folder not found: {od_folder}')
            return

        if args.hostname:
            hostnames = [args.hostname]
        elif cfg_hostnames:
            # Config hostnames exist — use them, discover extras
            discovered = discover_hostnames(od_folder,
                                            extra_stopwords=cfg_stopwords,
                                            exclude_dirs=cfg_exclude)
            picker = HostnamePicker(cfg_hostnames, discovered)
            hostnames = picker.run()
            if not hostnames:
                return
        else:
            # No config, no CLI flag — discover and pick
            discovered = discover_hostnames(od_folder,
                                            extra_stopwords=cfg_stopwords,
                                            exclude_dirs=cfg_exclude)
            if not discovered:
                print('No conflict hostname patterns detected.')
                return
            picker = HostnamePicker([], discovered)
            hostnames = picker.run()
            if not hostnames:
                return
        app = ConflictApp(od_folder=od_folder, hostnames=hostnames,
                          exclude_dirs=cfg_exclude)
        app.run()

    elif mode == 'dbexplore':
        accounts = args.account or cfg_accounts or discover_accounts()
        if not accounts:
            print('No OneDrive accounts found.')
            return
        db_explore(accounts, output_dir=args.output)

    elif mode == 'reset':
        exe = onedrive_exe_path()
        if not exe:
            print('OneDrive.exe not found.')
            print('Check registry HKCU\\Software\\Microsoft\\OneDrive\\OneDriveTrigger')
            return

        print(f'OneDrive executable: {exe}')
        print('')
        print('This will:')
        print('  - Kill the OneDrive process')
        print('  - Clear the local sync database')
        print('  - Re-enumerate all files (may take minutes)')
        print('  - NOT delete any files')
        print('')
        confirm = input('Proceed with reset? [y/N]: ').strip().lower()
        if confirm != 'y':
            print('Cancelled.')
            return

        print(f'Running: {exe} /reset')
        try:
            subprocess.run([exe, '/reset'], timeout=30,
                           capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
            print('Reset command sent. OneDrive will relaunch automatically.')
        except subprocess.TimeoutExpired:
            print('Reset in progress (process is restarting).')
        except OSError as e:
            print(f'Failed: {e}')


if __name__ == '__main__':
    main()
