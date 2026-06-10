import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.12.254.122', 22, 'codexcheck', 'codexcheck', look_for_keys=False, allow_agent=False, timeout=15)

# Check both gateway and callback
for svc in ['ant-colony-gateway', 'ant-colony-callback']:
    _, out, _ = ssh.exec_command(f'systemctl status {svc} --no-pager | head -4', timeout=5)
    print(f"--- {svc} ---")
    print(out.read().decode())

# Check all recent logs from both services
for svc in ['ant-colony-gateway', 'ant-colony-callback']:
    _, out, _ = ssh.exec_command(f'journalctl -u {svc} --since "2 minutes ago" --no-pager 2>/dev/null | tail -10', timeout=10)
    print(f"--- {svc} logs ---")
    print(out.read().decode() or "(no logs)")

ssh.close()
