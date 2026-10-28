import asyncio
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.network import NetworkMonitor, REMOTE_NETWORK_SCRIPT, probe_target


class NetworkTests(unittest.TestCase):
    def test_icmp_latency_and_loss(self):
        output = '3 packets transmitted, 2 received, 33.3333% packet loss\nrtt min/avg/max/mdev = 1.2/2.4/3.6/0.3 ms\n'
        with patch('subprocess.run', return_value=SimpleNamespace(stdout=output, returncode=1)):
            result = probe_target({'id':'destination','host':'example.invalid'})
        self.assertEqual(result['status'], 'degraded')
        self.assertEqual(result['latency_ms'], 2.4)
        self.assertEqual(result['loss_pct'], 33.3)

    def test_no_reply_is_distinct_from_missing_probe(self):
        with patch('subprocess.run', return_value=SimpleNamespace(stdout='3 packets transmitted, 0 received, 100% packet loss', returncode=1)):
            result = probe_target({'id':'destination','host':'example.invalid'})
        self.assertEqual(result['status'], 'no_response')
        self.assertEqual(result['loss_pct'], 100)
        with patch('subprocess.run', side_effect=FileNotFoundError()):
            result = probe_target({'id':'destination','host':'example.invalid'})
        self.assertEqual(result['status'], 'probe_error')
        self.assertIsNone(result['loss_pct'])

    def test_tcp_success_and_failure(self):
        target={'id':'destination','host':'example.invalid','mode':'tcp','port':443}
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='[]')):
            result = probe_target(target)
        self.assertEqual(result['status'], 'no_response')
        self.assertEqual(result['loss_pct'], 100)
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='[1,2,3]')):
            result = probe_target(target)
        self.assertEqual(result['status'], 'reachable')
        self.assertEqual(result['received'], 3)
        self.assertIsNotNone(result['latency_ms'])
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('tcp', 5)):
            result = probe_target(target)
        self.assertEqual(result['status'], 'probe_error')
        self.assertIsNone(result['loss_pct'])

    def test_self_links_skipped_and_source_errors_not_target_failures(self):
        monitor=NetworkMonitor({'enabled':True,'sources':[{'id':'source','ssh_host':'source-alias'}],
                                'targets':[{'id':'source','host':'source.example'},{'id':'destination','host':'destination.example'}]})
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('ssh',20)):
            monitor.collect()
        data=monitor.snapshot()
        self.assertEqual(len(data['links']), 1)
        self.assertEqual(data['links'][0]['status'], 'source_unavailable')
        self.assertIsNone(data['links'][0]['loss_pct'])
        self.assertNotIn('host',data['targets'][0])
        self.assertNotIn('ssh_host',data['sources'][0])
        monitor._checked_at -= 121
        self.assertTrue(monitor.snapshot()['stale'])

    def test_nested_ssh_script_and_disabled_defaults(self):
        monitor=NetworkMonitor({'enabled':True,'sources':[{'id':'worker','ssh_host':'worker-alias','via':'controller-alias'}],
                                'targets':[{'id':'destination','host':'destination.example'}]})
        payload=[dict(target_id='destination',mode='icmp',status='reachable',latency_ms=1,loss_pct=0,sent=3,received=3)]
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(payload))) as runner:
            monitor.collect()
        command=runner.call_args.args[0]
        self.assertEqual(command[-2], 'controller-alias')
        self.assertIn('worker-alias',command[-1])
        compile(runner.call_args.kwargs['input'],'<remote network>','exec')
        self.assertEqual(monitor.snapshot()['links'][0]['source_id'],'worker')
        self.assertFalse(NetworkMonitor({}).snapshot()['enabled'])
        compile(REMOTE_NETWORK_SCRIPT,'<remote network>','exec')

    def test_configuration_validation(self):
        for config in [{'sources':[{'id':'bad id','local':True}]},
                       {'targets':[{'id':'target','host':'example.invalid','mode':'unknown'}]},
                       {'sources':[{'id':'source'}]},
                       {'targets':[{'id':'target','host':'example.invalid','port':70000}]}]:
            with self.assertRaises(ValueError):
                NetworkMonitor(config)
