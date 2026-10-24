"""Local synthetic-workload experiment; does not contact AWS."""
import json
from pathlib import Path

import joblib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from common import HORIZON, features, simulate, summary

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'artifacts'


def main():
    OUT.mkdir(exist_ok=True)
    config = ROOT / 'config.json'
    settings = json.loads(config.read_text()) if config.exists() else {}
    capacity = settings.get('capacity_rps', 10.0)
    calibrated = 'capacity_rps' in settings
    rng = np.random.default_rng(42)
    minute = np.arange(8 * 1440)
    phase = minute % 20
    # Repeated scheduled traffic with noise; deliberately synthetic, not NASA data.
    shape = np.interp(phase, [0, 4, 9, 12, 13, 19], [.22, .22, 1.25, 1.25, .22, .22])
    daily = 1 + .08 * np.sin(2 * np.pi * minute / 1440)
    load = capacity * np.clip(shape * daily + rng.normal(0, .025, len(minute)), .05, 1.6)
    df = pd.DataFrame(dict(minute=minute, load=load))
    X, y = features(df), df.load.shift(-HORIZON)
    # 6 days train, 1 validation, 1 test. Purge horizon-crossing labels.
    valid = X.notna().all(axis=1) & y.notna()
    train = valid & (df.minute + HORIZON < 6 * 1440)
    val = valid & (df.minute >= 6 * 1440) & (df.minute + HORIZON < 7 * 1440)
    test = valid & (df.minute >= 7 * 1440)
    model = RandomForestRegressor(n_estimators=120, max_depth=10, n_jobs=2, random_state=42)
    model.fit(X.loc[train], y.loc[train])
    scores = []
    for split, mask in [('validation', val), ('test', test)]:
        truth = y.loc[mask].to_numpy()
        preds = {'persistence': X.loc[mask, 'lag0'].to_numpy(),
                 'moving_average_5': X.loc[mask, 'mean5'].to_numpy(),
                 'RandomForest': model.predict(X.loc[mask])}
        for name, pred in preds.items():
            err = truth - pred
            scores.append(dict(split=split, model=name, MAE=np.abs(err).mean(),
                               RMSE=np.sqrt(np.mean(err ** 2)),
                               WAPE_pct=100 * np.abs(err).sum() / truth.sum()))
    scores = pd.DataFrame(scores)
    scores.to_csv(OUT / 'accuracy.csv', index=False)
    joblib.dump(model, OUT / 'model.joblib')
    (OUT / 'training_metadata.json').write_text(json.dumps(dict(capacity_rps=capacity,
        horizon_minutes=HORIZON, synthetic=True, calibrated=calibrated), indent=2))
    df.to_csv(OUT / 'trace.csv', index=False)
    # A prediction made at index t is about t+5, not the current minute.
    test_df = df.loc[test].copy()
    test_df['prediction'] = model.predict(X.loc[test])
    test_df['target_minute'] = test_df.minute + HORIZON
    test_df['actual_future'] = y.loc[test]
    test_df.to_csv(OUT / 'test_predictions.csv', index=False)
    curves, records = {}, []
    base = test_df.load.to_numpy()
    prediction = test_df.prediction.to_numpy()
    for scenario in ['normal', 'unexpected_spike', 'unexpected_drop']:
        actual = base.copy()
        if scenario == 'unexpected_spike':
            actual[200:215] += capacity
        if scenario == 'unexpected_drop':
            actual[300:325] *= .15
        for policy in ['reactive', 'predictive']:
            # Fault tests hold the unperturbed forecast fixed on purpose.
            boot = max(1, int(np.ceil(settings.get('boot_seconds', 120) / 60)))
            curve = simulate(policy, actual, prediction, capacity, boot_minutes=boot)
            curve.to_csv(OUT / f'sim_{scenario}_{policy}.csv', index=False)
            record = dict(scenario=scenario, policy=policy, **summary(curve))
            record['compute_cost_model_usd'] = (record['instance_hours'] * settings['compute_hourly_usd']
                                                if 'compute_hourly_usd' in settings else np.nan)
            records.append(record)
            if scenario == 'normal':
                curves[policy] = curve
    pd.DataFrame(records).to_csv(OUT / 'simulation_results.csv', index=False)
    start = int(test_df.minute.iloc[0]) + 3
    replay = df[(df.minute >= start) & (df.minute < start + 15)].copy()
    # Same reproducible unexpected spike/drop is used in BOTH live policies.
    replay.loc[replay.index[6:8], 'load'] = 1.7 * capacity
    replay.loc[replay.index[10:], 'load'] = .15 * capacity
    replay.to_csv(OUT / 'replay.csv', index=False)
    df[(df.minute >= start - 60) & (df.minute < start)].to_csv(OUT / 'seed_history.csv', index=False)
    fig, ax = plt.subplots(3, 1, figsize=(12, 9))
    ax[0].plot(test_df.target_minute.iloc[:180], test_df.actual_future.iloc[:180], label='actual at target minute')
    ax[0].plot(test_df.target_minute.iloc[:180], test_df.prediction.iloc[:180], label='forecast made 5 min earlier')
    ax[0].set_ylabel('requests/second'); ax[0].legend()
    for policy, curve in curves.items():
        ax[1].step(curve.minute.iloc[:180], curve.ready.iloc[:180], label=policy)
    ax[1].set_ylabel('ready instances'); ax[1].legend()
    for policy, curve in curves.items():
        ax[2].plot(curve.minute.iloc[:180], curve.latency_proxy_ms.iloc[:180], label=policy)
    ax[2].set_ylabel('latency proxy (ms)'); ax[2].set_xlabel('simulation minute'); ax[2].legend()
    fig.tight_layout(); fig.savefig(OUT / 'comparison.png', dpi=150); plt.close(fig)
    print(scores.round(3).to_string(index=False))
    print('\nSIMULATION (latency, utilization and energy are modeled):')
    print(pd.DataFrame(records).round(3).to_string(index=False))
    print(f'\nCapacity: {capacity:.2f} RPS; calibrated={calibrated}; outputs: {OUT}')
    print('Fault simulations use frozen baseline forecasts; live forecasts update from observed history.')


if __name__ == '__main__':
    main()
