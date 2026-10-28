"""Rate-limited, read-only network observations from configured probe hosts."""
import asyncio
import concurrent.futures
import datetime as dt
import inspect
import json
import re
import shlex
import subprocess
import threading
import time

from app.probes.ssh_probe import SSH_COMMON_OPTS


def probe_target(target, attempts=3):
    # Standalone: its source is sent to probe hosts, without extra packages.
    import os
    import re
    import subprocess

    result = dict(target_id=target['id'], mode=target.get('mode', 'icmp'),
                  status='probe_error', sent=attempts, received=0,
                  latency_ms=None, loss_pct=None, error=None)
    if result['mode'] == 'tcp':
        # socket timeouts do not bound DNS lookup. Isolate the entire TCP sample
        # so a resolver stall cannot discard all other links from this source.
        import json
        import sys
        code = """import json, socket, sys, time
host, port, attempts = json.loads(sys.argv[1])
latencies = []
for _ in range(attempts):
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=1):
            latencies.append((time.monotonic() - start) * 1000)
    except OSError:
        pass
print(json.dumps(latencies))
"""
        try:
            response = subprocess.run([sys.executable, '-c', code,
                                       json.dumps([target['host'], target.get('port', 443), attempts])],
                                      capture_output=True, text=True, timeout=5)
            if response.returncode:
                raise ValueError('TCP worker failed')
            latencies = json.loads(response.stdout)
            result.update(received=len(latencies), loss_pct=round((1 - len(latencies) / attempts) * 100, 1),
                          latency_ms=round(sum(latencies) / len(latencies), 2) if latencies else None,
                          status='reachable' if len(latencies) == attempts else 'degraded' if latencies else 'no_response')
        except (OSError, ValueError, subprocess.TimeoutExpired):
            result['error'] = 'TCP probe or address lookup did not complete'
        return result
    try:
        response = subprocess.run(['ping', '-n', '-c', str(attempts), '-i', '0.3', '-W', '1', '-w', '4', '--', target['host']],
                                  capture_output=True, text=True, timeout=5,
                                  env=dict(os.environ, LC_ALL='C'))
        stats = re.search(r'(\d+) packets transmitted,\s*(\d+) (?:packets )?received', response.stdout)
        latency = re.search(r'=\s*[\d.]+/([\d.]+)/[\d.]+/[\d.]+\s*ms', response.stdout)
        if stats:
            sent, received = map(int, stats.groups())
            result.update(sent=sent, received=received,
                          loss_pct=round((1 - received / sent) * 100, 1) if sent else None,
                          latency_ms=float(latency.group(1)) if latency else None,
                          status='reachable' if received == sent and sent else 'degraded' if received else 'no_response')
        else:
            result['error'] = 'ICMP unavailable, address unresolved, or ping not permitted'
    except FileNotFoundError:
        result['error'] = 'ping is not installed on the source'
    except (OSError, subprocess.TimeoutExpired):
        result['error'] = 'ICMP probe could not complete'
    return result


REMOTE_NETWORK_SCRIPT = (inspect.getsource(probe_target) + '''
import concurrent.futures
import json
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(lambda target: probe_target(target, ATTEMPTS), TARGETS))
print(json.dumps(results))
''')


class NetworkMonitor:
    def __init__(self, config):
        self.enabled = bool(config.get('enabled', False))
        self.interval = max(30, int(config.get('interval_seconds', 60)))
        self.attempts = max(1, min(3, int(config.get('attempts', 3))))
        self.sources = config.get('sources', [])
        self.targets = config.get('targets', [])
        for entries in [self.sources, self.targets]:
            ids = [entry['id'] for entry in entries]
            if len(ids) != len(set(ids)) or any(not re.fullmatch(r'[A-Za-z0-9_-]+', value) for value in ids):
                raise ValueError('Network endpoint IDs must be unique within sources/targets and contain letters, digits, underscores or hyphens')
        for target in self.targets:
            if not target.get('host') or target.get('mode', 'icmp') not in {'icmp', 'tcp'}:
                raise ValueError('Network targets need a host and icmp or tcp mode')
            if not 1 <= int(target.get('port', 443)) <= 65535:
                raise ValueError('Invalid TCP target port')
            target['port'] = int(target.get('port', 443))
        for source in self.sources:
            if not source.get('local') and not source.get('ssh_host'):
                raise ValueError('Network sources need local=true or an ssh_host')
            if any(str(source.get(key, '')).startswith('-') for key in ('ssh_host', 'via')):
                raise ValueError('SSH source aliases cannot start with a dash')
        if len(self.sources) > 32 or len(self.targets) > 32:
            raise ValueError('Limit network monitoring to 32 sources and targets')
        self._lock = threading.Lock()
        self._task = None
        self._checked_at = 0
        self._links = []
        self._running = False

    def start(self):
        if self.enabled and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while True:
            started = time.monotonic()
            try:
                await asyncio.to_thread(self.collect)
            except Exception:
                # Keep the prior observation; age/stale will expose failures.
                pass
            await asyncio.sleep(max(1, self.interval - (time.monotonic() - started)))

    def snapshot(self):
        with self._lock:
            age = time.time() - self._checked_at if self._checked_at else None
            return dict(enabled=self.enabled, interval_seconds=self.interval, attempts=self.attempts,
                        checking=self._running,
                        checked_at=dt.datetime.fromtimestamp(self._checked_at, dt.timezone.utc).isoformat() if self._checked_at else None,
                        age_seconds=round(max(0, age), 1) if age is not None else None,
                        stale=age is None or age > self.interval * 2,
                        sources=[dict(id=s['id'], name=s.get('name', s['id'])) for s in self.sources],
                        targets=[dict(id=t['id'], name=t.get('name', t['id']), mode=t.get('mode', 'icmp')) for t in self.targets],
                        links=[dict(link) for link in self._links])

    def _source_links(self, source):
        targets = [target for target in self.targets if target['id'] != source['id']]
        if not targets:
            return []
        try:
            if source.get('local'):
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                    results = list(executor.map(lambda t: probe_target(t, self.attempts), targets))
            else:
                script = 'TARGETS = ' + repr(targets) + '\nATTEMPTS = ' + repr(self.attempts) + '\n' + REMOTE_NETWORK_SCRIPT
                host = source['ssh_host']
                remote = [host, 'python3 -']
                if source.get('via'):
                    nested = shlex.join(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=3', host, 'python3 -'])
                    remote = [source['via'], nested]
                response = subprocess.run(['ssh'] + SSH_COMMON_OPTS + remote, input=script, text=True,
                                          capture_output=True, timeout=max(20, 8 + 5 * ((len(targets) + 3) // 4)))
                if response.returncode:
                    raise OSError('source SSH failed')
                results = json.loads(response.stdout)
                if {r['target_id'] for r in results} != {t['id'] for t in targets}:
                    raise ValueError('Incomplete source results')
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
            results = [dict(target_id=t['id'], mode=t.get('mode', 'icmp'), status='source_unavailable',
                            latency_ms=None, loss_pct=None, sent=None, received=None,
                            error='Source SSH or Python probe unavailable') for t in targets]
        return [dict(result, source_id=source['id']) for result in results]

    def collect(self):
        with self._lock:
            if not self.enabled or self._running:
                return
            self._running = True
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                groups = list(executor.map(self._source_links, self.sources))
            with self._lock:
                self._links = [link for group in groups for link in group]
                self._checked_at = time.time()
        finally:
            with self._lock:
                self._running = False
