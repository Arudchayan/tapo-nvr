# Shared helpers for the Windows relay installation scripts.

function Read-DotEnv {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing environment file: $Path. Copy .env.example to .env and fill it in."
    }

    $config = @{}
    $lineNumber = 0
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $lineNumber++
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith('#')) {
            continue
        }
        $separator = $line.IndexOf('=')
        if ($separator -lt 1) {
            throw "Invalid line $lineNumber in ${Path}: expected KEY=VALUE."
        }
        $key = $line.Substring(0, $separator).Trim()
        $value = $line.Substring($separator + 1).Trim()
        if ($value.Length -ge 2 -and ($value[0] -eq '"' -or $value[0] -eq "'")) {
            $quote = $value[0]
            $end = $value.IndexOf($quote, 1)
            if ($end -lt 0) {
                throw "Unterminated quote on line $lineNumber in $Path."
            }
            $value = $value.Substring(1, $end - 1)
        }
        elseif ($value.Contains(' #')) {
            $value = $value.Substring(0, $value.IndexOf(' #')).Trim()
        }
        $config[$key] = $value
    }
    return $config
}

function Get-DotEnvValue {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Config,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [string]$DefaultValue = ''
    )

    if ($Config.ContainsKey($Name) -and $Config[$Name]) {
        return $Config[$Name]
    }
    return $DefaultValue
}

function Resolve-PythonPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Config
    )

    $candidate = Get-DotEnvValue -Config $Config -Name 'PYTHON_PATH'
    if ($candidate -and (Test-Path -LiteralPath $candidate)) {
        return $candidate
    }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    throw "Could not find Python. Install Python 3.10+ or set PYTHON_PATH in .env."
}

function Resolve-TailscaleIp {
    [CmdletBinding()]
    param()

    $address = (tailscale ip -4 2>$null | Select-Object -First 1)
    if (-not $address) {
        throw "Could not determine this host's Tailscale IPv4 address."
    }
    return $address.Trim()
}

function Get-RelaySettings {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Config
    )

    $cameraHost = Get-DotEnvValue -Config $Config -Name 'CAMERA_HOST'
    if (-not $cameraHost) {
        throw 'CAMERA_HOST is required in .env.'
    }
    $cameraPort = [int](Get-DotEnvValue -Config $Config -Name 'CAMERA_RTSP_PORT' -DefaultValue '554')

    $relayHost = Get-DotEnvValue -Config $Config -Name 'RELAY_HOST'
    if (-not $relayHost -or $relayHost -eq 'auto') {
        $relayHost = Resolve-TailscaleIp
    }
    $relayPort = [int](Get-DotEnvValue -Config $Config -Name 'RELAY_PORT' -DefaultValue '8554')

    $allowedValue = Get-DotEnvValue -Config $Config -Name 'RELAY_ALLOWED_CIDR' -DefaultValue '100.64.0.0/10'
    $allowedCidrs = @(
        $allowedValue -split ',' |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    )

    return [pscustomobject]@{
        CameraHost = $cameraHost
        CameraPort = $cameraPort
        RelayHost  = $relayHost
        RelayPort  = $relayPort
        Allowed    = $allowedCidrs
    }
}

function Assert-TapoNvrInstalled {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath
    )

    & $PythonPath -c 'import tapo_nvr' 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "The tapo_nvr package is not installed for $PythonPath. Run: `"$PythonPath`" -m pip install ."
    }
}
