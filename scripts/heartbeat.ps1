param([switch]$AutoLaunch)

$ProjectRoot = "D:\Onedrive\CodeX\projects\ant colony"
$HandoffFile = Join-Path $ProjectRoot "docs\handoff.md"
$HeartbeatLog = Join-Path $ProjectRoot "data\heartbeat.log"
$StateFile = Join-Path $ProjectRoot "data\heartbeat-state.json"

$null = New-Item -ItemType Directory -Path (Split-Path $HeartbeatLog -Parent) -Force

if (-not (Test-Path $HandoffFile)) { exit 0 }

$handoff = Get-Content $HandoffFile -Raw -Encoding UTF8

# Find the latest "next steps" section
$lines = $handoff -split "`n"
$inSection = $false
$steps = @()
foreach ($line in $lines) {
    if ($line -match '^\#\#\# \u4e0b\u4e00\u6b65\u5efa\u8bae') {
        $inSection = $true; continue
    }
    if ($inSection -and $line -match '^\#\#\# ') { break }
    if ($inSection -and $line -match '^\d+\.\s+(.*)') {
        $steps += $matches[1].Trim()
    }
}

if ($steps.Count -eq 0) { exit 0 }

# Separate auto steps from AI-needed steps
$autoKeys = @('restart', 'reboot', 'test')
$aiSteps = @()
foreach ($s in $steps) {
    $isAuto = $false
    foreach ($k in $autoKeys) {
        if ($s.ToLower().Contains($k)) { $isAuto = $true; break }
    }
    if (-not $isAuto) { $aiSteps += $s }
}

$msg = "heartbeat | $(Get-Date -Format 'HH:mm:ss') | total=$($steps.Count) pending=$($aiSteps.Count)"
Add-Content -Path $HeartbeatLog -Value $msg -Encoding UTF8

if ($aiSteps.Count -gt 0) {
    $short = $aiSteps[0]
    if ($short.Length -gt 60) { $short = $short.Substring(0,60) + "..." }
    Add-Content -Path $HeartbeatLog -Value "  NEXT: $short" -Encoding UTF8

    # Save state for AI session
    $state = @{
        ts = (Get-Date -Format 'o')
        pending = $aiSteps
    }
    $state | ConvertTo-Json -Compress | Set-Content -Path $StateFile -Encoding UTF8

    # Popup notification via separate process (reliable from Task Scheduler)
    try {
        $title = "Ant Colony Heartbeat"
        $body = "pending: $($aiSteps.Count)"
        $shortList = $aiSteps | ForEach-Object { if ($_.Length -gt 40) { $_.Substring(0,40) + "..." } else { $_ } }
        $body += "`n1. $($shortList[0])"
        if ($shortList.Count -gt 1) { $body += "`n2. $($shortList[1])" }
        if ($shortList.Count -gt 2) { $body += "`n... +$($shortList.Count - 2) more" }
        $esc = $body -replace "'", "''"
        Start-Process powershell.exe -ArgumentList "-NoProfile -WindowStyle Hidden -Command `"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('$esc','$title',0,64) | Out-Null`"" -WindowStyle Hidden
    } catch { }
}

# Keep last 100 lines
$all = Get-Content $HeartbeatLog
if ($all.Count -gt 100) { $all[-100..-1] | Set-Content $HeartbeatLog -Encoding UTF8 }
