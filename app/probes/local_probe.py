import datetime
import os
import socket
import subprocess
import time
from typing import List, Set
import psutil

from app.probes.disk_probe import collect_local_disks

from app.job_merge import merge_gpu_processes
from app.models import NodeMetrics, GPUMetrics, JobInfo

class LocalProbe:
    def __init__(self, node_id: str = "local", my_users: Set[str] = None):
        self.node_id = node_id
        self.my_users = set(my_users or ())

    def collect(self) -> NodeMetrics:
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            hostname = socket.gethostname()
            cpu_pct = psutil.cpu_percent(interval=0.1)
            cpu_count = psutil.cpu_count(logical=True) or 1
            load = psutil.getloadavg()
            mem = psutil.virtual_memory()
            
            # Read uptime
            uptime_str = ""
            try:
                boot_time = psutil.boot_time()
                uptime_secs = int(time.time() - boot_time)
                days = uptime_secs // 86400
                hours = (uptime_secs % 86400) // 3600
                mins = (uptime_secs % 3600) // 60
                uptime_str = f"{days}d {hours}h {mins}m"
            except Exception:
                pass

            # Collect GPUs via nvidia-smi
            gpus: List[GPUMetrics] = []
            try:
                cmd = ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw,uuid", "--format=csv,noheader,nounits"]
                out = subprocess.check_output(cmd, text=True, timeout=3)
                for line in out.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 6:
                        idx = int(parts[0])
                        name = parts[1]
                        m_tot = float(parts[2])
                        m_used = float(parts[3])
                        m_free = float(parts[4])
                        u_gpu = float(parts[5])
                        temp = float(parts[6]) if len(parts) > 6 and parts[6] != "[N/A]" else None
                        power = float(parts[7]) if len(parts) > 7 and parts[7] != "[N/A]" else None
                        
                        m_pct = round((m_used / m_tot * 100), 1) if m_tot > 0 else 0.0
                        gpus.append(GPUMetrics(
                            index=idx,
                            uuid=parts[8] if len(parts) > 8 else "",
                            name=name,
                            memory_total_mb=m_tot,
                            memory_used_mb=m_used,
                            memory_free_mb=m_free,
                            memory_util_pct=m_pct,
                            utilization_gpu=u_gpu,
                            temperature_c=temp,
                            power_draw_w=power
                        ))
            except Exception:
                pass

            # Running processes (GPU processes + high-CPU user processes)
            jobs: List[JobInfo] = []
            gpu_apps = []
            gpu_indices = {g.uuid: g.index for g in gpus if g.uuid}
            try:
                cmd_apps = ["nvidia-smi", "--query-compute-apps=gpu_name,pid,process_name,used_memory,gpu_uuid", "--format=csv,noheader,nounits"]
                out_apps = subprocess.check_output(cmd_apps, text=True, timeout=2)
                for line in out_apps.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 4:
                        gname, pid, pname, umem = parts[0], parts[1], parts[2], parts[3]
                        gpu_uuid = parts[4] if len(parts) > 4 else ""
                        user_name = "unknown"
                        started_at = None
                        try:
                            p = psutil.Process(int(pid))
                            user_name = p.username()
                            started_at = datetime.datetime.fromtimestamp(p.create_time(), datetime.timezone.utc).isoformat()
                        except Exception:
                            pass
                        
                        gpu_apps.append(dict(pid=pid, user=user_name, process=pname,
                                             gpu=gname, used_memory_mb=float(umem),
                                             gpu_uuid=gpu_uuid, gpu_index=gpu_indices.get(gpu_uuid),
                                             started_at=started_at))
            except Exception:
                pass
            jobs = merge_gpu_processes([], gpu_apps, {}, hostname, self.my_users)

            # Top CPU processes for user
            try:
                for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_info', 'cmdline']):
                    try:
                        u = proc.info['username']
                        if u and u.lower() in self.my_users:
                            cpu_p = proc.info['cpu_percent'] or 0.0
                            if cpu_p > 20.0:  # significant work
                                mem_mb = (proc.info['memory_info'].rss / (1024 * 1024)) if proc.info.get('memory_info') else 0
                                cmdline = " ".join(proc.info.get('cmdline') or [proc.info['name']])
                                pid_str = str(proc.info['pid'])
                                # avoid duplicating gpu jobs
                                if not any(j.id == f"PID-{pid_str}" for j in jobs):
                                    jobs.append(JobInfo(
                                        id=f"PID-{pid_str}",
                                        name=proc.info['name'],
                                        user=u,
                                        is_my_job=True,
                                        state="RUNNING",
                                        time=f"{cpu_p:.1f}% CPU",
                                        nodes=hostname,
                                        resources=f"{mem_mb:.0f} MiB RAM",
                                        type="process",
                                        started_at=datetime.datetime.fromtimestamp(proc.create_time(), datetime.timezone.utc).isoformat(),
                                        timing_source="process start",
                                        command=cmdline[:80]
                                    ))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except Exception:
                pass

            # VRAM totals
            tot_vram = sum(g.memory_total_mb for g in gpus)
            used_vram = sum(g.memory_used_mb for g in gpus)
            vram_pct = round((used_vram / tot_vram * 100), 1) if tot_vram > 0 else 0.0
            avg_gpu_util = round(sum(g.utilization_gpu for g in gpus) / len(gpus), 1) if gpus else 0.0

            my_jobs = [j for j in jobs if j.is_my_job]

            return NodeMetrics(
                id=self.node_id,
                name=f"{hostname} (Workstation)",
                type="workstation",
                role="Local Host",
                status="ONLINE",
                description=f"{len(gpus)} GPUs · {cpu_count} logical cores · {mem.total / 1024**3:.0f} GB RAM",
                uptime=uptime_str,
                ip=None,
                cpu_count=cpu_count,
                cpu_util_pct=cpu_pct,
                cpu_load_1m=round(load[0], 2),
                cpu_load_5m=round(load[1], 2),
                cpu_load_15m=round(load[2], 2),
                mem_total_mb=round(mem.total / (1024 * 1024), 1),
                mem_used_mb=round(mem.used / (1024 * 1024), 1),
                mem_avail_mb=round(mem.available / (1024 * 1024), 1),
                mem_util_pct=mem.percent,
                disks=collect_local_disks(),
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
        except Exception as e:
            return NodeMetrics(
                id=self.node_id,
                name=f"{self.node_id} (Workstation)",
                type="workstation",
                status="OFFLINE",
                error_message=str(e),
                last_updated=now_str
            )

