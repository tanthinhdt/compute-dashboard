"""Group GPU processes by verified SLURM allocation membership."""
from app.models import GPUProcessInfo, JobInfo


def slurm_job_id_from_cgroup(cgroup):
    import re
    ids = set(re.findall(r'(?:^|/)job_(\d+)(?=/|\.scope(?:/|$)|$)', cgroup, re.MULTILINE))
    return next(iter(ids)) if len(ids) == 1 else None


def merge_gpu_processes(jobs, gpu_apps, allocation_ids, node_name, my_users):
    # Array display IDs (e.g. 2260_0) can differ from the actual allocation ID
    # (2261). Only use allocation IDs reported by squeue, never name/user guesses.
    allocations = {}
    for job in jobs:
        if job.state in {'PD', 'PENDING', 'QUEUED'}:
            continue
        allocation = allocation_ids.get(job.id, job.id if job.id.isdigit() else None)
        if allocation:
            allocations.setdefault(str(allocation), []).append(job)

    processes = {}
    for app in gpu_apps:
        pid = str(app['pid'])
        if pid not in processes:
            processes[pid] = dict(app, pid=pid, used_memory_mb=0.0, gpu_indices=set(), gpu_uuids=set())
        # nvidia-smi can report one PID on multiple GPUs. Sum device memory but
        # count the process once, whether scheduled or standalone.
        processes[pid]['used_memory_mb'] += float(app.get('used_memory_mb', 0))
        if app.get('gpu_index') is not None:
            processes[pid]['gpu_indices'].add(int(app['gpu_index']))
        if app.get('gpu_uuid'):
            processes[pid]['gpu_uuids'].add(app['gpu_uuid'])

    for app in processes.values():
        process = GPUProcessInfo(
            pid=app['pid'], user=app['user'], command=app['process'],
            gpu_name=app.get('gpu', ''), memory_used_mb=app['used_memory_mb'],
            gpu_indices=sorted(app['gpu_indices']), gpu_uuids=sorted(app['gpu_uuids']))
        candidates = allocations.get(str(app.get('slurm_job_id')), [])
        if len(candidates) == 1:
            candidates[0].gpu_processes.append(process)
            continue
        elapsed = app.get('elapsed_seconds')
        jobs.append(JobInfo(
            id=f"PID-{process.pid}", name=process.command.rsplit('/', 1)[-1],
            user=process.user, is_my_job=process.user.lower() in my_users,
            state='RUNNING', nodes=node_name, type='process',
            resources=f'{process.gpu_name} ({process.memory_used_mb:.0f} MiB)',
            time=f'{elapsed}s elapsed' if elapsed is not None else 'active',
            started_at=app.get("started_at"),
            timing_source="process start" if app.get("started_at") else "",
            command=process.command, gpu_processes=[process]))
    return jobs
