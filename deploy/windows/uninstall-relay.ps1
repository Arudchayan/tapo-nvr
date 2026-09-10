<#
.SYNOPSIS
    Removes the tapo-nvr relay scheduled task, firewall rule, and startup shortcut.

.DESCRIPTION
    Run this from an elevated PowerShell session to remove everything. When it
    is not elevated it still removes the user Startup shortcut and stops relay
    processes, and skips the scheduled task and firewall rule with a warning.

.PARAMETER KeepFirewallRule
    Keep the inbound firewall rule instead of removing it (elevated only).

.EXAMPLE
    .\uninstall-relay.ps1
#>
[CmdletBinding()]
param(
    [switch]$KeepFirewallRule
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if ($isAdmin) {
    Stop-ScheduledTask -TaskName 'tapo-nvr relay' -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName 'tapo-nvr relay' -Confirm:$false -ErrorAction SilentlyContinue

    if (-not $KeepFirewallRule) {
        Get-NetFirewallRule -DisplayName 'tapo-nvr relay' -ErrorAction SilentlyContinue |
            Remove-NetFirewallRule
    }
}
else {
    Write-Warning 'Not elevated: skipping scheduled task and firewall rule cleanup.'
}

foreach ($name in @('tapo-nvr relay.lnk', 'Tapo C220 RTSP Relay.lnk')) {
    $shortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) $name
    Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue
}

Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like '*tapo_nvr.relay*' -or $_.CommandLine -like '*rtsp_relay*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host 'tapo-nvr relay was removed.'
