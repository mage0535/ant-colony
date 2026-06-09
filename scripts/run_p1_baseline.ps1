$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot\..

Write-Host "== P-1 baseline: environment snapshot =="
./scratchpad/p1_verify_env.ps1

Write-Host "`n== P-1 baseline: import verification =="
python ./scratchpad/p1_verify_imports.py

Write-Host "`n== P-1 baseline: smoke tests =="
./scripts/run_smoke_test.ps1
