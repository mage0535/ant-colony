import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.12.254.122', 22, 'codexcheck', 'codexcheck', look_for_keys=False, allow_agent=False, timeout=15)
_, stdout, _ = ssh.exec_command('journalctl -u ant-colony-gateway --since "5 minutes ago" --no-pager 2>/dev/null | grep -c "src.tools"', timeout=10)
print(stdout.read().decode())
ssh.close()
