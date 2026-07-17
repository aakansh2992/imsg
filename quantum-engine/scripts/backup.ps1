<#
Back up the Quantum Engine project to a timestamped folder on a backup drive.

Default destination: F:\QuantumEngineBackups\<timestamp>_<git-sha>\ containing
  quantum-engine\   a browsable copy of the working tree
  repo.bundle       the FULL git history in one file (restore with:
                    git clone repo.bundle restored)

Usage (from the quantum-engine folder):
  powershell -ExecutionPolicy Bypass -File scripts\backup.ps1
  powershell -ExecutionPolicy Bypass -File scripts\backup.ps1 -BackupRoot "D:\Backups" -Keep 30

Set the root once for all runs with the QE_BACKUP_ROOT environment variable.
To back up automatically on every commit, run scripts\install-backup-hook.ps1 once.
#>

param(
    [string]$BackupRoot = $(if ($env:QE_BACKUP_ROOT) { $env:QE_BACKUP_ROOT } else { 'F:\QuantumEngineBackups' }),
    [int]$Keep = 0   # 0 = keep every backup; N > 0 = keep only the N newest
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot

$driveRoot = [System.IO.Path]::GetPathRoot($BackupRoot)
if (-not (Test-Path $driveRoot)) {
    Write-Error ("Backup drive '$driveRoot' not found. Pass -BackupRoot <path> or set " +
                 "QE_BACKUP_ROOT to a location that exists on this machine.")
    exit 1
}

$stamp = Get-Date -Format 'yyyy-MM-dd_HH-mm-ss'
$sha = ''
try {
    $sha = (& git -C $projectRoot rev-parse --short HEAD 2>$null)
    if ($LASTEXITCODE -ne 0) { $sha = '' }
} catch { $sha = '' }

$name = if ($sha) { "${stamp}_${sha}" } else { $stamp }
$dest = Join-Path $BackupRoot $name
New-Item -ItemType Directory -Path $dest -Force | Out-Null

# 1) Browsable copy of the working tree (caches and VCS internals excluded).
$copyDest = Join-Path $dest 'quantum-engine'
& robocopy $projectRoot $copyDest /E /R:2 /W:2 `
    /XD .git __pycache__ .pytest_cache .venv venv .eggs build dist `
    /XF *.pyc | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error "robocopy failed with exit code $LASTEXITCODE"
    exit 1
}

# 2) Full git history as a single restorable file.
if ($sha) {
    & git -C $projectRoot bundle create (Join-Path $dest 'repo.bundle') --all | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'git bundle failed; working-tree copy was still written.'
    }
}

if ($Keep -gt 0) {
    Get-ChildItem -Directory $BackupRoot |
        Sort-Object Name -Descending |
        Select-Object -Skip $Keep |
        Remove-Item -Recurse -Force
}

Write-Host "Backed up to $dest"
