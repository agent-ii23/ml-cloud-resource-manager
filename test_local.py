"""Local checks only. Never launches, starts, stops or queries AWS resources."""
import unittest
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pandas as pd

from common import features, simulate, target
from traffic import Traffic, request_summary


class Checks(unittest.TestCase):
    def test_real_http_generator_counts_errors(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.send_header('Content-Type', 'application/json')
                self.end_headers(); self.wfile.write(b'{"ok":true}')
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        traffic = Traffic()
        try:
            traffic.set(10, [f'http://127.0.0.1:{server.server_port}']); traffic.begin()
            time.sleep(.5)
            traffic.set(10, []); time.sleep(.3)
        finally:
            traffic.finish(); server.shutdown(); server.server_close()
        result = request_summary(traffic.records)
        self.assertGreater(result['attempted'], 3)
        self.assertGreater(result['error_pct'], 0)
        self.assertLess(result['error_pct'], 100, str(traffic.records))
        self.assertEqual(result['generator_backlog'], 0)

    def test_worker_endpoints(self):
        from worker import app
        with app.test_client() as client:
            self.assertEqual(client.get('/health').json['status'], 'ok')
            self.assertIn('cpu_percent', client.get('/metrics').json)
            self.assertTrue(client.get('/').json['ok'])

    def test_no_future_feature_leak(self):
        before = pd.DataFrame({'minute': range(40), 'load': np.arange(40, dtype=float)})
        changed = before.copy(); changed.loc[26:, 'load'] = 99999
        pd.testing.assert_series_equal(features(before).loc[25], features(changed).loc[25])

    def test_capacity_bounds_and_fallback(self):
        self.assertEqual(target('predictive', 9999, 1, 1, 10), 2)
        self.assertEqual(target('predictive', -5, 1, 1, 10), 1)
        self.assertEqual(target('predictive', 0, 12, 1, 10), 2)
        self.assertEqual(target('predictive', 0, 1, 1, 10, cpu=85), 2)

    def test_boot_has_cost_before_capacity(self):
        c = simulate('reactive', [12] * 5, [12] * 5, 10, boot_minutes=2)
        self.assertEqual(c.ready.tolist(), [1, 1, 2, 2, 2])
        self.assertEqual(c.running.tolist(), [2, 2, 2, 2, 2])

    def test_scalein_waits_three_low_minutes(self):
        c = simulate('reactive', [12, 12, 12, 1, 1, 1], [0] * 6, 10, boot_minutes=1)
        self.assertEqual(c.ready.iloc[3], 2)
        self.assertEqual(c.ready.iloc[4], 2)
        self.assertEqual(c.ready.iloc[5], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
