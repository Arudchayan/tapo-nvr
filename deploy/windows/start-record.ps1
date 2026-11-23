<#
.SYNOPSIS
    Runs and supervises `tapo-nvr record` for the current user.

.DESCRIPTION
    Started from the user's Startup folder at logon. The recorder writes its own
    rotating log and JSON heartbeat under RECORD_STAGING_DIR. This wrapper
    restarts it after a failure, backing off when the recorder paused because
    staging is full. A clean Ctrl+C exit (0) ends the supervisor.
#>
[CmdletBinding()]
param(
    [string]$Staging = 'E:\tapo-staging'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$envFile = Join-Path $repoRoot '.env'
$startupLog = Join-Path $env:LOCALAPPDATA 'tapo-nvr\start-record.log'

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $startupLog) | Out-Null

function Write-StartupLog {
    param([string]$Message)
    Add-Content -LiteralPath $startupLog -Encoding UTF8 `
        -Value ("{0:o} {1}" -f (Get-Date), $Message)
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-StartupLog "missing Python: $python"
    exit 1
}
if (-not (Test-Path -LiteralPath $envFile)) {
    Write-StartupLog "missing environment file: $envFile"
    exit 1
}

while ($true) {
    & $python -m tapo_nvr record --env $envFile
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        Write-StartupLog 'recorder stopped cleanly'
        exit 0
    }

    $delay = 10
    $statusPath = Join-Path $Staging 'status.json'
    if (Test-Path -LiteralPath $statusPath) {
        try {
            $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
            if ($status.state -eq 'paused' -or $status.exit_code -eq 3) {
                $delay = 600
            }
            elseif ($status.exit_code -eq 2) {
                $delay = 300
            }
        }
        catch {
            Write-StartupLog "could not read recorder status: $($_.Exception.Message)"
        }
    }

    Write-StartupLog "recorder exited $code; restarting in ${delay}s"
    Start-Sleep -Seconds $delay
}
