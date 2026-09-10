param(
    [ValidateSet('start', 'status', 'stop')][string]$Action = 'status',
    [string]$ProfilePath,
    [string]$RuntimeRoot,
    [ValidateRange(1024, 65535)][int]$Port = 8011,
    [switch]$Fake
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$requestedHostRuntime = $RuntimeRoot
. (Join-Path $PSScriptRoot 'common.ps1')

if (-not $requestedHostRuntime) {
    $requestedHostRuntime = Join-Path $script:ProjectRoot 'runtime\ai-provider-host'
}
$hostRuntime = [IO.Path]::GetFullPath($requestedHostRuntime)
$statePath = Join-Path $hostRuntime 'process.json'
$tokenPath = Join-Path $hostRuntime '.secrets\ai-provider-host.token'
$pythonPath = Join-Path $script:ProjectRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
}

function Get-OwnedHost($state) {
    $hostProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$state.process_id)"
    if ($null -eq $hostProcess) { return $null }
    if ($hostProcess.CreationDate.ToUniversalTime().ToString('o') -ne $state.created_at -or
        $hostProcess.ExecutablePath -ne $pythonPath -or
        -not $hostProcess.CommandLine.Contains('quant_lab.ai_provider_host') -or
        -not $hostProcess.CommandLine.Contains($tokenPath)) {
        throw 'AI_HOST_PID_OWNERSHIP_MISMATCH'
    }
    return $hostProcess
}

function Stop-OwnedHost($owned) {
    # A Windows venv launcher can have a base-interpreter child. Validate exact lineage
    # and invocation before stopping it; never terminate arbitrary Python processes.
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($owned.ProcessId)")
    foreach ($child in $children) {
        if ($child.CommandLine -and $child.CommandLine.Contains('quant_lab.ai_provider_host') -and
            $child.CommandLine.Contains($tokenPath) -and $child.CreationDate -ge $owned.CreationDate) {
            Stop-Process -Id $child.ProcessId -ErrorAction Stop
        }
    }
    Stop-Process -Id $owned.ProcessId -ErrorAction SilentlyContinue
    Wait-Process -Id $owned.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
}

# An OS handle serializes all operations, including separate PowerShell processes.
# Keep the empty lock file: deleting it can split waiters across different files.
New-Item -ItemType Directory -Path $hostRuntime -Force | Out-Null
$operationLock = $null
$lockDeadline = [DateTime]::UtcNow.AddSeconds(30)
while ($null -eq $operationLock) {
    try {
        $operationLock = [IO.File]::Open((Join-Path $hostRuntime '.operation.lock'),
            [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] {
        if ([DateTime]::UtcNow -ge $lockDeadline) { throw 'AI_HOST_RUNTIME_BUSY' }
        Start-Sleep -Milliseconds 100
    }
}
try {
$savedState = $null
if (Test-Path -LiteralPath $statePath) {
    $savedState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
}
if ($Action -eq 'status') {
    if ($null -ne $savedState -and $null -ne (Get-OwnedHost $savedState)) {
        Write-Output "AI Host running: PID $($savedState.process_id), port $($savedState.port)"
    } else { Write-Output 'AI Host stopped' }
    exit 0
}
if ($Action -eq 'stop') {
    if ($null -eq $savedState) { Write-Output 'AI Host stopped'; exit 0 }
    $owned = Get-OwnedHost $savedState
    if ($null -ne $owned) {
        Stop-OwnedHost $owned
    }
    # Exact owned files only; no recursive cleanup and no process-name termination.
    Remove-Item -LiteralPath $tokenPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $statePath -Force
    Write-Output 'AI Host stopped; token removed'
    exit 0
}
if ($null -ne $savedState -and $null -ne (Get-OwnedHost $savedState)) {
    throw 'AI_HOST_ALREADY_RUNNING'
}
if ($null -eq $savedState -and (Test-Path -LiteralPath $tokenPath)) {
    throw 'AI_HOST_UNOWNED_TOKEN'
}
if (-not $ProfilePath -or -not (Test-Path -LiteralPath $ProfilePath -PathType Leaf)) {
    throw 'AI_HOST_PROFILE_REQUIRED'
}
if (-not (Test-ProjectPortAvailable -Port $Port)) { throw 'AI_HOST_PORT_IN_USE' }
$resolvedProfile = (Resolve-Path -LiteralPath $ProfilePath).Path
foreach ($argumentPath in @($resolvedProfile, $tokenPath)) {
    if ($argumentPath.Contains('"')) { throw 'AI_HOST_PATH_INVALID' }
}
New-Item -ItemType Directory -Path $hostRuntime -Force | Out-Null
if ($null -ne $savedState) {
    Remove-Item -LiteralPath $tokenPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $statePath -Force
}
$hostArguments = @('-m', 'quant_lab.ai_provider_host', 'serve', '--profile',
    ('"' + $resolvedProfile + '"'), '--token-file', ('"' + $tokenPath + '"'), '--port', "$Port")
if ($Fake) { $hostArguments += '--fake' }
# Windows PowerShell 5 Start-Process merges Path case-sensitively internally.
# Python-launched shells may inherit PATH instead. Normalize only this process.
$hostInheritedPath = [Environment]::GetEnvironmentVariable('PATH', 'Process')
[Environment]::SetEnvironmentVariable('PATH', $null, 'Process')
[Environment]::SetEnvironmentVariable('Path', $hostInheritedPath, 'Process')
$started = Start-Process -FilePath $pythonPath -ArgumentList $hostArguments `
    -WorkingDirectory $script:ProjectRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $hostRuntime 'stdout.log') `
    -RedirectStandardError (Join-Path $hostRuntime 'stderr.log')
$record = $null
try {
    $record = Get-CimInstance Win32_Process -Filter "ProcessId = $($started.Id)"
    if ($null -eq $record) { throw 'AI_HOST_START_FAILED' }
    @{process_id=$started.Id; created_at=$record.CreationDate.ToUniversalTime().ToString('o'); port=$Port} |
        ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while ([DateTime]::UtcNow -lt $deadline) {
        $started.Refresh()
        if ($started.HasExited) { throw 'AI_HOST_START_FAILED' }
        if ((Test-Path -LiteralPath $tokenPath) -and -not (Test-ProjectPortAvailable -Port $Port)) {
            Write-Output "AI Host started: http://127.0.0.1:$Port (PID $($started.Id))"
            exit 0
        }
        Start-Sleep -Milliseconds 100
    }
    throw 'AI_HOST_START_TIMEOUT'
} catch {
    $started.Refresh()
    if (-not $started.HasExited) {
        if ($null -ne $record) { Stop-OwnedHost $record }
        else { $started.Kill(); $started.WaitForExit(10000) | Out-Null }
    }
    # Under the exclusive runtime lock both paths were absent before this launch.
    # Stop this launch before removing its resources; pre-existing unowned tokens
    # are rejected above and can never reach this cleanup.
    Remove-Item -LiteralPath $tokenPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    throw
}
} finally {
    $operationLock.Dispose()
}
