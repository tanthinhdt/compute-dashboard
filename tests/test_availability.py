import asyncio
import importlib.util
import os
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from app.availability import resource_snapshot
from app.models import DashboardResponse, DashboardSummary, OrganizationGroup, ClusterGroup, NodeMetrics, GPUMetrics


def fixture():
    nodes = [NodeMetrics(id='gpu-a', name='GPU A', type='gpu', cpu_count=16, mem_avail_mb=65536,
                         jobs=[], gpus=[GPUMetrics(index=0, name='Example GPU', memory_total_mb=24576,
                                                   memory_free_mb=20480, utilization_gpu=5)]),
             NodeMetrics(id='offline', name='Offline', type='gpu', status='OFFLINE', mem_avail_mb=65536,
                         gpus=[GPUMetrics(index=0, name='Example GPU', memory_free_mb=20480)]),
             NodeMetrics(id='cpu-a', name='CPU A', type='cpu', mem_avail_mb=32768)]
    return DashboardResponse(summary=DashboardSummary(), organizations=[OrganizationGroup(id='org', name='Resources',
        clusters=[ClusterGroup(id='group', name='Group', type='mixed', nodes=nodes)])])


class AvailabilityTests(unittest.TestCase):
    def test_fresh_filtered_observations(self):
        result = resource_snapshot(fixture(), time.time(), 30, min_free_vram_gb=16)
        self.assertEqual(result['candidate_resource_ids'], ['gpu-a'])
        self.assertEqual(result['resources'][0]['gpus'][0]['free_vram_gb'], 20)
        self.assertNotIn('jobs', result['resources'][0])
        self.assertNotIn('ip', result['resources'][0])

    def test_stale_missing_and_offline_data_are_not_candidates(self):
        for stamp in [0, time.time() - 100]:
            result = resource_snapshot(fixture(), stamp, 30)
            self.assertTrue(result['stale'])
            self.assertEqual(result['candidate_resource_ids'], [])
        result = resource_snapshot(fixture(), time.time(), 30, resource_type='cpu', min_free_vram_gb=1)
        self.assertEqual(result['candidate_resource_ids'], [])
        self.assertEqual(len(result['resources']), 1)

    def test_http_auth_validation_and_network_policy(self):
        from app.main import app, collector
        async def check():
            transport = httpx.ASGITransport(app=app, client=('127.0.0.1', 1234))
            with patch.object(collector, 'get_latest_metrics', new=AsyncMock(return_value=fixture())), patch.object(collector, '_last_refresh_time', time.time()):
                async with httpx.AsyncClient(transport=transport, base_url='http://localhost') as client:
                    with patch.dict(os.environ, {'COMPUTE_DASHBOARD_API_TOKEN': 'test-only-token'}):
                        self.assertEqual((await client.get('/api/v1/resources')).status_code, 401)
                        headers = {'Authorization': 'Bearer test-only-token'}
                        response = await client.get('/api/v1/resources?min_free_vram_gb=16', headers=headers)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json()['candidate_resource_ids'], ['gpu-a'])
                        self.assertEqual((await client.get('/api/v1/resources?max_gpu_util_pct=101', headers=headers)).status_code, 422)
            blocked = httpx.ASGITransport(app=app, client=('192.0.2.20', 1234))
            async with httpx.AsyncClient(transport=blocked, base_url='http://localhost') as client:
                self.assertEqual((await client.get('/api/v1/resources')).status_code, 403)
                self.assertEqual((await client.get('/api/v1/resources', headers={'X-Forwarded-For': '127.0.0.1'})).status_code, 403)
        asyncio.run(check())

    def test_client_rejects_token_over_remote_plaintext(self):
        path = Path(__file__).resolve().parents[1] / 'skills/compute-resources/scripts/query_resources.py'
        spec = importlib.util.spec_from_file_location('resource_client_test', path)
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
        with patch.dict(os.environ, {'COMPUTE_DASHBOARD_URL': 'http://example.invalid', 'COMPUTE_DASHBOARD_API_TOKEN': 'test-only-token'}):
            with self.assertRaises(ValueError):
                client.query_resources()
