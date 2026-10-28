import unittest

from app.job_merge import merge_gpu_processes, slurm_job_id_from_cgroup
from app.models import JobInfo


def job(jid, state='RUNNING'):
    return JobInfo(id=jid, name='same name', user='same-user', state=state, type='slurm')


def process(pid, allocation=None, memory=100):
    return dict(pid=str(pid), user='same-user', process='/opt/example-env/bin/python', gpu='GPU',
                used_memory_mb=memory, elapsed_seconds=30, slurm_job_id=allocation)


class JobMergeTests(unittest.TestCase):
    def test_cgroup_membership(self):
        for value in ['0::/system.slice/compute-node_slurmstepd.scope/job_101/step_batch/user/task_0\n',
                      '5:cpuset:/slurm/uid_1000/job_101/step_0\n',
                      '0::/job_101.scope/step_0\n']:
            self.assertEqual(slurm_job_id_from_cgroup(value), '101')
        for value in ['', '/user.slice/session-101.scope', '/job_101extra/step', '/job_1/step\n/job_2/step']:
            self.assertIsNone(slurm_job_id_from_cgroup(value))

    def test_verified_processes_merge_but_distinct_same_named_jobs_remain(self):
        jobs = merge_gpu_processes([job('101'), job('102')],
                                   [process(1, '101'), process(2, '102')], {}, 'gpu-node', set())
        self.assertEqual([j.id for j in jobs], ['101', '102'])
        self.assertEqual(jobs[0].gpu_processes[0].pid, '1')
        self.assertEqual(jobs[1].gpu_processes[0].pid, '2')

    def test_array_task_uses_actual_allocation_id(self):
        jobs = merge_gpu_processes([job('200_0'), job('200_1')],
                                   [process(1, '201'), process(2, '202')],
                                   {'200_0': '201', '200_1': '202'}, 'gpu-node', set())
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].gpu_processes[0].pid, '1')
        self.assertEqual(jobs[1].gpu_processes[0].pid, '2')

    def test_unverified_processes_are_never_merged_by_user_or_name(self):
        jobs = merge_gpu_processes([job('101')], [process(1), process(2, '999')], {}, 'gpu-node', {'same-user'})
        self.assertEqual([j.id for j in jobs], ['101', 'PID-1', 'PID-2'])
        self.assertTrue(jobs[1].is_my_job)

    def test_one_process_across_multiple_gpus_counts_once(self):
        for scheduled in [True, False]:
            jobs = merge_gpu_processes([job('101')] if scheduled else [],
                                       [process(1, '101', 100), process(1, '101', 200)], {}, 'gpu-node', set())
            self.assertEqual(len(jobs), 1)
            self.assertEqual(len(jobs[0].gpu_processes), 1)
            self.assertEqual(jobs[0].gpu_processes[0].memory_used_mb, 300)

    def test_device_indices_survive_multi_gpu_process_merge(self):
        apps = [dict(process(1, '101', 100), gpu_index=0, gpu_uuid='GPU-zero'),
                dict(process(1, '101', 200), gpu_index=3, gpu_uuid='GPU-three'),
                dict(process(2, '101', 50), gpu_index=3, gpu_uuid='GPU-three')]
        jobs = merge_gpu_processes([job('101')], apps, {}, 'gpu-node', set())
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].gpu_processes[0].gpu_indices, [0, 3])
        self.assertEqual(jobs[0].gpu_processes[0].gpu_uuids, ['GPU-three', 'GPU-zero'])
        self.assertEqual(jobs[0].gpu_processes[0].memory_used_mb, 300)
        self.assertEqual(jobs[0].gpu_processes[1].gpu_indices, [3])

    def test_pending_or_ambiguous_allocations_do_not_swallow_processes(self):
        jobs = merge_gpu_processes([job('1', 'PD')], [process(2, '1')], {}, 'gpu-node', set())
        self.assertEqual(len(jobs), 2)
        jobs = merge_gpu_processes([job('10_0'), job('10_1')], [process(2, '1')],
                                   {'10_0': '1', '10_1': '1'}, 'gpu-node', set())
        self.assertEqual(len(jobs), 3)
