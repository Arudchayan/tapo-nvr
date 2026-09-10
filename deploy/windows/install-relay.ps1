#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Installs the tapo-nvr relay as a boot-time Windows scheduled task.

.DESCRIPTION
    Creates an inbound firewall rule restricted to the configured CIDR ranges
    and registers the relay to start at boot under the SYSTEM account. Run this
    from an elevated PowerShell session.

.PARAMETER EnvFile
    Path to the environment file. Defaults to the repository's .env file.

.EXAMPLE
    .\install-relay.ps1
    .\install-relay.ps1 -EnvFile C:\tapo-nvr\.env
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

$logDirectory = Join-Path $env:ProgramData 'tapo-nvr'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logFile = Join-Path $logDirectory 'relay.log'

$ruleName = 'tapo-nvr relay'
Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort $relay.RelayPort -RemoteAddress $relay.Allowed -Profile Any | Out-Null

$arguments = '-m tapo_nvr.relay --bind {0} --listen-port {1} --target {2} --target-port {3} --allowed-cidr {4} --log-file "{5}"' -f `
    $relay.RelayHost, $relay.RelayPort, $relay.CameraHost, $relay.CameraPort, ($relay.Allowed -join ','), $logFile

$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel Highest
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName 'tapo-nvr relay' -Action $action -Trigger $trigger `
    -Principal $principal -Settings $taskSettings -Force | Out-Null
Start-ScheduledTask -TaskName 'tapo-nvr relay'
Start-Sleep -Seconds 3

$listening = Get-NetTCPConnection -State Listen -LocalPort $relay.RelayPort -ErrorAction SilentlyContinue
if (-not $listening) {
    throw "The relay was installed but nothing is listening on port $($relay.RelayPort). Check $logFile."
}

Write-Host "Relay installed: $($relay.RelayHost):$($relay.RelayPort) (scheduled task 'tapo-nvr relay')"
