import inspect
import json
import logging
import subprocess
import time
from typing import Dict, List, Set, Optional

from app.job_merge import merge_gpu_processes, slurm_job_id_from_cgroup
from app.models import DiskMetrics, GPUMetrics, JobInfo, NodeMetrics
from app.probes.disk_probe import collect_remote_disks

REMOTE_DISK_SCRIPT = inspect.getsource(collect_remote_disks)


def parse_slurm_timestamp(value):
    import datetime
    try:
        parsed = datetime.datetime.fromisoformat(value)
        # Ignore unknown/unlimited markers rather than inventing a deadline.
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(datetime.timezone.utc).isoformat()
    except (ValueError, TypeError):
        return None


REMOTE_SLURM_SCRIPT = inspect.getsource(parse_slurm_timestamp)


logger = logging.getLogger("ssh_probe")

SSH_COMMON_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=4",
    "-o", "ControlMaster=auto",
    "-o", "ControlPath=/tmp/ssh-mux-%r@%h:%p",
    "-o", "ControlPersist=600",
    "-o", "StrictHostKeyChecking=accept-new"
]

REMOTE_GPU_SCRIPT = REMOTE_DISK_SCRIPT + REMOTE_SLURM_SCRIPT + inspect.getsource(slurm_job_id_from_cgroup) + """import json
import subprocess
import os
import pwd
import time

def run():
    load = list(os.getloadavg())
    cpu_count = os.cpu_count() or 1
    
    # Meminfo
    mem_info = {}
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                parts = line.split(':')
                mem_info[parts[0].strip()] = int(parts[1].split()[0])
    except Exception:
        pass
            
    total_mem_mb = mem_info.get('MemTotal', 0) // 1024
    avail_mem_mb = mem_info.get('MemAvailable', 0) // 1024
    used_mem_mb = max(total_mem_mb - avail_mem_mb, 0)
    
    # Uptime
    uptime_str = ''
    try:
        with open('/proc/uptime') as f:
            uptime_secs = int(float(f.readline().split()[0]))
            d = uptime_secs // 86400
            h = (uptime_secs % 86400) // 3600
            m = (uptime_secs % 3600) // 60
            uptime_str = f'{d}d {h}h {m}m'
    except Exception:
        pass

    # GPUs
    gpus = []
    try:
        out = subprocess.check_output(
            ['nvidia-smi', '--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw,uuid', '--format=csv,noheader,nounits'],
            text=True, timeout=3
        )
        for line in out.strip().split('\\n'):
            if not line.strip(): continue
            p = [x.strip() for x in line.split(',')]
            if len(p) >= 6:
                idx = int(p[0])
                name = p[1]
                m_tot = float(p[2])
                m_used = float(p[3])
                m_free = float(p[4])
                u_gpu = float(p[5])
                temp = float(p[6]) if len(p) > 6 and p[6] != '[N/A]' else None
                power = float(p[7]) if len(p) > 7 and p[7] != '[N/A]' else None
                gpus.append({
                    'index': idx,
                    'uuid': p[8] if len(p) > 8 else '',
                    'name': name,
                    'memory_total_mb': m_tot,
                    'memory_used_mb': m_used,
                    'memory_free_mb': m_free,
                    'utilization_gpu': u_gpu,
                    'temperature_c': temp,
                    'power_draw_w': power
                })
    except Exception:
        pass

    # SLURM Jobs
    slurm_jobs = []
    try:
        sq = subprocess.check_output(['squeue', '-o', '%i|%u|%j|%t|%M|%D|%R|%b|%S|%e|%A'], text=True, timeout=2, env=dict(os.environ, SLURM_TIME_FORMAT='%Y-%m-%dT%H:%M:%S%z'))
        lines = sq.strip().split('\\n')
        if len(lines) > 1:
            for line in lines[1:]:
                if not line.strip(): continue
                p = [x.strip() for x in line.split('|')]
                if len(p) >= 7:
                    slurm_jobs.append({
                        'id': p[0],
                        'user': p[1],
                        'name': p[2],
                        'state': p[3],
                        'time': p[4],
                        'nodes': p[5],
                        'nodelist': p[6],
                        'gres': p[7] if len(p) > 7 else '',
                        'started_at': parse_slurm_timestamp(p[8]) if len(p) > 8 and p[3] in ('R', 'RUNNING') else None,
                        'scheduled_end_at': parse_slurm_timestamp(p[9]) if len(p) > 9 else None,
                        'allocation_id': p[10] if len(p) > 10 else None
                    })
    except Exception:
        pass

    # GPU compute apps / processes
    gpu_apps = []
    gpu_indices = {g['uuid']: g['index'] for g in gpus if g.get('uuid')}
    try:
        out_apps = subprocess.check_output(['nvidia-smi', '--query-compute-apps=gpu_name,pid,process_name,used_memory,gpu_uuid', '--format=csv,noheader,nounits'], text=True, timeout=2)
        for line in out_apps.strip().split('\\n'):
            if not line.strip(): continue
            p = [x.strip() for x in line.split(',')]
            if len(p) >= 4:
                gname, pid, pname, umem = p[0], p[1], p[2], p[3]
                gpu_uuid = p[4] if len(p) > 4 else ''
                u = 'unknown'
                elapsed_seconds = None
                slurm_job_id = None
                try:
                    u = pwd.getpwuid(os.stat('/proc/' + pid).st_uid).pw_name
                except (OSError, KeyError):
                    pass
                try:
                    with open('/proc/' + pid + '/cgroup') as f:
                        slurm_job_id = slurm_job_id_from_cgroup(f.read())
                except OSError:
                    pass
                try:
                    process_info = subprocess.check_output(['ps', '-o', 'etimes=', '-p', pid], text=True, timeout=1).split()
                    elapsed_seconds = int(process_info[0])
                except Exception:
                    pass
                gpu_apps.append({
                    'slurm_job_id': slurm_job_id,
                    'elapsed_seconds': elapsed_seconds,
                    'gpu': gname,
                    'gpu_uuid': gpu_uuid,
                    'gpu_index': gpu_indices.get(gpu_uuid),
                    'pid': pid,
                    'user': u,
                    'process': pname,
                    'used_memory_mb': float(umem)
                })
    except Exception:
        pass

    return {
        'load': load,
        'cpu_count': cpu_count,
        'mem_total_mb': total_mem_mb,
        'mem_used_mb': used_mem_mb,
        'mem_avail_mb': avail_mem_mb,
        'uptime': uptime_str,
        'disks': collect_remote_disks(),
        'gpus': gpus,
        'slurm_jobs': slurm_jobs,
        'gpu_apps': gpu_apps
    }

print(json.dumps(run()))
"""

class RemoteGPUProbe:
    def __init__(self, node_config: dict, my_users: Set[str]):
        self.node_id = node_config["id"]
        self.name = node_config.get("name", self.node_id)
        self.ssh_host = node_config.get("ssh_host", self.node_id)
        self.role = node_config.get("role", "GPU Node")
        self.description = node_config.get("description", "")
        self.my_users = my_users

    def collect(self) -> NodeMetrics:
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        cmd = ["ssh"] + SSH_COMMON_OPTS + [self.ssh_host, "python3 -"]
        
        try:
            res = subprocess.run(cmd, input=REMOTE_GPU_SCRIPT, capture_output=True, text=True, timeout=8)
            if res.returncode != 0:
                logger.warning(f"SSH probe failed for {self.node_id}: {res.stderr.strip()[:100]}")
                return NodeMetrics(
                    id=self.node_id,
                    name=self.name,
                    type="gpu",
                    role=self.role,
                    status="OFFLINE",
                    description=self.description,
                    error_message=res.stderr.strip() or "Connection error",
                    last_updated=now_str
                )

            data = json.loads(res.stdout)
            
            # Build GPUMetrics
            gpus: List[GPUMetrics] = []
            for g in data.get("gpus", []):
                tot = g["memory_total_mb"]
                used = g["memory_used_mb"]
                pct = round((used / tot * 100), 1) if tot > 0 else 0.0
                gpus.append(GPUMetrics(
                    index=g["index"],
                    uuid=g.get("uuid", ""),
                    name=g["name"],
                    memory_total_mb=tot,
                    memory_used_mb=used,
                    memory_free_mb=g.get("memory_free_mb", tot - used),
                    memory_util_pct=pct,
                    utilization_gpu=g["utilization_gpu"],
                    temperature_c=g.get("temperature_c"),
                    power_draw_w=g.get("power_draw_w")
                ))

            # Build Jobs: SLURM jobs + GPU Apps
            jobs: List[JobInfo] = []
            
            # 1. SLURM jobs
            for sj in data.get("slurm_jobs", []):
                jid = str(sj["id"])
                user = sj["user"]
                is_my = user.lower() in self.my_users
                jobs.append(JobInfo(
                    id=jid,
                    name=sj["name"],
                    user=user,
                    is_my_job=is_my,
                    state="RUNNING" if sj["state"] in ("R", "RUNNING") else sj["state"],
                    time=sj["time"],
                    started_at=sj.get("started_at"),
                    scheduled_end_at=sj.get("scheduled_end_at"),
                    timing_source="scheduler start" if sj.get("started_at") else "",
                    nodes=sj.get("nodelist", self.name),
                    resources=f"SLURM ({sj.get('gres') or 'GPU'})",
                    type="slurm"
                ))

            # GPU processes in a known allocation belong to that job. Keep
            # their metadata, but do not count them as additional jobs.
            allocation_ids = {str(sj["id"]): sj.get("allocation_id")
                              for sj in data.get("slurm_jobs", []) if sj.get("allocation_id")}
            jobs = merge_gpu_processes(jobs, data.get("gpu_apps", []), allocation_ids,
                                       self.name, self.my_users)

            my_jobs = [j for j in jobs if j.is_my_job]
            
            # Load averages & CPU
            load = data.get("load", [0, 0, 0])
            cpu_cnt = data.get("cpu_count", 1)
            cpu_util = min(round((load[0] / cpu_cnt * 100), 1), 100.0) if cpu_cnt > 0 else 0.0

            # Memory
            mem_tot = float(data.get("mem_total_mb", 0))
            mem_used = float(data.get("mem_used_mb", 0))
            mem_avail = float(data.get("mem_avail_mb", 0))
            mem_pct = round((mem_used / mem_tot * 100), 1) if mem_tot > 0 else 0.0

            # VRAM totals
            tot_vram = sum(g.memory_total_mb for g in gpus)
            used_vram = sum(g.memory_used_mb for g in gpus)
            vram_pct = round((used_vram / tot_vram * 100), 1) if tot_vram > 0 else 0.0
            avg_gpu_util = round(sum(g.utilization_gpu for g in gpus) / len(gpus), 1) if gpus else 0.0

            status = "ONLINE"
            if avg_gpu_util > 50 or cpu_util > 50:
                status = "BUSY"
            elif avg_gpu_util > 5 or cpu_util > 5:
                status = "MIXED"
            else:
                status = "IDLE"

            return NodeMetrics(
                id=self.node_id,
                name=self.name,
                type="gpu",
                role=self.role,
                status=status,
                description=self.description,
                uptime=data.get("uptime", ""),
                ip=self.ssh_host,
                cpu_count=cpu_cnt,
                cpu_util_pct=cpu_util,
                cpu_load_1m=round(load[0], 2),
                cpu_load_5m=round(load[1], 2),
                cpu_load_15m=round(load[2], 2),
                mem_total_mb=mem_tot,
                mem_used_mb=mem_used,
                mem_avail_mb=mem_avail,
                mem_util_pct=mem_pct,
                disks=[DiskMetrics(**d) for d in data.get("disks", [])],
                gpus=gpus,
                total_vram_total_mb=tot_vram,
                total_vram_used_mb=used_vram,
                total_vram_util_pct=vram_pct,
                avg_gpu_util_pct=avg_gpu_util,
                jobs=jobs,
                my_jobs_count=len(my_jobs),
                total_jobs_count=len(jobs),
                last_updated=now_str
            )
        except subprocess.TimeoutExpired:
            return NodeMetrics(
                id=self.node_id,
                name=self.name,
                type="gpu",
                role=self.role,
                status="OFFLINE",
                description=self.description,
                error_message="SSH connection timed out",
                last_updated=now_str
            )
        except Exception as e:
            logger.exception(f"Error querying GPU node {self.node_id}")
            return NodeMetrics(
                id=self.node_id,
                name=self.name,
                type="gpu",
                role=self.role,
                status="OFFLINE",
                description=self.description,
                error_message=str(e),
                last_updated=now_str
            )


REMOTE_CPU_CLUSTER_SCRIPT = (REMOTE_SLURM_SCRIPT + REMOTE_DISK_SCRIPT + "\nDISK_WORKER_SCRIPT = "
                             + repr(REMOTE_DISK_SCRIPT + "\nimport json\nprint(json.dumps(collect_remote_disks()))")
                             + "\n") + """import os
import subprocess
import re
import json
import concurrent.futures

def get_node_mem(node):
    try:
        cmd = ["free", "-m"] if node == CONTROLLER_NODE else ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=2", PROBE_HOSTS[node], "free", "-m"]
        out = subprocess.check_output(cmd, text=True, timeout=3)
        for line in out.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                return node, {"total_mb": int(parts[1]), "used_mb": int(parts[2]), "avail_mb": int(parts[6])}
    except Exception:
        pass
    return node, {"total_mb": 0, "used_mb": 0, "avail_mb": 0}

def get_node_disks(node):
    if node == CONTROLLER_NODE:
        return node, collect_remote_disks()
    try:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=2", PROBE_HOSTS[node], "python3 -"]
        out = subprocess.check_output(cmd, input=DISK_WORKER_SCRIPT, text=True, timeout=3)
        return node, json.loads(out)
    except Exception:
        return node, []

nodes_mem = {}
nodes_disks = {}
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
    mem_futures = [ex.submit(get_node_mem, n) for n in list(PROBE_HOSTS)]
    disk_futures = [ex.submit(get_node_disks, n) for n in list(PROBE_HOSTS)]
    for future in mem_futures:
        node, mem = future.result()
        nodes_mem[node] = mem
    for future in disk_futures:
        node, disks = future.result()
        nodes_disks[node] = disks

out = subprocess.check_output(["scontrol", "show", "nodes"], text=True, timeout=3)
nodes = {}
for block in out.strip().split("\\n\\n"):
    if not block.strip(): continue
    name_m = re.search(r"NodeName=([^\\s]+)", block)
    if not name_m: continue
    name = name_m.group(1)
    
    cpu_alloc = int(re.search(r"CPUAlloc=(\\d+)", block).group(1)) if re.search(r"CPUAlloc=(\\d+)", block) else 0
    cpu_tot = int(re.search(r"CPUTot=(\\d+)", block).group(1)) if re.search(r"CPUTot=(\\d+)", block) else 0
    cpu_load_m = re.search(r"CPULoad=([\\d\\.]+)", block)
    cpu_load = float(cpu_load_m.group(1)) if cpu_load_m else 0.0
    state_m = re.search(r"State=([^\\s]+)", block)
    state = state_m.group(1) if state_m else "UNKNOWN"
    
    mem = nodes_mem.get(name, {"total_mb": 0, "used_mb": 0, "avail_mb": 0})
    m_pct = round((mem["used_mb"] / mem["total_mb"] * 100), 1) if mem["total_mb"] > 0 else 0.0
    cpu_util = round((cpu_load / cpu_tot * 100), 1) if cpu_tot > 0 else 0.0
    
    nodes[name] = {
        "name": name,
        "state": state,
        "cpu_alloc": cpu_alloc,
        "cpu_tot": cpu_tot,
        "cpu_load": cpu_load,
        "cpu_util_pct": min(cpu_util, 100.0),
        "mem_total_mb": mem["total_mb"],
        "mem_used_mb": mem["used_mb"],
        "mem_avail_mb": mem["avail_mb"],
        "disks": nodes_disks.get(name, []),
        "mem_util_pct": m_pct
    }

# Jobs
sq_out = subprocess.check_output(["squeue", "-o", "%i|%u|%j|%t|%M|%D|%R|%C|%m|%S|%e"], text=True, timeout=3, env=dict(os.environ, SLURM_TIME_FORMAT="%Y-%m-%dT%H:%M:%S%z"))
jobs = []
for line in sq_out.strip().split("\\n")[1:]:
    if not line.strip(): continue
    parts = [p.strip() for p in line.split("|")]
    if len(parts) >= 7:
        jobs.append({
            "id": parts[0],
            "user": parts[1],
            "name": parts[2],
            "state": parts[3],
            "time": parts[4],
            "nodes": parts[5],
            "nodelist": parts[6],
            "cpus": parts[7] if len(parts) > 7 else "",
            "mem": parts[8] if len(parts) > 8 else "",
            "started_at": parse_slurm_timestamp(parts[9]) if len(parts) > 9 and parts[3] in ("R", "RUNNING") else None,
            "scheduled_end_at": parse_slurm_timestamp(parts[10]) if len(parts) > 10 else None
        })

print(json.dumps({"nodes": nodes, "jobs": jobs}))
"""

class RemoteCPUClusterProbe:
    def __init__(self, cluster_config: dict, my_users: Set[str]):
        self.controller_ssh = cluster_config["controller_ssh_host"]
        self.controller_node = cluster_config.get("controller_node", "")
        self.nodes_config = {n["id"]: n for n in cluster_config.get("nodes", [])}
        self.my_users = my_users

    def collect(self) -> Dict[str, NodeMetrics]:
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        cmd = ["ssh"] + SSH_COMMON_OPTS + [self.controller_ssh, "python3 -"]
        
        results: Dict[str, NodeMetrics] = {}
        try:
            probe_hosts = {nid: cfg.get("ssh_host", nid) for nid, cfg in self.nodes_config.items()}
            runtime_script = ("PROBE_HOSTS = " + repr(probe_hosts) + "\nCONTROLLER_NODE = "
                              + repr(self.controller_node) + "\n" + REMOTE_CPU_CLUSTER_SCRIPT)
            res = subprocess.run(cmd, input=runtime_script, capture_output=True, text=True, timeout=12)
            if res.returncode != 0:
                logger.warning(f"SSH probe failed for CPU cluster {self.controller_ssh}: {res.stderr.strip()[:100]}")
                for nid, cfg in self.nodes_config.items():
                    results[nid] = NodeMetrics(
                        id=nid,
                        name=cfg.get("name", nid),
                        type="cpu",
                        role=cfg.get("role", "Compute Worker"),
                        status="OFFLINE",
                        description=cfg.get("description", ""),
                        error_message="SSH connection failed",
                        last_updated=now_str
                    )
                return results

            data = json.loads(res.stdout)
            raw_nodes = data.get("nodes", {})
            raw_jobs = data.get("jobs", [])

            # Parse SLURM jobs
            all_jobs: List[JobInfo] = []
            for j in raw_jobs:
                u = j["user"]
                is_my = u.lower() in self.my_users
                all_jobs.append(JobInfo(
                    id=j["id"],
                    name=j["name"],
                    user=u,
                    is_my_job=is_my,
                    state="RUNNING" if j["state"] in ("R", "RUNNING") else j["state"],
                    time=j["time"],
                    started_at=j.get("started_at"),
                    scheduled_end_at=j.get("scheduled_end_at"),
                    timing_source="scheduler start" if j.get("started_at") else "",
                    nodes=j["nodelist"],
                    resources=f"{j.get('cpus','')} CPUs, {j.get('mem','')}",
                    type="slurm"
                ))

            for nid, cfg in self.nodes_config.items():
                node_data = raw_nodes.get(nid)
                if not node_data:
                    results[nid] = NodeMetrics(
                        id=nid,
                        name=cfg.get("name", nid),
                        type="cpu",
                        role=cfg.get("role", "Compute Worker"),
                        status="OFFLINE",
                        description=cfg.get("description", ""),
                        last_updated=now_str
                    )
                    continue

                # Filter jobs running on this node
                node_jobs = [j for j in all_jobs if nid in j.nodes or j.nodes == "all"]
                my_jobs = [j for j in node_jobs if j.is_my_job]
                
                raw_state = node_data.get("state", "IDLE").upper()
                status = "IDLE"
                if "MIX" in raw_state or "ALLOC" in raw_state:
                    status = "MIXED"
                elif "DRAIN" in raw_state or "DOWN" in raw_state:
                    status = "OFFLINE"
                elif node_data.get("cpu_util_pct", 0) > 60:
                    status = "BUSY"

                results[nid] = NodeMetrics(
                    id=nid,
                    name=cfg.get("name", nid),
                    type="cpu",
                    role=cfg.get("role", "Compute Worker"),
                    status=status,
                    description=cfg.get("description", ""),
                    ip=cfg.get("ssh_host"),
                    cpu_count=node_data.get("cpu_tot", 0),
                    cpu_util_pct=node_data.get("cpu_util_pct", 0.0),
                    cpu_load_1m=node_data.get("cpu_load", 0.0),
                    mem_total_mb=node_data.get("mem_total_mb", 0),
                    mem_used_mb=node_data.get("mem_used_mb", 0),
                    mem_avail_mb=node_data.get("mem_avail_mb", 0),
                    mem_util_pct=node_data.get("mem_util_pct", 0.0),
                    disks=[DiskMetrics(**d) for d in node_data.get("disks", [])],
                    gpus=[],
                    jobs=node_jobs,
                    my_jobs_count=len(my_jobs),
                    total_jobs_count=len(node_jobs),
                    last_updated=now_str
                )

            return results
        except Exception as e:
            logger.exception("Error querying CPU cluster")
            for nid, cfg in self.nodes_config.items():
                results[nid] = NodeMetrics(
                    id=nid,
                    name=cfg.get("name", nid),
                    type="cpu",
                    role=cfg.get("role", "Compute Worker"),
                    status="OFFLINE",
                    description=cfg.get("description", ""),
                    error_message=str(e),
                    last_updated=now_str
                )
            return results
