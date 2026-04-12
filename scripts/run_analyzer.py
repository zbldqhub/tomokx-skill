import subprocess, os, json, sys
env = os.environ.copy()
with open('/root/.openclaw/workspace/.env.trading') as f:
    for line in f:
        line=line.strip()
        if line.startswith('export '):
            line=line[7:]
        if '=' in line and not line.startswith('#'):
            k,v=line.split('=',1)
            v=v.strip().strip('"')
            env[k]=v
r = subprocess.run([sys.executable, '/root/.openclaw/workspace/scripts/eth_market_analyzer.py'], env=env, capture_output=True, text=True, timeout=25)
print(r.stdout or r.stderr)
