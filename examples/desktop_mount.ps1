# Desktop launcher. Python reads desktop.yaml and owns the mount in the foreground.
$ErrorActionPreference = 'Stop'
$desktopPython = Join-Path $HOME '.venv/Scripts/python.exe'
$desktopLog = 'C:/.cache/gppufs-desktop'
New-Item -ItemType Directory -Path $desktopLog -Force | Out-Null
Start-Process -FilePath $desktopPython -ArgumentList @('-u', (Join-Path $PSScriptRoot 'desktop_mount.py')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $desktopLog 'stdout.log') -RedirectStandardError (Join-Path $desktopLog 'stderr.log')
