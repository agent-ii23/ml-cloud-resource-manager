"""Verify a credit-aware working capacity before either live policy is tested."""
import time
import numpy as np
import pandas as pd
from cloud import Cloud, ROOT, read_config, save_config
from traffic import Traffic, request_summary


def main():
    config = read_config()
    table = pd.read_csv(ROOT / 'artifacts' / 'calibration.csv')
    passing = table[table.passes & (table.cpu_percent > 0)]
    best = passing.sort_values('rate_rps').iloc[-1]
    config['burst_capacity_rps'] = config['capacity_rps']
    config['highest_passing_burst_rate_rps'] = float(best.rate_rps)
    config['baseline_cpu_percent'] = 10.0
    candidate = .8 * float(best.rate_rps) * min(1, 10 / float(best.cpu_percent))
    cloud = Cloud(config)
    records = []
    try:
        cloud.start(config['worker1']); url = cloud.wait_ready(config['worker1'])
        for attempt in range(2):
            print(f'Confirming {candidate:.3f} RPS for 60 seconds at a 10% CPU baseline', flush=True)
            traffic = Traffic(); traffic.set(candidate, [url]); traffic.begin()
            cpu = []
            start = time.monotonic()
            try:
                while time.monotonic() - start < 60:
                    time.sleep(min(10, 60 - (time.monotonic() - start)))
                    worker = next(w for w in cloud.probe() if w['id'] == config['worker1'])
                    if worker['cpu'] is not None:
                        cpu.append(worker['cpu'])
            finally:
                traffic.finish()
            stats = request_summary(traffic.records)
            average = float(np.mean(cpu)) if cpu else None
            passed = average is not None and average <= 10 and stats['sla_violation_pct'] <= 1 and stats['generator_backlog'] == 0
            records.append(dict(rate_rps=candidate, avg_cpu_percent=average, passes=passed, **stats))
            pd.DataFrame(records).to_csv(ROOT / 'artifacts' / 'capacity_confirmation.csv', index=False)
            traffic.save(ROOT / 'artifacts' / f'capacity_confirmation_{attempt}_requests.csv')
            if passed:
                config['capacity_rps'] = candidate
                config['capacity_note'] = 'Highest passing burst rate scaled to T3.micro 10% CPU baseline with 20% reserve, then verified for 60 seconds. This is a conservative working capacity, not maximum throughput.'
                config['capacity_reference'] = 'https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html'
                save_config(config)
                print(f'CREDIT-AWARE CAPACITY VERIFIED: {candidate:.3f} RPS, measured CPU {average:.2f}%, SLA violations {stats["sla_violation_pct"]:.2f}%', flush=True)
                return
            print('Confirmation did not pass; reducing working rate once before either policy test.', flush=True)
            candidate /= 2
        raise RuntimeError('Working capacity confirmation failed. Both workers will stop; do not start policy tests.')
    finally:
        cloud.stop(cloud.ids)


if __name__ == '__main__':
    main()
