# PowerShell 快速测试脚本
# 直接向本地网关发送消息，绕过企微回调

$GATEWAY = "http://localhost:18090"

Write-Host "=== 1. 发送直发消息 → 个人 Agent 回复 ==="
$body = '{"from":"alice","content":"现在几点了"}'
$r = Invoke-RestMethod -Uri $GATEWAY -Method POST -Body $body -ContentType "application/json"
Write-Host "回复: $($r.reply)"

Write-Host ""
Write-Host "=== 2. 设置个人 Agent 侧车记忆 ==="
$body = '{"from":"alice","content":"设置我的角色=前端开发"}'
$r = Invoke-RestMethod -Uri $GATEWAY -Method POST -Body $body -ContentType "application/json"
Write-Host "回复: $($r.reply)"

Write-Host ""
Write-Host "=== 3. 空间消息 → 缓冲 (需 2 条触发冲刷) ==="
$msg1 = '{"from":"alice","content":"首页加载太慢了，需要优化","space_id":"proj-test"}'
$msg2 = '{"from":"bob","content":"对，图片没做懒加载，每次都要等3秒","space_id":"proj-test"}'
$r1 = Invoke-RestMethod -Uri $GATEWAY -Method POST -Body $msg1 -ContentType "application/json"
$r2 = Invoke-RestMethod -Uri $GATEWAY -Method POST -Body $msg2 -ContentType "application/json"
Write-Host "缓冲: $($r2.buffered)"

Write-Host ""
Write-Host "=== 4. 查看草稿 (等待 30 秒 flusher 冲刷) ==="
Start-Sleep -Seconds 5
$drafts = Invoke-RestMethod -Uri "$GATEWAY/drafts?space_id=proj-test"
Write-Host "待确认草稿:"
$drafts.drafts | ForEach-Object { Write-Host "  #$($_.id) $($_.title) (置信度: $($_.confidence))" }

Write-Host ""
Write-Host "=== 5. 聊天确认草稿 ==="
$body = '{"from":"alice","content":"确认","space_id":"proj-test"}'
$r = Invoke-RestMethod -Uri $GATEWAY -Method POST -Body $body -ContentType "application/json"
Write-Host "已确认: $($r.confirmed | ConvertTo-Json)"

Write-Host ""
Write-Host "=== 6. 查看任务板 ==="
$tasks = Invoke-RestMethod -Uri "$GATEWAY/tasks?space_id=proj-test"
Write-Host "任务列表:"
$tasks.tasks | ForEach-Object { Write-Host "  $($_.id) [$($_.status)] $($_.title)" }

Write-Host ""
Write-Host "=== 7. Dashboard: http://localhost:18092 ==="
Write-Host "打开浏览器查看实时仪表盘"
