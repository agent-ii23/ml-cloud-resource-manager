import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from cloud import ROOT

out = ROOT / 'artifacts'
rows = []
fig, ax = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
for policy in ['reactive', 'predictive']:
    result = json.loads((out / f'live_{policy}_summary.json').read_text())
    if not result['complete']:
        raise SystemExit(f'{policy} run was interrupted; do not treat it as a full comparison.')
    rows.append(result)
    c = pd.read_csv(out / f'live_{policy}_control.csv')
    m = pd.read_csv(out / f'live_{policy}_minutes.csv')
    ax[0].step(c.elapsed_s / 60, c.ready, label=policy)
    ax[1].plot(m.minute + 1, m.p95_success_latency_ms, marker='.', label=policy)
    ax[2].plot(m.minute + 1, m.cpu_percent, marker='.', label=policy)
    if policy == 'predictive':
        # Forecast t is about t+5; history last observation was minute t-1.
        plot, p = plt.subplots(figsize=(11, 4))
        p.plot(m.minute, m.observed_rps, label='actual offered RPS')
        p.plot(m.minute + 4, m.prediction_5min_rps, label='forecast aligned to target minute')
        p.legend(); p.set_xlabel('replay minute'); p.set_ylabel('RPS')
        plot.tight_layout(); plot.savefig(out / 'live_forecast.png', dpi=150); plt.close(plot)
ax[0].set_ylabel('ready workers'); ax[0].legend()
ax[1].axhline(1000, color='red', linestyle='--', label='1000ms SLA')
ax[1].set_ylabel('successful-request p95 (ms)'); ax[1].legend()
ax[2].set_ylabel('measured CPU (%)'); ax[2].set_xlabel('replay minute'); ax[2].legend()
fig.tight_layout(); fig.savefig(out / 'live_comparison.png', dpi=150); plt.close(fig)
table = pd.DataFrame(rows)
table.to_csv(out / 'live_results.csv', index=False)
print(table.drop(columns=['note']).round(4).to_string(index=False))
print('\nSaved live_results.csv, live_comparison.png, live_forecast.png')
print('p95 excludes failures: always report error_pct and sla_violation_pct alongside it.')
print('A run with generator_backlog > 0 is limited by the laptop generator; disclose or repeat at lower load.')
from report import build_report
build_report()
