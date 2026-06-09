"""Check approval_parser.py for vacation balance data."""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.12.254.122', 22, 'codexcheck', 'codexcheck', look_for_keys=False, allow_agent=False, timeout=15)

script = r"""
import os
parser = "/opt/wecom-attendance/src/attendance_app/services/approval_parser.py"
if os.path.isfile(parser):
    with open(parser, encoding='utf-8') as f:
        print(f.read())
"""

sftp = ssh.open_sftp()
with sftp.open('/tmp/check_parser.py', 'w') as f:
    f.write(script.encode('utf-8'))
sftp.close()

stdin, stdout, stderr = ssh.exec_command("python3 /tmp/check_parser.py > /tmp/parser_out.txt 2>&1")
stdout.channel.recv_exit_status()

sftp2 = ssh.open_sftp()
with sftp2.open('/tmp/parser_out.txt', 'r') as f:
    result = f.read()
sftp2.close()
print(result[:5000])
ssh.close()
