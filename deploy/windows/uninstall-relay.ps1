#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Removes the tapo-nvr relay scheduled task, firewall rule, and startup shortcut.

.PARAMETER KeepFirewallRule
    Keep the inbound firewall rule instead of removing it.

.EXAMPLE
    .\uninstall-relay.ps1
#>
[CmdletBinding()]
param(
    [switch]$KeepFirewallRule
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

Stop-ScheduledTask -TaskName 'tapo-nvr relay' -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName 'tapo-nvr relay' -Confirm:$false -ErrorAction SilentlyContinue

if (-not $KeepFirewallRule) {
    Get-NetFirewallRule -DisplayName 'tapo-nvr relay' -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule
}

$shortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'tapo-nvr relay.lnk'
Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue

Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like '*tapo_nvr.relay*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host 'tapo-nvr relay was removed.'
