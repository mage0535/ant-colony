$ErrorActionPreference = "Continue"

Set-Location $PSScriptRoot\..

Write-Host "== P-1 full check: baseline =="
./scripts/run_p1_baseline.ps1

Write-Host "`n== P-1 full check: components =="
./scripts/run_p1_components.ps1
