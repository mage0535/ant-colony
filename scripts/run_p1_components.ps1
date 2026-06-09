$ErrorActionPreference = "Continue"

Set-Location $PSScriptRoot\..

Write-Host "== P-1 component check: OpenVort =="
python ./scratchpad/p1_verify_openvort.py

Write-Host "`n== P-1 component check: Hermes =="
python ./scratchpad/p1_verify_hermes.py

Write-Host "`n== P-1 component check: Memory Sidecar =="
python ./scratchpad/p1_verify_sidecar.py

Write-Host "`n== P-1 component check: gbrain =="
python ./scratchpad/p1_verify_gbrain.py
