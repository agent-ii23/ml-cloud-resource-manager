import json
import re
import time
from pathlib import Path

import boto3
import requests
from credentials_local import demo_session

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'config.json'


def read_config():
    if not CONFIG.exists():
        raise SystemExit('Run: python cloud.py setup')
    return json.loads(CONFIG.read_text())


def save_config(config):
    CONFIG.write_text(json.dumps(config, indent=2))


class Cloud:
    def __init__(self, config):
        self.config = config
        self.ids = [config['worker1'], config['worker2']]
        if len(set(self.ids)) != 2:
            raise ValueError('Worker IDs must differ.')
        self.ec2 = demo_session().client('ec2', region_name=config.get('region', 'ap-southeast-2'))
        self.http = requests.Session()
        self.http.trust_env = False
        self.validate()

    def describe(self):
        result = self.ec2.describe_instances(InstanceIds=self.ids)
        return {i['InstanceId']: i for r in result['Reservations'] for i in r['Instances']}

    def validate(self):
        info = self.describe()
        for iid in self.ids:
            i = info[iid]
            tags = {t['Key']: t['Value'] for t in i.get('Tags', [])}
            if tags.get('Project') != 'CloudML':
                raise ValueError(f'{iid}: missing Project=CloudML tag. Fix tags in EC2 console.')
            if i['InstanceType'] != 't3.micro':
                raise ValueError(f'{iid}: this runbook requires t3.micro, found {i["InstanceType"]}.')
            if i['State']['Name'] in ('terminated', 'shutting-down'):
                raise ValueError(f'{iid}: instance is terminated.')
        credit = self.ec2.describe_instance_credit_specifications(InstanceIds=self.ids)
        if any(i['CpuCredits'] != 'standard' for i in credit['InstanceCreditSpecifications']):
            raise ValueError('CPU credits must be Standard on both workers. Fix in EC2 console.')

    def start(self, iid):
        if iid not in self.ids:
            raise ValueError('Refusing to operate on an unknown instance.')
        state = self.describe()[iid]['State']['Name']
        if state == 'stopped':
            print(f'START requested: {iid}', flush=True)
            self.ec2.start_instances(InstanceIds=[iid])
        elif state == 'stopping':
            print('Waiting for previous stop to finish...', flush=True)
            self.ec2.get_waiter('instance_stopped').wait(InstanceIds=[iid])
            self.ec2.start_instances(InstanceIds=[iid])

    def stop(self, ids):
        if not set(ids).issubset(self.ids):
            raise ValueError('Refusing to operate on an unknown instance.')
        info = self.describe()
        selected = [i for i in ids if info[i]['State']['Name'] in ('pending', 'running')]
        if selected:
            self.ec2.stop_instances(InstanceIds=selected)
            print(f'STOP requested: {selected}', flush=True)

    def probe(self):
        info = self.describe()
        workers = []
        for iid in self.ids:
            i = info[iid]
            row = dict(id=iid, state=i['State']['Name'], ready=False, url=None, cpu=None)
            if row['state'] == 'running' and i.get('PublicIpAddress'):
                row['url'] = f'http://{i["PublicIpAddress"]}:5000'
                try:
                    health = self.http.get(row['url'] + '/health', timeout=2)
                    row['ready'] = health.ok and health.json().get('status') == 'ok'
                    if row['ready']:
                        row['cpu'] = float(self.http.get(row['url'] + '/metrics', timeout=2).json()['cpu_percent'])
                except (requests.RequestException, ValueError, KeyError):
                    pass
            workers.append(row)
        return workers

    def wait_ready(self, iid, timeout=600):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for w in self.probe():
                if w['id'] == iid and w['ready']:
                    print(f'HEALTHY: {iid} {w["url"]}', flush=True)
                    return w['url']
            print('Waiting for app startup (up to 10 minutes)...', flush=True)
            time.sleep(10)
        raise RuntimeError('App not reachable. Check My IP rule, public IPv4, and Get system log for CLOUD_ML_READY.')


def main():
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if action == 'setup':
        config = read_config() if CONFIG.exists() else {}
        print('Enter IDs of the TWO NEW Project=CloudML t3.micro workers, not the old lab instance.')
        for name in ('worker1', 'worker2'):
            value = input(f'{name} instance ID (i-...): ').strip()
            if not re.fullmatch(r'i-[0-9a-f]{8,17}', value):
                raise SystemExit('Invalid instance ID.')
            config[name] = value
        rate = float(input('Linux t3.micro On-Demand USD/hour shown by AWS (compute only): ').strip())
        if not 0 < rate <= .1:
            raise SystemExit('Rate unexpected for a micro instance. Recheck decimal and selected type.')
        config['compute_hourly_usd'] = rate
        config['region'] = 'ap-southeast-2'
        Cloud(config)
        save_config(config)
        print('Configuration validated and saved. No credentials saved in project files.')
    else:
        cloud = Cloud(read_config())
        if action == 'stop':
            cloud.stop(cloud.ids)
        elif action == 'status':
            print(json.dumps(cloud.probe(), indent=2))
        else:
            raise SystemExit('Usage: cloud.py setup|status|stop')


if __name__ == '__main__':
    main()
