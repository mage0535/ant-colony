param(
    [string]$InstallDir = "C:\AntColony\workflow-collector",
    [string]$DashboardBaseUrl = "http://<dashboard-host>:18092",
    [string]$IngestToken = "",
    [string]$SqlServer = "127.0.0.1",
    [string[]]$SourceDatabases = @("business_a", "business_b"),
    [string]$TaskName = "AntColony-Ratemin-Collector",
    [string]$WatchdogTaskName = "AntColony-Ratemin-Collector-Watchdog"
)

$ErrorActionPreference = "Stop"

if (!$IngestToken) {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $IngestToken = [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_").TrimEnd("=")
}

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

$collectorSource = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "ratemin_collector.ps1"
$collectorTarget = Join-Path $InstallDir "ratemin_collector.ps1"
if ((Resolve-Path -LiteralPath $collectorSource).Path -ne (Resolve-Path -LiteralPath $collectorTarget -ErrorAction SilentlyContinue).Path) {
    Copy-Item -LiteralPath $collectorSource -Destination $collectorTarget -Force
}

$configPath = Join-Path $InstallDir "collector.config.json"
$config = [ordered]@{
    platform = "wecom"
    ingest_url = ($DashboardBaseUrl.TrimEnd("/") + "/api/v1/site/ratemin/ingest")
    current_ingest_url = ($DashboardBaseUrl.TrimEnd("/") + "/api/v1/site/ratemin/current/ingest")
    user_ingest_url = ($DashboardBaseUrl.TrimEnd("/") + "/api/v1/site/ratemin/users/ingest")
    ingest_token = $IngestToken
    poll_interval_seconds = 5
    lookback_days = 30
    max_seen = 10000
    source_databases = $SourceDatabases
    connection_string_template = "Server=$SqlServer;Database={database};Integrated Security=True;TrustServerCertificate=True"
    state_path = (Join-Path $InstallDir "collector.state.json")
    log_path = (Join-Path $InstallDir "collector.log")
}
$config | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $configPath -Encoding UTF8

$runCmd = Join-Path $InstallDir "start-ratemin-collector.cmd"
@"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$collectorTarget" -ConfigPath "$configPath"
"@ | Set-Content -LiteralPath $runCmd -Encoding Default

$onceCmd = Join-Path $InstallDir "test-ratemin-collector-once.cmd"
@"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$collectorTarget" -ConfigPath "$configPath" -Once
pause
"@ | Set-Content -LiteralPath $onceCmd -Encoding Default

$watchdogTarget = Join-Path $InstallDir "ratemin_collector_watchdog.ps1"
@"
param(
    [string]`$TaskName = "$TaskName",
    [string]`$LogPath = "$(Join-Path $InstallDir "collector.log")"
)
`$ErrorActionPreference = "Stop"
try {
    `$task = Get-ScheduledTask -TaskName `$TaskName -ErrorAction Stop
    if (`$task.State -ne "Running") {
        Start-ScheduledTask -TaskName `$TaskName
        Add-Content -LiteralPath `$LogPath -Encoding UTF8 -Value ("{0} WATCHDOG started task={1} previous_state={2}" -f (Get-Date).ToString("s"), `$TaskName, `$task.State)
    }
} catch {
    Add-Content -LiteralPath `$LogPath -Encoding UTF8 -Value ("{0} WATCHDOG error={1}" -f (Get-Date).ToString("s"), `$_.Exception.Message)
    throw
}
"@ | Set-Content -LiteralPath $watchdogTarget -Encoding UTF8

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$collectorTarget`" -ConfigPath `"$configPath`""
$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $startupTrigger -Settings $settings -RunLevel Highest -Force | Out-Null

$watchdogCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$watchdogTarget`" -TaskName `"$TaskName`" -LogPath `"$($config.log_path)`""
schtasks.exe /Create /TN $WatchdogTaskName /SC MINUTE /MO 1 /TR $watchdogCommand /RL HIGHEST /F | Out-Null
Start-ScheduledTask -TaskName $TaskName

[pscustomobject]@{
    installed = $true
    install_dir = $InstallDir
    config_path = $configPath
    task_name = $TaskName
    ingest_url = $config.ingest_url
    ingest_token = $IngestToken
    manual_start = $runCmd
    manual_test_once = $onceCmd
    watchdog_task_name = $WatchdogTaskName
    watchdog_script = $watchdogTarget
}
