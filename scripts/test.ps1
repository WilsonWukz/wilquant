$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot 'common.ps1')

$backendPython = Join-Path $script:ProjectRoot 'backend\.venv\Scripts\python.exe'
$rootPython = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
$pythonPath = if (Test-Path -LiteralPath $backendPython) { $backendPython } else { $rootPython }
$npmCommand = Assert-ProjectCommand -Name 'npm.cmd'
$powershellCommand = Assert-ProjectCommand -Name 'powershell.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Backend virtual environment not found. Run scripts/bootstrap.ps1 first.'
}

$tempRoot = [System.IO.Path]::GetTempPath()

$foundationFiles = @(
    'backend/tests/test_config.py',
    'backend/tests/test_duckdb.py',
    'backend/tests/test_health_api.py',
    'backend/tests/test_logging.py',
    'backend/tests/test_phase_2c_openapi.py',
    'backend/tests/test_sqlite.py',
    'backend/tests/test_sqlite_bootstrap.py'
)
$datasetsShardA = @(
    'backend/tests/datasets/test_dataset_api.py',
    'backend/tests/datasets/test_dataset_repository.py',
    'backend/tests/datasets/test_fingerprints.py',
    'backend/tests/datasets/test_migration.py'
)
$datasetsShardB = @(
    'backend/tests/datasets/test_persistence.py',
    'backend/tests/datasets/test_processing.py',
    'backend/tests/datasets/test_publication_claim.py',
    'backend/tests/datasets/test_publication_pipeline.py'
)

Push-Location $script:ProjectRoot
try {
    $actualDatasetFiles = @(
        Get-ChildItem -Path 'backend/tests/datasets' -Filter 'test_*.py' -File |
            ForEach-Object { 'backend/tests/datasets/' + $_.Name }
    ) | Sort-Object
    $declaredDatasetFiles = @($datasetsShardA) + @($datasetsShardB) | Sort-Object
    $actualJoined = $actualDatasetFiles -join [Environment]::NewLine
    $declaredJoined = $declaredDatasetFiles -join [Environment]::NewLine
    if ($actualJoined -ne $declaredJoined) {
        $missing = @($actualDatasetFiles) | Where-Object { $_ -notin $declaredDatasetFiles }
        $extra = @($declaredDatasetFiles) | Where-Object { $_ -notin $actualDatasetFiles }
        throw "Dataset shard coverage mismatch. Missing from shards: [$($missing -join ', ')] Extra: [$($extra -join ', ')]"
    }
    $overlap = @($datasetsShardA) | Where-Object { $_ -in $datasetsShardB }
    if ($overlap) {
        throw "Dataset shards overlap: [$($overlap -join ', ')]"
    }
    $actualFoundationFiles = @(
        Get-ChildItem -Path 'backend/tests' -Filter 'test_*.py' -File |
            ForEach-Object { 'backend/tests/' + $_.Name }
    ) | Sort-Object
    $declaredFoundationFiles = @($foundationFiles) | Sort-Object
    if (($actualFoundationFiles -join [Environment]::NewLine) -ne ($declaredFoundationFiles -join [Environment]::NewLine)) {
        $missing = @($actualFoundationFiles) | Where-Object { $_ -notin $declaredFoundationFiles }
        $extra = @($declaredFoundationFiles) | Where-Object { $_ -notin $actualFoundationFiles }
        throw "Foundation coverage mismatch. Missing: [$($missing -join ', ')] Extra: [$($extra -join ', ')]"
    }

    function Invoke-PytestShard {
        param(
            [Parameter(Mandatory)][string]$Name,
            [Parameter(Mandatory)][string[]]$Paths
        )

        $basetemp = Join-Path $tempRoot ("quant-lab-pytest-" + $Name + "-" + [guid]::NewGuid().ToString('N'))
        $arguments = @('-m', 'pytest') + $Paths + @('-q', '-p', 'no:cacheprovider', '--basetemp', $basetemp)
        Invoke-ProjectCommand -FilePath $pythonPath -ArgumentList $arguments
    }

    $env:RUFF_CACHE_DIR = Join-Path $tempRoot 'quant-lab-ruff-cache'
    $env:MYPY_CACHE_DIR = Join-Path $tempRoot 'quant-lab-mypy-cache'
    Invoke-ProjectCommand -FilePath $powershellCommand.Source -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $script:ProjectRoot 'scripts\test_common.ps1')
    )
    Invoke-PytestShard -Name 'foundation' -Paths $foundationFiles
    Invoke-PytestShard -Name 'datasets-a' -Paths $datasetsShardA
    Invoke-PytestShard -Name 'datasets-b' -Paths $datasetsShardB
    Invoke-PytestShard -Name 'market-data' -Paths @('backend/tests/market_data')
    Invoke-PytestShard -Name 'backtest' -Paths @('backend/tests/backtest')
    Invoke-PytestShard -Name 'research' -Paths @('backend/tests/research')
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
