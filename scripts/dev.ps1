$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot 'common.ps1')

$backendPort = 8000
$frontendPort = 5173
$pythonPath = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
$nodeCommand = Assert-ProjectCommand -Name 'node'
$vitePath = Join-Path $script:ProjectRoot 'frontend\node_modules\vite\bin\vite.js'

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Project virtual environment not found. Run scripts/bootstrap.ps1 first.'
}
if (-not (Test-Path -LiteralPath $vitePath)) {
    throw 'Frontend dependencies not found. Run scripts/bootstrap.ps1 first.'
}
foreach ($port in @($backendPort, $frontendPort)) {
    if (-not (Test-ProjectPortAvailable -Port $port)) {
        throw "Port $port is already in use. No project process was started."
    }
}
foreach ($name in @('backend', 'frontend')) {
    $savedProcessId = Read-ProjectPid -Name $name
    if ($null -ne $savedProcessId -and (Get-Process -Id $savedProcessId -ErrorAction SilentlyContinue)) {
        throw "A saved project PID is still running: $name=$savedProcessId. Run scripts/stop.ps1 first."
    }
}

New-Item -ItemType Directory -Force -Path $script:RunDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $script:LogDirectory | Out-Null

$backendProcess = $null
$frontendProcess = $null
try {
    $backendProcess = Start-Process -FilePath $pythonPath -ArgumentList @(
        '-m', 'uvicorn', 'quant_lab.main:app',
        '--app-dir', (Join-Path $script:ProjectRoot 'backend\src'),
        '--host', '127.0.0.1', '--port', "$backendPort"
    ) -WorkingDirectory $script:ProjectRoot `
        -RedirectStandardOutput (Join-Path $script:LogDirectory 'backend.stdout.log') `
        -RedirectStandardError (Join-Path $script:LogDirectory 'backend.stderr.log') `
        -WindowStyle Hidden -PassThru
    Save-ProjectPid -Name 'backend' -ProcessId $backendProcess.Id

    $frontendProcess = Start-Process -FilePath $nodeCommand.Source -ArgumentList @(
        $vitePath, '--config', (Join-Path $script:ProjectRoot 'frontend\vite.config.ts'),
        '--host', '127.0.0.1', '--port', "$frontendPort"
    ) -WorkingDirectory (Join-Path $script:ProjectRoot 'frontend') `
        -RedirectStandardOutput (Join-Path $script:LogDirectory 'frontend.stdout.log') `
        -RedirectStandardError (Join-Path $script:LogDirectory 'frontend.stderr.log') `
        -WindowStyle Hidden -PassThru
    Save-ProjectPid -Name 'frontend' -ProcessId $frontendProcess.Id

    Start-Sleep -Seconds 2
    $backendProcess.Refresh()
    $frontendProcess.Refresh()
    if ($backendProcess.HasExited -or $frontendProcess.HasExited) {
        throw 'A service exited during startup. Inspect the logs directory.'
    }
} catch {
    foreach ($process in @($frontendProcess, $backendProcess)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id
        }
    }
    throw
}

Write-Output "Backend started: http://127.0.0.1:$backendPort (PID $($backendProcess.Id))"
Write-Output "Frontend started: http://127.0.0.1:$frontendPort (PID $($frontendProcess.Id))"
