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
