$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$script:ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:RunDirectory = Join-Path $script:ProjectRoot '.run'
$script:LogDirectory = Join-Path $script:ProjectRoot 'logs'

function Assert-ProjectCommand {
    param([Parameter(Mandatory)][string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Required command '$Name' was not found. Install it and retry."
    }
    return $command
}

function Invoke-ProjectCommand {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($ArgumentList -join ' ')"
    }
}

function Test-ProjectPortAvailable {
    param([Parameter(Mandatory)][int]$Port)

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $null -eq $listener
}

function Read-ProjectPid {
    param([Parameter(Mandatory)][string]$Name)

    $pidPath = Join-Path $script:RunDirectory "$Name.pid"
    if (-not (Test-Path -LiteralPath $pidPath)) {
        return $null
    }
    [int]$savedProcessId = 0
    $rawValue = (Get-Content -Raw -LiteralPath $pidPath).Trim()
    if (-not [int]::TryParse($rawValue, [ref]$savedProcessId) -or $savedProcessId -le 0) {
        throw "Invalid PID file: $pidPath"
    }
    return $savedProcessId
}

function Save-ProjectPid {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][int]$ProcessId
    )

    New-Item -ItemType Directory -Force -Path $script:RunDirectory | Out-Null
    $pidPath = Join-Path $script:RunDirectory "$Name.pid"
    Set-Content -LiteralPath $pidPath -Value $ProcessId -Encoding ascii
}

function Test-ProjectProcess {
    param(
        [Parameter(Mandatory)][int]$ProcessId,
        [Parameter(Mandatory)][string]$ExpectedFragment
    )

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process -or [string]::IsNullOrWhiteSpace($process.CommandLine)) {
        return $false
    }
    $identityText = "$($process.ExecutablePath) $($process.CommandLine)"
    $containsProject = $identityText.IndexOf(
        $script:ProjectRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -ge 0
    $containsFragment = $identityText.IndexOf(
        $ExpectedFragment,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -ge 0
    return $containsProject -and $containsFragment
}
