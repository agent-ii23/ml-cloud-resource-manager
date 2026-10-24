"""15-minute real EC2 replay. Only starts/stops the two configured workers."""
import argparse
import json
import time

import joblib
import numpy as np
import pandas as pd

from cloud import Cloud, ROOT, read_config
from common import features, target
from traffic import Traffic, request_summary


def run(policy):
    config = read_config()
    if 'capacity_rps' not in config:
        raise SystemExit('Run calibrate.py and then train.py first.')
    capacity = config['capacity_rps']
    out = ROOT / 'artifacts'
    history = pd.read_csv(out / 'seed_history.csv')
    replay = pd.read_csv(out / 'replay.csv')
    model = joblib.load(out / 'model.joblib')  # Only our locally trained artifact.
    if len(replay) != 15:
        raise SystemExit('Expected exactly 15 replay minutes.')
    # Prevent accidental use of replay trained with placeholder capacity.
    meta = json.loads((out / 'training_metadata.json').read_text())
    if abs(meta['capacity_rps'] - capacity) > 1e-9:
        raise SystemExit('Capacity changed: rerun train.py before live tests.')
    cloud = Cloud(config)
    traffic = Traffic()
    controls, minutes = [], []
    complete = False
    traffic_started = False
    preflight_start = time.monotonic()
    print(f'{policy.upper()} replay: 15 minutes. Ctrl+C stops traffic and requests both workers stop.')
    try:
        cloud.stop([config['worker2']])
        cloud.ec2.get_waiter('instance_stopped').wait(InstanceIds=[config['worker2']])
        cloud.start(config['worker1'])
        url = cloud.wait_ready(config['worker1'])
        # Exclude a short settling period from experiment timing.
        time.sleep(10)
        start = time.monotonic()
        traffic.set_timeline(replay.load.tolist(), start)
        traffic.set(0, [url]); traffic.begin(); traffic_started = True
        previous = start
        low_minutes = 0
        standby_ready_since = None
        wanted_last = 1
        startup_requested_at = None
        drain_until = None
        for minute, row in replay.reset_index(drop=True).iterrows():
            minute_start = start + minute * 60
            minute_end = minute_start + 60
            prediction = max(0, float(model.predict(features(history).iloc[[-1]])[0]))
            observed = float(history.load.iloc[-1])
            ready_urls = [w['url'] for w in cloud.probe() if w['ready']
                          and (drain_until is None or w['id'] != config['worker2'])]
            traffic.set(float(row.load), ready_urls)
            minute_cpu = []
            last_workers = []
            while time.monotonic() < minute_end:
                workers = cloud.probe(); last_workers = workers
                now = time.monotonic()
                dt = now - previous; previous = now
                if drain_until is not None and now >= drain_until:
                    cloud.stop([config['worker2']])
                    drain_until = None
                    standby_ready_since = None
                    workers = cloud.probe(); last_workers = workers
                ready = [w for w in workers if w['ready']
                         and (drain_until is None or w['id'] != config['worker2'])]
                traffic.set(float(row.load), [w['url'] for w in ready])
                recent = traffic.window(max(start, now - 10), now)
                if now - minute_start >= 10:
                    observed = len(recent) / min(10, now - start)
                cpus = [w['cpu'] for w in ready if w['cpu'] is not None]
                cpu_max = max(cpus) if cpus else None
                minute_cpu.extend(cpus)
                standby = next(w for w in workers if w['id'] == config['worker2'])
                if standby['ready'] and standby_ready_since is None and drain_until is None:
                    standby_ready_since = now
                    if startup_requested_at is not None:
                        print(f'STANDBY READY after {now - startup_requested_at:.1f}s', flush=True)
                wanted = target(policy, prediction, observed, len(ready), capacity, cpu_max or 0)
                if wanted == 2 and standby['state'] == 'stopped':
                    cloud.start(config['worker2']); startup_requested_at = now
                    print('Scale-out reason: forecast/demand/CPU threshold', flush=True)
                if wanted == 2:
                    low_minutes = 0
                    drain_until = None
                wanted_last = wanted
                running = sum(w['state'] in ('pending', 'running', 'stopping') for w in workers)
                controls.append(dict(elapsed_s=now - start, minute=int(minute), dt_s=dt,
                                     prediction_5min_rps=prediction, observed_rps=observed,
                                     ready=len(ready), running=running,
                                     desired=wanted, cpu_max_percent=cpu_max,
                                     cpu_sum_percent=sum(cpus), cpu_samples=len(cpus)))
                time.sleep(max(0, min(10, minute_end - time.monotonic())))
            now = time.monotonic()
            # Attribute the trailing sampling interval to the last observed state.
            if controls:
                tail = dict(controls[-1]); tail['elapsed_s'] = now - start
                tail['dt_s'] = now - previous; controls.append(tail); previous = now
            events = traffic.window(minute_start, minute_end)
            observed_minute = len(events) / 60
            history = pd.concat([history, pd.DataFrame([dict(minute=int(row.minute), load=observed_minute)])], ignore_index=True)
            standby = next(w for w in last_workers if w['id'] == config['worker2'])
            # A complete low-demand minute is required; missing CPU never allows scale-in.
            low = (wanted_last == 1 and observed_minute < .65 * capacity
                   and bool(minute_cpu) and max(minute_cpu) < 35)
            low_minutes = low_minutes + 1 if low else 0
            if (standby['ready'] and low_minutes >= 3 and standby_ready_since is not None
                    and now - standby_ready_since >= 180):
                # Drain asynchronously so the next load minute is not shifted.
                primary = [w['url'] for w in last_workers if w['id'] == config['worker1'] and w['ready']]
                traffic.set(float(row.load), primary)
                drain_until, low_minutes = now + 4, 0
            minutes.append(dict(minute=int(minute), trace_minute=int(row.minute),
                                requested_rps=float(row.load), observed_rps=observed_minute,
                                prediction_5min_rps=prediction,
                                cpu_percent=float(np.mean(minute_cpu)) if minute_cpu else None))
            print(f'{policy} minute {minute+1:02}/15: offered={observed_minute:.2f} '
                  f'forecast(+5min)={prediction:.2f} ready={controls[-1]["ready"]} '
                  f'desired={wanted_last}', flush=True)
            pd.DataFrame(controls).to_csv(out / f'live_{policy}_control.csv', index=False)
        complete = True
    finally:
        if traffic_started:
            traffic.finish()
            traffic.save(out / f'live_{policy}_requests.csv')
        # Stop first; artifact-writing failures must not leave workers running.
        cloud.stop(cloud.ids)
        if controls:
            pd.DataFrame(controls).to_csv(out / f'live_{policy}_control.csv', index=False)
            m = pd.DataFrame(minutes)
            for i in m.index:
                a = start + int(m.loc[i, 'minute']) * 60
                for key, value in request_summary(traffic.window(a, a + 60)).items():
                    m.loc[i, key] = value
            m.to_csv(out / f'live_{policy}_minutes.csv', index=False)
            c = pd.DataFrame(controls)
            hours = float((c.running * c.dt_s).sum() / 3600)
            cpu_weight = c.cpu_samples * c.dt_s
            cpu = float((c.cpu_sum_percent * c.dt_s).sum() / cpu_weight.sum()) if cpu_weight.sum() else None
            result = dict(policy=policy, complete=complete, **request_summary(traffic.records),
                          avg_measured_cpu_pct=cpu, workload_instance_hours=hours,
                          compute_cost_model_usd=hours * config['compute_hourly_usd'],
                          energy_model_kwh=float(((10 * c.running + .15 * c.cpu_sum_percent) * c.dt_s).sum() / 3600 / 1000),
                          preflight_wall_seconds=start - preflight_start,
                          note='Instance-hours/cost cover sampled workload only; exclude setup, calibration, preflight, shutdown, EBS, IPv4 and transfer. Energy assumes 10W idle/25W full CPU per VM; missing CPU assumed idle.')
            (out / f'live_{policy}_summary.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result, indent=2))
        print('Stop requested for both workers. Confirm Stopped in EC2; delete resources when done.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('policy', choices=['reactive', 'predictive'])
    run(parser.parse_args().policy)
