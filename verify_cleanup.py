"""Read-only final verification; never deletes anything."""
import json
from datetime import datetime, timezone
from pathlib import Path
from credentials_local import demo_session

root = Path(__file__).resolve().parent
settings = json.loads((root / 'config.json').read_text())
ec2 = demo_session().client('ec2', region_name=settings['region'])
ids = [settings['worker1'], settings['worker2']]
instances = [i for r in ec2.describe_instances(InstanceIds=ids)['Reservations'] for i in r['Instances']]
volumes = ec2.describe_volumes()['Volumes']
addresses = ec2.describe_addresses()['Addresses']
snapshots = ec2.describe_snapshots(OwnerIds=['self'])['Snapshots']
images = ec2.describe_images(Owners=['self'])['Images']
groups = [g for g in ec2.describe_security_groups()['SecurityGroups'] if g['GroupName'] == 'cloud-ml-sg']
result = {
    'verified_at_utc': datetime.now(timezone.utc).isoformat(),
    'region': settings['region'],
    'instances': {i['InstanceId']: i['State']['Name'] for i in instances},
    'remaining_volumes': len(volumes),
    'remaining_elastic_ips': len(addresses),
    'remaining_owned_snapshots': len(snapshots),
    'remaining_owned_amis': len(images),
    'remaining_project_security_groups': len(groups),
    'other_regions': 'Mumbai inventory was denied by the account SCP; no resources were created there during this implementation.',
    'controller_identity_removed': False,
    'local_credentials_removed': False,
    'summary': 'The resource inventory below must be combined with the IAM deletion and Billing screenshots.'
}
clean = (len(instances) == 2 and all(i['State']['Name'] == 'terminated' for i in instances)
         and not volumes and not addresses and not snapshots and not images and not groups)
result['cloud_resources_clean'] = clean
file = root.parent / 'cloud-ml-evidence' / 'cleanup-verification.json'
file.write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
if not clean:
    raise SystemExit('Project cleanup not yet verified. Resolve listed remaining resources before claiming completion.')
