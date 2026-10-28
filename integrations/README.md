# Assistant integration

## HTTP API

`GET /api/v1/resources` reads the latest snapshot. `/docs` and `/openapi.json`
provide the FastAPI schema. Filters:

| Parameter | Meaning | Default |
| --- | --- | --- |
| resource_type | gpu, cpu, workstation, or kaggle | all |
| min_free_vram_gb | Minimum free memory on each candidate GPU | 0 |
| min_available_ram_gb | Minimum available RAM on a node | 0 |
| max_gpu_util_pct | Maximum observed GPU utilization | 20 |

```bash
curl 'http://127.0.0.1:8080/api/v1/resources?min_free_vram_gb=16'
```

The response includes `collected_at` (UTC), `age_seconds`, `stale`,
`candidate_resource_ids`, resource observations and limitations. Snapshots older
than three refresh intervals (minimum 30 seconds), and offline nodes, are never
candidates. Cloud quota is separate from hardware availability. This API neither
reserves resources nor runs commands. When configured, send the environment token
as a bearer Authorization header. Do not put tokens in URLs.

## Portable skill

Copy `skills/compute-resources` into the skill directory of your assistant, such
as `~/.codex/skills/compute-resources` or `~/.claude/skills/compute-resources` for
local Codex/Claude Code installations. Supply environment settings to the actual
assistant process, not only an unrelated shell:

```bash
export COMPUTE_DASHBOARD_URL=http://127.0.0.1:8080
python3 skills/compute-resources/scripts/query_resources.py --min-free-vram-gb 16
```

Optionally set `COMPUTE_DASHBOARD_API_TOKEN` privately. The client requires HTTPS
for a token sent to a non-loopback host, does not follow redirects, and times out
after 15 seconds. An SSH tunnel to loopback is another option. Do not check token
values or actual deployment URLs into the public repository.

Ask: "Which GPUs have at least 16 GB free?" or "What CPU resources are available?"
The skill reports freshness and distinguishes observed candidates from confirmed
scheduler availability. It cannot submit jobs.

## Stdio MCP for local assistant hosts

Install the maintained v1 SDK line explicitly:

```bash
.venv/bin/python -m pip install -r requirements-mcp.txt
.venv/bin/python -m integrations.mcp_server
```

The second command is a stdio server, not an interactive command-line UI. Configure
your MCP-capable host to launch it. A typical Claude Desktop configuration entry:

```json
{
  "mcpServers": {
    "compute-dashboard": {
      "command": "/absolute/path/to/checkout/.venv/bin/python",
      "args": ["/absolute/path/to/checkout/integrations/mcp_server.py"],
      "env": {"COMPUTE_DASHBOARD_URL": "http://127.0.0.1:8080"}
    }
  }
}
```

This exposes the read-only `query_compute_resources` tool with the same filters.
Store an optional token in your host's secure environment; never share real
credential-bearing configuration. The adapter contacts the dashboard but does
not collect metrics or access SSH itself.

Hosted ChatGPT/Claude clients cannot automatically use a local stdio process or
reach your machine's loopback address. Those clients need a separately configured,
reachable authenticated HTTPS API/action or an authenticated remote MCP service.
This repository does not publish a remote endpoint, open firewall rules or add
account connectors. A local skill alone does not establish hosted connectivity.

SDK reference: https://py.sdk.modelcontextprotocol.io/v1/
