param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot\..

$sourceSample = ".\scratchpad\openvort_probe.env.sample"
$targetEnv = ".\external\openvort\source\.env"

Write-Host "== Prepare OpenVort probe .env =="
Write-Host "Source sample: ./scratchpad/openvort_probe.env.sample"
Write-Host "Target file: ./external/openvort/source/.env"

if (-not (Test-Path $sourceSample)) {
    Write-Host "FAIL: source sample is missing."
    exit 1
}

if (-not (Test-Path ".\external\openvort\source")) {
    Write-Host "FAIL: OpenVort source checkout is missing. Run ./scripts/acquire_openvort.ps1 -Clone first."
    exit 1
}

if ((Test-Path $targetEnv) -and (-not $Force)) {
    Write-Host "SKIP: target .env already exists."
    Write-Host "Use -Force to overwrite it intentionally."
    exit 0
}

if (Test-Path $targetEnv) {
    $backup = ".\external\openvort\source\.env.backup"
    Copy-Item $targetEnv $backup -Force
    Write-Host "Backed up existing .env to ./external/openvort/source/.env.backup"
}

Copy-Item $sourceSample $targetEnv -Force
Write-Host "Prepared ./external/openvort/source/.env"
Write-Host ""
Write-Host "Next steps:"
Write-Host "- Fill in real PostgreSQL / LLM / admin / WeCom values."
Write-Host "- Run ./scripts/check_openvort_prereqs.ps1"
Write-Host "- Run ./scripts/run_p1_openvort.ps1"
