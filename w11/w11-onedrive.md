# w11-onedrive — OneDrive Sync Diagnostics & Conflict Cleanup

TUI tool for diagnosing OneDrive for Business sync issues and cleaning up hostname-based conflict files.

## Usage

```bash
python w11-onedrive.py                     # interactive mode selector
python w11-onedrive.py diag                # sync diagnostics (all accounts)
python w11-onedrive.py diag --watch        # auto-refresh health every 10s
python w11-onedrive.py diag --account Business1
python w11-onedrive.py conflicts           # conflict analysis (interactive)
python w11-onedrive.py conflicts --hostname Mailstore
```

## Mode 1: Sync Diagnostics (`diag`)

Multi-account tabbed view showing per-account sync health.

### Data Sources

| Source | Path | What it tells us |
|--------|------|-----------------|
| `SyncDiagnostics.log` | `%LOCALAPPDATA%\Microsoft\OneDrive\logs\{Account}\` | Sync progress, stall detection, file counts |
| `downloads3.txt` | `%LOCALAPPDATA%\Microsoft\OneDrive\settings\{Account}\` | Stuck download queue (UTF-16LE, locked by OD) |
| `SyncEngineDatabase.db` | `%LOCALAPPDATA%\Microsoft\OneDrive\settings\{Account}\` | SQLite DB with file records, postponed changes, hydrations |
| Registry | `HKCU\Software\Microsoft\OneDrive\Accounts\{Account}` | UserFolder, UserEmail |

### Panels

- **Health** — sync stall flags, failed counts, uptime, file/folder totals
- **Stuck/Errored Files** — downloads stuck in queue, postponed changes (with retry count), active hydrations
- **Progress** — real-time sync counters (files/bytes to download/upload)
- **Detail** — full info on selected row with recommendations

### Keybindings

| Key | Action |
|-----|--------|
| `r` | Refresh all data |
| `n` | Normalize filename (fix trailing spaces, illegal chars) |
| `x` | Reset OneDrive (two-step: first press arms, second confirms) |
| `d` | Toggle dark/light mode |
| `Esc` | Clear detail panel / cancel armed reset |
| `q` | Quit |

### What it detects

- **Stuck finalizing**: `BytesDownloaded == BytesToDownload` but `FilesToDownload > 0`
- **Filename issues**: trailing whitespace, space before extension, illegal Windows chars
- **Orphaned postponed changes**: parent folders missing from sync scope (common with SharePoint folder shortcuts)
- **Stalled syncs**: `syncStallDetected` / `scanStateStallDetected` flags

### OneDrive Reset (`x`)

Runs `OneDrive.exe /reset`. This:
- Kills the OneDrive process
- Clears the local sync database
- Does NOT delete files
- Re-enumerates all files on restart (shows "Processing N changes")

The exe path is resolved from `HKCU\Software\Microsoft\OneDrive\OneDriveTrigger` or known install locations.

## Mode 2: Conflict Analysis (`conflicts`)

OneDrive creates conflict copies when the same file is modified on multiple machines. The naming pattern is `{name}-{hostname}.{ext}`.

### How it works

1. Scans the OneDrive folder for files matching `-{hostname}.{ext}` pattern
2. Verifies the base file exists (without the hostname suffix)
3. Shows pairs with dates and sizes for comparison
4. Allows selective or bulk deletion of conflict files

### Keybindings

| Key | Action |
|-----|--------|
| `r` | Re-scan |
| `Delete` | Delete selected conflict file |
| `a` | Delete ALL conflict files (two-step confirmation) |
| `d` | Toggle dark/light |
| `Esc` | Cancel armed delete-all |
| `q` | Quit |

### Hostname discovery

On startup, scans the OneDrive folder to detect which hostnames appear as conflict suffixes. Filters out common English words (alt, copy, small, etc.) and requires the hostname to start with uppercase.

## Account discovery

Accounts are auto-discovered by scanning `%LOCALAPPDATA%\Microsoft\OneDrive\logs\` for directories that contain a `SyncDiagnostics.log`. Common accounts:

| Folder | Type |
|--------|------|
| `Business1` | Primary business account |
| `Business2` | Secondary business account |
| `Personal` | Personal OneDrive |

## Dependencies

- Python 3.10+
- `textual` (TUI framework)
- Windows only (uses `winreg`, `ctypes`, OneDrive-specific paths)

## Known limitations

- ODL/AODL binary logs are not parsed (require Microsoft's ODL Reader)
- Conflict hostname detection can have false positives for short names
- SharePoint folder shortcuts ("Add to My files") often cause permanently postponed changes that only a reset can clear
