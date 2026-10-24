# Actual AWS implementation

The completed live implementation uses **Sydney ap-southeast-2** because AWS denied
Mumbai through the account's service control policy. These notes describe the
actual completed run; the superseded manual runbook is excluded from the archive.

## What runs where

- Laptop: Random Forest training, held-out simulation, independent-arrival HTTP load
  generator, health-aware round-robin routing, and boto3 controller.
- AWS: two pre-provisioned Linux t3.micro workers with Standard CPU credits, each
  with an 8 GiB gp3 root disk. No load balancer, NAT Gateway or Elastic IP.
- The worker runs Flask behind Gunicorn under systemd and starts automatically.
- Only port 5000 from the laptop public IP is exposed. There is no SSH key.
- IAM access is limited to EC2 reads and tagged-worker start/stop. Temporary local
  credentials are Windows-user encrypted and must be removed after IAM revocation.

## Measurements and capacity

The initial staged calibration measures short burst performance. A t3.micro has a
10 percent CPU baseline. Therefore the highest passing burst point is scaled to
that baseline with 20 percent reserve, then confirmed under the measured one-second
SLA and CPU checks. A failed confirmation reduces the rate once before either live
comparison is run. The resulting working capacity is conservative and is not a
claim of maximum sustained throughput.

The failed 64-RPS calibration point includes local backlog errors and must not be
described as entirely server-generated failures. The Locust smoke test completed
40 requests without request errors. Locust emitted a CSV-writer shutdown exception
after printing final statistics; the main experiments use the separate bounded
HTTP generator and its request CSV files.

## Reproduction

Reproduction after cleanup requires new instances, a fresh restricted credential,
and updated config.json. Instance IDs and public IPs from this run are not reusable.

1. Generate user-data.sh with make_userdata.py; launch two tagged workers in an
   allowed region, explicitly choosing Standard CPU credits.
2. Copy config.example.json to config.json and fill in the NEW IDs/region and
   currently displayed Linux compute rate. The original workers were terminated.
3. Use the normal boto3 credential chain, or the optional Windows DPAPI helper.
4. Run calibrate.py, safe_capacity.py, then train.py.
5. Run live.py reactive and live.py predictive, sequentially.
6. Run evaluate.py. The report and plots distinguish measured and modeled values.
7. Stop controllers, terminate the test instances, check EBS/IP resources and revoke
   the temporary IAM identity. Do not include credentials in any submission archive.

## Limits

Data is deliberately synthetic and highly periodic. Model accuracy does not prove
generalization to production traces. One pair of short tests is a demonstration,
not a statistically conclusive ranking. Energy is an assumed power-allocation model.
Workload compute estimates exclude preparation, calibration, EBS, IPv4 and transfer.
Billing and credit consumption must be checked after AWS usage posts.
