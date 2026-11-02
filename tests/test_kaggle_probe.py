import time
import unittest
from types import SimpleNamespace

from app.availability import resource_snapshot
from app.models import ClusterGroup, DashboardResponse, DashboardSummary, OrganizationGroup
from app.probes.kaggle_probe import KaggleProbe


class KaggleProbeTests(unittest.TestCase):
    def collect(self):
        probe = KaggleProbe('example-user')
        probe._api = SimpleNamespace(
            quota_view=lambda: {'gpuQuota':{'timeUsed':'3600s','totalTimeAllowed':'108000s'},
                                'tpuQuota':{'timeUsed':'1800s','totalTimeAllowed':'72000s'}},
            kernels_list=lambda **kwargs: [])
        return probe.collect()

    def test_catalogs_and_quotas_are_separate(self):
        nodes=self.collect()
        gpu=nodes['kaggle-gpu']
        self.assertEqual(gpu.kaggle_quota.gpu_time_remaining_hours,29)
        self.assertEqual(gpu.accelerator_kind,'gpu')
        ids={option.id for option in gpu.accelerator_options}
        self.assertEqual(ids,{'NvidiaTeslaT4','NvidiaTeslaA100','NvidiaL4','NvidiaL4X1','NvidiaH100','NvidiaRtxPro6000'})
        self.assertNotIn('NvidiaTeslaP100',ids)
        self.assertEqual({option.id for option in nodes['kaggle-tpu'].accelerator_options},{'TpuV5E8','TpuV6E8'})

    def test_quota_is_not_hardware_telemetry(self):
        for node in self.collect().values():
            self.assertEqual(node.gpus,[])
            self.assertEqual(node.cpu_count,0)
            self.assertEqual(node.cpu_util_pct,0)
            self.assertEqual(node.mem_total_mb,0)
            self.assertEqual(node.total_vram_total_mb,0)

    def test_assistant_response_does_not_claim_account_eligibility(self):
        node=self.collect()['kaggle-tpu']
        node.id='custom-cloud-id'
        data=DashboardResponse(summary=DashboardSummary(),organizations=[OrganizationGroup(id='org',name='Resources',clusters=[ClusterGroup(id='cloud',name='Cloud',type='kaggle',nodes=[node])])])
        result=resource_snapshot(data,time.time(),30)
        item=result['resources'][0]
        self.assertFalse(item['accelerator_options_account_verified'])
        self.assertFalse(item['observed_candidate'])
        self.assertEqual(item['cloud_quota_remaining_hours'],19.5)
        self.assertEqual(len(item['documented_accelerators']),2)
        self.assertNotIn('username',item)
