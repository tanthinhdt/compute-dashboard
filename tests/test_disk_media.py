import io
import os
import stat
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.probes.disk_probe import disk_media_type


class DiskMediaTests(unittest.TestCase):
    def classify(self, root, files=None, slaves=None, links=None, device='/dev/example'):
        files=files or {}
        slaves=slaves or {}
        links=links or {}
        def read(path, *args, **kwargs):
            if path not in files:
                raise FileNotFoundError(path)
            return io.StringIO(files[path])
        def realpath(path):
            if path == '/sys/dev/block/8:1':
                return root
            return links.get(path,path)
        with patch('os.stat',return_value=SimpleNamespace(st_mode=stat.S_IFBLK,st_rdev=os.makedev(8,1))), \
             patch('os.path.realpath',side_effect=realpath), \
             patch('os.path.exists',side_effect=lambda path:path in files), \
             patch('os.listdir',side_effect=lambda path:slaves.get(path,[])), \
             patch('builtins.open',side_effect=read):
            return disk_media_type(device,'ext4')

    def test_partition_inherits_hdd(self):
        self.assertEqual(self.classify('/sys/devices/block/sda/sda1',
            {'/sys/devices/block/sda/sda1/partition':'1','/sys/devices/block/sda/queue/rotational':'1'}),'HDD')

    def test_nvme_and_sata_ssd(self):
        for path in ['/sys/devices/block/nvme0n1','/sys/devices/block/sdb']:
            self.assertEqual(self.classify(path,{path+'/queue/rotational':'0'}),'SSD')

    def test_lvm_and_mixed_raid(self):
        root='/sys/devices/virtual/block/dm-0'
        a='/sys/devices/block/sda'
        b='/sys/devices/block/sdb'
        slaves={root+'/slaves':['sda','sdb']}
        links={root+'/slaves/sda':a,root+'/slaves/sdb':b}
        self.assertEqual(self.classify(root,{a+'/queue/rotational':'0',b+'/queue/rotational':'0'},slaves,links),'SSD')
        self.assertEqual(self.classify(root,{a+'/queue/rotational':'0',b+'/queue/rotational':'1'},slaves,links),'Mixed')
        self.assertEqual(self.classify(root,{a+'/queue/rotational':'0'},slaves,links),'Unknown')

    def test_virtual_and_unavailable_metadata(self):
        self.assertEqual(self.classify('/sys/devices/pci/virtio/block/vda'),'Virtual')
        self.assertEqual(self.classify('/sys/devices/virtual/block/dm-0'),'Virtual')
        self.assertEqual(self.classify('/sys/devices/block/sda'),'Unknown')
        with patch('os.stat',side_effect=PermissionError()):
            self.assertEqual(disk_media_type('/dev/denied','ext4'),'Unknown')
        self.assertEqual(disk_media_type('none','ext4'),'Unknown')

    def test_network_mounts_do_not_guess_remote_media(self):
        with patch('os.stat',side_effect=AssertionError('Must not stat a network mount')):
            for fstype in ['nfs','nfs4','cifs','fuse.sshfs','lustre']:
                self.assertEqual(disk_media_type('server:/share',fstype),'Network')
