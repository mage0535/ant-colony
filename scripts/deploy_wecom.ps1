# Deploy WeCom callback + ngrok on test server
# Run from: D:\Onedrive\CodeX\projects\ant colony

$server = "codexcheck@10.12.254.122"
$project = "/home/codexcheck/ant-colony-probe"

Write-Host "=== 1. Package & upload source ==="
$zip = "$env:TEMP\ant-src-deploy.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path src -DestinationPath $zip -Force
scp $zip ${server}:$project/
ssh $server "cd $project && unzip -o ant-src-deploy.zip && rm ant-src-deploy.zip"
Write-Host "Source deployed"

Write-Host "`n=== 2. WeCom env config ==="
$envBlock = @"
WECOM_CORP_ID=ww310c6e23dfcd46f9
WECOM_AGENT_ID=1000006
WECOM_SECRET=5_bZIFtwR2KaQ0sjdEtwCzNX0NOwzGVDLSUwXh5mBp4
WECOM_CALLBACK_TOKEN=4UeOR5hmEi
WECOM_CALLBACK_AES_KEY=UAbdlIX2YIDb5X1n6KqvqBjZIBx2V1wrwaCy0Uvb2BR
"@
ssh $server "echo '$envBlock' | sudo tee /etc/ant-colony-wecom.env"
ssh $server "sudo chmod 600 /etc/ant-colony-wecom.env"

Write-Host "`n=== 3. Callback systemd service ==="
$unitFile = @"
[Unit]
Description=Ant Colony WeCom Callback
After=network.target

[Service]
Type=simple
WorkingDirectory=$project
ExecStart=/usr/bin/python3 -m src.gateway.wecom_callback_server
Restart=always
RestartSec=5
EnvironmentFile=/etc/ant-colony-wecom.env

[Install]
WantedBy=multi-user.target
"@
$unitEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($unitFile))
ssh $server "echo $unitEncoded | base64 -d | sudo tee /etc/systemd/system/ant-colony-callback.service"
ssh $server "sudo systemctl daemon-reload && sudo systemctl enable ant-colony-callback && sudo systemctl restart ant-colony-callback"
ssh $server "systemctl status ant-colony-callback --no-pager | head -5"
Write-Host "Callback service running"

Write-Host "`n=== 4. ngrok tunnel ==="
ssh $server "ngrok config add-authtoken 3Ekyy5qqkZkob51XmYhMMDkvB6s_27FYyLsd9pUp8214PA8hQ 2>/dev/null; pkill ngrok 2>/dev/null; sleep 1; nohup ngrok http 18091 --log=stdout > /var/log/ngrok.log 2>&1 & sleep 4"
$url = ssh $server "curl -s http://127.0.0.1:4040/api/tunnels | python3 -c 'import sys,json; print(json.load(sys.stdin)[\"tunnels\"][0][\"public_url\"])'" 2>$null
Write-Host "`n*** PUBLIC URL: $url ***"
Write-Host "`nNow go to WeCom admin panel and set URL: $url/callback"
