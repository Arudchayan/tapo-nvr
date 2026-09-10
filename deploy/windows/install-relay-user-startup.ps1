<#
.SYNOPSIS
    Installs the tapo-nvr relay for the current user without administrator rights.

.DESCRIPTION
    Creates a shortcut in the user's Startup folder that starts the relay at
    logon. Prefer install-relay.ps1 when elevation is available, because the
    boot-time task also adds the required firewall rule.

.PARAMETER EnvFile
    Path to the environment file. Defaults to the repository's .env file.

.EXAMPLE
    .\install-relay-user-startup.ps1
#>
[CmdletBinding()]
param(
    [string]$EnvFile
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $EnvFile) {
    $EnvFile = Join-Path $repoRoot '.env'
}

$config = Read-DotEnv -Path $EnvFile
$python = Resolve-PythonPath -Config $config
Assert-TapoNvrInstalled -PythonPath $python
$relay = Get-RelaySettings -Config $config
Write-Host "Using Python: $python"

$logDirectory = Join-Path $env:LOCALAPPDATA 'tapo-nvr'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logFile = Join-Path $logDirectory 'relay.log'

$arguments = '-m tapo_nvr.relay --bind {0} --listen-port {1} --target {2} --target-port {3} --allowed-cidr {4} --log-file "{5}"' -f `
    $relay.Bind, $relay.RelayPort, $relay.CameraHost, $relay.CameraPort, ($relay.Allowed -join ','), $logFile

$startupFolder = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupFolder 'tapo-nvr relay.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $python
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $repoRoot
$shortcut.WindowStyle = 7
$shortcut.Description = 'tapo-nvr camera-only RTSP relay'
$shortcut.Save()

$alreadyRunning = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like '*tapo_nvr.relay*' }
if (-not $alreadyRunning) {
    Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $repoRoot -WindowStyle Hidden
}

Write-Host "Startup shortcut installed: $shortcutPath"
Write-Warning "If the relay is unreachable, allow inbound TCP port $($relay.RelayPort) or run install-relay.ps1 as administrator."
