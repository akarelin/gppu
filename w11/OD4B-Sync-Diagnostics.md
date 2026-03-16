# OneDrive for Business Sync Diagnostics

## Log Locations

### SyncDiagnostics (plain text, key file)
```
%LocalAppData%\Microsoft\OneDrive\logs\Business1\SyncDiagnostics.log
```

### SyncEngine logs (binary .odl/.aodl, need ODL Reader)
```
%LocalAppData%\Microsoft\OneDrive\logs\Business1\SyncEngine-*.aodl
%LocalAppData%\Microsoft\OneDrive\logs\Business1\SyncEngine-*.odl
```

### Other log directories
- `Business1/` — primary business account
- `Business2/` — secondary business account (if linked)
- `Common/` — FileCoAuth logs (co-authoring)
- `Personal/` — personal OneDrive
- `ListSync/` — SharePoint list sync

## SyncDiagnostics.log Key Fields

| Field | Meaning | Healthy Value |
|-------|---------|---------------|
| `ChangesToProcess` | Pending server changes | `0` |
| `ChangesToSend` | Pending local changes | `0` |
| `FilesToDownload` | Files still downloading | `0` |
| `FilesToUpload` | Files still uploading | `0` |
| `BytesToDownload` / `BytesDownloaded` | Download progress | Equal when done |
| `numFileFailedDownloads` | Failed download count | `0` |
| `numFileFailedUploads` | Failed upload count | `0` |
| `syncStallDetected` | OneDrive thinks it's stalled | `0` |
| `scanStateStallDetected` | Scan is stalled | `0` |
| `EstTimeRemainingInSec` | Estimated time to sync | `0` |
| `SyncProgressState` | Bitfield: 65536 = syncing | `0` when idle |

## Troubleshooting Stuck Sync

### Symptom: "Downloading 1 file, X MB of X MB" (100% but stuck)
File is fully downloaded but can't be finalized locally.

1. **Pause & Resume** — right-click tray icon
2. **Check file locks** — another app may hold the file open
3. **Reset OneDrive:**
   ```
   "C:\Program Files\Microsoft OneDrive\OneDrive.exe" /reset
   ```
   Note: Default path `%LocalAppData%\Microsoft\OneDrive\onedrive.exe` may not exist.
   Check registry for actual path:
   ```
   reg query "HKCU\Software\Microsoft\OneDrive" /v OneDriveTrigger
   ```

### After Reset
- OneDrive clears its local sync database
- Re-enumerates all files (shows "Processing N changes")
- `SyncDiagnostics.log` won't update until reset completes
- New `SyncEngine-*.odl` files will be generated with new PID
- Files are NOT deleted — only metadata is rebuilt

## Monitoring

### Watch SyncDiagnostics.log
```bash
tail -f "%LocalAppData%\Microsoft\OneDrive\logs\Business1\SyncDiagnostics.log"
```

### Quick health check (PowerShell)
```powershell
Get-Content "$env:LocalAppData\Microsoft\OneDrive\logs\Business1\SyncDiagnostics.log" |
  Select-String "FilesToDownload|FilesToUpload|ChangesToProcess|syncStallDetected|numFileFailedDownloads"
```

### Key indicators of a problem
- `BytesDownloaded == BytesToDownload` but `FilesToDownload > 0` — stuck finalizing
- `numFileFailedDownloads > 0` — download failures
- `syncStallDetected == 1` — OneDrive detected stall
- `EstTimeRemainingInSec` stays constant — no progress

## Registry Info
```
HKCU\Software\Microsoft\OneDrive
  OneDriveTrigger  = C:\Program Files\Microsoft OneDrive\OneDrive.exe
  Version          = 26.032.0217.0003
  UserDomainCollection = karelin
```
