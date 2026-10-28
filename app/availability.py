"""Compact, read-only resource observations for assistant clients."""
import datetime as dt
import time


def resource_snapshot(data, collected_at, max_age_seconds, *, resource_type=None,
                      min_free_vram_gb=0.0, min_available_ram_gb=0.0,
                      max_gpu_util_pct=20.0):
    age = max(0.0, time.time() - collected_at) if collected_at else None
    stale = age is None or age > max_age_seconds
    resources = []
    for org in data.organizations:
        for cluster in org.clusters:
            for node in cluster.nodes:
                if resource_type and node.type != resource_type:
                    continue
                online = node.status != 'OFFLINE'
                ram_gb = round(node.mem_avail_mb / 1024, 2) if online else None
                gpus = []
                for gpu in node.gpus:
                    free_gb = round(gpu.memory_free_mb / 1024, 2)
                    candidate = (online and not stale and node.type != 'kaggle'
                                 and free_gb >= min_free_vram_gb
                                 and gpu.utilization_gpu <= max_gpu_util_pct
                                 and ram_gb >= min_available_ram_gb)
                    gpus.append(dict(index=gpu.index, name=gpu.name,
                                     total_vram_gb=round(gpu.memory_total_mb / 1024, 2),
                                     free_vram_gb=free_gb if online else None,
                                     utilization_pct=gpu.utilization_gpu if online else None,
                                     observed_candidate=candidate))
                candidate = (online and not stale and node.type != 'kaggle'
                             and ram_gb >= min_available_ram_gb
                             and (any(g['observed_candidate'] for g in gpus) if gpus
                                  else min_free_vram_gb == 0 and node.cpu_util_pct <= 50))
                item = dict(id=node.id, name=node.name, organization=org.name,
                            group=cluster.name, type=node.type, status=node.status,
                            cpu_cores=node.cpu_count, cpu_utilization_pct=node.cpu_util_pct if online else None,
                            available_ram_gb=ram_gb, gpus=gpus,
                            active_jobs=node.total_jobs_count, observed_candidate=candidate,
                            last_updated=node.last_updated)
                if node.kaggle_quota:
                    quota = node.kaggle_quota
                    is_tpu = node.id.endswith('tpu')
                    remaining = (quota.tpu_time_allowed_hours - quota.tpu_time_used_hours
                                 if is_tpu else quota.gpu_time_remaining_hours)
                    item['cloud_quota_remaining_hours'] = max(remaining, 0)
                resources.append(item)
    return dict(schema_version='1.0',
                collected_at=dt.datetime.fromtimestamp(collected_at, dt.timezone.utc).isoformat() if collected_at else None,
                age_seconds=round(age, 1) if age is not None else None,
                stale=stale, max_age_seconds=max_age_seconds,
                filters=dict(resource_type=resource_type, min_free_vram_gb=min_free_vram_gb,
                             min_available_ram_gb=min_available_ram_gb, max_gpu_util_pct=max_gpu_util_pct),
                candidate_resource_ids=[r['id'] for r in resources if r['observed_candidate']],
                resources=resources,
                limitations=['Candidates reflect observed usage, not scheduler reservations or guaranteed availability.',
                             'Check scheduler allocation and access before running work.',
                             'Cloud quota is reported separately and is not proof of an available accelerator.'])
