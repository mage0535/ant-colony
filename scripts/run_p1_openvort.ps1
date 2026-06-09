$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot\..

$vendorDir = ".\scratchpad\vendor\openvort_probe"
$sourceDir = ".\external\openvort\source\src"

Write-Host "== P-1 OpenVort validation =="
Write-Host "Workspace root: ./"
Write-Host "Source dir: ./external/openvort/source/src"
Write-Host "Vendor deps dir: ./scratchpad/vendor/openvort_probe"

if (-not (Test-Path $sourceDir)) {
    Write-Host "FAIL: OpenVort source is missing. Run ./scripts/acquire_openvort.ps1 -Clone first."
    exit 1
}

if (-not (Test-Path $vendorDir)) {
    Write-Host "FAIL: vendor probe dependencies are missing."
    Write-Host "Next step: install probe dependencies into ./scratchpad/vendor/openvort_probe before rerunning."
    exit 1
}

$env:PYTHONPATH = "$((Resolve-Path $vendorDir).Path);$((Resolve-Path $sourceDir).Path)"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

python .\scratchpad\p1_verify_openvort.py
