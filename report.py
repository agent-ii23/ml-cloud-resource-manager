"""Generate a local, printable HTML report from completed experiment artifacts."""
from html import escape
import json

import pandas as pd

from cloud import ROOT, read_config


def build_report():
    out = ROOT / 'artifacts'
    config = read_config()
    accuracy = pd.read_csv(out / 'accuracy.csv')
    sim = pd.read_csv(out / 'simulation_results.csv')
    live = pd.read_csv(out / 'live_results.csv')
    columns = ['policy', 'p95_success_latency_ms', 'error_pct', 'sla_violation_pct',
               'avg_measured_cpu_pct', 'workload_instance_hours', 'compute_cost_model_usd', 'energy_model_kwh']
    cap = config['capacity_rps']
    rate = config['compute_hourly_usd']
    body = f'''<h1>ML-Based Cloud Resource Management</h1>
<p>Parth — Computer Engineering</p>
<h2>1. Objective and implementation</h2>
<p>Predict application workload and adjust cloud capacity between one and two Amazon EC2
Linux t3.micro workers in Sydney. A laptop trains a Random Forest, generates requests,
distributes traffic to application-healthy workers, and uses boto3 to start or stop a
pre-provisioned standby. This is a custom resource manager, not AWS Auto Scaling.
The base worker is required while traffic runs. Both workers are stopped automatically after each test.</p>
<h2>2. Input data, features and algorithm</h2>
<p>The workload is synthetic: eight days of one-minute request-rate observations, a repeating
20-minute demand cycle, daily modulation and seeded random noise. It is deliberately easy to
reproduce and is not a public production trace. Input features are the latest completed
minute and nine previous minutes, trailing five/fifteen-minute means and standard deviations,
daily sine/cosine features, and minute of hour. The target is requests/second five minutes
ahead. A 120-tree Random Forest of maximum depth ten is compared with persistence and a
five-minute moving average. Six days are used for training, one for validation and one
for testing; training targets crossing each time boundary are excluded. No random split is used.</p>
{accuracy.round(4).to_html(index=False, border=0)}
<h2>3. Capacity and scaling</h2>
<p>Each request consumes approximately 30 milliseconds of thread CPU time. Measured capacity
for this experiment is <b>{cap:.3f} requests/second per worker</b>: the passing burst
rate scaled to the t3.micro 10% CPU baseline with 20% reserve, reduced further when
confirmation failed, and verified for sixty seconds before either policy comparison.
It is a conservative working capacity rather than a maximum-throughput claim.
Measured standby restart-to-application-ready time is <b>{config['boot_seconds']:.1f} seconds</b>.
The simulated startup delay is that measurement rounded up to whole minutes. These short
measurements do not establish long-run capacity on burstable instances.</p>
<p>Predictive desired capacity = min(2, max(1, ceil(1.2 × forecast / capacity))). Reactive scale-out
uses observed offered demand above 80% of ready capacity or CPU above 80%. Predictive fallback
uses demand above 90% or CPU above 80%. The live controller checks state about every ten seconds,
refreshes public IPs after restarts and only routes requests to workers whose health endpoint
passes. Scale-in requires three consecutive low-demand minutes, measured CPU below 35%,
a forecast of one worker for the predictive policy, and three minutes of standby readiness.
Traffic is drained before stopping the standby. Pending starts are not duplicated. No new
instances can be launched by the controller credentials.</p>
<h2>4. Experiment and metrics</h2>
<p>Both policies replay the same fifteen-minute arrival-rate schedule. A higher spike is injected
at minutes six and seven, followed by a low-demand interval from minute ten. Demand is
scheduled independently of server response time. Each policy begins with one worker and
the same preceding history; live forecasts are recomputed from observed request attempts.
CPU-credit balances and network conditions can differ, so one pair of runs is a demonstration,
not statistically conclusive evidence. AWS basic CPU monitoring is supporting evidence;
application telemetry provides faster CPU samples.</p>
<p>MAE = mean absolute forecast error; RMSE = square root of mean squared error;
WAPE = 100 × sum absolute errors / sum actual values. Successful-request p95 is reported
alongside errors. SLA violations include failed requests, timeouts and successful requests
longer than 1000 milliseconds, with each request counted once.</p>
{live[columns].round(5).to_html(index=False, border=0)}
<img src="live_comparison.png"><img src="live_forecast.png">
<h2>5. Long-run simulation and wrong predictions</h2>
<p>The held-out trace is simulated with both policies, an explicit standby startup delay,
and a three-minute scale-in confirmation. The spike and drop tests deliberately retain
the unperturbed forecast: they are frozen-forecast fault injection, not predictions from
a model updated with the injected observations. Underprediction increases overloaded minutes
until reactive fallback and startup restore capacity; a two-worker maximum can still leave
excess demand. Overprediction leaves spare capacity running until conservative scale-in.
No forecaster guarantees prevention of unexpected overload.</p>
{sim.round(5).to_html(index=False, border=0)}
<img src="comparison.png">
<h2>6. Cost, utilization and energy assumptions</h2>
<p>Simulation utilization = min(load / (ready workers × capacity), 1). The simulated
latency proxy is 30 / (1 − min(load / capacity, 0.98)) milliseconds, where capacity means
total ready capacity. Its p95 is a percentile of minute-level proxy values, not a percentile
of real request latencies. Overloaded-minute percentage is not a measured request SLA rate.</p>
<p>Workload instance-hours = sum(sampled running/pending/stopping count × interval seconds) / 3600.
Modeled workload compute cost = instance-hours × {rate:.6f} USD/hour, using the rate recorded
from AWS. It excludes setup, calibration, preflight, shutdown, EBS, IPv4 and transfer.
Full gross cloud cost also includes volume GB-months, public IPv4 address-hours and billable
transfer. Credits reduce payable charges, not gross resource consumption. The final Billing
screen is the source for account charges and credits; its immediate value may lag usage.</p>
<p>Energy is an illustrative allocation model, not measured EC2 power: each running worker is
assumed to consume 10 W idle and 25 W at full utilization/CPU, linearly interpolated. Energy
(kWh) = sum(power W × interval hours) / 1000. Startup is counted at idle power; missing CPU
samples use idle power and may underestimate energy. Halving/doubling both assumed powers
halves/doubles modeled energy. Physical hardware power, PUE and shared-host allocation are unknown.</p>
<h2>7. Limitations and conclusion</h2>
<p>This demonstrates a working prediction-and-control loop on real EC2 resources. Predictive
capacity can trade more instance time for fewer overloads; the result table should be used
to judge the actual tradeoff. Repeated synthetic patterns favor the model, short burstable-CPU
measurements may not generalize, there are only two workers, and the laptop is both traffic
generator and router. Production use would require representative traces, repeated trials,
robust routing, queue/backpressure control, stronger telemetry failure handling and budget controls.</p>
<h2>8. AWS evidence and cleanup</h2>
<p>The following screenshots document the actual account, workers, CPU monitoring and cleanup.
An empty screenshot section means this evidence still needs to be added. Stopped instances
retain storage; termination and volume checks are necessary. A Free account plan was retained
without upgrade. Final billing should be rechecked after AWS posts delayed usage.</p>
'''
    shots = out / 'screenshots'; shots.mkdir(exist_ok=True)
    names = ['01-free-plan.png', '02-workers.png', '03-reactive-scaling.png',
             '04-predictive-scaling.png', '05-cpu-worker1.png', '06-cpu-worker2.png',
             '07-terminated.png', '08-volumes.png', '09-billing.png']
    for name in names:
        if (shots / name).exists():
            body += f'<h3>{escape(name)}</h3><img src="screenshots/{escape(name)}">'
        else:
            body += f'<p>Evidence pending: {escape(name)}</p>'
    style = '''body{font-family:Arial,sans-serif;max-width:1100px;margin:36px auto;line-height:1.5;color:#152238}
    h1,h2{color:#123c69}table{border-collapse:collapse;font-size:11px;width:100%;margin:18px 0}
    td,th{border:1px solid #ddd;padding:6px;text-align:left}img{max-width:100%;margin:12px 0}
    @media print{body{margin:0}h2{break-after:avoid}tr,img{break-inside:avoid}}'''
    (out / 'report.html').write_text('<!doctype html><html><head><meta charset="utf-8"><title>Cloud ML Report</title>'
                                   f'<style>{style}</style></head><body>{body}</body></html>', encoding='utf-8')
    print(f'Printable report saved: {out / "report.html"}')


if __name__ == '__main__':
    build_report()
