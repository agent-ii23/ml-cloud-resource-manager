"""Bounded open-loop HTTP generator. Offered demand is independent of latency."""
import csv
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

from common import SLA_MS


class Traffic:
    def __init__(self):
        self.rate = 0.0
        self.urls = []
        self.records = []
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.slots = threading.BoundedSemaphore(128)
        self.pool = ThreadPoolExecutor(max_workers=64)
        self.local = threading.local()
        self.thread = threading.Thread(target=self.schedule, daemon=True)
        self.counter = 0
        self.timeline = None
        self.timeline_start = None

    def set_timeline(self, rates, started):
        with self.lock:
            self.timeline, self.timeline_start = list(rates), started

    def begin(self):
        self.thread.start()

    def set(self, rate, urls):
        with self.lock:
            self.rate, self.urls = float(rate), list(urls)

    def schedule(self):
        next_at = time.monotonic()
        while not self.stop_event.is_set():
            with self.lock:
                rate, urls = self.rate, list(self.urls)
                if self.timeline is not None:
                    minute = int(max(0, time.monotonic() - self.timeline_start) // 60)
                    rate = self.timeline[minute] if minute < len(self.timeline) else 0
            if rate <= 0:
                self.stop_event.wait(.05)
                next_at = time.monotonic()
                continue
            if self.stop_event.wait(max(0, next_at - time.monotonic())):
                break
            now = time.monotonic()
            row = dict(at=now, latency_ms=None, success=False, reason='pending')
            with self.lock:
                self.records.append(row)
            if not urls:
                row.update(latency_ms=0, reason='no_healthy_worker')
            elif not self.slots.acquire(blocking=False):
                row.update(latency_ms=0, reason='generator_backlog')
            else:
                url = urls[self.counter % len(urls)]
                self.counter += 1
                self.pool.submit(self.request, row, url)
            next_at += 1 / rate
            if now - next_at > .5:
                # Never dump a large catch-up burst after a laptop scheduling stall.
                next_at = now

    def request(self, row, url):
        started = time.monotonic()
        try:
            if not hasattr(self.local, 'session'):
                self.local.session = requests.Session()
                self.local.session.trust_env = False
            response = self.local.session.get(url + '/', timeout=(2, 3))
            ok = response.status_code == 200 and response.json().get('ok') is True
            row.update(latency_ms=(time.monotonic() - started) * 1000,
                       success=ok, reason='ok' if ok else f'http_{response.status_code}')
        except (requests.RequestException, ValueError) as exc:
            row.update(latency_ms=(time.monotonic() - started) * 1000,
                       reason=f'timeout_or_connection_error: {type(exc).__name__}: {str(exc)[:180]}')
        finally:
            self.slots.release()

    def window(self, since, until=None):
        until = time.monotonic() if until is None else until
        with self.lock:
            return [dict(r) for r in self.records if since <= r['at'] < until]

    def finish(self):
        self.stop_event.set()
        self.thread.join(timeout=5)
        self.pool.shutdown(wait=True)

    def save(self, path):
        with open(path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['at', 'latency_ms', 'success', 'reason'])
            writer.writeheader(); writer.writerows(self.records)


def request_summary(records):
    n = len(records)
    latencies = [r['latency_ms'] for r in records if r['success'] and r['latency_ms'] is not None]
    return dict(attempted=n,
                error_pct=100 * sum(not r['success'] for r in records) / max(1, n),
                sla_violation_pct=100 * sum(not r['success'] or r['latency_ms'] is None or r['latency_ms'] > SLA_MS for r in records) / max(1, n),
                p95_success_latency_ms=float(np.percentile(latencies, 95)) if latencies else None,
                generator_backlog=sum(r['reason'] == 'generator_backlog' for r in records))
