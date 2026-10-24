"""Generate a self-contained Linux startup script. No AWS credentials needed."""
from pathlib import Path

root = Path(__file__).resolve().parent
worker = (root / 'worker.py').read_text(encoding='utf-8')
script = '''#!/bin/bash
set -euxo pipefail
exec > >(tee -a /var/log/cloud-ml-setup.log /dev/console) 2>&1
trap 'echo CLOUD_ML_SETUP_FAILED' ERR
dnf install -y python3 python3-pip
mkdir -p /opt/cloud-ml
python3 -m venv /opt/cloud-ml/venv
/opt/cloud-ml/venv/bin/python -m pip install --retries 3 --timeout 60 flask gunicorn psutil
cat > /opt/cloud-ml/worker.py <<'PYWORKER'
''' + worker + '''
PYWORKER
chown -R ec2-user:ec2-user /opt/cloud-ml
cat > /etc/systemd/system/cloud-ml.service <<'SERVICE'
[Unit]
Description=Cloud ML demonstration worker
Wants=network-online.target
After=network-online.target
[Service]
User=ec2-user
WorkingDirectory=/opt/cloud-ml
ExecStart=/opt/cloud-ml/venv/bin/gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 4 --timeout 30 worker:app
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
[Install]
WantedBy=multi-user.target
SERVICE
systemctl daemon-reload
systemctl enable --now cloud-ml
for i in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:5000/health; then
    echo CLOUD_ML_READY
    exit 0
  fi
  sleep 2
done
echo CLOUD_ML_HEALTH_FAILED
exit 1
'''
path = root / 'user-data.sh'
path.write_text(script, encoding='utf-8', newline='\n')
assert path.stat().st_size < 16384
print(f'Created {path} ({path.stat().st_size} bytes). Upload this file in Advanced details > User data.')
