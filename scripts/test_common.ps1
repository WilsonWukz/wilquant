$ErrorActionPreference = 'Stop'

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

Remove-Item -LiteralPath $pidPath -Force
Write-Output 'PowerShell common helper tests passed.'
