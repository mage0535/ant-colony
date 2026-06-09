param(
    [string]$RepositoryUrl = "https://github.com/openvort/openvort.git",
    [string]$Branch = "master",
    [switch]$ForceSync
)

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot\..

$projectRoot = Get-Location
$openvortRoot = Join-Path $projectRoot "external/openvort"
$sourceDir = Join-Path $openvortRoot "source"
$metadataPath = Join-Path $openvortRoot "source-metadata.json"

Write-Host "== OpenVort source landing =="
Write-Host "Target root: ./external/openvort/"
Write-Host "Target source dir: ./external/openvort/source"
Write-Host "Repository: $RepositoryUrl"
Write-Host "Branch: $Branch"

if (-not (Test-Path $openvortRoot)) {
    New-Item -ItemType Directory -Path $openvortRoot | Out-Null
}

if (Test-Path $sourceDir) {
    if (-not (Test-Path (Join-Path $sourceDir ".git"))) {
        throw "Target path exists but is not a git checkout: ./external/openvort/source"
    }

    Write-Host "Existing source checkout detected."
    if ($ForceSync) {
        Write-Host "ForceSync enabled: fetching latest branch state."
        git -C $sourceDir fetch origin $Branch --depth 1
        git -C $sourceDir checkout $Branch
        git -C $sourceDir reset --hard ("origin/" + $Branch)
    } else {
        Write-Host "Keeping existing checkout. Use -ForceSync to refresh from remote."
    }
} else {
    git clone --depth 1 --branch $Branch $RepositoryUrl $sourceDir
}

$commit = (git -C $sourceDir rev-parse HEAD).Trim()
$branchName = (git -C $sourceDir branch --show-current).Trim()
$timestamp = (Get-Date).ToString("s")

$metadata = [ordered]@{
    repository_url = $RepositoryUrl
    branch = $branchName
    commit = $commit
    landed_at = $timestamp
    target_directory = "./external/openvort/source"
}

$metadata | ConvertTo-Json | Set-Content -Encoding UTF8 $metadataPath

Write-Host ""
Write-Host "Landing complete."
Write-Host "Commit: $commit"
Write-Host "Metadata file: ./external/openvort/source-metadata.json"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Update ./docs/external-sources-register.md with repository, branch, and commit."
Write-Host "  2. Update ./docs/handoff.md with the landing result."
Write-Host "  3. Rerun ./scratchpad/p1_verify_openvort.py"
