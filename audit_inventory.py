"""Read-only inventory of the two regions seen in this task."""
import json
from botocore.exceptions import ClientError
from pathlib import Path
from credentials_local import demo_session

session = demo_session()
identity = session.client('sts').get_caller_identity()
print('Controller identity:', identity['Arn'])
result = {}
for region in ['ap-south-1', 'ap-southeast-2']:
    ec2 = session.client('ec2', region_name=region)
    try:
        instances = [i for page in ec2.get_paginator('describe_instances').paginate()
                     for r in page['Reservations'] for i in r['Instances']]
    except ClientError as exc:
        result[region] = {'inventory_unavailable': exc.response['Error']['Code'],
                          'reason': 'Service control policy or account permission denies this region.'}
        print(region, json.dumps(result[region]))
        continue
    result[region] = {
        'instances': [{'id': i['InstanceId'], 'type': i['InstanceType'], 'state': i['State']['Name'],
                       'tags': i.get('Tags', [])} for i in instances],
        'volumes': [{'id': v['VolumeId'], 'state': v['State'], 'size_gib': v['Size'],
                     'tags': v.get('Tags', [])} for v in ec2.describe_volumes()['Volumes']],
        'elastic_ips': len(ec2.describe_addresses()['Addresses']),
        'owned_snapshots': len(ec2.describe_snapshots(OwnerIds=['self'])['Snapshots'])}
    print(region, json.dumps(result[region]))
out = Path(__file__).resolve().parent.parent / 'cloud-ml-evidence' / 'inventory-before.json'
out.write_text(json.dumps(result, indent=2))
