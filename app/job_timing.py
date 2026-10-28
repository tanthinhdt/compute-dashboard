"""Normalize probe timing without inventing a schedule for queued jobs."""
import datetime as dt
import re


def populate_job_timing(job, observed_at):
    if job.started_at or job.state not in {'RUNNING', 'R', 'MIXED'}:
        return
    seconds = None
    if job.type == 'slurm':
        # squeue elapsed time is [days-]hours:minutes:seconds or minutes:seconds.
        match = re.fullmatch(r'(?:(\d+)-)?(\d+):(\d{2})(?::(\d{2}))?', job.time)
        if match:
            days, a, b, c = match.groups()
            seconds = int(days or 0) * 86400
            seconds += int(a) * (3600 if c is not None else 60)
            seconds += int(b) * (60 if c is not None else 1) + int(c or 0)
    elif job.type == 'process':
        match = re.fullmatch(r'(\d+)s elapsed', job.time)
        if match:
            seconds = int(match.group(1))
    if seconds is not None:
        job.started_at = (observed_at - dt.timedelta(seconds=seconds)).isoformat()
        job.timing_source = 'estimated from elapsed time'
