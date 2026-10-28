import datetime as dt
import unittest

from app.job_timing import populate_job_timing
from app.models import JobInfo
from app.probes.ssh_probe import parse_slurm_timestamp


class JobTimingTests(unittest.TestCase):
    def test_elapsed_formats(self):
        now = dt.datetime(2026, 10, 28, 12, tzinfo=dt.timezone.utc)
        for kind, value, seconds in [('slurm', '01:02', 62), ('slurm', '02:03:04', 7384),
                                     ('slurm', '2-02:03:04', 180184), ('process', '120s elapsed', 120)]:
            job = JobInfo(id='1', name='test', user='me', type=kind, time=value)
            populate_job_timing(job, now)
            self.assertEqual(dt.datetime.fromisoformat(job.started_at), now - dt.timedelta(seconds=seconds))
            self.assertIn('estimated', job.timing_source)

    def test_queued_unknown_and_known_timing(self):
        now = dt.datetime.now(dt.timezone.utc)
        for state, value in [('PENDING', '00:00'), ('RUNNING', 'active'), ('RUNNING', '25% CPU')]:
            job = JobInfo(id='1', name='test', user='me', time=value, state=state)
            populate_job_timing(job, now)
            self.assertIsNone(job.started_at)
        job = JobInfo(id='1', name='test', user='me', started_at=now.isoformat(), time='01:00')
        populate_job_timing(job, now)
        self.assertEqual(job.started_at, now.isoformat())


class SchedulerTimestampTests(unittest.TestCase):
    def test_timezone_conversion(self):
        self.assertEqual(parse_slurm_timestamp('2026-10-29T18:00:00+0900'), '2026-10-29T09:00:00+00:00')

    def test_missing_unknown_and_unlimited(self):
        for value in [None, '', 'Unknown', 'N/A', 'UNLIMITED', 'INVALID', '2026-10-29T18:00:00']:
            self.assertIsNone(parse_slurm_timestamp(value))
