param(
    [string]$ConfigPath = "C:\AntColony\workflow-collector\collector.config.json",
    [switch]$Once
)

$ErrorActionPreference = "Stop"
$CollectorQueryVersion = "ratemin-current-todos-v3"

function Read-Config {
    param([string]$Path)
    if (!(Test-Path -LiteralPath $Path)) {
        throw "Missing config: $Path"
    }
    Get-Content -LiteralPath $Path -Encoding UTF8 -Raw | ConvertFrom-Json
}

function Ensure-Directory {
    param([string]$Path)
    $dir = Split-Path -Parent $Path
    if ($dir -and !(Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

function Load-State {
    param([string]$Path)
    $state = $null
    if (Test-Path -LiteralPath $Path) {
        try { $state = (Get-Content -LiteralPath $Path -Encoding UTF8 -Raw | ConvertFrom-Json) } catch {}
    }
    if ($null -eq $state) {
        $state = [pscustomobject]@{ seen = @{}; last_success_at = ""; last_error = ""; collector_query_version = "" }
    }
    if ($null -eq $state.seen) {
        $state | Add-Member -NotePropertyName seen -NotePropertyValue ([pscustomobject]@{}) -Force
    }
    if ($null -eq $state.last_success_at) {
        $state | Add-Member -NotePropertyName last_success_at -NotePropertyValue "" -Force
    }
    if ($null -eq $state.last_error) {
        $state | Add-Member -NotePropertyName last_error -NotePropertyValue "" -Force
    }
    if ($null -eq $state.collector_query_version) {
        $state | Add-Member -NotePropertyName collector_query_version -NotePropertyValue "" -Force
    }
    $state
}

function Save-State {
    param($State, [string]$Path)
    Ensure-Directory $Path
    $State | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Invoke-SqlQuery {
    param([string]$ConnectionString, [string]$Sql)
    $cn = New-Object System.Data.SqlClient.SqlConnection($ConnectionString)
    $cn.Open()
    try {
        $cmd = $cn.CreateCommand()
        $cmd.CommandText = $Sql
        $cmd.CommandTimeout = 30
        $da = New-Object System.Data.SqlClient.SqlDataAdapter($cmd)
        $dt = New-Object System.Data.DataTable
        [void]$da.Fill($dt)
        return ,$dt
    } finally {
        $cn.Close()
    }
}

function Convert-DataTable {
    param($Table)
    $items = @()
    foreach ($row in $Table.Rows) {
        $obj = [ordered]@{}
        foreach ($col in $Table.Columns) {
            $value = $row.Item($col.ColumnName)
            if ($value -is [System.DBNull]) { $value = "" }
            if ($value -is [datetime]) { $value = $value.ToString("yyyy-MM-dd HH:mm:ss") }
            $obj[$col.ColumnName] = [string]$value
        }
        $items += [pscustomobject]$obj
    }
    $items
}

function Build-RateminQuery {
@"
with base_todos as (
    select
           'tabFlowMS' as source_table,
           cast(ms.FlowID as varchar(50)) as flow_id,
           cast(ms.FlowPostID as varchar(50)) as flow_post_id,
           cast(ms.DataID as varchar(50)) as data_id,
           cast(ms.taskID as varchar(50)) as task_id,
           isnull(f.flowCaption, '') as flow_name,
           isnull(t.taskCaption, '') as task_name,
           isnull(nullif(ms.sSubject, ''), isnull(f.flowCaption, '')) as subject,
           isnull(ms.sDesc, '') as content,
           convert(varchar(19), ms.HasHintTime, 120) as todo_time,
           isnull(starter.LoginName, '') as initiator_login_name,
           isnull(starter.sName, '') as initiator_name,
           isnull(ms.ToDoUsers, '') as todo_users,
           isnull(ms.ToDoDepts, '') as todo_depts,
           isnull(ms.ToDoRoles, '') as todo_roles,
           ms.HasHintTime as sort_time
    from dbo.tabFlowMS ms
    left join dbo.tabFlow f on f.flowID = ms.FlowID
    left join dbo.tabFlowTask t on t.FlowID = ms.FlowID and t.taskID = ms.taskID
    outer apply (
      select top 1 p.* from (
        select * from dbo.tabFlowPostS where FlowPostID = ms.FlowPostID and DataID = ms.DataID and FlowID = ms.FlowID
        union all select * from dbo.tabFlowPostF where FlowPostID = ms.FlowPostID and DataID = ms.DataID and FlowID = ms.FlowID
        union all select * from dbo.tabFlowPost where FlowPostID = ms.FlowPostID and DataID = ms.DataID and FlowID = ms.FlowID
      ) p
      where p.DoUser is not null
      order by p.iOrd desc, p.DoTime desc
    ) prev
    left join dbo.tabOperator starter on starter.OperID = prev.DoUser
    where ms.HasHintTime >= dateadd(day, -isnull(__LOOKBACK_DAYS__, 30), getdate())
      and (isnull(ms.ToDoUsers, '') <> '' or isnull(ms.ToDoDepts, '') <> '' or isnull(ms.ToDoRoles, '') <> '')

    union all

    select
           'tabFlowPost' as source_table,
           cast(p.FlowID as varchar(50)) as flow_id,
           cast(p.FlowPostID as varchar(50)) as flow_post_id,
           cast(p.DataID as varchar(50)) as data_id,
           cast(p.taskID as varchar(50)) as task_id,
           isnull(f.flowCaption, '') as flow_name,
           isnull(t.taskCaption, '') as task_name,
           isnull(nullif(p.sSubject, ''), isnull(f.flowCaption, '')) as subject,
           isnull(p.sDesc, '') as content,
           convert(varchar(19), isnull(p.HasHintTime, isnull(p.DoTime1, p.DoTime)), 120) as todo_time,
           isnull(starter.LoginName, '') as initiator_login_name,
           isnull(starter.sName, '') as initiator_name,
           isnull(p.ToDoUsers, '') as todo_users,
           isnull(p.ToDoDepts, '') as todo_depts,
           isnull(p.ToDoRoles, '') as todo_roles,
           isnull(p.HasHintTime, isnull(p.DoTime1, p.DoTime)) as sort_time
    from dbo.tabFlowPost p
    left join dbo.tabFlow f on f.flowID = p.FlowID
    left join dbo.tabFlowTask t on t.FlowID = p.FlowID and t.taskID = p.taskID
    left join dbo.tabOperator starter on starter.OperID = p.DoUser
    where isnull(p.iState, 0) = 0
      and (isnull(p.ToDoUsers, '') <> '' or isnull(p.ToDoDepts, '') <> '' or isnull(p.ToDoRoles, '') <> '')
      and isnull(p.HasHintTime, isnull(p.DoTime1, p.DoTime)) >= dateadd(day, -isnull(__LOOKBACK_DAYS__, 30), getdate())
),
expanded_recipients as (
    select b.*, recv.OperID, recv.LoginName, recv.sName
    from base_todos b
    join dbo.tabOperator recv on charindex(',' + cast(recv.OperID as varchar(20)) + ',', b.todo_users) > 0
    where isnull(recv.NotUsed, '0') <> '1'

    union

    select b.*, recv.OperID, recv.LoginName, recv.sName
    from base_todos b
    join dbo.tabRoleOper ro on charindex(',' + cast(ro.RoleID as varchar(20)) + ',', b.todo_roles) > 0
    join dbo.tabOperator recv on recv.OperID = ro.OperID
    where isnull(b.todo_roles, '') <> ''
      and isnull(recv.NotUsed, '0') <> '1'
      and (
        isnull(b.todo_depts, '') = ''
        or isnull(ro.DeptID, '') = ''
        or isnull(ro.DeptID, '0') = '0'
        or charindex(',' + cast(ro.DeptID as varchar(20)) + ',', b.todo_depts) > 0
      )

    union

    select b.*, recv.OperID, recv.LoginName, recv.sName
    from base_todos b
    join dbo.tabOperator recv on charindex(',' + cast(recv.DeptID as varchar(20)) + ',', b.todo_depts) > 0
    where isnull(b.todo_depts, '') <> ''
      and isnull(b.todo_roles, '') = ''
      and isnull(recv.NotUsed, '0') <> '1'
)
select top 1000
       flow_id,
       flow_post_id,
       data_id,
       task_id,
       flow_name,
       task_name,
       cast(OperID as varchar(50)) as recipient_oper_id,
       isnull(LoginName, '') as recipient_login_name,
       isnull(sName, '') as recipient_name,
       subject,
       content,
       todo_time,
       initiator_login_name,
       initiator_name,
       sort_time
from expanded_recipients
where OperID is not null
order by sort_time desc
"@
}

function Build-RateminUserQuery {
@"
select
       cast(OperID as varchar(50)) as rate_oper_id,
       isnull(LoginName, '') as rate_login_name,
       isnull(sName, '') as rate_display_name
from dbo.tabOperator
where isnull(NotUsed, '0') <> '1'
  and isnull(sName, '') <> ''
  and OperID > 0
order by sName, LoginName, OperID
"@
}

function Get-CurrentEvents {
    param($Config)
    $candidates = @()
    foreach ($db in @($Config.source_databases)) {
        $connectionString = $Config.connection_string_template.Replace("{database}", [string]$db)
        $lookbackDays = [int]($Config.lookback_days)
        if ($lookbackDays -le 0) { $lookbackDays = 30 }
        $sql = (Build-RateminQuery).Replace("__LOOKBACK_DAYS__", [string]$lookbackDays)
        $rows = Convert-DataTable (Invoke-SqlQuery -ConnectionString $connectionString -Sql $sql)
        foreach ($row in $rows) {
            if (!$row.recipient_oper_id) { continue }
            $key = "$db|$($row.flow_id)|$($row.flow_post_id)|$($row.data_id)|$($row.task_id)|$($row.recipient_oper_id)"
            $candidates += [pscustomobject]@{ db = [string]$db; key = $key; row = $row }
        }
    }

    $candidates
}

function Get-NewEvents {
    param($Candidates, $State)
    $seenNames = @($State.seen.PSObject.Properties.Name)
    $isEmptyState = ($seenNames.Count -eq 0 -and -not [string]$State.last_success_at)
    $isQueryUpgrade = ([string]$State.collector_query_version -ne [string]$CollectorQueryVersion)
    if ($isEmptyState -or $isQueryUpgrade) {
        foreach ($candidate in @($Candidates)) {
            $State.seen | Add-Member -NotePropertyName $candidate.key -NotePropertyValue (Get-Date).ToString("s") -Force
        }
        $State.collector_query_version = $CollectorQueryVersion
        return @()
    }

    $events = @()
    foreach ($candidate in @($Candidates)) {
        $seenNames = @($State.seen.PSObject.Properties.Name)
        if ($seenNames -contains $candidate.key) { continue }
        $row = $candidate.row
        $events += [ordered]@{
                _collector_key = $candidate.key
                source_db = [string]$candidate.db
                flow_id = $row.flow_id
                flow_post_id = $row.flow_post_id
                data_id = $row.data_id
                task_id = $row.task_id
                flow_name = $row.flow_name
                recipient_oper_id = $row.recipient_oper_id
                recipient_login_name = $row.recipient_login_name
                recipient_name = $row.recipient_name
                subject = $row.subject
                content = $row.content
                todo_time = $row.todo_time
                received_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
                initiator_login_name = $row.initiator_login_name
                initiator_name = $row.initiator_name
        }
    }
    $events
}

function Get-Users {
    param($Config)
    $users = @()
    foreach ($db in @($Config.source_databases)) {
        $connectionString = $Config.connection_string_template.Replace("{database}", [string]$db)
        $rows = Convert-DataTable (Invoke-SqlQuery -ConnectionString $connectionString -Sql (Build-RateminUserQuery))
        foreach ($row in $rows) {
            if (!$row.rate_oper_id) { continue }
            $users += [ordered]@{
                source_db = [string]$db
                rate_oper_id = $row.rate_oper_id
                rate_login_name = $row.rate_login_name
                rate_display_name = $row.rate_display_name
            }
        }
    }
    $users
}

function Submit-Events {
    param($Config, $Events)
    if (!$Events -or $Events.Count -eq 0) { return @{ skipped = 0 } }
    $submitEvents = @()
    foreach ($event in @($Events)) {
        $copy = [ordered]@{}
        foreach ($key in $event.Keys) {
            if ($key -eq "_collector_key") { continue }
            $copy[$key] = $event[$key]
        }
        $submitEvents += $copy
    }
    $body = @{
        platform = $Config.platform
        events = $submitEvents
    } | ConvertTo-Json -Depth 20
    try {
        Invoke-RestMethod -Method Post -Uri $Config.ingest_url -Headers @{ Authorization = "Bearer $($Config.ingest_token)" } -ContentType "application/json; charset=utf-8" -Body $body -TimeoutSec 30
    } catch {
        $detail = $_.Exception.Message
        if ($_.Exception.Response) {
            try {
                $stream = $_.Exception.Response.GetResponseStream()
                if ($stream) {
                    $reader = New-Object System.IO.StreamReader($stream)
                    $responseBody = $reader.ReadToEnd()
                    if ($responseBody) { $detail = "$detail body=$responseBody" }
                }
            } catch {}
        }
        throw $detail
    }
}

function Submit-CurrentEvents {
    param($Config, $Events)
    $currentUrl = [string]$Config.current_ingest_url
    if (!$currentUrl) {
        $currentUrl = ([string]$Config.ingest_url).Replace("/api/v1/site/ratemin/ingest", "/api/v1/site/ratemin/current/ingest")
    }
    $submitEvents = @()
    foreach ($event in @($Events)) {
        if (!$event) { continue }
        $row = $event.row
        if ($null -eq $row) { continue }
        $copy = [ordered]@{
            source_db = [string]$event.db
            flow_id = $row.flow_id
            flow_post_id = $row.flow_post_id
            data_id = $row.data_id
            task_id = $row.task_id
            flow_name = $row.flow_name
            recipient_oper_id = $row.recipient_oper_id
            recipient_login_name = $row.recipient_login_name
            recipient_name = $row.recipient_name
            subject = $row.subject
            content = $row.content
            todo_time = $row.todo_time
            initiator_login_name = $row.initiator_login_name
            initiator_name = $row.initiator_name
        }
        $submitEvents += $copy
    }
    $body = @{
        platform = $Config.platform
        source_databases = @($Config.source_databases)
        events = $submitEvents
    } | ConvertTo-Json -Depth 20
    Invoke-RestMethod -Method Post -Uri $currentUrl -Headers @{ Authorization = "Bearer $($Config.ingest_token)" } -ContentType "application/json; charset=utf-8" -Body $body -TimeoutSec 60
}

function Mark-EventsSeen {
    param($State, $Events)
    if (!$Events -or $Events.Count -eq 0) { return }
    foreach ($event in @($Events)) {
        if (!$event) { continue }
        $key = $event["_collector_key"]
        if (!$key) { continue }
        $State.seen | Add-Member -NotePropertyName $key -NotePropertyValue (Get-Date).ToString("s") -Force
    }
}

function Test-SubmitSucceededFully {
    param($Result)
    if ($null -eq $Result) { return $false }
    $errors = @($Result.errors)
    return ($errors.Count -eq 0)
}

function Submit-Users {
    param($Config, $Users)
    if (!$Users -or $Users.Count -eq 0) { return @{ skipped = 0 } }
    $body = @{
        platform = $Config.platform
        auto_bind = $true
        users = $Users
    } | ConvertTo-Json -Depth 20
    Invoke-RestMethod -Method Post -Uri $Config.user_ingest_url -Headers @{ Authorization = "Bearer $($Config.ingest_token)" } -ContentType "application/json; charset=utf-8" -Body $body -TimeoutSec 60
}

function Trim-Seen {
    param($State, [int]$MaxSeen)
    if ($MaxSeen -le 0) { $MaxSeen = 10000 }
    $names = @($State.seen.PSObject.Properties.Name)
    if ($names.Count -le $MaxSeen) { return }
    $remove = $names | Select-Object -First ($names.Count - $MaxSeen)
    foreach ($name in $remove) {
        $State.seen.PSObject.Properties.Remove($name)
    }
}

$config = Read-Config $ConfigPath
$statePath = if ($config.state_path) { [string]$config.state_path } else { "C:\AntColony\workflow-collector\collector.state.json" }
$logPath = if ($config.log_path) { [string]$config.log_path } else { "C:\AntColony\workflow-collector\collector.log" }
Ensure-Directory $statePath
Ensure-Directory $logPath
$state = Load-State $statePath
$interval = [int]($config.poll_interval_seconds)
if ($interval -lt 5) { $interval = 5 }

while ($true) {
    try {
        $currentEvents = @(Get-CurrentEvents -Config $config)
        $events = Get-NewEvents -Candidates $currentEvents -State $state
        $users = @(Get-Users -Config $config)
        $userResult = Submit-Users -Config $config -Users $users
        $result = Submit-Events -Config $config -Events $events
        $currentResult = Submit-CurrentEvents -Config $config -Events $currentEvents
        if (Test-SubmitSucceededFully -Result $result) {
            Mark-EventsSeen -State $state -Events $events
        } elseif ($events.Count -gt 0) {
            throw "rate-sensitive ingest returned partial errors; events will be retried"
        }
        $state.last_success_at = (Get-Date).ToString("s")
        $state.last_error = ""
        Trim-Seen -State $state -MaxSeen ([int]$config.max_seen)
        Save-State -State $state -Path $statePath
        "$(Get-Date -Format s) OK users=$($users.Count) userResult=$($userResult | ConvertTo-Json -Compress -Depth 8) current=$($currentEvents.Count) currentResult=$($currentResult | ConvertTo-Json -Compress -Depth 8) events=$($events.Count) result=$($result | ConvertTo-Json -Compress -Depth 8)" | Add-Content -LiteralPath $logPath -Encoding UTF8
    } catch {
        $line = if ($_.InvocationInfo) { [string]$_.InvocationInfo.ScriptLineNumber } else { "" }
        $state.last_error = ([string]$_.Exception.Message) + ($(if ($line) { " at line $line" } else { "" }))
        Save-State -State $state -Path $statePath
        "$(Get-Date -Format s) ERROR $($state.last_error)" | Add-Content -LiteralPath $logPath -Encoding UTF8
        Start-Sleep -Seconds ([Math]::Max($interval, 10))
    }
    if ($Once) { break }
    Start-Sleep -Seconds $interval
}
