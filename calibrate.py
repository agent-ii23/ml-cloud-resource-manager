import json
import time

import numpy as np
import pandas as pd

from cloud import Cloud, ROOT, read_config, save_config
from traffic import Traffic, request_summary


def main():
    config = read_config()
    cloud = Cloud(config)
    out = ROOT / 'artifacts'; out.mkdir(exist_ok=True)
    results = []
    try:
        cloud.start(config['worker1'])
        url = cloud.wait_ready(config['worker1'])
        # Measure restart-to-application-ready time, not just EC2 running state.
        cloud.stop([config['worker2']])
        cloud.ec2.get_waiter('instance_stopped').wait(InstanceIds=[config['worker2']])
        start = time.monotonic()
        cloud.start(config['worker2']); cloud.wait_ready(config['worker2'])
        config['boot_seconds'] = time.monotonic() - start
        print(f'Measured standby startup: {config["boot_seconds"]:.1f} seconds')
        cloud.stop([config['worker2']])
        for rate in [1, 2, 4, 8, 16, 32, 64]:
            print(f'CALIBRATION: {rate} requests/sec for 30 seconds', flush=True)
            traffic = Traffic(); traffic.set(rate, [url]); traffic.begin()
            samples = []
            try:
                for _ in range(3):
                    time.sleep(10)
                    w = next(w for w in cloud.probe() if w['id'] == config['worker1'])
                    if w['cpu'] is not None:
                        samples.append(w['cpu'])
            finally:
                traffic.finish()
            values = request_summary(traffic.records)
            cpu = float(np.mean(samples)) if samples else None
            passed = (values['attempted'] > 0 and values['sla_violation_pct'] <= 1
                      and values['generator_backlog'] == 0 and cpu is not None and cpu < 80)
            results.append(dict(rate_rps=rate, cpu_percent=cpu, passes=passed, **values))
            traffic.save(out / f'calibration_{rate}_requests.csv')
            print(json.dumps(results[-1]), flush=True)
            pd.DataFrame(results).to_csv(out / 'calibration.csv', index=False)
            if not passed:
                break
        good = [r['rate_rps'] for r in results if r['passes']]
        if not good:
            raise RuntimeError('Even 1 RPS failed. Do not continue: inspect app/network and calibration.csv.')
        config['capacity_rps'] = .8 * max(good)
        config['capacity_note'] = '80% of highest passing short calibration rate; not a long-run guarantee'
        save_config(config)
        print(f'\nCAPACITY SAVED: {config["capacity_rps"]:.2f} RPS. Both workers will now stop.')
        print('Rerun train.py, then live.py reactive, then live.py predictive.')
    finally:
        cloud.stop(cloud.ids)


if __name__ == '__main__':
    main()
