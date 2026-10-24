import math

import numpy as np
import pandas as pd

HORIZON = 5
MAX_INSTANCES = 2
SLA_MS = 1000


def features(df):
    s = df['load']
    out = pd.DataFrame({f'lag{i}': s.shift(i) for i in range(10)})
    for n in (5, 15):
        out[f'mean{n}'] = s.rolling(n).mean()
        out[f'std{n}'] = s.rolling(n).std()
    # Timestamp features are known at prediction time.
    out['hour_sin'] = np.sin(2 * np.pi * df['minute'] / 1440)
    out['hour_cos'] = np.cos(2 * np.pi * df['minute'] / 1440)
    out['minute_of_hour'] = df['minute'] % 60
    return out


def target(policy, prediction, load, ready, capacity, cpu=0):
    ready = max(1, ready)
    if policy == 'predictive':
        desired = max(1, math.ceil(max(0, prediction) * 1.2 / capacity))
        if load / (ready * capacity) > .90 or cpu > 80:
            desired = 2
    else:
        desired = ready
        if load / (ready * capacity) > .80 or cpu > 80:
            desired = 2
        elif load / capacity < .30 and cpu < 35:
            desired = 1
    return min(MAX_INSTANCES, desired)


def simulate(policy, loads, predictions, capacity, boot_minutes=2):
    """One base worker, one standby, explicit startup and scale-in state."""
    online = False
    pending = None
    low = 0
    rows = []
    for minute, (load, pred) in enumerate(zip(loads, predictions)):
        if pending is not None and minute >= pending:
            online, pending = True, None
        ready = 1 + int(online)
        want = target(policy, pred, load, ready, capacity)
        if want == 2:
            low = 0
            if not online and pending is None:
                pending = minute + boot_minutes
        elif online and load < .65 * capacity:
            low += 1
            if low >= 3:
                online, low = False, 0
        else:
            low = 0
        ready = 1 + int(online)
        running = 1 + int(online or pending is not None)
        rho = load / (ready * capacity)
        # These two quantities are explicitly proxies, never real AWS latency/CPU.
        latency_proxy = 30 / (1 - min(rho, .98))
        energy_w = ready * (10 + 15 * min(rho, 1)) + 10 * int(pending is not None)
        rows.append(dict(minute=minute, load=load, prediction=pred, ready=ready,
                         running=running, utilization_proxy=min(rho, 1),
                         latency_proxy_ms=latency_proxy, overload=rho > 1,
                         energy_w=energy_w))
    return pd.DataFrame(rows)


def summary(curve):
    return dict(avg_utilization_proxy=float(curve.utilization_proxy.mean()),
                p95_of_minute_latency_proxy_ms=float(np.percentile(curve.latency_proxy_ms, 95)),
                overloaded_minutes_pct=float(100 * curve.overload.mean()),
                instance_hours=float(curve.running.sum() / 60),
                energy_model_kwh=float(curve.energy_w.sum() / 60 / 1000))
