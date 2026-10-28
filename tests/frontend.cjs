// Run with NODE_PATH pointing at an installed jsdom package directory.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM } = require('jsdom');
const dom = new JSDOM(fs.readFileSync('static/index.html', 'utf8'), {
  url: 'http://localhost/', runScripts: 'outside-only',
});
const { window } = dom;
window.eval(fs.readFileSync('static/app.js', 'utf8') + '\nwindow.testRun = (code) => eval(code);');
const run = (code) => window.testRun(code);
class FakeEventSource {
  constructor() { this.handlers = {}; FakeEventSource.latest = this; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  close() {}
}
window.EventSource = FakeEventSource;
const base = {
  id: 'one', name: 'Host One', role: 'Worker', description: 'test', type: 'gpu', status: 'ONLINE',
  jobs: [{id: '1', type: 'process', name: 'Train', user: 'me', is_my_job: true, state: 'RUNNING', time: '1m'}],
  disks: [{mountpoint: '/data', device: '/dev/sda', fstype: 'xfs', total_gb: 100, used_gb: 25, free_gb: 75, usage_pct: 25}],
  gpus: [{index: 0, name: 'GPU', memory_util_pct: 25, utilization_gpu: 20,
    memory_total_mb: 8192, memory_used_mb: 2048, memory_free_mb: 6144}],
  my_jobs_count: 1, cpu_count: 8, cpu_util_pct: 10, mem_util_pct: 25, mem_used_mb: 4096, mem_total_mb: 16384, mem_avail_mb: 12288,
  cpu_load_1m: 1, cpu_load_5m: 1, cpu_load_15m: 1, total_vram_total_mb: 8192,
  total_vram_used_mb: 2048, total_vram_util_pct: 25, avg_gpu_util_pct: 20,
};
const summary = {online_nodes: 2, total_nodes: 2, total_gpus: 2, used_vram_gb: 4, total_vram_gb: 16, total_cpu_cores: 16, my_running_jobs: 2, kaggle_gpu_remaining_hours: 30};
window.fixture = {summary, organizations: [{id: 'org', name: 'Lab', description: '', clusters: [
  {id: 'cluster', name: 'Cluster', description: '', nodes: [base, {...base, id: 'two', name: 'Host Two'}]},
]}]};
run('setupEventListeners(); initSSE();');
FakeEventSource.latest.handlers.metrics({data: JSON.stringify(window.fixture)});
run('currentData = fixture; render();');
const doc = window.document;
const card = doc.querySelector('[data-node-id="one"]');
const progress = card.querySelector('.progress-fill');
const title = card.querySelector('.node-name');
const range = doc.createRange(); range.selectNodeContents(title.firstChild);
window.getSelection().addRange(range);
const selection = window.getSelection().toString();
window.fixture.organizations[0].clusters[0].nodes[0].cpu_util_pct = 55;
FakeEventSource.latest.handlers.metrics({data: JSON.stringify(window.fixture)});
assert.equal(card, doc.querySelector('[data-node-id="one"]'));
assert.equal(progress, card.querySelector('.progress-fill'));
assert.equal(progress.style.width, '55%');
assert.equal(window.getSelection().toString(), selection);
card.querySelector('.view-details-link').click();
assert.equal(window.location.hash, '#/node/one');
run('currentData = fixture;');
run('fixture.organizations[0].clusters[0].nodes.reverse(); render();');
assert.equal(card, doc.querySelector('[data-node-id="one"]'));
assert.equal(doc.querySelector('.node-card').dataset.nodeId, 'two');
run('fixture.organizations[0].clusters[0].nodes[1].jobs[0].type = "slurm"; currentView = {type: "detail", nodeId: "one"}; render();');
const detail = doc.querySelector('.detail-view');
const disk = doc.querySelector('[data-key="disk:/data"]');
const row = doc.querySelector('tbody tr');
const gpu = doc.querySelector('.gpu-card');
run(`fixture.organizations[0].clusters[0].nodes[1].jobs[0].gpu_processes = [{pid:"10001", command:"/opt/example-env/bin/python", memory_used_mb:826}]; render();`);
assert.equal(doc.querySelectorAll('tbody tr').length, 1);
assert.match(doc.querySelector('.job-process-list').textContent, /GPU process PID 10001/);
run(`fixture.organizations[0].clusters[0].nodes[1].disks[0].usage_pct = 80;
fixture.organizations[0].clusters[0].nodes[1].jobs.unshift({id:'2', type:'process', name:'New', user:'me', state:'RUNNING'});
render();`);
assert.equal(detail, doc.querySelector('.detail-view'));
assert.equal(disk, doc.querySelector('[data-key="disk:/data"]'));
assert.equal(disk.querySelector('.progress-fill').style.width, '80%');
assert.equal(row, doc.querySelector('tbody tr:last-child'));
run('fixture.organizations[0].clusters[0].nodes[1].gpus = []; render();');
assert.equal(disk, doc.querySelector('[data-key="disk:/data"]'));
assert.equal(row, doc.querySelector('tbody tr:last-child'));
assert.equal(gpu.isConnected, false);
run('currentView = {type: "overview", nodeId: null}; searchQuery = "host one"; render();');
assert.equal(doc.querySelectorAll('.node-card').length, 1);
run('myJobsOnlyFilter = true; fixture.organizations[0].clusters[0].nodes[1].jobs = []; fixture.organizations[0].clusters[0].nodes[1].my_jobs_count = 0; render();');
assert.equal(doc.querySelectorAll('.node-card').length, 0);
run('currentView = {type: "detail", nodeId: "missing"}; render();');
assert.match(doc.querySelector('#organizations-container').textContent, /Resource Not Found/);
// Every patch must exactly match freshly generated markup, even after repeated
// transitions between conditional children, duplicate keys and reordered lists.
run(`const originalUpdatePage = updatePage;
updatePage = function(container, html) {
  originalUpdatePage(container, html);
  const expected = document.createElement("template"); expected.innerHTML = html;
  if (container.childNodes.length !== expected.content.childNodes.length ||
      !Array.from(container.childNodes).every((node, i) => node.isEqualNode(expected.content.childNodes[i]))) {
    throw new Error("Patched DOM diverged from desired markup");
  }
};
currentView = {type: "overview", nodeId: null}; myJobsOnlyFilter = false; searchQuery = "";`);
for (let i = 0; i < 100; i++) {
  window.iteration = i;
  run(`const nodes = fixture.organizations[0].clusters[0].nodes;
    nodes.reverse(); nodes[0].status = iteration % 2 ? "OFFLINE" : "ONLINE";
    nodes[0].jobs = iteration % 3 ? [{id: "same", name: "Test", user: "me", state: "RUNNING"}] : [];
    render();`);
}
assert.equal(doc.querySelectorAll('.node-card').length, 2);
assert.equal(doc.querySelectorAll('section.cluster-section').length, 1);
run(`calendarDate = new Date("2026-10-28T12:00:00");
fixture.organizations[0].clusters[0].nodes[0].jobs = [
 {id:"multi", name:"Long running", user:"me", type:"slurm", state:"RUNNING", is_my_job:true, started_at:"2026-10-26T01:00:00Z"},
 {id:"queued", name:"Waiting", user:"other", type:"slurm", state:"PENDING"},
 {id:"complete", name:"Finished", user:"me", type:"kaggle", state:"COMPLETE", started_at:"2026-10-27T01:00:00Z", timing_source:"last run"}
];
fixture.organizations[0].clusters[0].nodes[1].jobs = [...fixture.organizations[0].clusters[0].nodes[0].jobs];
window.location.hash = "#/calendar"; handleRouting();`);
assert.equal(doc.querySelectorAll('.calendar-day').length, 7);
assert.equal(doc.querySelector('.calendar-header h2').textContent, 'Calendar');
assert.equal(doc.querySelector('[data-view="calendar"]').textContent, 'Calendar');
assert.equal(doc.querySelectorAll('[data-key="event:cluster:slurm:multi"]').length, 1);
run(`window.spanDays = Array.from({length:7}, (_, i) => new Date(2026, 9, 26 + i));
window.spanEntry = {job:{state:"RUNNING", started_at:"2026-10-26T16:15:00"}};
window.spanResult = calendarJobSpan(spanEntry, spanDays, new Date(2026, 9, 28, 18));`);
assert.equal(run('spanResult.column'), 1);
assert.equal(run('spanResult.span'), 3);
assert.equal(run('spanResult.before'), false);
assert.equal(run('spanResult.after'), false);
run(`window.crossing = calendarJobSpan({job:{state:"RUNNING", started_at:"2026-10-20T12:00:00"}}, spanDays, new Date(2026, 10, 4));
window.midnight = calendarJobSpan({job:{state:"COMPLETE", started_at:"2026-10-26T12:00:00", ended_at:"2026-10-28T00:00:00"}}, spanDays);
window.point = calendarJobSpan({job:{state:"COMPLETE", started_at:"2026-10-27T12:00:00"}}, spanDays);
window.outside = calendarJobSpan({job:{state:"COMPLETE", started_at:"2026-11-05T12:00:00"}}, spanDays);`);
assert.equal(run('crossing.span'), 7);
assert.equal(run('crossing.before && crossing.after'), true);
assert.equal(run('midnight.span'), 2);
assert.equal(run('point.column'), 2);
assert.equal(run('point.span'), 1);
assert.equal(run('outside'), null);
run(`fixture.organizations[0].clusters[0].nodes[0].jobs[0].ended_at = "2026-10-28T18:00:00"; render();`);
const timelineBar = doc.querySelector('[data-key="event:cluster:slurm:multi"]');
assert.equal(timelineBar.style.gridColumn, '1 / span 3');
assert.equal(doc.querySelectorAll('.calendar-bar').length, 2);
run('render();');
assert.equal(timelineBar, doc.querySelector('[data-key="event:cluster:slurm:multi"]'));
assert.equal(run('calendarJobs().length'), 3);
assert.equal(doc.querySelectorAll('.calendar-undated .calendar-event').length, 1);
assert.match(doc.querySelector('.calendar-undated').textContent, /Waiting/);
assert.equal(doc.querySelectorAll('[data-key="event:cluster:slurm:queued"]').length, 1);
const calendarDay = doc.querySelector('.calendar-day');
run('render();');
assert.equal(calendarDay, doc.querySelector('.calendar-day'));
const oldWeek = doc.querySelector('.calendar-day').dataset.key;
doc.querySelector('[data-calendar-action="next"]').click();
assert.notEqual(oldWeek, doc.querySelector('.calendar-day').dataset.key);
doc.querySelector('[data-calendar-action="previous"]').click();
assert.equal(oldWeek, doc.querySelector('.calendar-day').dataset.key);
run('myJobsOnlyFilter = true; render();');
assert.equal(run('calendarJobs().length'), 1);
run('myJobsOnlyFilter = false; searchQuery = "finished"; render();');
assert.equal(run('calendarJobs().length'), 1);
// Scheduler deadlines extend running bars into the future and stay distinct
// from actual ends. Processes without a deadline never invent one.
run(`searchQuery = "";
fixture.organizations[0].clusters[0].nodes[0].jobs[0].ended_at = null;
fixture.organizations[0].clusters[0].nodes[0].jobs[0].scheduled_end_at = "2026-10-30T18:00:00";
render();
window.scheduledSpan = calendarJobSpan({job:{state:"RUNNING", started_at:"2026-10-26T16:15:00", scheduled_end_at:"2026-10-30T18:00:00"}}, spanDays, new Date(2026, 9, 28, 18));`);
assert.equal(run('scheduledSpan.span'), 5);
assert.match(doc.querySelector('[data-key="event:cluster:slurm:multi"] .calendar-end').textContent, /Scheduled end \(time limit\):/);
assert.match(run('renderCalendarEvent({key:"unknown", nodes:[{id:"one",name:"Host"}],job:{id:"p",name:"test",state:"RUNNING",started_at:"2026-10-26T12:00:00"}})'), /End time unknown/);
assert.match(run('renderCalendarEvent({key:"ended", nodes:[{id:"one",name:"Host"}],job:{id:"p",name:"test",state:"COMPLETE",started_at:"2026-10-26T12:00:00",ended_at:"2026-10-27T18:00:00"}})'), /Ended:/);
assert.equal(doc.querySelector('link[rel="icon"][type="image/svg+xml"]').getAttribute('href'), '/static/favicon.svg?v=2');
// Nine jobs owned by three teammates must not be labeled nine teammates.
run(`window.nineJobs = Array.from({length:9}, (_, index) => ({id:String(index), name:"Job", user:["alice","bob","carol"][index % 3], state:index === 8 ? "PD" : "RUNNING", type:"slurm", time:"1:00", resources:"GPU", gpu_processes:index === 8 ? [] : [{pid:String(100+index), command:"python", memory_used_mb:100, gpu_indices:[index % 8]}]}));
window.nineJobMarkup = renderStandardDetailSections({...fixture.organizations[0].clusters[0].nodes[0], jobs:nineJobs}, [], nineJobs);`);
const nineJobsTemplate = doc.createElement('template');
nineJobsTemplate.innerHTML = run('nineJobMarkup');
assert.match(nineJobsTemplate.content.querySelector('[data-key="jobs"] h3').textContent, /\(9\)/);
assert.equal(nineJobsTemplate.content.querySelector('.teammate-count').textContent, '3 Teammates');
assert.equal(nineJobsTemplate.content.querySelectorAll('tbody tr').length, 9);
assert.equal(nineJobsTemplate.content.querySelector('.job-gpu-devices').textContent, 'GPU #0');
assert.equal(nineJobsTemplate.content.querySelector('tbody tr:last-child .job-gpu-devices').textContent, 'Not assigned (queued)');
assert.equal(run('jobGpuLabel({state:"RUNNING",gpu_processes:[{gpu_indices:[3,0]},{gpu_indices:[3]}]})'), 'GPU #0, GPU #3');
assert.equal(run('jobGpuLabel({state:"RUNNING"})'), 'Device not reported');
assert.equal(run('teammateCount([{user:"Alice"},{user:"alice"},{user:" unknown "},{user:""}])'), 1);
console.log('Frontend checks passed: SSE identity, selection, 100 structural updates, group cards, calendar routing, deduplication, week navigation, continuous multi-day bars, week clipping, midnight boundaries and filters.');
dom.window.close();
