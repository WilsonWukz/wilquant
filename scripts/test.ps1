$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot 'common.ps1')

$pythonPath = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
$npmCommand = Assert-ProjectCommand -Name 'npm.cmd'
$powershellCommand = Assert-ProjectCommand -Name 'powershell.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Project virtual environment not found. Run scripts/bootstrap.ps1 first.'
}

Push-Location $script:ProjectRoot
try {
    $env:RUFF_CACHE_DIR = Join-Path ([System.IO.Path]::GetTempPath()) 'quant-lab-ruff-cache'
    Invoke-ProjectCommand -FilePath $powershellCommand.Source -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $script:ProjectRoot 'scripts\test_common.ps1')
    )
    Invoke-ProjectCommand -FilePath $pythonPath -ArgumentList @(
        '-m', 'pytest', 'backend/tests', '-q'
    )
    Invoke-ProjectCommand -FilePath $pythonPath -ArgumentList @(
        '-m', 'ruff', 'check', 'backend/src', 'backend/tests', 'backend/alembic'
    )
    Invoke-ProjectCommand -FilePath $pythonPath -ArgumentList @(
        '-m', 'mypy', 'backend/src'
    )

    Push-Location (Join-Path $script:ProjectRoot 'frontend')
    try {
        Invoke-ProjectCommand -FilePath $npmCommand.Source -ArgumentList @('run', 'test:run')
        Invoke-ProjectCommand -FilePath $npmCommand.Source -ArgumentList @('run', 'build')
    } finally {
        Pop-Location
    }
} finally {
    Pop-Location
}

Write-Output 'All backend and frontend checks passed.'
