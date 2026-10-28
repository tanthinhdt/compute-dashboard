# Compute Dashboard

A self-hosted dashboard for local workstations, SSH GPU hosts, SLURM CPU clusters
and optional Kaggle quota monitoring. Includes a resource overview, device and
storage details, deduplicated job tables, and a weekly job timeline.

## Run locally

Requires Python 3.11+ on Linux. NVIDIA metrics use `nvidia-smi` when available.
Remote hosts need Python 3; SSH GPU hosts also use `nvidia-smi`. SLURM controllers
need `squeue` and `scontrol`; CPU workers use `free` and Python 3 over SSH.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp config.example.yaml config.yaml
.venv/bin/python -m app.main
```

Open http://127.0.0.1:8080. The example monitors one local workstation, binds to
loopback, and allows only loopback clients. `config.yaml` is ignored by Git.
Set `COMPUTE_DASHBOARD_CONFIG` to use another configuration path. Environment
examples in `.env.example` are documentation; the app does not automatically load
that file. Configure `user_identifiers` to make My Jobs Only recognize your accounts.

## Add resources

The configuration is organized as organizations -> clusters -> nodes. Node IDs
must be globally unique and use letters, numbers, underscores or hyphens. Add
these example clusters under an organization's `clusters` list:

```yaml
- id: gpu-pool
  name: GPU pool
  type: gpu
  nodes:
    - id: gpu-a
      name: GPU A
      ssh_host: gpu-a-alias
- id: cpu-pool
  name: CPU pool
  type: cpu
  controller_ssh_host: scheduler-alias
  controller_node: controller
  nodes:
    - id: controller
      ssh_host: controller-alias
    - id: worker-a
      ssh_host: worker-a-alias
```

SSH aliases, keys and known hosts belong in your SSH configuration, never this
repository. CPU node IDs must match SLURM node names. `controller_node` identifies
the node probed locally on the controller; all other CPU nodes use their configured
`ssh_host` or node ID. Multiple CPU and GPU groups are supported. Configure exactly
one local workstation; use SSH probes for other hosts.

For optional Kaggle monitoring install `requirements-kaggle.txt`, authenticate
using Kaggle's supported credential setup outside the repository, and add:

```yaml
- id: cloud
  name: Cloud quota
  type: kaggle
  username: example-account
  nodes:
    - id: cloud-gpu
      name: Cloud GPU
      accelerator_type: gpu
    - id: cloud-tpu
      name: Cloud TPU
      accelerator_type: tpu
```

## What the dashboard reports

- GPU indices, observed utilization, VRAM, temperatures and power.
- CPU, RAM, and mounted-disk usage; inaccessible and pseudo mounts are skipped.
- SLURM jobs with GPU processes grouped by verified cgroup/allocation membership.
  Same-name jobs remain separate. Processes without a confirmed parent stay separate.
- GPU device indices observed for each process/job; queued or unreported devices
  are labeled explicitly. Teammate counts use distinct usernames.
- One timeline bar per job spanning its days. SLURM scheduled ends represent time
  limits, not guaranteed completion. Unknown end times are explicit. Current
  probes provide snapshots, not a complete historical job archive.
- Live updates preserve DOM nodes and selection. The calendar uses browser timezone.

## Assistant API, MCP and skill

See [integrations/README.md](integrations/README.md) for API filters, a stdio MCP
adapter and installation of the portable `compute-resources` skill. The compact
`GET /api/v1/resources` endpoint reports freshness, per-device observations and
candidate resource IDs. It omits process commands, usernames and addresses.
Candidate means observed low usage, not a scheduler reservation or guaranteed
availability. The API supports an optional environment-provided bearer token.

## Deployment access

The default is local-only. For private network deployment configure both the bind
address and explicit allowed networks. Forwarded headers are trusted only from
explicit `trusted_proxies`; leave this empty without a trusted reverse proxy.
Uvicorn's own proxy-header trust is disabled by the provided launch command so the
application evaluates the actual socket peer. CORS is disabled unless origins are
configured. Keep credentials and deployment files outside Git.

`COMPUTE_DASHBOARD_API_TOKEN` protects the compact assistant endpoint only. Other
UI/API routes rely on network controls. For internet-facing access, put the entire
service behind authenticated HTTPS and review access policy; a source release
should not expose a private monitoring service. Stdio MCP runs locally and does
not open a listening port.

The example user service assumes a checkout at `%h/compute-dashboard`; adapt its
working directory and executable path if installed elsewhere. Use systemd to stop
only this service rather than matching unrelated process names.

## Test

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
npm install
npm test
.venv/bin/python scripts/audit_release.py
```

MCP integration tests additionally require `requirements-mcp.txt`. Tests use
synthetic data; no private configuration or credentials are included.

## License

Apache-2.0. See [LICENSE](LICENSE).
