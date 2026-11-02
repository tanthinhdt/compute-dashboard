"""Disk collection helpers; collect_remote_disks is also sent to SSH hosts."""


def disk_media_type(device, fstype):
    """Best-effort Linux media type; never infer remote server backing media."""
    import os
    import stat

    network_types = {'nfs', 'nfs4', 'cifs', 'smb3', 'smbfs', 'ceph', 'glusterfs',
                     'fuse.glusterfs', 'fuse.sshfs', 'sshfs', 'lustre', 'afs', '9p'}
    if fstype.lower() in network_types:
        return 'Network'
    if not device.startswith('/dev/'):
        return 'Unknown'
    try:
        info = os.stat(device)
        if not stat.S_ISBLK(info.st_mode):
            return 'Unknown'
        path = os.path.realpath('/sys/dev/block/{}:{}'.format(os.major(info.st_rdev), os.minor(info.st_rdev)))
    except (OSError, ValueError, AttributeError):
        return 'Unknown'

    def classify(path, visited):
        path = os.path.realpath(path)
        if path in visited:
            return 'Unknown'
        visited = visited | {path}
        # Partitions inherit their parent device's rotational flag.
        if os.path.exists(os.path.join(path, 'partition')):
            path = os.path.dirname(path)
        try:
            slaves = os.listdir(os.path.join(path, 'slaves'))
        except OSError:
            slaves = []
        if slaves:
            kinds = {classify(os.path.join(path, 'slaves', name), visited) for name in slaves}
            if kinds == {'SSD'} or kinds == {'HDD'}:
                return next(iter(kinds))
            return 'Mixed' if kinds == {'SSD', 'HDD'} else 'Unknown'
        if '/virtual/' in path or os.path.basename(path).startswith(('vd', 'xvd')):
            return 'Virtual'
        try:
            with open(os.path.join(path, 'queue', 'rotational')) as stream:
                flag = stream.read().strip()
            return {'0': 'SSD', '1': 'HDD'}.get(flag, 'Unknown')
        except OSError:
            return 'Unknown'

    return classify(path, set())


def collect_remote_disks():
    # Keep imports inside this function so its source runs on hosts without psutil.
    import os
    import re

    disks = []
    seen = set()
    try:
        with open('/proc/mounts') as mounts:
            entries = mounts.readlines()
    except OSError:
        return disks
    for line in entries:
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mountpoint, fstype = [
            re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), p)
            for p in parts[:3]
        ]
        if (mountpoint.startswith(('/snap', '/boot', '/proc', '/sys', '/dev', '/run'))
                or device.startswith('/dev/loop')
                or fstype in {'tmpfs', 'devtmpfs', 'squashfs', 'overlay', 'autofs'}
                or mountpoint in seen):
            continue
        try:
            stat = os.statvfs(mountpoint)
        except OSError:
            continue
        total = stat.f_blocks * stat.f_frsize
        if total <= 0:
            continue
        used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize
        seen.add(mountpoint)
        disks.append(dict(mountpoint=mountpoint, device=device, fstype=fstype,
                          media_type=disk_media_type(device, fstype),
                          total_gb=round(total / 1024**3, 2),
                          used_gb=round(used / 1024**3, 2),
                          free_gb=round(free / 1024**3, 2),
                          usage_pct=round(used / (used + free) * 100, 1)
                          if used + free else 0.0))
    return disks


def collect_local_disks():
    import psutil
    from app.models import DiskMetrics

    disks = []
    seen = set()
    try:
        partitions = psutil.disk_partitions(all=False)
    except OSError:
        return disks
    for partition in partitions:
        if (partition.mountpoint.startswith(('/snap', '/boot'))
                or partition.device.startswith('/dev/loop')
                or partition.fstype in {'tmpfs', 'devtmpfs', 'squashfs', 'overlay', 'autofs'}
                or partition.mountpoint in seen):
            continue
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except OSError:
            continue
        if usage.total <= 0:
            continue
        seen.add(partition.mountpoint)
        disks.append(DiskMetrics(
            mountpoint=partition.mountpoint, device=partition.device,
            fstype=partition.fstype,
            media_type=disk_media_type(partition.device, partition.fstype), total_gb=round(usage.total / 1024**3, 2),
            used_gb=round(usage.used / 1024**3, 2),
            free_gb=round(usage.free / 1024**3, 2), usage_pct=usage.percent))
    return disks
