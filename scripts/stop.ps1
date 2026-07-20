$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot 'common.ps1')

$processDefinitions = @(
    @{ Name = 'frontend'; Fragment = 'vite.js' },
    @{ Name = 'backend'; Fragment = 'quant_lab.main:app' }
)

foreach ($definition in $processDefinitions) {
    $name = $definition.Name
    $pidPath = Join-Path $script:RunDirectory "$name.pid"
    $savedProcessId = Read-ProjectPid -Name $name
    if ($null -eq $savedProcessId) {
        Write-Output "${name}: no PID record."
        continue
    }

    $process = Get-Process -Id $savedProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        Remove-Item -LiteralPath $pidPath -Force
        Write-Output "${name}: process already exited; removed stale PID record."
        continue
    }
    if (-not (Test-ProjectProcess -ProcessId $savedProcessId -ExpectedFragment $definition.Fragment)) {
        throw "$name PID $savedProcessId does not belong to this project; refusing to stop it."
    }

    Stop-Process -Id $savedProcessId
    Wait-Process -Id $savedProcessId -Timeout 10 -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $pidPath -Force
    Write-Output "${name}: stopped PID $savedProcessId."
}
