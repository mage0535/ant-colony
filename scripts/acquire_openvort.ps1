param(
    [switch]$Clone,
    [string]$RepositoryUrl = "https://github.com/openvort/openvort.git",
    [string]$Branch = "master"
)

$ErrorActionPreference = "Continue"

Set-Location $PSScriptRoot\..

$projectRoot = Get-Location
$openvortRoot = Join-Path $projectRoot "external/openvort"
$sourceDir = Join-Path $openvortRoot "source"
$metadataPath = Join-Path $openvortRoot "source-metadata.json"

Write-Host "== OpenVort acquisition check =="
Write-Host "Project root: ./"
Write-Host "Expected source dir: ./external/openvort/source"

Write-Host "`n[1/5] Current verification probe"
python ./scratchpad/p1_verify_openvort.py

Write-Host "`n[2/5] pip package probe"
python -m pip index versions openvort 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "INFO: pip probe did not find an installable 'openvort' distribution in the current environment."
}

Write-Host "`n[3/5] Remote repository probe"
$remoteHead = $null
try {
    $remoteHead = git ls-remote --symref $RepositoryUrl HEAD
    if ($LASTEXITCODE -eq 0 -and $remoteHead) {
        $remoteHead | Out-Host
    } else {
        Write-Host "WARN: git ls-remote returned no data."
    }
} catch {
    Write-Host "WARN: failed to probe remote repository -> $($_.Exception.Message)"
}

Write-Host "`n[4/5] Current local landing status"
if (Test-Path $sourceDir) {
    Write-Host "Source already present under ./external/openvort/source"
    Get-ChildItem $sourceDir -Force | Select-Object Name, Mode | Out-Host
} else {
    Write-Host "Source not present yet under ./external/openvort/source"
}

if ($Clone) {
    Write-Host "`n[5/5] Source landing"
    & "$PSScriptRoot/land_openvort_source.ps1" -RepositoryUrl $RepositoryUrl -Branch $Branch
    exit $LASTEXITCODE
}

Write-Host "`n[5/5] Recommended next steps"
Write-Host "- The current default is source-based onboarding."
if (Test-Path $sourceDir) {
    Write-Host "- Source is already present under ./external/openvort/source"
    Write-Host "- Rerun ./scratchpad/p1_verify_openvort.py after any refresh."
    Write-Host "- Use ./scripts/land_openvort_source.ps1 -ForceSync to refresh the local checkout."
} else {
    Write-Host "- To land the upstream source, run:"
    Write-Host "  ./scripts/acquire_openvort.ps1 -Clone"
    Write-Host "- After landing source, update ./docs/external-sources-register.md and rerun ./scratchpad/p1_verify_openvort.py"
}
