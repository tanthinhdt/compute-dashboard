"""Read-only MCP adapter. Run: python -m integrations.mcp_server"""
import importlib.util
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

client_path = Path(__file__).resolve().parents[1] / 'skills/compute-resources/scripts/query_resources.py'
spec = importlib.util.spec_from_file_location('compute_resources_client', client_path)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
mcp = FastMCP('Compute Dashboard')


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True))
def query_compute_resources(resource_type: str | None = None, min_free_vram_gb: float = 0,
                            min_available_ram_gb: float = 0, max_gpu_util_pct: float = 20) -> dict:
    """Read current compute observations. Candidates are not reservations; inspect stale and age_seconds."""
    return client.query_resources(resource_type, min_free_vram_gb, min_available_ram_gb, max_gpu_util_pct)


if __name__ == '__main__':
    mcp.run(transport='stdio')
