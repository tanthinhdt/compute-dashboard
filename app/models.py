from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class GPUMetrics(BaseModel):
    index: int
    uuid: str = ""
    name: str
    memory_total_mb: float = 0.0
    memory_used_mb: float = 0.0
    memory_free_mb: float = 0.0
    memory_util_pct: float = 0.0
    utilization_gpu: float = 0.0
    temperature_c: Optional[float] = None
    power_draw_w: Optional[float] = None

class GPUProcessInfo(BaseModel):
    pid: str
    user: str
    command: str
    gpu_name: str = ""
    gpu_indices: List[int] = Field(default_factory=list)
    gpu_uuids: List[str] = Field(default_factory=list)
    memory_used_mb: float = 0.0


class JobInfo(BaseModel):
    id: str
    name: str
    user: str
    is_my_job: bool = False
    state: str = "RUNNING"
    time: str = ""
    nodes: str = ""
    resources: str = ""
    type: str = "slurm"  # "slurm", "process", "kaggle"
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    scheduled_end_at: Optional[str] = None
    timing_source: str = ""
    gpu_processes: List[GPUProcessInfo] = Field(default_factory=list)
    command: Optional[str] = None
    url: Optional[str] = None

class KaggleQuota(BaseModel):
    username: str
    gpu_time_used_hours: float = 0.0
    gpu_time_allowed_hours: float = 30.0
    gpu_time_remaining_hours: float = 30.0
    gpu_util_pct: float = 0.0
    quota_refresh_time: str = ""
    refresh_countdown: str = ""
    tpu_time_used_hours: float = 0.0
    tpu_time_allowed_hours: float = 20.0
    has_ever_run: bool = True

class DiskMetrics(BaseModel):
    mountpoint: str
    device: str = ""
    fstype: str = ""
    total_gb: float = 0.0
    used_gb: float = 0.0
    free_gb: float = 0.0
    usage_pct: float = 0.0

class NodeMetrics(BaseModel):
    id: str
    name: str
    type: str  # "gpu", "cpu", "workstation", "kaggle"
    role: str = ""
    status: str = "ONLINE"  # "ONLINE", "MIXED", "IDLE", "BUSY", "OFFLINE"
    description: str = ""
    uptime: Optional[str] = None
    ip: Optional[str] = None
    
    # CPU
    cpu_count: int = 0
    cpu_util_pct: float = 0.0
    cpu_load_1m: float = 0.0
    cpu_load_5m: float = 0.0
    cpu_load_15m: float = 0.0
    
    # Memory
    mem_total_mb: float = 0.0
    mem_used_mb: float = 0.0
    mem_avail_mb: float = 0.0
    mem_util_pct: float = 0.0
    
    # GPU
    gpus: List[GPUMetrics] = Field(default_factory=list)
    total_vram_total_mb: float = 0.0
    total_vram_used_mb: float = 0.0
    total_vram_util_pct: float = 0.0
    avg_gpu_util_pct: float = 0.0
    
    # Disk
    disks: List[DiskMetrics] = Field(default_factory=list)
    
    # Kaggle-specific quota
    kaggle_quota: Optional[KaggleQuota] = None
    
    # Jobs
    jobs: List[JobInfo] = Field(default_factory=list)
    my_jobs_count: int = 0
    total_jobs_count: int = 0
    
    last_updated: str = ""
    error_message: Optional[str] = None

class ClusterGroup(BaseModel):
    id: str
    name: str
    type: str
    description: str = ""
    nodes: List[NodeMetrics] = Field(default_factory=list)

class OrganizationGroup(BaseModel):
    id: str
    name: str
    description: str = ""
    clusters: List[ClusterGroup] = Field(default_factory=list)

class DashboardSummary(BaseModel):
    total_nodes: int = 0
    online_nodes: int = 0
    total_gpus: int = 0
    total_vram_gb: float = 0.0
    used_vram_gb: float = 0.0
    total_cpu_cores: int = 0
    total_ram_gb: float = 0.0
    used_ram_gb: float = 0.0
    my_running_jobs: int = 0
    total_running_jobs: int = 0
    kaggle_gpu_remaining_hours: float = 0.0
    last_refresh: str = ""

class DashboardResponse(BaseModel):
    summary: DashboardSummary
    organizations: List[OrganizationGroup]
    client_ip: str = ""
    access_granted: bool = True
    network_info: Dict[str, Any] = Field(default_factory=dict)
    network: Dict[str, Any] = Field(default_factory=dict)

