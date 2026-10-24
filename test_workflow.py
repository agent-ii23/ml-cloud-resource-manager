"""Offline integration check. Fake EC2/clock/traffic; all outputs are temporary."""
import contextlib
import io
import json
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
from unittest.mock import patch

import live
import cloud
import report


class Clock:
    def __init__(self):
        self.now = 1000.0
    def monotonic(self):
        return self.now
    def sleep(self, seconds):
        self.now += max(0, seconds)


class WorkflowTest(unittest.TestCase):
    def test_full_control_and_report_offline(self):
        source = Path(__file__).resolve().parent
        if not (source / 'artifacts' / 'model.joblib').exists():
            self.skipTest('Run train.py before this optional integration test.')
        clock = Clock()
        fixture_capacity = json.loads((source / 'artifacts' / 'training_metadata.json').read_text())['capacity_rps']
        config = dict(worker1='i-test1', worker2='i-test2', capacity_rps=fixture_capacity,
                      compute_hourly_usd=.01, boot_seconds=31)
        actions = []

        class FakeCloud:
            def __init__(self, settings):
                self.ids = ['i-test1', 'i-test2']
                self.states = {i: 'stopped' for i in self.ids}
                self.started = {}
                self.ec2 = self
            def get_waiter(self, name):
                return self
            def wait(self, **kwargs):
                pass
            def start(self, iid):
                actions.append(('start', iid))
                self.states[iid] = 'pending'; self.started[iid] = clock.now
            def stop(self, ids):
                for iid in ids:
                    actions.append(('stop', iid)); self.states[iid] = 'stopped'
            def wait_ready(self, iid):
                clock.sleep(31); self.states[iid] = 'running'
                return 'http://fake1'
            def probe(self):
                rows = []
                for number, iid in enumerate(self.ids, 1):
                    if self.states[iid] == 'pending' and clock.now - self.started[iid] >= 30:
                        self.states[iid] = 'running'
                    ready = self.states[iid] == 'running'
                    rows.append(dict(id=iid, state=self.states[iid], ready=ready,
                                     url=f'http://fake{number}' if ready else None,
                                     cpu=10.0 if ready else None))
                return rows

        class FakeTraffic:
            def __init__(self):
                self.records = []
            def set_timeline(self, rates, started):
                for minute, rate in enumerate(rates):
                    count = max(1, round(60 * rate))
                    for k in range(count):
                        self.records.append(dict(at=started + 60 * minute + 60 * (k + .5) / count,
                                                 latency_ms=100.0, success=True, reason='ok'))
            def set(self, *args):
                pass
            def begin(self):
                pass
            def finish(self):
                pass
            def save(self, path):
                import pandas as pd
                pd.DataFrame(self.records).to_csv(path, index=False)
            def window(self, since, until=None):
                end = clock.now if until is None else until
                return [dict(r) for r in self.records if since <= r['at'] < end]

        with tempfile.TemporaryDirectory(prefix='cloud-ml-workflow-') as tmp:
            root = Path(tmp); out = root / 'artifacts'; out.mkdir()
            for name in ['model.joblib', 'seed_history.csv', 'replay.csv', 'training_metadata.json',
                         'accuracy.csv', 'simulation_results.csv']:
                shutil.copy2(source / 'artifacts' / name, out / name)
            with contextlib.redirect_stdout(io.StringIO()), \
                 patch.object(live, 'ROOT', root), patch.object(live, 'read_config', return_value=config), \
                 patch.object(live, 'Cloud', FakeCloud), patch.object(live, 'Traffic', FakeTraffic), \
                 patch.object(live, 'time', clock):
                live.run('reactive'); live.run('predictive')
            for policy in ['reactive', 'predictive']:
                result = json.loads((out / f'live_{policy}_summary.json').read_text())
                self.assertTrue(result['complete'])
                self.assertEqual(result['error_pct'], 0)
                self.assertGreater(result['workload_instance_hours'], 0)
            self.assertTrue(all(iid in ['i-test1', 'i-test2'] for _, iid in actions))
            self.assertIn(('start', 'i-test2'), actions)
            with contextlib.redirect_stdout(io.StringIO()), \
                 patch.object(cloud, 'ROOT', root), patch.object(report, 'ROOT', root), \
                 patch.object(report, 'read_config', return_value=config):
                runpy.run_path(str(source / 'evaluate.py'), run_name='__main__')
            self.assertTrue((out / 'report.html').exists())
            self.assertTrue((out / 'live_comparison.png').exists())
            self.assertIn('Evidence pending', (out / 'report.html').read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
