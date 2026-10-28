import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from app.collector import MetricsCollector
from app.models import NodeMetrics


class ConfigTests(unittest.TestCase):
    def make_config(self, clusters):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)/'config.yaml'
        path.write_text(yaml.safe_dump({'organizations':[{'id':'example','name':'Example','clusters':clusters}]}))
        return path

    def test_arbitrary_local_id_and_no_implicit_owners(self):
        cfg = self.make_config([{'id':'local-group','name':'Local','type':'workstation','nodes':[{'id':'my-local','name':'My Local'}]}])
        collector = MetricsCollector(cfg)
        probe = next(iter(collector._probes.values()))
        self.assertEqual(probe.node_id, 'my-local')
        self.assertEqual(probe.my_users, set())
        with patch.object(probe, 'collect', return_value=NodeMetrics(id='my-local',name='Detected',type='workstation')):
            response = asyncio.run(collector.refresh_all())
        self.assertEqual(response.organizations[0].clusters[0].nodes[0].name, 'My Local')
        self.assertEqual(response.network_info, {})

    def test_multiple_cpu_groups_do_not_overwrite_each_other(self):
        clusters = [{'id':f'pool-{index}','type':'cpu','controller_ssh_host':f'controller-{index}',
                     'nodes':[{'id':f'worker-{index}'}]} for index in [1,2]]
        collector = MetricsCollector(self.make_config(clusters))
        self.assertEqual(len(collector._probes), 2)
        patches = []
        for key, probe in collector._probes.items():
            nid = next(iter(probe.nodes_config))
            patches.append(patch.object(probe,'collect',return_value={nid:NodeMetrics(id=nid,name=nid,type='cpu')}))
        with patches[0], patches[1]:
            response = asyncio.run(collector.refresh_all())
        self.assertEqual(response.summary.online_nodes, 2)

    def test_duplicate_node_ids_are_rejected(self):
        clusters = [{'id':f'pool-{index}','type':'gpu','nodes':[{'id':'duplicate'}]} for index in [1,2]]
        with self.assertRaises(ValueError):
            MetricsCollector(self.make_config(clusters))

    def test_cpu_runtime_targets_come_from_configuration(self):
        from app.probes.ssh_probe import RemoteCPUClusterProbe
        probe = RemoteCPUClusterProbe({'controller_ssh_host':'scheduler-alias','controller_node':'scheduler',
                                       'nodes':[{'id':'worker-z','ssh_host':'worker-z-alias'}]},set())
        from types import SimpleNamespace
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='{"nodes":{},"jobs":[]}')) as runner:
            probe.collect()
        script=runner.call_args.kwargs['input']
        self.assertIn("'worker-z': 'worker-z-alias'",script)
        self.assertIn("CONTROLLER_NODE = 'scheduler'",script)
        compile(script,'<configured probe>','exec')
