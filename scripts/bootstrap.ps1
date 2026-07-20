$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot 'common.ps1')

$uvCommand = Assert-ProjectCommand -Name 'uv'
[void](Assert-ProjectCommand -Name 'node')
$npmCommand = Assert-ProjectCommand -Name 'npm.cmd'

$env:UV_PROJECT_ENVIRONMENT = Join-Path $script:ProjectRoot '.venv'
$env:UV_CACHE_DIR = Join-Path $script:ProjectRoot '.uv-cache'

Push-Location $script:ProjectRoot
try {
    Invoke-ProjectCommand -FilePath $uvCommand.Source -ArgumentList @(
        'sync', '--project', 'backend', '--all-groups'
    )

    Push-Location (Join-Path $script:ProjectRoot 'frontend')
    try {
        $npmAction = if (Test-Path -LiteralPath 'package-lock.json') { 'ci' } else { 'install' }
        Invoke-ProjectCommand -FilePath $npmCommand.Source -ArgumentList @(
            $npmAction, '--no-audit', '--no-fund'
        )
    } finally {
        Pop-Location
    }
} finally {
    Pop-Location
}

Write-Output 'Project dependencies are installed in .venv and frontend/node_modules.'
