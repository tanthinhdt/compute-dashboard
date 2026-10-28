import io
import json
import unittest
from collections import namedtuple
from types import SimpleNamespace
from unittest.mock import patch

from app.probes.disk_probe import collect_local_disks, collect_remote_disks
from app.probes.ssh_probe import (
    REMOTE_CPU_CLUSTER_SCRIPT, REMOTE_GPU_SCRIPT,
    RemoteCPUClusterProbe, RemoteGPUProbe,
)


class DiskTests(unittest.TestCase):
    def test_local_filters_and_inaccessible_mounts(self):
        Partition = namedtuple('Partition', 'device mountpoint fstype')
        partitions = [Partition('/dev/sda', '/', 'xfs'),
                      Partition('/dev/sdb', '/data', 'ext4'),
                      Partition('/dev/sdb', '/denied', 'ext4'),
                      Partition('/dev/loop0', '/other', 'ext4'),
                      Partition('/dev/sda1', '/boot/efi', 'vfat'),
                      Partition('tmpfs', '/memory', 'tmpfs'),
                      Partition('/dev/sda', '/', 'xfs')]
        def usage(mount):
            if mount == '/denied':
                raise PermissionError()
            return SimpleNamespace(total=10 * 1024**3, used=6 * 1024**3,
                                   free=4 * 1024**3, percent=60)
        with patch('psutil.disk_partitions', return_value=partitions), patch('psutil.disk_usage', side_effect=usage):
            disks = collect_local_disks()
        self.assertEqual([d.mountpoint for d in disks], ['/', '/data'])
        self.assertEqual(disks[1].total_gb, 10)
        self.assertEqual(disks[1].usage_pct, 60)

    def test_remote_escaped_mounts_reserved_blocks_and_failures(self):
        mounts = '/dev/sda / xfs rw 0 0\n/dev/sdb /data\\040disk ext4 rw 0 0\n'
        mounts += 'tmpfs /ram tmpfs rw 0 0\n/dev/loop0 /snap/a squashfs ro 0 0\n'
        mounts += '/dev/sdc /denied xfs rw 0 0\n/dev/sdd /empty xfs rw 0 0\n'
        def stat(mount):
            if mount == '/denied':
                raise OSError()
            return SimpleNamespace(f_blocks=0 if mount == '/empty' else 100,
                                   f_bfree=40, f_bavail=30, f_frsize=1024**3)
        with patch('builtins.open', return_value=io.StringIO(mounts)), patch('os.statvfs', side_effect=stat):
            disks = collect_remote_disks()
        self.assertEqual([d['mountpoint'] for d in disks], ['/', '/data disk'])
        self.assertEqual(disks[0]['used_gb'], 60)
        self.assertEqual(disks[0]['free_gb'], 30)
        self.assertEqual(disks[0]['usage_pct'], 66.7)

    def test_remote_disk_failures_are_empty(self):
        with patch('builtins.open', side_effect=OSError()):
            self.assertEqual(collect_remote_disks(), [])

    def test_disk_data_reaches_gpu_and_cpu_models(self):
        disk = dict(mountpoint='/data', fstype='xfs', total_gb=100, used_gb=25, usage_pct=25)
        gpu = RemoteGPUProbe({'id': 'gpu'}, set())
        cpu = RemoteCPUClusterProbe({'controller_ssh_host': 'controller', 'nodes': [{'id': 'controller'}, {'id': 'worker-a'}]}, set())
        for probe, payload in [(gpu, {'disks': [disk]}),
                               (cpu, {'nodes': {'controller': {'disks': [disk]}, 'worker-a': {}}, 'jobs': []})]:
            with patch('subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(payload))):
                result = probe.collect()
            node = result['controller'] if isinstance(result, dict) else result
            self.assertEqual(node.disks[0].mountpoint, '/data')
            if isinstance(result, dict):
                self.assertEqual(result['worker-a'].disks, [])

    def test_embedded_scripts_compile(self):
        for script in [REMOTE_GPU_SCRIPT, REMOTE_CPU_CLUSTER_SCRIPT]:
            compile(script, '<remote>', 'exec')
        # Also compile the worker script sent over the nested SSH hop.
        prefix = REMOTE_CPU_CLUSTER_SCRIPT.split('import subprocess', 1)[0]
        namespace = {}
        exec(prefix, namespace)
        compile(namespace['DISK_WORKER_SCRIPT'], '<worker>', 'exec')


if __name__ == '__main__':
    unittest.main()
