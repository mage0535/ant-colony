"""Use docker exec on existing container to find DOI_RESOLVERS."""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.12.254.122', 22, 'codexcheck', 'codexcheck', look_for_keys=False, allow_agent=False, timeout=15)

def run(cmd, t=15):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=t)
    r = stdout.read().decode(errors='replace')
    e = stderr.read().decode(errors='replace')
    return (r + e).strip()

# Check container status
print('=== Container status ===')
print(run('docker ps -a --filter name=searxng --format "{{.ID}} {{.Status}}"', 5))

# Try docker exec into stopped container using start+exec or just exec
# Actually, let me try a different approach: use docker diff on stopped container
# Or let me use docker with the image directly - find Python files

# Search for DOI_RESOLVERS by extracting the searx package
print('\n=== Trying with tar export ===')
r = run('CID=$(docker create ghcr.io/searxng/searxng:latest 2>&1); '
        'docker export $CID | tar tf - 2>/dev/null | grep -i "preferences\\.py" | head -5; '
        'docker rm $CID >/dev/null 2>&1; echo "done"', 30)
print(r[:1000])

ssh.close()
