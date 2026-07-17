<#
Install a git post-commit hook so EVERY commit is automatically backed up to
the backup drive via scripts\backup.ps1 ("backup on each update").

Run once, from anywhere inside the repository:

  powershell -ExecutionPolicy Bypass -File scripts\install-backup-hook.ps1

Notes:
- The hook never blocks or fails a commit; if PowerShell or the backup drive
  is unavailable it prints a warning and moves on.
- Works in both layouts: quantum-engine nested inside a larger repo, or
  quantum-engine as the repository root.
#>

$ErrorActionPreference = 'Stop'

& git rev-parse --show-toplevel | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error 'Not inside a git repository. cd into the project first.'
    exit 1
}
$gitDir = (& git rev-parse --absolute-git-dir)
$hooksDir = Join-Path $gitDir 'hooks'
New-Item -ItemType Directory -Path $hooksDir -Force | Out-Null

# Git runs hooks with its bundled sh, so the hook is a small sh shim that
# locates backup.ps1 and hands off to PowerShell.
$hook = @'
#!/bin/sh
top="$(git rev-parse --show-toplevel)"
for s in "$top/quantum-engine/scripts/backup.ps1" "$top/scripts/backup.ps1"; do
  if [ -f "$s" ]; then
    if command -v powershell.exe >/dev/null 2>&1; then
      powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$s"
    elif command -v pwsh >/dev/null 2>&1; then
      pwsh -NoProfile -File "$s"
    else
      echo "post-commit backup: PowerShell not found; skipping" >&2
    fi
    exit 0
  fi
done
echo "post-commit backup: backup.ps1 not found; skipping" >&2
exit 0
'@

$hookPath = Join-Path $hooksDir 'post-commit'
[System.IO.File]::WriteAllText($hookPath, ($hook -replace "`r`n", "`n"))

Write-Host "Installed post-commit backup hook: $hookPath"
Write-Host 'Every git commit now backs up to F:\QuantumEngineBackups'
Write-Host '(override with the QE_BACKUP_ROOT environment variable).'
