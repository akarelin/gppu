"""
Watch Windows Event Viewer logs with a TUI — history + common errors + live tail.
Uses gppu Env for configuration.

Usage:
    python w11-events.py                    # configured logs
    python w11-events.py --all-logs         # all available logs
    python w11-events.py --days 30
    python w11-events.py --level Error
    python w11-events.py --export events.json
    python w11-events.py --logs System "Microsoft-Windows-Kernel-PnP/Configuration"
    python w11-events.py --stats            # recalculate stats and exit
"""

from __future__ import annotations

import argparse
import ctypes
import json
import re
import socket
import subprocess
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from gppu import Env, dict_from_yml, dict_to_yml
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, RichLog, Static

# ── Event model ──────────────────────────────────────────────────────────────

NS = '{http://schemas.microsoft.com/win/2004/08/events/event}'

LEVEL_NAMES = {0: 'INF', 1: 'CRT', 2: 'ERR', 3: 'WRN', 4: 'INF', 5: 'VRB'}
LEVEL_STYLES = {
    'CRT': 'bold magenta',
    'ERR': 'bold red',
    'WRN': 'yellow',
    'INF': 'white',
    'VRB': 'dim white',
}
LEVEL_NUMS = {'Critical': 1, 'Error': 2, 'Warning': 3, 'Information': 4, 'Verbose': 5, 'All': 99}
SEVERITY_ORDER = ['CRT', 'ERR', 'WRN', 'INF', 'VRB']


def time_since(dt: datetime) -> str:
    delta = datetime.now() - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        return 'now'
    if secs < 60:
        return f'{secs}s ago'
    mins = secs // 60
    if mins < 60:
        return f'{mins}m ago'
    hours = mins // 60
    if hours < 24:
        return f'{hours}h ago'
    days = hours // 24
    if days < 30:
        return f'{days}d ago'
    return f'{days // 30}mo ago'


def dedup_key(evt: dict) -> str:
    # Named source → collapse all events from that source
    if evt.get('_source'):
        return f"source|{evt['_source']}"
    # Matched error with source_value → collapse by error+source_value
    if evt.get('_error_slug') and evt.get('_source_value'):
        return f"error|{evt['_error_slug']}|{evt['_source_value']}"
    # Matched error without source_value → collapse all of this error type
    if evt.get('_error_slug'):
        return f"error|{evt['_error_slug']}"
    # Default — normalize numbers and GUIDs
    norm = re.sub(r'\{[0-9A-Fa-f-]{36}\}', '{GUID}', evt['message'])
    norm = re.sub(r'\d+', '#', norm)
    return f"{evt['level']}|{evt['log']}|{evt['provider']}|{evt['event_id']}|{norm}"


def parse_event_xml(xml_str: str) -> dict | None:
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return None

    sys_el = root.find(f'{NS}System')
    if sys_el is None:
        return None

    provider_el = sys_el.find(f'{NS}Provider')
    time_el = sys_el.find(f'{NS}TimeCreated')
    level_el = sys_el.find(f'{NS}Level')
    eid_el = sys_el.find(f'{NS}EventID')
    channel_el = sys_el.find(f'{NS}Channel')
    computer_el = sys_el.find(f'{NS}Computer')

    provider = provider_el.get('Name', '?') if provider_el is not None else '?'
    if provider.startswith('Microsoft-Windows-'):
        provider = provider[18:]
    ts_str = time_el.get('SystemTime', '') if time_el is not None else ''
    level_num = int(level_el.text) if level_el is not None and level_el.text else 4
    event_id = int(eid_el.text) if eid_el is not None and eid_el.text else 0
    log_name = channel_el.text if channel_el is not None and channel_el.text else '?'
    computer = computer_el.text if computer_el is not None and computer_el.text else '?'

    try:
        ts_str = ts_str.rstrip('Z').split('.')[0]
        dt = datetime.strptime(ts_str, '%Y-%m-%dT%H:%M:%S')
    except (ValueError, IndexError):
        dt = datetime.now()

    message = ''
    rd = root.find(f'{NS}RenderingInfo')
    if rd is not None:
        msg_el = rd.find(f'{NS}Message')
        if msg_el is not None and msg_el.text:
            message = msg_el.text
    if not message:
        ed = root.find(f'{NS}EventData')
        if ed is not None:
            parts = [d.text for d in ed.findall(f'{NS}Data') if d.text]
            message = ' | '.join(parts)
    if not message:
        message = '(no message)'

    message = message.replace('\r\n', ' | ').replace('\n', ' | ')

    # Extract named EventData fields
    event_data = {}
    ed = root.find(f'{NS}EventData')
    if ed is not None:
        for d in ed.findall(f'{NS}Data'):
            name = d.get('Name')
            if name and d.text:
                event_data[name] = d.text

    return {
        'datetime': dt,
        'since': time_since(dt),
        'level': LEVEL_NAMES.get(level_num, '???'),
        'level_num': level_num,
        'event_id': event_id,
        'provider': provider,
        'log': log_name,
        'log_short': {'Application': 'A', 'System': 'S', 'Security': 'X'}.get(
            log_name, log_name.split('/')[-1][:1].upper()),
        'computer': computer,
        'message': message,
        'event_data': event_data,
    }


# ── Common error patterns ────────────────────────────────────────────────────

class CommonErrorTracker:
    """Track errors and sources using category/source rules.

    Key format in config:
        category/  = category definition (error pattern, matches any source)
        /source    = source definition (match pattern, matches any category)
        category/source = explicit pairing
    """

    def __init__(self, rules: dict | None = None, categories: dict | None = None):
        rules = rules or {}

        # Category group icons (e.g. app -> "A", service -> "S")
        self.group_icons: dict[str, str] = {}
        for group, info in (categories or {}).items():
            if isinstance(info, dict):
                self.group_icons[group] = info.get('icon', group[0].upper())

        self.categories: dict[str, dict] = {}  # category slug -> definition
        self.sources: dict[str, dict] = {}      # source slug -> definition
        self.pairings: set[tuple[str, str]] = set()  # explicit (category, source) pairs

        for key, entry in rules.items():
            entry = entry or {}
            if key.endswith('/') and not key.startswith('/'):
                # category/ — category definition
                cat = key.rstrip('/')
                raw = entry.get('pattern', '')
                if isinstance(raw, str):
                    raw = [raw] if raw else []
                self.categories[cat] = {
                    'slug': cat,
                    'name': entry.get('name', cat),
                    'regexes': [re.compile(p, re.IGNORECASE) for p in raw],
                    'field_map': entry.get('extract') or {},
                    'source_field': entry.get('source_field'),
                    'history_count': 0,
                    'live_count': 0,
                    'last_extracted': {},
                }
            elif key.startswith('/') and not key.endswith('/'):
                # /source — source definition (global)
                src = key.lstrip('/')
                self.sources[src] = {
                    'slug': src,
                    'name': entry.get('name', src),
                    'match': re.compile(entry.get('match', src), re.IGNORECASE),
                    'global': True,
                    'history_count': 0,
                    'live_count': 0,
                    'error_breakdown': {},
                }
            elif '/' in key:
                # category/source — explicit pairing
                cat, src = key.split('/', 1)
                self.pairings.add((cat, src))
                if src not in self.sources:
                    self.sources[src] = {
                        'slug': src,
                        'name': entry.get('name', src),
                        'match': re.compile(entry.get('match', src), re.IGNORECASE),
                        'global': False,
                        'history_count': 0,
                        'live_count': 0,
                        'error_breakdown': {},
                    }

    def _cat_icon(self, cat_slug: str) -> str:
        """Get icon for a category based on its group prefix."""
        for group, icon in self.group_icons.items():
            if cat_slug.startswith(group):
                return icon
        return ' '

    @property
    def errors(self):
        return self.categories

    def load_from_stats(self, stats_file: Path) -> bool:
        if not stats_file.exists():
            return False
        try:
            data = dict_from_yml(stats_file)
        except Exception:
            return False

        saved_errors = data.get('common_errors') or {}
        saved_sources = data.get('common_sources') or {}
        if not saved_errors and not saved_sources:
            return False

        for slug, err in self.errors.items():
            entry = saved_errors.get(slug)
            if isinstance(entry, dict):
                err['history_count'] = entry.get('count', 0)
                err['last_extracted'] = entry.get('extracted', {})
            elif isinstance(entry, int):
                err['history_count'] = entry
        for slug, src in self.sources.items():
            entry = saved_sources.get(slug)
            if isinstance(entry, dict):
                src['history_count'] = entry.get('count', 0)
                src['error_breakdown'] = {
                    k: {'history': v, 'live': 0}
                    for k, v in entry.get('errors', {}).items()
                }
        return True

    def as_stats_dict(self) -> tuple[dict, dict]:
        errors = {}
        for slug, err in self.errors.items():
            if err['history_count'] == 0:
                continue
            entry: dict = {'count': err['history_count']}
            if err['last_extracted']:
                entry['extracted'] = dict(err['last_extracted'])
            errors[slug] = entry
        sources = {}
        for slug, src in self.sources.items():
            if src['history_count'] == 0:
                continue
            entry = {'count': src['history_count']}
            if src['error_breakdown']:
                entry['errors'] = {k: v['history']
                                   for k, v in src['error_breakdown'].items()
                                   if v['history'] > 0}
            sources[slug] = entry
        return errors, sources

    def _extract(self, err: dict, evt: dict) -> None:
        ed = evt.get('event_data', {})
        for display_name, xml_field in err['field_map'].items():
            if xml_field in ed:
                err['last_extracted'][display_name] = ed[xml_field]

    def _matches(self, err: dict, msg: str) -> bool:
        return any(rx.search(msg) for rx in err['regexes'])

    def _source_accepts_category(self, src_slug: str, cat_slug: str) -> bool:
        """Check if source accepts this category (global or explicit pairing)."""
        src = self.sources[src_slug]
        if src.get('global'):
            return True
        return (cat_slug, src_slug) in self.pairings

    def _attribute_source(self, cat: dict, evt: dict, counter: str) -> str | None:
        """Check if event belongs to a known source. Tags evt['_source']. Returns slug."""
        msg = evt['message']
        ed = evt.get('event_data', {})
        search_text = msg + ' ' + ' '.join(ed.values())
        for src in self.sources.values():
            if not self._source_accepts_category(src['slug'], cat['slug']):
                continue
            if src['match'].search(search_text):
                src[f'{counter}_count'] += 1
                csl = cat['slug']
                if csl not in src['error_breakdown']:
                    src['error_breakdown'][csl] = {'history': 0, 'live': 0}
                src['error_breakdown'][csl][counter] += 1
                evt['_source'] = src['slug']
                return src['slug']
        return None

    def match_history(self, evt: dict) -> None:
        msg = evt['message']
        for cat in self.categories.values():
            if self._matches(cat, msg):
                cat['history_count'] += 1
                self._extract(cat, evt)
                self._attribute_source(cat, evt, 'history')

    def match_live(self, evt: dict) -> None:
        msg = evt['message']
        for cat in self.categories.values():
            if self._matches(cat, msg):
                cat['live_count'] += 1
                self._extract(cat, evt)
                self._attribute_source(cat, evt, 'live')

    def tag_event(self, evt: dict) -> None:
        """Tag event with _source, _error_slug, _source_value for dedup. No counting."""
        msg = evt['message']
        ed = evt.get('event_data', {})
        for cat in self.categories.values():
            if not self._matches(cat, msg):
                continue
            evt['_error_slug'] = cat['slug']
            sf = cat.get('source_field')
            if sf:
                xml_field = cat['field_map'].get(sf)
                val = ed.get(xml_field) if xml_field else None
                if val:
                    evt['_source_value'] = val
            search_text = msg + ' ' + ' '.join(ed.values())
            for src in self.sources.values():
                if not self._source_accepts_category(src['slug'], cat['slug']):
                    continue
                if src['match'].search(search_text):
                    evt['_source'] = src['slug']
                    break
            break

    @staticmethod
    def slugify(val: str) -> str:
        """Convert a value like 'TiWorker.exe' to a slug like 'tiworker'."""
        s = val.lower().replace('.exe', '').replace('.dll', '')
        s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
        return s

    def event_source_slug(self, evt: dict) -> str:
        """Return slug for source column with icon: icon category/source."""
        err = evt.get('_error_slug', '')
        src = evt.get('_source', '')
        icon = self._cat_icon(err) if err else ''
        if err and src:
            return f'{icon} {err}/{src}'
        if err:
            return f'{icon} {err}'
        return ''

    def format_table(self) -> str:
        if not self.categories:
            return 'No error rules configured.'

        lines = []

        # ── Categories ──
        slug_w = max((len(s) for s in self.categories), default=5)
        slug_w = max(slug_w, 8)
        lines.append(f"[bold]  {'Category':<{slug_w}}  {'Hist':>6}  {'Live':>6}[/]")
        lines.append('-' * (slug_w + 20))
        for slug, cat in self.categories.items():
            h, l = cat['history_count'], cat['live_count']
            if h == 0 and l == 0:
                continue
            icon = self._cat_icon(slug)
            if l > 0:
                so, sc = '[bold red]', '[/]'
            else:
                so, sc = '[yellow]', '[/]'
            lines.append(f"{so}{icon} {slug:<{slug_w}}  {h:>6}  {l:>6}{sc}")

        # ── Sources (sorted by count desc) ──
        active_sources = [(s, d) for s, d in self.sources.items()
                          if d['history_count'] > 0 or d['live_count'] > 0]
        if active_sources:
            lines.append('')
            src_w = max(len(s) for s, _ in active_sources)
            src_w = max(src_w, 6)
            lines.append(f"[bold]  {'Source':<{src_w}}  {'Hist':>6}  {'Live':>6}[/]")
            lines.append('-' * (src_w + 20))
            for src_slug, src in sorted(active_sources, key=lambda x: x[1]['history_count'], reverse=True):
                h, l = src['history_count'], src['live_count']
                so = '[bold red]' if l > 0 else '[yellow]'
                lines.append(f"{so}  {src_slug:<{src_w}}  {h:>6}  {l:>6}[/]")
                if src['error_breakdown']:
                    for esl, counts in sorted(src['error_breakdown'].items(),
                                              key=lambda x: x[1]['history'], reverse=True):
                        icon = self._cat_icon(esl)
                        gh, gl = counts['history'], counts['live']
                        live_str = f' [bold red]+{gl}[/]' if gl else ''
                        lines.append(f"[dim]  {icon} {esl}: {gh}{live_str}[/]")

        return '\n'.join(lines)


# ── Event queries via wevtutil ───────────────────────────────────────────────

def get_all_log_names() -> list[str]:
    try:
        result = subprocess.run(
            ['wevtutil', 'el'], capture_output=True, text=True, timeout=15,
            encoding='utf-8', errors='replace',
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ['Application', 'System', 'Security']


def query_events(log_name: str, level: str, days: int, max_msg_len: int) -> list[dict]:
    lvl_num = LEVEL_NUMS.get(level, 99)

    conditions = []
    if lvl_num < 99:
        level_parts = ' or '.join(f'Level={i}' for i in range(1, lvl_num + 1))
        if lvl_num >= 4:
            level_parts += ' or Level=0'
        conditions.append(f'({level_parts})')
    if days > 0:
        ms = days * 86400 * 1000
        conditions.append(f'TimeCreated[timediff(@SystemTime) <= {ms}]')

    xpath = '*'
    if conditions:
        xpath = f"*[System[{' and '.join(conditions)}]]"

    try:
        result = subprocess.run(
            ['wevtutil', 'qe', log_name, '/q:' + xpath, '/rd:false', '/f:renderedxml'],
            capture_output=True, text=True, timeout=60,
            encoding='utf-8', errors='replace',
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    events = []
    for xml_match in re.finditer(r'<Event .+?</Event>', result.stdout, re.DOTALL):
        evt = parse_event_xml(xml_match.group())
        if evt:
            if len(evt['message']) > max_msg_len:
                evt['message'] = evt['message'][:max_msg_len - 3] + '...'
            events.append(evt)

    return events


def deduplicate(events: list[dict]) -> list[dict]:
    """Global dedup: collapse all events with the same key, keep latest, show total count.
    Events tagged with _source are collapsed by source slug.
    Output is sorted by the latest occurrence of each unique event."""
    if not events:
        return []
    seen: dict[str, dict] = {}   # key -> {evt, count}
    order: dict[str, datetime] = {}  # key -> latest datetime
    for evt in events:
        k = dedup_key(evt)
        if k in seen:
            seen[k]['count'] += 1
            if evt['datetime'] > order[k]:
                seen[k]['evt'] = evt
                order[k] = evt['datetime']
        else:
            seen[k] = {'evt': evt, 'count': 1}
            order[k] = evt['datetime']
    sorted_keys = sorted(seen.keys(), key=lambda k: order[k])
    return [{**seen[k]['evt'], 'count': seen[k]['count']} for k in sorted_keys]


def format_line(evt: dict) -> str:
    since = evt['since'].ljust(8)
    count = f" (x{evt.get('count', 1)})" if evt.get('count', 1) > 1 else ''
    return f"[{since}] [{evt['level']}] [{evt['log_short']}] {evt['provider']} ({evt['event_id']}): {evt['message']}{count}"


# ── Host stats ───────────────────────────────────────────────────────────────

def build_stats(events: list[dict]) -> dict:
    stats: dict = {}
    for evt in events:
        log = evt['log']
        sev = evt['level']
        if log not in stats:
            stats[log] = {}
        if sev not in stats[log]:
            stats[log][sev] = {
                'last_message': evt['message'],
                'last_seen': evt['datetime'].isoformat(),
                'count': 1,
            }
        else:
            entry = stats[log][sev]
            entry['count'] += 1
            if evt['datetime'].isoformat() > entry['last_seen']:
                entry['last_seen'] = evt['datetime'].isoformat()
                entry['last_message'] = evt['message']

    ordered: dict = {}
    for log in sorted(stats.keys()):
        ordered[log] = {}
        for sev in SEVERITY_ORDER:
            if sev in stats[log]:
                ordered[log][sev] = stats[log][sev]
    return ordered


def stats_path_for_host(hostname: str) -> Path:
    """Stats file is always {hostname}.yaml next to the config."""
    return Env.app_path / f'{hostname}.yaml'


def save_stats(stats: dict, stats_file: Path, hostname: str,
               common_errors: dict | None = None,
               common_sources: dict | None = None) -> Path:
    output = {
        'host': hostname,
        'generated': datetime.now().isoformat(timespec='seconds'),
        'logs': stats,
    }
    if common_errors:
        output['common_errors'] = common_errors
    if common_sources:
        output['common_sources'] = common_sources
    dict_to_yml(stats_file, output)
    return stats_file


def recalculate_stats(log_names, level, days, max_msg_len, stats_file, hostname,
                      error_tracker: CommonErrorTracker | None = None, progress_cb=None):
    all_events = []
    for i, log_name in enumerate(log_names):
        if progress_cb:
            short = log_name.split('/')[-1] if '/' in log_name else log_name
            progress_cb(f'Stats — [{i + 1}/{len(log_names)}] {short}...')
        events = query_events(log_name, level, days, max_msg_len)
        all_events.extend(events)
    all_events.sort(key=lambda e: e['datetime'])

    # Count common error patterns
    ce, cs = None, None
    if error_tracker:
        for err in error_tracker.errors.values():
            err['history_count'] = 0
            err['last_extracted'] = {}
        for src in error_tracker.sources.values():
            src['history_count'] = 0
            src['live_count'] = 0
            src['error_breakdown'] = {}
        for evt in all_events:
            error_tracker.match_history(evt)
        ce, cs = error_tracker.as_stats_dict()

    stats = build_stats(all_events)
    path = save_stats(stats, stats_file, hostname, common_errors=ce, common_sources=cs)
    if progress_cb:
        progress_cb(f'Stats — saved {len(all_events)} events from {len(stats)} logs to {path.name}')
    return path


# ── Clear logs ────────────────────────────────────────────────────────────────

def _is_admin() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def clear_event_logs(log_names: list[str], progress_cb=None) -> tuple[int, int]:
    """Clear Windows event logs. Elevates via UAC if needed. Returns (cleared, failed)."""
    if not _is_admin():
        return _clear_logs_elevated(log_names, progress_cb)
    cleared = failed = 0
    for i, log_name in enumerate(log_names):
        if progress_cb:
            short = log_name.split('/')[-1] if '/' in log_name else log_name
            progress_cb(f'Clearing [{i + 1}/{len(log_names)}] {short}...')
        try:
            result = subprocess.run(
                ['wevtutil', 'cl', log_name],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                cleared += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    return cleared, failed


def _clear_logs_elevated(log_names: list[str], progress_cb=None) -> tuple[int, int]:
    """Clear event logs via a single UAC elevation prompt."""
    if progress_cb:
        progress_cb('Requesting admin elevation...')
    script_path = result_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ps1', delete=False) as f:
            script_path = f.name
            result_path = script_path + '.result'
            f.write('$c = 0; $f = 0\n')
            for name in log_names:
                safe = name.replace("'", "''")
                f.write(f"& wevtutil cl '{safe}'\n")
                f.write('if ($LASTEXITCODE -eq 0) { $c++ } else { $f++ }\n')
            rp_safe = result_path.replace("'", "''")
            f.write(f"Set-Content -Path '{rp_safe}' -Value \"$c,$f\"\n")
        subprocess.run(
            [
                'powershell', '-NoProfile', '-Command',
                f'Start-Process powershell -Verb RunAs -Wait '
                f'-ArgumentList \'-NoProfile -ExecutionPolicy Bypass -File "{script_path}"\'',
            ],
            timeout=120,
        )
        rp = Path(result_path)
        if rp.exists():
            parts = rp.read_text().strip().split(',')
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
        return 0, len(log_names)
    except Exception:
        return 0, len(log_names)
    finally:
        if script_path:
            Path(script_path).unlink(missing_ok=True)
        if result_path:
            Path(result_path).unlink(missing_ok=True)


# ── Live tail ────────────────────────────────────────────────────────────────

class LiveTail:
    def __init__(self, log_names: list[str], level: str, callback):
        self.log_names = log_names
        self.level = level
        self.callback = callback
        self._procs: list[subprocess.Popen] = []
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    def start(self):
        lvl_num = LEVEL_NUMS.get(self.level, 99)
        conditions = []
        if lvl_num < 99:
            level_parts = ' or '.join(f'Level={i}' for i in range(1, lvl_num + 1))
            if lvl_num >= 4:
                level_parts += ' or Level=0'
            conditions.append(f'({level_parts})')
        xpath = '*'
        if conditions:
            xpath = f"*[System[{' and '.join(conditions)}]]"

        for log_name in self.log_names:
            try:
                proc = subprocess.Popen(
                    ['powershell.exe', '-NoProfile', '-Command',
                     f"$watcher = New-Object System.Diagnostics.Eventing.Reader.EventLogWatcher("
                     f"  (New-Object System.Diagnostics.Eventing.Reader.EventLogQuery('{log_name}', "
                     f"  [System.Diagnostics.Eventing.Reader.PathType]::LogName, '{xpath}')));"
                     f"$watcher.add_EventRecordWritten({{ param($s,$e); "
                     f"  $r = $e.EventRecord; "
                     f"  Write-Output $r.ToXml(); "
                     f"  Write-Output '---EVTBREAK---' }});"
                     f"$watcher.Enabled = $true;"
                     f"while($true) {{ Start-Sleep -Milliseconds 200 }}"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding='utf-8', errors='replace',
                )
                self._procs.append(proc)
                t = threading.Thread(target=self._read_stream, args=(proc,), daemon=True)
                t.start()
                self._threads.append(t)
            except Exception:
                pass

    def _read_stream(self, proc: subprocess.Popen):
        buf = ''
        while not self._stop.is_set():
            try:
                line = proc.stdout.readline()
                if not line:
                    break
                if '---EVTBREAK---' in line:
                    evt = parse_event_xml(buf.strip())
                    if evt:
                        self.callback(evt)
                    buf = ''
                else:
                    buf += line
            except Exception:
                break

    def stop(self):
        self._stop.set()
        for proc in self._procs:
            try:
                proc.kill()
            except Exception:
                pass


# ── TUI ──────────────────────────────────────────────────────────────────────

class EventLogApp(App):
    CSS = """
    #main-layout {
        height: 1fr;
    }
    #history-panel {
        border: solid $accent;
        height: 2fr;
    }
    #history-table {
        height: 1fr;
    }
    #bottom-split {
        height: 1fr;
    }
    #errors-panel {
        border: solid $warning;
        width: 2fr;
        height: 1fr;
    }
    #detail-panel {
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
    #history-label { background: $accent-darken-2; }
    #errors-label  { background: $warning-darken-2; }
    #detail-label  { background: $success-darken-2; }
    #errors-log {
        height: 1fr;
        max-height: 100%;
    }
    #detail-log {
        height: 1fr;
        max-height: 100%;
    }
    #errors-panel, #detail-panel {
        overflow-y: auto;
    }
    """

    BINDINGS = [
        ('q', 'quit', 'Quit'),
        ('d', 'toggle_dark', 'Dark/Light'),
        ('s', 'recalc_stats', 'Stats'),
        ('r', 'refresh_errors', 'Refresh'),
        ('c', 'clear_logs', 'Clear Logs'),
        ('e', 'export_history', 'Export History'),
        ('w', 'export_errors', 'Export Errors'),
        ('a', 'add_rule', 'Add Rule'),
        ('o', 'analyze_overlap', 'Overlap'),
        ('escape', 'clear_detail', 'Clear Detail'),
    ]

    def __init__(self, log_names, level, days, do_dedup, max_msg_len, export_path,
                 hostname, error_tracker: CommonErrorTracker):
        super().__init__()
        self.log_names = log_names
        self.level = level
        self.days = days
        self.do_dedup = do_dedup
        self.max_msg_len = max_msg_len
        self.export_path = export_path
        self.hostname = hostname
        self.stats_file = stats_path_for_host(hostname)
        self.error_tracker = error_tracker
        self._export_fh = None
        self._all_events: list[dict] = []
        self._display_events: list[dict] = []
        self._detail_mode = False  # True = showing selected event detail

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id='main-layout'):
            with Vertical(id='history-panel'):
                yield Static(f'History — last {self.days} days', id='history-label', classes='panel-label')
                yield DataTable(id='history-table', cursor_type='row', zebra_stripes=True)
            with Horizontal(id='bottom-split'):
                with Vertical(id='errors-panel'):
                    yield Static('Common Errors', id='errors-label', classes='panel-label')
                    yield RichLog(id='errors-log', highlight=True, markup=True, wrap=False)
                with Vertical(id='detail-panel'):
                    yield Static('Detail — select a row above', id='detail-label', classes='panel-label')
                    yield RichLog(id='detail-log', highlight=True, markup=True, wrap=False)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one('#history-table', DataTable)
        table.add_columns('Since', 'Lvl', 'Log', 'Source', 'Provider', 'ID', 'Message', 'x')
        if self.export_path:
            self._export_fh = open(self.export_path, 'a', encoding='utf-8')
        self.load_history()

    def _refresh_errors_display(self) -> None:
        errors_log = self.query_one('#errors-log', RichLog)
        errors_log.clear()
        errors_log.write(self.error_tracker.format_table())
        label = self.query_one('#errors-label', Static)
        total_h = sum(e['history_count'] for e in self.error_tracker.errors.values())
        total_l = sum(e['live_count'] for e in self.error_tracker.errors.values())
        label.update(f'Common Errors — hist:{total_h} live:{total_l}')

    def _show_event_detail(self, evt: dict) -> None:
        """Show full detail of a selected event in the detail panel."""
        self._detail_mode = True
        detail_log = self.query_one('#detail-log', RichLog)
        detail_log.clear()
        label = self.query_one('#detail-label', Static)
        label.update('Event Detail (Esc = back to live)')

        ts = evt['datetime'].strftime('%Y-%m-%d %H:%M:%S')
        detail_log.write(f'[bold]Timestamp:[/] {ts}  ({evt["since"]})')
        detail_log.write(f'[bold]Level:[/]     {evt["level"]}')
        detail_log.write(f'[bold]Log:[/]       {evt["log"]}')
        detail_log.write(f'[bold]Provider:[/]  {evt["provider"]}')
        detail_log.write(f'[bold]Event ID:[/]  {evt["event_id"]}')
        if evt.get('computer'):
            detail_log.write(f'[bold]Computer:[/]  {evt["computer"]}')
        count = evt.get('count', 1)
        if count > 1:
            detail_log.write(f'[bold]Count:[/]     {count}')
        detail_log.write('')
        detail_log.write('[bold]Message:[/]')
        # Show full message without truncation, wrap manually
        msg = evt.get('_full_message', evt['message'])
        for part in msg.split(' | '):
            detail_log.write(f'  {_escape(part)}')

        ed = evt.get('event_data', {})
        if ed:
            detail_log.write('')
            detail_log.write('[bold]EventData (XML fields):[/]')
            for k, v in ed.items():
                detail_log.write(f'  [bold]{_escape(k)}:[/] {_escape(v)}')

    def action_add_rule(self) -> None:
        """Add selected history row as a rule to error_rules.yaml.
        If event has no category match: adds category/.
        If event has category but no source: adds /source."""
        table = self.query_one('#history-table', DataTable)
        detail_log = self.query_one('#detail-log', RichLog)
        idx = table.cursor_row
        if idx < 0 or idx >= len(self._display_events):
            detail_log.clear()
            detail_log.write('[bold red]Select a row first[/]')
            return

        evt = self._display_events[idx]
        rules_file = Env.app_path / 'error_rules.yaml'
        rules_data = dict_from_yml(rules_file)
        detail_log.clear()

        error_slug = evt.get('_error_slug')

        if not error_slug:
            # No category match — add category/
            provider_slug = self.error_tracker.slugify(evt['provider'])
            slug = f'{provider_slug}-{evt["event_id"]}'

            if slug in self.error_tracker.categories:
                detail_log.write(f'[yellow]Category "{slug}/" already exists[/]')
                return

            msg = evt['message']
            snippet = msg.split('|')[0].strip() if '|' in msg[:80] else msg[:40]
            snippet = re.sub(r'[\d.]+\s*$', '', snippet).strip().rstrip(',.:;')
            if len(snippet) > 40:
                snippet = snippet[:40].rsplit(' ', 1)[0]
            pattern = re.escape(snippet)

            new_entry = {
                'name': f'{evt["provider"]} {evt["event_id"]}',
                'pattern': pattern,
            }
            ed = evt.get('event_data', {})
            if ed:
                extract = {self.error_tracker.slugify(k): k for k in list(ed.keys())[:5]}
                if extract:
                    new_entry['extract'] = extract

            rules_data[f'{slug}/'] = new_entry
            dict_to_yml(rules_file, rules_data)

            self.error_tracker.categories[slug] = {
                'slug': slug,
                'name': new_entry['name'],
                'regexes': [re.compile(pattern, re.IGNORECASE)],
                'field_map': new_entry.get('extract') or {},
                'source_field': None,
                'history_count': 0,
                'live_count': 0,
                'last_extracted': {},
            }

            detail_log.write(f'[bold green]Added category "{slug}/"[/]')
            detail_log.write(f'  pattern: {_escape(pattern[:80])}')

        else:
            # Has category but no source — add /source
            if evt.get('_source'):
                detail_log.write(f'[yellow]Already matched: {error_slug}/{evt["_source"]}[/]')
                return

            source_val = evt.get('_source_value')
            if source_val:
                slug = self.error_tracker.slugify(source_val)
                match_str = source_val.split('.')[0]
            else:
                slug = self.error_tracker.slugify(evt['provider'])
                match_str = evt['provider']

            if slug in self.error_tracker.sources:
                detail_log.write(f'[yellow]Source "/{slug}" already exists[/]')
                return

            rules_data[f'/{slug}'] = {
                'name': match_str,
                'match': match_str,
            }
            dict_to_yml(rules_file, rules_data)

            self.error_tracker.sources[slug] = {
                'slug': slug,
                'name': match_str,
                'match': re.compile(match_str, re.IGNORECASE),
                'global': True,
                'history_count': 0,
                'live_count': 0,
                'error_breakdown': {},
            }

            detail_log.write(f'[bold green]Added source "/{slug}"[/]')
            detail_log.write(f'  match: "{match_str}"')

        detail_log.write(f'  saved to {_escape(str(rules_file))}')
        detail_log.write('[dim]Press "s" to recalculate stats[/]')

    def action_analyze_overlap(self) -> None:
        """Analyze rules for overlaps, gaps, and coverage."""
        detail_log = self.query_one('#detail-log', RichLog)
        detail_log.clear()

        tracker = self.error_tracker
        total = len(self._all_events)
        detail_log.write(f'[bold]Rule Analysis[/] ({total:,} events)')
        detail_log.write('')

        # ── 1. Category coverage ──
        cat_counts: dict[str, int] = {}
        for evt in self._all_events:
            slug = evt.get('_error_slug')
            if slug:
                cat_counts[slug] = cat_counts.get(slug, 0) + 1
        matched_total = sum(cat_counts.values())
        unmatched_total = total - matched_total
        pct = (matched_total / total * 100) if total else 0
        detail_log.write(f'[bold]Coverage:[/] {matched_total:,}/{total:,} ({pct:.0f}%) matched')
        detail_log.write('')

        # ── 2. Multiple category matches ──
        multi_cat: dict[str, list[str]] = {}
        for evt in self._all_events:
            msg = evt['message']
            matched = [s for s, c in tracker.categories.items() if tracker._matches(c, msg)]
            if len(matched) > 1:
                key = f"{evt['provider']}({evt['event_id']})"
                if key not in multi_cat:
                    multi_cat[key] = matched
        if multi_cat:
            detail_log.write(f'[bold red]Category overlap ({len(multi_cat)}):[/]')
            for key, slugs in sorted(multi_cat.items()):
                icons = ' '.join(tracker._cat_icon(s) for s in slugs)
                detail_log.write(f'  {icons} {key}: {", ".join(slugs)}')
        else:
            detail_log.write('[green]No category overlaps[/]')
        detail_log.write('')

        # ── 3. Multiple source matches ──
        multi_src: dict[str, list[str]] = {}
        for evt in self._all_events:
            err_slug = evt.get('_error_slug')
            if not err_slug:
                continue
            msg = evt['message']
            ed = evt.get('event_data', {})
            search_text = msg + ' ' + ' '.join(ed.values())
            hits = [s for s, src in tracker.sources.items()
                    if tracker._source_accepts_category(s, err_slug)
                    and src['match'].search(search_text)]
            if len(hits) > 1:
                key = f"{evt['provider']}({evt['event_id']})"
                if key not in multi_src:
                    multi_src[key] = hits
        if multi_src:
            detail_log.write(f'[bold red]Source overlap ({len(multi_src)}):[/]')
            for key, slugs in sorted(multi_src.items()):
                detail_log.write(f'  {key}: {", ".join(slugs)}')
        else:
            detail_log.write('[green]No source overlaps[/]')
        detail_log.write('')

        # ── 4. Unmatched events (no category) ──
        unmatched: dict[str, dict] = {}  # key -> {count, sample}
        for evt in self._all_events:
            if not evt.get('_error_slug'):
                key = f"{evt['provider']}({evt['event_id']})"
                if key not in unmatched:
                    unmatched[key] = {'count': 0, 'sample': evt['message'][:60]}
                unmatched[key]['count'] += 1
        if unmatched:
            sorted_un = sorted(unmatched.items(), key=lambda x: x[1]['count'], reverse=True)
            detail_log.write(f'[yellow]No category ({len(unmatched)} types, {unmatched_total:,} events):[/]')
            for key, info in sorted_un[:20]:
                detail_log.write(f'  [bold]{key}[/]: {info["count"]}')
                detail_log.write(f'    [dim]{_escape(info["sample"])}[/]')
            if len(sorted_un) > 20:
                detail_log.write(f'  ... and {len(sorted_un) - 20} more')
        else:
            detail_log.write('[green]All events have a category[/]')
        detail_log.write('')

        # ── 5. Matched category but no source ──
        no_src: dict[str, dict] = {}
        for evt in self._all_events:
            if evt.get('_error_slug') and not evt.get('_source'):
                cat = evt['_error_slug']
                icon = tracker._cat_icon(cat)
                sv = evt.get('_source_value', '')
                key = f"{icon} {cat}/{sv}" if sv else f"{icon} {cat}"
                if key not in no_src:
                    no_src[key] = {'count': 0, 'sample': evt['message'][:60]}
                no_src[key]['count'] += 1
        if no_src:
            sorted_ns = sorted(no_src.items(), key=lambda x: x[1]['count'], reverse=True)
            detail_log.write(f'[yellow]No source ({len(no_src)} types):[/]')
            for key, info in sorted_ns[:20]:
                detail_log.write(f'  [bold]{_escape(key)}[/]: {info["count"]}')
            if len(sorted_ns) > 20:
                detail_log.write(f'  ... and {len(sorted_ns) - 20} more')
        else:
            detail_log.write('[green]All matched events have a source[/]')
        detail_log.write('')

        # ── 6. Unused rules ──
        unused_cats = [s for s, c in tracker.categories.items() if c['history_count'] == 0]
        unused_srcs = [s for s, d in tracker.sources.items() if d['history_count'] == 0]
        if unused_cats or unused_srcs:
            detail_log.write('[dim]Unused rules:[/]')
            for s in unused_cats:
                detail_log.write(f'  [dim]{tracker._cat_icon(s)} {s}/[/]')
            for s in unused_srcs:
                detail_log.write(f'  [dim]/{s}[/]')
        else:
            detail_log.write('[green]All rules matched at least once[/]')

        # ── Summary ──
        issues = len(multi_cat) + len(multi_src) + len(unmatched) + len(no_src)
        detail_log.write('')
        if issues == 0:
            detail_log.write('[bold green]No issues[/]')
        else:
            detail_log.write(f'[bold yellow]{issues} issue types found[/]')

    def action_clear_detail(self) -> None:
        """Esc: clear detail panel."""
        self._detail_mode = False
        label = self.query_one('#detail-label', Static)
        label.update('Detail — select a row above')
        detail_log = self.query_one('#detail-log', RichLog)
        detail_log.clear()

    def action_export_history(self) -> None:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = Env.app_path / f'history_{self.hostname}_{ts}.txt'
        lines = []
        for evt in self._display_events:
            src = self.error_tracker.event_source_slug(evt)
            err = evt.get('_error_slug', '')
            count = evt.get('count', 1)
            count_str = f' (x{count})' if count > 1 else ''
            tag = src or err
            tag_str = f' [{tag}]' if tag else ''
            lines.append(
                f"[{evt['since']:<8}] [{evt['level']}] [{evt['log_short']}]{tag_str} "
                f"{evt['provider']} ({evt['event_id']}): {evt['message']}{count_str}"
            )
        path.write_text('\n'.join(lines), encoding='utf-8')
        detail_log = self.query_one('#detail-log', RichLog)
        detail_log.clear()
        detail_log.write(f'[bold green]History exported: {_escape(str(path))}[/]')
        detail_log.write(f'{len(lines)} events')

    def action_export_errors(self) -> None:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = Env.app_path / f'errors_{self.hostname}_{ts}.txt'
        # Strip Rich markup for plain text
        table = self.error_tracker.format_table()
        clean = re.sub(r'\[/?[^\]]*\]', '', table)
        path.write_text(clean, encoding='utf-8')
        detail_log = self.query_one('#detail-log', RichLog)
        detail_log.clear()
        detail_log.write(f'[bold green]Errors exported: {_escape(str(path))}[/]')

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """When a history row is clicked/selected, show its detail."""
        idx = event.cursor_row
        if 0 <= idx < len(self._display_events):
            self._show_event_detail(self._display_events[idx])

    @work(thread=True)
    def load_history(self) -> None:
        table = self.query_one('#history-table', DataTable)
        history_label = self.query_one('#history-label', Static)

        # Try loading common error counts from stats (instant)
        stats_loaded = self.error_tracker.load_from_stats(self.stats_file)
        if stats_loaded:
            self.call_from_thread(self._refresh_errors_display)

        detail_log = self.query_one('#detail-log', RichLog)
        self.call_from_thread(detail_log.clear)

        def progress(msg):
            self.call_from_thread(setattr, self, 'sub_title', msg)
            self.call_from_thread(history_label.update, f'History — {msg}')

        all_events = []
        logs_with_events = 0
        total = len(self.log_names)
        for i, log_name in enumerate(self.log_names):
            short = log_name.split('/')[-1] if '/' in log_name else log_name
            progress(f'Loading [{i + 1}/{total}] {short}')
            events = query_events(log_name, self.level, self.days, self.max_msg_len)
            if events:
                logs_with_events += 1
            all_events.extend(events)
            self.call_from_thread(
                detail_log.write,
                f'  {short}: {len(events)} events'
            )

        progress(f'Sorting {len(all_events):,} events')
        all_events.sort(key=lambda e: e['datetime'])
        self._all_events = list(all_events)
        raw_count = len(all_events)

        # Tag events for dedup (sets _source, _error_slug, _source_value)
        for i, evt in enumerate(all_events):
            self.error_tracker.tag_event(evt)
            if not stats_loaded:
                self.error_tracker.match_history(evt)
            if i > 0 and i % 10000 == 0:
                progress(f'Processing {i:,}/{raw_count:,}')

        if not stats_loaded:
            self.call_from_thread(self._refresh_errors_display)

        progress(f'Deduplicating {raw_count:,} events')
        if self.do_dedup:
            display_events = deduplicate(all_events)
        else:
            display_events = all_events

        self._display_events = display_events
        self.call_from_thread(history_label.update, f'History — rendering {len(display_events)} rows...')

        for evt in display_events:
            count = evt.get('count', 1)
            count_str = str(count) if count > 1 else ''
            msg = evt['message'][:120] if len(evt['message']) > 120 else evt['message']
            source_name = self.error_tracker.event_source_slug(evt)
            self.call_from_thread(
                table.add_row,
                evt['since'],
                evt['level'],
                evt['log_short'],
                source_name,
                evt['provider'],
                str(evt['event_id']),
                msg,
                count_str,
            )
            if self._export_fh:
                self._export_fh.write(json.dumps({
                    'timestamp': evt['datetime'].isoformat(),
                    'since': evt['since'],
                    'level': evt['level'],
                    'event_id': evt['event_id'],
                    'provider': evt['provider'],
                    'log': evt['log'],
                    'message': evt['message'],
                    'count': count,
                }, ensure_ascii=False) + '\n')
                self._export_fh.flush()

        self.call_from_thread(
            history_label.update,
            f'History — {raw_count:,} ({len(display_events)} deduped) from {logs_with_events} logs, {self.days}d'
        )
        self.call_from_thread(detail_log.write, '')
        self.call_from_thread(detail_log.write,
            f'[bold green]Done: {raw_count:,} events -> {len(display_events)} rows[/]')
        self.call_from_thread(
            setattr, self, 'sub_title',
            f'{self.hostname} | {self.level}+ | {self.days}d | {logs_with_events} logs'
        )

        # Save stats
        self._save_stats_from_events(all_events)

    def _save_stats_from_events(self, events: list[dict]) -> None:
        stats = build_stats(events)
        ce, cs = self.error_tracker.as_stats_dict()
        save_stats(stats, self.stats_file, self.hostname,
                   common_errors=ce, common_sources=cs)

    def action_recalc_stats(self) -> None:
        self._do_recalc_stats()

    @work(thread=True)
    def _do_recalc_stats(self) -> None:
        detail_log = self.query_one('#detail-log', RichLog)
        detail_label = self.query_one('#detail-label', Static)

        def progress(msg):
            self.call_from_thread(detail_label.update, msg)

        path = recalculate_stats(
            self.log_names, self.level, self.days, self.max_msg_len,
            self.stats_file, self.hostname,
            error_tracker=self.error_tracker, progress_cb=progress,
        )
        self.call_from_thread(
            detail_log.write,
            f'[bold green]Stats saved to {_escape(str(path))}[/]'
        )
        self.call_from_thread(detail_label.update, 'Live tail')

    def action_refresh_errors(self) -> None:
        self._refresh_errors_display()

    def action_clear_logs(self) -> None:
        self._do_clear_logs()

    @work(thread=True)
    def _do_clear_logs(self) -> None:
        detail_log = self.query_one('#detail-log', RichLog)
        detail_label = self.query_one('#detail-label', Static)

        def progress(msg):
            self.call_from_thread(detail_label.update, msg)

        cleared, failed = clear_event_logs(self.log_names, progress_cb=progress)
        msg = f'[bold green]Cleared {cleared} logs[/]'
        if failed:
            msg += f' [bold red]({failed} failed — UAC declined?)[/]'
        self.call_from_thread(detail_log.write, msg)
        self.call_from_thread(detail_label.update, f'Live tail — cleared {cleared} logs')

    def on_unmount(self) -> None:
        if self._export_fh:
            self._export_fh.close()

    def action_toggle_dark(self) -> None:
        self.theme = 'textual-light' if self.theme == 'textual-dark' else 'textual-dark'


def _escape(text: str) -> str:
    return text.replace('[', '\\[')


# ── CLI stats mode ───────────────────────────────────────────────────────────

def run_stats_cli(log_names, level, days, max_msg_len, hostname):
    stats_file = stats_path_for_host(hostname)
    print(f'Recalculating stats for {hostname} -> {stats_file}')
    def progress(msg):
        print(f'  {msg}')
    error_tracker = CommonErrorTracker(Env.glob_dict('error_rules'),
                                       categories=Env.glob_dict('event_categories'))
    path = recalculate_stats(log_names, level, days, max_msg_len, stats_file, hostname,
                             error_tracker=error_tracker, progress_cb=progress)
    print(f'\nSaved: {path}')
    data = dict_from_yml(path)
    for log_name, severities in data.get('logs', {}).items():
        short = log_name.split('/')[-1] if '/' in log_name else log_name
        parts = [f'{sev}:{info["count"]}' for sev, info in severities.items()]
        print(f'  {short}: {", ".join(parts)}')


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Watch Windows Event Logs with TUI')
    parser.add_argument('--days', type=int, help='Override days from config')
    parser.add_argument('--level', help='Override level from config')
    parser.add_argument('--export', help='Export events to file (JSON)')
    parser.add_argument('--no-dedup', action='store_true', help='Disable deduplication')
    parser.add_argument('--all-logs', action='store_true', help='Watch ALL available event logs')
    parser.add_argument('--logs', nargs='+', help='Specific log names to watch')
    parser.add_argument('--stats', action='store_true', help='Recalculate host stats and exit')
    parser.add_argument('--clear-logs', action='store_true', help='Clear all configured event logs (needs admin)')
    args = parser.parse_args()

    Env(name='w11-events', app_path=Path(__file__).resolve().parent)
    Env.load()

    if args.all_logs:
        log_names = get_all_log_names()
    elif args.logs:
        log_names = args.logs
    else:
        log_names = Env.glob_list('logs', default=['Application', 'System', 'Security'])

    level = args.level or Env.glob('level', default='Warning')
    days = args.days or Env.glob_int('days', default=10)
    do_dedup = not args.no_dedup and Env.glob('dedup', default=True)
    max_msg_len = Env.glob_int('max_message_length', default=300)
    export_path = args.export
    hostname = socket.gethostname()

    # Common errors patterns (resolved via !include in YAML)
    error_tracker = CommonErrorTracker(Env.glob_dict('error_rules'),
                                       categories=Env.glob_dict('event_categories'))

    if args.clear_logs:
        print(f'Clearing {len(log_names)} logs (requires admin)...')
        cleared, failed = clear_event_logs(log_names, progress_cb=lambda m: print(f'  {m}'))
        print(f'Done: {cleared} cleared, {failed} failed')
        return

    if args.stats:
        run_stats_cli(log_names, level, days, max_msg_len, hostname)
        return

    app = EventLogApp(log_names, level, days, do_dedup, max_msg_len, export_path,
                      hostname, error_tracker)
    app.title = 'Event Log Watcher'
    app.sub_title = f'{hostname} | {level}+ | {days}d | {len(log_names)} logs'
    app.run()


if __name__ == '__main__':
    main()
