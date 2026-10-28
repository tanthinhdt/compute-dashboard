"""Optional end-to-end MCP check using a synthetic loopback API server."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'Install requirements-mcp.txt to test MCP transport')
class MCPStdioTests(unittest.TestCase):
    def test_tool_lists_and_queries_api(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((urlsplit(self.path), self.headers.get('Authorization')))
                body = json.dumps({'schema_version': '1.0', 'stale': False,
                                   'resources': [{'id': 'example-gpu'}],
                                   'candidate_resource_ids': ['example-gpu']}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        async def check():
            adapter = Path(__file__).resolve().parents[1] / 'integrations/mcp_server.py'
            env = dict(os.environ, COMPUTE_DASHBOARD_URL=f'http://127.0.0.1:{server.server_port}',
                       COMPUTE_DASHBOARD_API_TOKEN='test-only-token')
            params = StdioServerParameters(command=sys.executable, args=[str(adapter)], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    self.assertEqual([tool.name for tool in listing.tools], ['query_compute_resources'])
                    self.assertTrue(listing.tools[0].annotations.readOnlyHint)
                    result = await session.call_tool('query_compute_resources', {'min_free_vram_gb': 16})
                    self.assertFalse(result.isError)
                    payload = result.structuredContent or json.loads(result.content[0].text)
                    self.assertEqual(payload['candidate_resource_ids'], ['example-gpu'])
        try:
            asyncio.run(check())
            self.assertEqual(seen[0][0].path, '/api/v1/resources')
            self.assertEqual(parse_qs(seen[0][0].query)['min_free_vram_gb'], ['16.0'])
            self.assertEqual(seen[0][1], 'Bearer test-only-token')
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
