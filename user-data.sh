#!/bin/bash
set -euxo pipefail
exec > >(tee -a /var/log/cloud-ml-setup.log /dev/console) 2>&1
trap 'echo CLOUD_ML_SETUP_FAILED' ERR
dnf install -y python3 python3-pip
mkdir -p /opt/cloud-ml
python3 -m venv /opt/cloud-ml/venv
/opt/cloud-ml/venv/bin/python -m pip install --retries 3 --timeout 60 flask gunicorn psutil
cat > /opt/cloud-ml/worker.py <<'PYWORKER'
"""Small, intentionally CPU-bound HTTP workload for a teaching demo."""
import os
import socket
import threading
import time

import psutil
from flask import Flask, jsonify

app = Flask(__name__)
cpu = 0.0


def sample_cpu():
    global cpu
    while True:
        cpu = psutil.cpu_percent(interval=1)


threading.Thread(target=sample_cpu, daemon=True).start()


@app.get('/health')
def health():
    return jsonify(status='ok', worker=socket.gethostname())


@app.get('/metrics')
def metrics():
    return jsonify(cpu_percent=cpu, worker=socket.gethostname())


@app.get('/')
def work():
    start = time.thread_time()
    value = 1
    while time.thread_time() - start < 0.030:
        value = (value * 1664525 + 1013904223) % (2 ** 32)
    return jsonify(ok=True, worker=socket.gethostname())


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '5000')), threaded=True)

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
