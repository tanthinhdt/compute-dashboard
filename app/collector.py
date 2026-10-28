"""Configuration-driven collection for local, SSH, SLURM and cloud resources."""
import asyncio
import logging
import re
import time
import datetime
from pathlib import Path

import yaml

from app.network import NetworkMonitor
from app.job_timing import populate_job_timing
from app.models import ClusterGroup, DashboardResponse, DashboardSummary, NodeMetrics, OrganizationGroup
from app.probes.kaggle_probe import KaggleProbe
from app.probes.local_probe import LocalProbe
from app.probes.ssh_probe import RemoteCPUClusterProbe, RemoteGPUProbe

logger = logging.getLogger(__name__)
ACTIVE_STATES = {'RUNNING', 'R', 'MIXED', 'PD', 'PENDING', 'QUEUED'}


class MetricsCollector:
    def __init__(self, config_path='config.yaml'):
        self.config_path = str(config_path)
        with Path(config_path).open() as stream:
            self.config = yaml.safe_load(stream) or {}
        self.refresh_interval = max(1, int(self.config.get('server', {}).get('refresh_interval_seconds', 10)))
        self.my_users = {u.lower() for u in self.config.get('user_identifiers', [])}
        self._probes = {}
        self._sources = {}
        seen = set()
        local_count = 0
        for org in self.config.get('organizations', []):
            for cluster in org.get('clusters', []):
                ctype = cluster['type']
                group_key = (org['id'], cluster['id'])
                if ctype == 'cpu':
                    self._probes[group_key] = RemoteCPUClusterProbe(cluster, self.my_users)
                elif ctype == 'kaggle':
                    self._probes[group_key] = KaggleProbe(cluster['username'])
                elif ctype not in {'gpu', 'workstation'}:
                    raise ValueError(f'Unsupported resource type: {ctype}')
                for node in cluster.get('nodes', []):
                    nid = node['id']
                    if nid in seen or not re.fullmatch(r'[a-zA-Z0-9_-]+', nid):
                        raise ValueError('Node IDs must be globally unique and contain only letters, digits, hyphens and underscores')
                    seen.add(nid)
                    if ctype == 'gpu':
                        key = (*group_key, nid)
                        self._probes[key] = RemoteGPUProbe(node, self.my_users)
                        self._sources[nid] = (key, None)
                    elif ctype == 'workstation':
                        local_count += 1
                        if local_count > 1:
                            raise ValueError('Configure one local workstation; use SSH GPU probes for other hosts')
                        key = (*group_key, nid)
                        self._probes[key] = LocalProbe(nid, self.my_users)
                        self._sources[nid] = (key, None)
                    elif ctype == 'kaggle':
                        accelerator = node.get('accelerator_type', 'gpu')
                        if accelerator not in {'gpu', 'tpu'}:
                            raise ValueError('Kaggle accelerator_type must be gpu or tpu')
                        self._sources[nid] = (group_key, f'kaggle-{accelerator}')
                    else:
                        self._sources[nid] = (group_key, nid)
        self._cache = None
        self._last_refresh_time = 0.0
        self._subscribers = []
        self.network_monitor = NetworkMonitor(self.config.get("network", {}))
        self._bg_task = None
        self._refresh_lock = asyncio.Lock()

    def start_background_loop(self):
        self.network_monitor.start()
        if self._bg_task is None or self._bg_task.done():
            self._bg_task = asyncio.create_task(self._run_loop())

    async def stop(self):
        await self.network_monitor.stop()
        if self._bg_task:
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        while True:
            try:
                await self.refresh_all()
            except Exception:
                logger.exception('Metrics collection failed')
            await asyncio.sleep(self.refresh_interval)

    async def refresh_all(self):
        async with self._refresh_lock:
            return await self._collect()

    async def _collect(self):
        keys = list(self._probes)
        results = await asyncio.gather(*(asyncio.to_thread(self._probes[k].collect) for k in keys), return_exceptions=True)
        collected = dict(zip(keys, results))
        organizations = []
        all_nodes = []
        now = datetime.datetime.now(datetime.timezone.utc)
        for org in self.config.get('organizations', []):
            groups = []
            for cluster in org.get('clusters', []):
                nodes = []
                for cfg in cluster.get('nodes', []):
                    key, subkey = self._sources[cfg['id']]
                    result = collected.get(key)
                    if subkey is not None and isinstance(result, dict):
                        result = result.get(subkey)
                    if not isinstance(result, NodeMetrics):
                        result = NodeMetrics(id=cfg['id'], name=cfg.get('name', cfg['id']),
                                             type=cluster['type'], status='OFFLINE',
                                             error_message='Collection unavailable', last_updated=now.isoformat())
                    node = result.model_copy(deep=True)
                    node.id = cfg['id']
                    for field in ('name', 'role', 'description'):
                        if field in cfg:
                            setattr(node, field, cfg[field])
                    for job in node.jobs:
                        populate_job_timing(job, now)
                    node.total_jobs_count = sum(j.state in ACTIVE_STATES for j in node.jobs)
                    node.my_jobs_count = sum(j.state in ACTIVE_STATES and j.is_my_job for j in node.jobs)
                    nodes.append(node)
                    all_nodes.append(node)
                groups.append(ClusterGroup(id=cluster['id'], name=cluster.get('name', cluster['id']),
                                           type=cluster['type'], description=cluster.get('description', ''), nodes=nodes))
            organizations.append(OrganizationGroup(id=org['id'], name=org.get('name', org['id']),
                                                   description=org.get('description', ''), clusters=groups))
        hosts = [n for n in all_nodes if n.type != 'kaggle']
        summary = DashboardSummary(
            total_nodes=len(all_nodes), online_nodes=sum(n.status != 'OFFLINE' for n in all_nodes),
            total_gpus=sum(len(n.gpus) for n in hosts),
            total_vram_gb=round(sum(n.total_vram_total_mb for n in hosts) / 1024, 1),
            used_vram_gb=round(sum(n.total_vram_used_mb for n in hosts) / 1024, 1),
            total_cpu_cores=sum(n.cpu_count for n in hosts),
            total_ram_gb=round(sum(n.mem_total_mb for n in hosts) / 1024, 1),
            used_ram_gb=round(sum(n.mem_used_mb for n in hosts) / 1024, 1),
            my_running_jobs=sum(n.my_jobs_count for n in all_nodes),
            total_running_jobs=sum(n.total_jobs_count for n in all_nodes),
            kaggle_gpu_remaining_hours=sum(n.kaggle_quota.gpu_time_remaining_hours for n in all_nodes
                                           if n.kaggle_quota and self._sources[n.id][1] == 'kaggle-gpu'),
            last_refresh=now.isoformat())
        self._cache = DashboardResponse(summary=summary, organizations=organizations, network=self.network_monitor.snapshot())
        self._last_refresh_time = time.time()
        payload = self._cache.model_dump_json()
        for queue in self._subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(payload)
        return self._cache

    async def get_latest_metrics(self):
        if self._cache is None:
            async with self._refresh_lock:
                if self._cache is None:
                    await self._collect()
        return self._cache.model_copy(deep=True)

    def subscribe(self):
        queue = asyncio.Queue(maxsize=1)
        self._subscribers.append(queue)
        if self._cache:
            queue.put_nowait(self._cache.model_dump_json())
        return queue

    def unsubscribe(self, queue):
        if queue in self._subscribers:
            self._subscribers.remove(queue)
