#!/bin/bash
# Deploy WeCom callback + ngrok on test server
# Run from your machine that has SSH access to 10.12.254.122

set -e

SERVER="codexcheck@10.12.254.122"
PROJECT="/home/codexcheck/ant-colony-probe"

echo "=== 1. Deploy latest source code ==="
cd "$(dirname "$0")/.."
tar -czf /tmp/ant-colony-src.tar.gz --exclude=external --exclude=scratchpad --exclude=__pycache__ --exclude=.git --exclude=node_modules src/ pyproject.toml 2>/dev/null
scp /tmp/ant-colony-src.tar.gz $SERVER:$PROJECT/
ssh $SERVER "cd $PROJECT && tar -xzf ant-colony-src.tar.gz && rm ant-colony-src.tar.gz && echo 'source deployed'"

echo ""
echo "=== 2. Write WeCom env file ==="
ssh $SERVER "cat > $PROJECT/infra/.env.wecom << 'ENVEOF'
WECOM_CORP_ID=ww310c6e23dfcd46f9
WECOM_AGENT_ID=1000006
WECOM_SECRET=5_bZIFtwR2KaQ0sjdEtwCzNX0NOwzGVDLSUwXh5mBp4
WECOM_CALLBACK_TOKEN=4UeOR5hmEi
WECOM_CALLBACK_AES_KEY=UAbdlIX2YIDb5X1n6KqvqBjZIBx2V1wrwaCy0Uvb2BR
ENVEOF
echo 'env file written'"

echo ""
echo "=== 3. Setup systemd callback service ==="
ssh $SERVER "sudo tee /etc/systemd/system/ant-colony-callback.service << 'UNITEOF'
[Unit]
Description=Ant Colony WeCom Callback
After=network.target

[Service]
Type=simple
WorkingDirectory=$PROJECT
ExecStart=/usr/bin/python3 -m src.gateway.wecom_callback_server
Restart=always
RestartSec=5
EnvironmentFile=$PROJECT/infra/.env.wecom

[Install]
WantedBy=multi-user.target
UNITEOF
sudo systemctl daemon-reload
sudo systemctl enable ant-colony-callback
sudo systemctl restart ant-colony-callback
echo 'service started'"

echo ""
echo "=== 4. Install & start ngrok ==="
ssh $SERVER "
if ! command -v ngrok &>/dev/null; then
  curl -sLO https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
  sudo tar xzf ngrok-v3-stable-linux-amd64.tgz -C /usr/local/bin/
  rm ngrok-v3-stable-linux-amd64.tgz
fi
ngrok config add-authtoken 3Ekyy5qqkZkob51XmYhMMDkvB6s_27FYyLsd9pUp8214PA8hQ
pkill ngrok 2>/dev/null || true
nohup ngrok http 18091 --log=stdout > /var/log/ngrok.log 2>&1 &
sleep 3
echo '--- PUBLIC URL ---'
curl -s http://127.0.0.1:4040/api/tunnels | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d[\"tunnels\"][0][\"public_url\"])'
"

echo ""
echo "=== Done. Copy the ngrok URL above into WeCom admin panel ==="
echo "    Format: <PUBLIC_URL>/callback"
