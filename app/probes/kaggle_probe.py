import datetime
import json
import logging
import re
import time
from typing import Dict, List, Optional
from dateutil import parser as dt_parser

from app.models import GPUMetrics, JobInfo, KaggleQuota, NodeMetrics

logger = logging.getLogger("kaggle_probe")

def parse_seconds(val) -> float:
    if not val:
        return 0.0
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(val))
    return float(m.group(1)) if m else 0.0

class KaggleProbe:
    def __init__(self, username: str):
        if not username:
            raise ValueError("Kaggle username must be configured")
        self.username = username
        self._api = None

    def _get_api(self):
        if self._api is None:
            try:
                from kaggle.api.kaggle_api_extended import KaggleApi
                api = KaggleApi()
                api.authenticate()
                self._api = api
            except Exception as e:
                logger.error(f"Failed to authenticate with Kaggle API: {e}")
                raise
        return self._api

    def collect(self) -> Dict[str, NodeMetrics]:
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            api = self._get_api()
            
            # Fetch Accelerator Quotas
            quota_resp = api.quota_view()
            q_dict = quota_resp.to_dict() if hasattr(quota_resp, "to_dict") else {}
            if not q_dict and isinstance(quota_resp, str):
                try:
                    q_dict = json.loads(quota_resp)
                except Exception:
                    pass

            gpu_quota = q_dict.get("gpuQuota", {})
            tpu_quota = q_dict.get("tpuQuota", {})
            refresh_time_str = q_dict.get("quotaRefreshTime", "")

            # GPU Quota
            gpu_used_secs = parse_seconds(gpu_quota.get("timeUsed", "0s"))
            gpu_allowed_secs = parse_seconds(gpu_quota.get("totalTimeAllowed", "108000s"))
            if gpu_allowed_secs == 0:
                gpu_allowed_secs = 108000.0  # 30 hours standard free tier

            gpu_used_hours = round(gpu_used_secs / 3600.0, 1)
            gpu_allowed_hours = round(gpu_allowed_secs / 3600.0, 1)
            gpu_rem_hours = max(round(gpu_allowed_hours - gpu_used_hours, 1), 0.0)
            gpu_pct = min(round((gpu_used_hours / gpu_allowed_hours * 100), 1), 100.0) if gpu_allowed_hours > 0 else 0.0

            # TPU Quota
            tpu_used_secs = parse_seconds(tpu_quota.get("timeUsed", "0s"))
            tpu_allowed_secs = parse_seconds(tpu_quota.get("totalTimeAllowed", "72000s"))  # 20 hours
            tpu_used_hours = round(tpu_used_secs / 3600.0, 1)
            tpu_allowed_hours = round(tpu_allowed_secs / 3600.0, 1) if tpu_allowed_secs > 0 else 20.0
            tpu_rem_hours = max(round(tpu_allowed_hours - tpu_used_hours, 1), 0.0)
            tpu_pct = min(round((tpu_used_hours / tpu_allowed_hours * 100), 1), 100.0) if tpu_allowed_hours > 0 else 0.0

            # Countdown string
            countdown_str = ""
            if refresh_time_str:
                try:
                    target_dt = dt_parser.isoparse(refresh_time_str)
                    now_utc = datetime.datetime.now(datetime.timezone.utc)
                    diff = target_dt - now_utc
                    if diff.total_seconds() > 0:
                        days = diff.days
                        hours = int(diff.seconds // 3600)
                        mins = int((diff.seconds % 3600) // 60)
                        countdown_str = f"{days}d {hours}h {mins}m"
                    else:
                        countdown_str = "Reset imminent"
                except Exception:
                    countdown_str = refresh_time_str

            # Fetch Recent Kernels
            all_kernels: List[JobInfo] = []
            try:
                kernels = api.kernels_list(mine=True, page_size=8)
                for k in kernels:
                    ref = getattr(k, "ref", "")
                    title = getattr(k, "title", ref)
                    last_run = getattr(k, "last_run_time", getattr(k, "lastRunTime", ""))
                    last_run_str = str(last_run)[:19] if last_run else "recently"
                    
                    status_str = "COMPLETE"
                    try:
                        st = api.kernels_status(ref)
                        if hasattr(st, "status"):
                            status_str = str(st.status).split(".")[-1].upper()
                        elif isinstance(st, dict):
                            status_str = str(st.get("status", "COMPLETE")).upper()
                    except Exception:
                        pass
                    
                    last_run_iso = None
                    if last_run and status_str not in ("RUNNING", "QUEUED"):
                        try:
                            parsed = dt_parser.parse(str(last_run))
                            if parsed.tzinfo is None:
                                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
                            last_run_iso = parsed.isoformat()
                        except (ValueError, TypeError, OverflowError):
                            pass
                    is_active = status_str in ("RUNNING", "QUEUED")

                    all_kernels.append(JobInfo(
                        id=ref,
                        name=title,
                        user=self.username,
                        is_my_job=True,
                        state=status_str,
                        started_at=last_run_iso,
                        timing_source="last run" if last_run_iso else "",
                        time=last_run_str,
                        nodes="Kaggle",
                        resources="Free Accelerator",
                        type="kaggle",
                        url=f"https://www.kaggle.com/code/{ref}"
                    ))
            except Exception as e:
                logger.warning(f"Error fetching Kaggle kernels: {e}")

            # Active jobs count (ONLY count truly running or queued jobs)
            active_jobs = [j for j in all_kernels if j.state in ("RUNNING", "QUEUED")]

            # 1. GPU Node Card
            gpu_quota_obj = KaggleQuota(
                username=self.username,
                gpu_time_used_hours=gpu_used_hours,
                gpu_time_allowed_hours=gpu_allowed_hours,
                gpu_time_remaining_hours=gpu_rem_hours,
                gpu_util_pct=gpu_pct,
                quota_refresh_time=refresh_time_str,
                refresh_countdown=countdown_str,
                tpu_time_used_hours=tpu_used_hours,
                tpu_time_allowed_hours=tpu_allowed_hours,
                has_ever_run=gpu_quota.get("hasEverRun", True)
            )

            gpu_metrics_list = [
                GPUMetrics(
                    index=0,
                    name="Kaggle Free GPU (2x T4 / P100)",
                    memory_total_mb=32768.0,
                    memory_used_mb=round(32768.0 * (gpu_pct / 100.0), 1),
                    memory_free_mb=round(32768.0 * ((100.0 - gpu_pct) / 100.0), 1),
                    memory_util_pct=gpu_pct,
                    utilization_gpu=gpu_pct
                )
            ]

            gpu_node = NodeMetrics(
                id="kaggle-gpu",
                name="Kaggle GPU (2x T4 / P100)",
                type="kaggle",
                role="Cloud GPU Accelerator",
                status="BUSY" if active_jobs else "ONLINE",
                description=f"Weekly Free GPU Quota ({gpu_allowed_hours:.0f}h/wk) · @{self.username}",
                uptime=f"Resets in {countdown_str}" if countdown_str else "Weekly Quota Active",
                ip="kaggle.com",
                cpu_count=4,
                cpu_util_pct=gpu_pct,
                mem_total_mb=30720,
                mem_used_mb=round(30720 * (gpu_pct / 100.0), 1),
                mem_avail_mb=round(30720 * ((100.0 - gpu_pct) / 100.0), 1),
                mem_util_pct=gpu_pct,
                gpus=gpu_metrics_list,
                total_vram_total_mb=32768.0,
                total_vram_used_mb=round(32768.0 * (gpu_pct / 100.0), 1),
                total_vram_util_pct=gpu_pct,
                avg_gpu_util_pct=gpu_pct,
                kaggle_quota=gpu_quota_obj,
                jobs=all_kernels,
                my_jobs_count=len(active_jobs),  # Only count truly active jobs
                total_jobs_count=len(active_jobs),
                last_updated=now_str
            )

            # 2. TPU Node Card
            tpu_quota_obj = KaggleQuota(
                username=self.username,
                gpu_time_used_hours=tpu_used_hours,
                gpu_time_allowed_hours=tpu_allowed_hours,
                gpu_time_remaining_hours=tpu_rem_hours,
                gpu_util_pct=tpu_pct,
                quota_refresh_time=refresh_time_str,
                refresh_countdown=countdown_str,
                tpu_time_used_hours=tpu_used_hours,
                tpu_time_allowed_hours=tpu_allowed_hours,
                has_ever_run=tpu_quota.get("hasEverRun", False)
            )

            tpu_metrics_list = [
                GPUMetrics(
                    index=0,
                    name="Google Cloud TPU v3-8 (128GB HBM)",
                    memory_total_mb=131072.0,
                    memory_used_mb=round(131072.0 * (tpu_pct / 100.0), 1),
                    memory_free_mb=round(131072.0 * ((100.0 - tpu_pct) / 100.0), 1),
                    memory_util_pct=tpu_pct,
                    utilization_gpu=tpu_pct
                )
            ]

            tpu_node = NodeMetrics(
                id="kaggle-tpu",
                name="Kaggle TPU (TPU v3-8)",
                type="kaggle",
                role="Cloud TPU Accelerator",
                status="ONLINE",
                description=f"Weekly Free TPU Quota ({tpu_allowed_hours:.0f}h/wk) · @{self.username}",
                uptime=f"Resets in {countdown_str}" if countdown_str else "Weekly Quota Active",
                ip="kaggle.com",
                cpu_count=8,
                cpu_util_pct=tpu_pct,
                mem_total_mb=65536,
                mem_used_mb=round(65536 * (tpu_pct / 100.0), 1),
                mem_avail_mb=round(65536 * ((100.0 - tpu_pct) / 100.0), 1),
                mem_util_pct=tpu_pct,
                gpus=tpu_metrics_list,
                total_vram_total_mb=131072.0,
                total_vram_used_mb=round(131072.0 * (tpu_pct / 100.0), 1),
                total_vram_util_pct=tpu_pct,
                avg_gpu_util_pct=tpu_pct,
                kaggle_quota=tpu_quota_obj,
                jobs=[],
                my_jobs_count=0,
                total_jobs_count=0,
                last_updated=now_str
            )

            return {
                "kaggle-gpu": gpu_node,
                "kaggle-tpu": tpu_node
            }
        except Exception as e:
            logger.exception("Error querying Kaggle API")
            err_node = NodeMetrics(
                id="kaggle-gpu",
                name="Kaggle Accelerators",
                type="kaggle",
                role="Cloud Compute Tier",
                status="OFFLINE",
                description=f"Account: @{self.username}",
                error_message=str(e),
                last_updated=now_str
            )
            return {
                "kaggle-gpu": err_node,
                "kaggle-tpu": err_node
            }
