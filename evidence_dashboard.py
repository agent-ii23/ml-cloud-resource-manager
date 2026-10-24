"""Read-only localhost view of experiment artifacts for genuine screenshots."""
import csv
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
ART = ROOT / 'artifacts'


def table(name, limit=20):
    file = ART / name
    if not file.exists():
        return '<p>Waiting for this experiment stage to complete.</p>'
    with file.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        rows = list(reader)
    html = '<table><tr>' + ''.join(f'<th>{escape(h)}</th>' for h in headers) + '</tr>'
    for row in rows[-limit:]:
        html += '<tr>' + ''.join(f'<td>{escape(str(row.get(h, "")))}</td>' for h in headers) + '</tr>'
    return html + '</table>'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = urlsplit(self.path).path
        if route.startswith('/assets/'):
            file = (ART / route.removeprefix('/assets/')).resolve()
            if not file.is_relative_to(ART.resolve()) or file.suffix not in ['.png', '.csv'] or not file.exists():
                self.send_error(404); return
            data = file.read_bytes()
            self.send_response(200); self.send_header('Content-Type', mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            self.end_headers(); self.wfile.write(data); return
        if route == '/calibration':
            body = '<h1>Real EC2 capacity calibration</h1><p>Two t3.micro workers in Sydney | Standard CPU credits | Actual request measurements</p>'
            body += table('calibration.csv')
            body += '<h2>Credit-aware working capacity confirmation</h2>' + table('capacity_confirmation.csv')
            if (ROOT / 'config.json').exists():
                config = json.loads((ROOT / 'config.json').read_text())
                body += f'<p>Working capacity: <b>{config.get("capacity_rps", "pending")} RPS</b> | Measured standby startup: <b>{config.get("boot_seconds", "pending")} seconds</b></p>'
        elif route == '/model':
            body = '<h1>Five-minute workload forecast</h1><p>Synthetic traffic | Chronological split with boundary purge | Random Forest and two baselines</p>'
            body += table('accuracy.csv') + '<img src="/assets/comparison.png">'
        elif route == '/live':
            body = '<h1>Actual EC2 scaling experiments</h1><p>Rows below are saved measurements and decisions, not invented demo values.</p>'
            for policy in ['reactive', 'predictive']:
                body += '<h2>' + policy.capitalize() + '</h2>'
                body += table(f'live_{policy}_minutes.csv', 3)
                body += table(f'live_{policy}_control.csv', 3)
        else:
            body = '<h1>Cloud resource management results</h1>'
            body += table('live_results.csv') + '<img src="/assets/live_comparison.png">'
        page = '<!doctype html><html><head><meta charset="utf-8"><style>'
        page += 'body{font-family:Arial,sans-serif;margin:28px;color:#152238}h1{font-size:26px}h2{font-size:20px}p{font-size:15px}table{border-collapse:collapse;font-size:12px;margin:18px 0;width:100%}th,td{border:1px solid #c8d2dd;padding:8px;text-align:left}th{background:#e6eef7}img{max-width:100%;max-height:650px}nav a{margin-right:24px}'
        page += '</style></head><body><nav><a href="/calibration">Calibration</a><a href="/model">Model</a><a href="/live">Live control</a><a href="/results">Results</a></nav>' + body + '</body></html>'
        self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers(); self.wfile.write(page.encode())

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    (ROOT.parent / 'cloud-ml-evidence' / 'local-dashboard-pid.txt').write_text(str(os.getpid()))
    print('Read-only evidence dashboard: http://127.0.0.1:8765/calibration', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
