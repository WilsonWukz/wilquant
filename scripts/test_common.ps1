$ErrorActionPreference = 'Stop'

$previousRuntimeRoot = $env:QUANT_LAB_RUNTIME_ROOT
$runtimeTestRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) "quant-lab-runtime-$PID-$([guid]::NewGuid().ToString('N'))"
try {
    $env:QUANT_LAB_RUNTIME_ROOT = $runtimeTestRoot
    . (Join-Path $PSScriptRoot 'common.ps1')

    $testName = 'common-test'
    $pidPath = Join-Path $script:RunDirectory "$testName.pid"
    Save-ProjectPid -Name $testName -ProcessId $PID
    $savedProcessId = Read-ProjectPid -Name $testName
    if ($savedProcessId -ne $PID) {
        throw "PID round trip failed: expected $PID, got $savedProcessId"
    }

    if (-not (Test-ProjectProcess -ProcessId $PID -ExpectedFragment 'test_common.ps1')) {
        throw 'Current test process was not recognized as a project process'
    }

    Set-Content -LiteralPath $pidPath -Value 'not-a-pid' -Encoding ascii
    $invalidPidRejected = $false
    try {
        [void](Read-ProjectPid -Name $testName)
    } catch {
        $invalidPidRejected = $true
    }
    if (-not $invalidPidRejected) {
        throw 'Malformed PID file was accepted'
    }

    if ($script:RunDirectory -ne (Join-Path $runtimeTestRoot '.run')) {
        throw 'Absolute runtime-root PID directory was not applied'
    }
    if ($script:LogDirectory -ne (Join-Path $runtimeTestRoot 'logs')) {
        throw 'Absolute runtime-root log directory was not applied'
    }

    $pytestTempDirectory = Join-Path (
        [System.IO.Path]::GetTempPath()
    ) "quant-lab-pytest-common-$PID-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Force -Path $pytestTempDirectory | Out-Null
    Set-Content -LiteralPath (Join-Path $pytestTempDirectory 'sentinel.txt') -Value 'temporary' -Encoding ascii
    Remove-ProjectTestTempDirectory -Path $pytestTempDirectory
    if (Test-Path -LiteralPath $pytestTempDirectory) {
        throw 'Pytest temp directory cleanup did not remove the approved directory'
    }

    $unsafeCleanupRejected = $false
    try {
        Remove-ProjectTestTempDirectory -Path $runtimeTestRoot
    } catch {
        $unsafeCleanupRejected = $true
    }
    if (-not $unsafeCleanupRejected) {
        throw 'Pytest temp directory cleanup accepted a path without the required prefix'
    }

    $relativeRuntimeRoot = "runtime-test-$PID"
    $env:QUANT_LAB_RUNTIME_ROOT = $relativeRuntimeRoot
    . (Join-Path $PSScriptRoot 'common.ps1')
    $expectedRelativeRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $script:ProjectRoot $relativeRuntimeRoot)
    )
    if ($script:RuntimeRoot -ne $expectedRelativeRoot) {
        throw 'Relative runtime root was not anchored to the project root'
    }
} finally {
    $env:QUANT_LAB_RUNTIME_ROOT = $previousRuntimeRoot
    if (Test-Path -LiteralPath $runtimeTestRoot) {
        Remove-Item -LiteralPath $runtimeTestRoot -Recurse -Force
    }
}
Write-Output 'PowerShell common helper tests passed.'
