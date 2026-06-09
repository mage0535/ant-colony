$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot\..

$envFile = ".\external\openvort\source\.env"
$exampleFile = ".\external\openvort\source\.env.example"

function Get-EnvMap {
    param([string]$Path)

    $map = @{}
    if (-not (Test-Path $Path)) {
        return $map
    }

    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed -split "=", 2
        if ($parts.Count -eq 2) {
            $map[$parts[0].Trim()] = $parts[1].Trim()
        }
    }
    return $map
}

function Get-ConfigValue {
    param(
        [string]$Key,
        [hashtable]$EnvMap
    )

    $processValue = [Environment]::GetEnvironmentVariable($Key)
    if ($processValue) {
        return $processValue
    }
    if ($EnvMap.ContainsKey($Key)) {
        return $EnvMap[$Key]
    }
    return ""
}

function Test-MeaningfulValue {
    param([string]$Value)

    if (-not $Value) {
        return $false
    }

    $normalized = $Value.Trim().ToLowerInvariant()
    if (-not $normalized) {
        return $false
    }

    $placeholderPrefixes = @(
        "replace-with-",
        "your-",
        "example-"
    )

    foreach ($prefix in $placeholderPrefixes) {
        if ($normalized.StartsWith($prefix)) {
            return $false
        }
    }

    if ($normalized -in @("admin", "changeme", "todo", "tbd")) {
        return $false
    }

    return $true
}

function Test-TcpPort {
    param(
        [string]$TargetHost,
        [int]$Port
    )

    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect($TargetHost, $Port, $null, $null)
        $success = $iar.AsyncWaitHandle.WaitOne(2000, $false)
        if (-not $success) {
            $client.Close()
            return $false
        }
        $client.EndConnect($iar)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

$envMap = Get-EnvMap -Path $envFile

$databaseUrl = Get-ConfigValue -Key "OPENVORT_DATABASE_URL" -EnvMap $envMap
if (-not $databaseUrl) {
    $databaseUrl = "postgresql+asyncpg://openvort:openvort@localhost:5432/openvort"
}

$llmApiKey = Get-ConfigValue -Key "OPENVORT_LLM_API_KEY" -EnvMap $envMap
$adminIds = Get-ConfigValue -Key "OPENVORT_CONTACTS_ADMIN_USER_IDS" -EnvMap $envMap
$webPassword = Get-ConfigValue -Key "OPENVORT_WEB_DEFAULT_PASSWORD" -EnvMap $envMap
if (-not $webPassword) {
    $webPassword = "admin"
}

$wecomKeys = @(
    "OPENVORT_WECOM_CORP_ID",
    "OPENVORT_WECOM_APP_SECRET",
    "OPENVORT_WECOM_AGENT_ID",
    "OPENVORT_WECOM_CALLBACK_TOKEN",
    "OPENVORT_WECOM_CALLBACK_AES_KEY"
)

$missingWecom = @()
foreach ($key in $wecomKeys) {
    $value = Get-ConfigValue -Key $key -EnvMap $envMap
    if (-not (Test-MeaningfulValue $value)) {
        $missingWecom += $key
    }
}

$dbHost = "localhost"
$dbPort = 5432
if ($databaseUrl -match "@(?<host>[^:/]+)(:(?<port>\d+))?\/") {
    $dbHost = $Matches["host"]
    if ($Matches["port"]) {
        $dbPort = [int]$Matches["port"]
    }
}

$dockerAvailable = [bool](Get-Command docker -ErrorAction SilentlyContinue)
$dbReachable = Test-TcpPort -TargetHost $dbHost -Port $dbPort
$llmConfigured = Test-MeaningfulValue $llmApiKey
$adminConfigured = Test-MeaningfulValue $adminIds
$webPasswordCustomized = (Test-MeaningfulValue $webPassword) -and ($webPassword -ne "admin")

Write-Host "== OpenVort prerequisite check =="
Write-Host "Config source: " -NoNewline
if (Test-Path $envFile) {
    Write-Host "./external/openvort/source/.env"
} else {
    Write-Host "(falling back to process env + defaults)"
}
Write-Host "Database URL: $databaseUrl"
Write-Host "Database reachable: $dbReachable"
Write-Host "Docker available: $dockerAvailable"
Write-Host "LLM API key configured: $llmConfigured"
Write-Host "Admin user ids configured: $adminConfigured"
Write-Host "Web default password customized: $webPasswordCustomized"
Write-Host "WeCom config complete: $($missingWecom.Count -eq 0)"
if ($missingWecom.Count -gt 0) {
    Write-Host "Missing WeCom keys:"
    $missingWecom | ForEach-Object { Write-Host "  - $_" }
}

Write-Host ""
Write-Host "Recommended next steps:"
if (-not $dbReachable) {
    if ($dockerAvailable) {
        Write-Host "- Provide a reachable PostgreSQL service or let OpenVort auto-start Docker-backed PostgreSQL."
    } else {
        Write-Host "- Install Docker or point OPENVORT_DATABASE_URL at an already running PostgreSQL instance."
    }
}
if (-not $llmConfigured) {
    Write-Host "- Set OPENVORT_LLM_API_KEY before expecting LLM-backed behavior."
}
if (-not $adminConfigured) {
    Write-Host "- Set OPENVORT_CONTACTS_ADMIN_USER_IDS for contact/admin operations."
}
if (-not $webPasswordCustomized) {
    Write-Host "- Override OPENVORT_WEB_DEFAULT_PASSWORD with a stronger value."
}
if ($missingWecom.Count -gt 0) {
    Write-Host "- Fill the required OPENVORT_WECOM_* values before testing the wecom channel."
}
