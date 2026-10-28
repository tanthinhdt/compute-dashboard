// Compute Dashboard Frontend - Navigation & Detail Views

let currentData = null;
let eventSource = null;
let myJobsOnlyFilter = false;
let searchQuery = "";
let currentView = { type: "overview", nodeId: null };
let calendarDate = new Date();
let calendarResource = "";
let refreshTimer = null;
let pollIntervalSeconds = 0; // 0 = SSE live

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  handleRouting();
  window.addEventListener("hashchange", handleRouting);
  window.addEventListener("popstate", handleRouting);
  initSSE();
  fetchMetrics();
});

function handleRouting() {
  const hash = window.location.hash || "";
  const match = hash.match(/^#\/node\/([a-zA-Z0-9_-]+)$/);
  if (hash === "#/calendar") {
    currentView = { type: "calendar", nodeId: null };
  } else if (hash === "#/network") {
    currentView = { type: "network", nodeId: null };
  } else if (match) {
    currentView = { type: "detail", nodeId: match[1] };
  } else {
    currentView = { type: "overview", nodeId: null };
  }
  render();
}

function navigateToNode(nodeId) {
  window.location.hash = `#/node/${nodeId}`;
}

function navigateToOverview() {
  window.location.hash = "#/";
}

function setupEventListeners() {
  document.getElementById("organizations-container").addEventListener("click", (event) => {
    const card = event.target.closest(".node-card[data-node-id]");
    if (card) navigateToNode(card.dataset.nodeId);
    const action = event.target.closest("[data-calendar-action]")?.dataset.calendarAction;
    if (action) {
      if (action === "today") calendarDate = new Date();
      else calendarDate.setDate(calendarDate.getDate() + (action === "next" ? 7 : -7));
      render();
    }
  });
  document.getElementById("organizations-container").addEventListener("change", (event) => {
    if (event.target.id === "calendar-date" && event.target.value) {
      calendarDate = new Date(`${event.target.value}T12:00:00`);
      render();
    }
    if (event.target.id === "calendar-resource") {
      calendarResource = event.target.value;
      render();
    }
  });
  const btnRefresh = document.getElementById("btn-refresh");
  if (btnRefresh) {
    btnRefresh.addEventListener("click", manualRefresh);
  }

  const btnMyJobs = document.getElementById("btn-my-jobs");
  if (btnMyJobs) {
    btnMyJobs.addEventListener("click", () => {
      myJobsOnlyFilter = !myJobsOnlyFilter;
      btnMyJobs.classList.toggle("btn-active", myJobsOnlyFilter);
      render();
    });
  }

  const searchInput = document.getElementById("search-input");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      searchQuery = e.target.value.toLowerCase().trim();
      render();
    });
  }

  const refreshSelect = document.getElementById("refresh-select");
  if (refreshSelect) {
    refreshSelect.addEventListener("change", (e) => {
      const val = parseInt(e.target.value, 10);
      setRefreshMode(val);
    });
  }

  const brand = document.querySelector(".brand");
  if (brand) {
    brand.addEventListener("click", navigateToOverview);
  }
}

function setRefreshMode(seconds) {
  pollIntervalSeconds = seconds;
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }

  if (seconds === 0) {
    initSSE();
  } else {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    updateConnectionStatus("polling", `Polling (${seconds}s)`);
    refreshTimer = setInterval(fetchMetrics, seconds * 1000);
  }
}

function initSSE() {
  if (eventSource) {
    eventSource.close();
  }

  updateConnectionStatus("connecting", "Connecting...");

  try {
    eventSource = new EventSource("/api/events");

    eventSource.addEventListener("metrics", (event) => {
      try {
        const data = JSON.parse(event.data);
        currentData = data;
        updateConnectionStatus("live", "Live SSE");
        render();
      } catch (e) {
        console.error("Error parsing SSE metrics:", e);
      }
    });

    eventSource.addEventListener("ping", () => {});

    eventSource.onerror = () => {
      updateConnectionStatus("warning", "Reconnecting...");
      fetchMetrics();
    };
  } catch (err) {
    console.error("Failed to initialize SSE:", err);
    setRefreshMode(10);
  }
}

function updateConnectionStatus(state, label) {
  const dot = document.getElementById("stream-dot");
  const text = document.getElementById("stream-status-text");
  if (!dot || !text) return;

  text.textContent = label;
  if (state === "live") {
    dot.style.background = "#10b981";
    dot.style.boxShadow = "0 0 8px #10b981";
  } else if (state === "polling") {
    dot.style.background = "#38bdf8";
    dot.style.boxShadow = "0 0 8px #38bdf8";
  } else if (state === "connecting" || state === "warning") {
    dot.style.background = "#f59e0b";
    dot.style.boxShadow = "0 0 8px #f59e0b";
  } else {
    dot.style.background = "#ef4444";
    dot.style.boxShadow = "0 0 8px #ef4444";
  }
}

async function fetchMetrics() {
  const refreshIcon = document.getElementById("refresh-icon");
  if (refreshIcon) refreshIcon.classList.add("spin");

  try {
    const res = await fetch("/api/metrics");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    currentData = data;
    render();
  } catch (err) {
    console.error("Failed to fetch metrics:", err);
  } finally {
    if (refreshIcon) refreshIcon.classList.remove("spin");
  }
}

async function manualRefresh() {
  const refreshIcon = document.getElementById("refresh-icon");
  if (refreshIcon) refreshIcon.classList.add("spin");

  try {
    const res = await fetch("/api/refresh", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    currentData = data;
    render();
  } catch (err) {
    console.error("Failed to force refresh:", err);
  } finally {
    if (refreshIcon) refreshIcon.classList.remove("spin");
  }
}

function getProgressColor(pct) {
  if (pct > 85) return "linear-gradient(90deg, #f59e0b, #ef4444)";
  if (pct > 65) return "linear-gradient(90deg, #10b981, #f59e0b)";
  return "linear-gradient(90deg, #06b6d4, #10b981)";
}

function formatBytesGB(mb) {
  if (mb >= 1024 * 1024) {
    return (mb / (1024 * 1024)).toFixed(1) + " TB";
  }
  return (mb / 1024).toFixed(1) + " GB";
}

function findNodeById(nodeId) {
  if (!currentData || !currentData.organizations) return null;
  for (const org of currentData.organizations) {
    for (const cluster of org.clusters) {
      for (const node of cluster.nodes) {
        if (node.id === nodeId) return { node, cluster, org };
      }
    }
  }
  return null;
}

// Reconcile detached markup with the live tree. Stable keys retain cards, rows,
// selection, scroll positions and listeners as metrics and lists change.
function domKey(node) {
  if (node.nodeType !== Node.ELEMENT_NODE) return null;
  for (const attr of ["data-key", "data-node-id"]) {
    if (node.hasAttribute(attr)) return `${attr}:${node.getAttribute(attr)}`;
  }
  return null;
}

function patchChildren(parent, desired) {
  const keyed = new Map();
  for (const child of parent.childNodes) {
    const key = domKey(child);
    if (key !== null) {
      if (!keyed.has(key)) keyed.set(key, []);
      keyed.get(key).push(child);
    }
  }
  const retained = new Set();
  let cursor = parent.firstChild;
  for (const next of Array.from(desired.childNodes)) {
    const key = domKey(next);
    let existing = key !== null ? keyed.get(key)?.shift() : cursor;
    if (existing && (retained.has(existing) || domKey(existing) !== key ||
        existing.nodeType !== next.nodeType || existing.nodeName !== next.nodeName)) existing = null;
    if (!existing) {
      existing = next.cloneNode(true);
      parent.insertBefore(existing, cursor);
    } else {
      if (existing !== cursor) parent.insertBefore(existing, cursor);
      if (existing.nodeType === Node.ELEMENT_NODE) {
        for (const attr of Array.from(existing.attributes)) {
          if (!next.hasAttribute(attr.name)) existing.removeAttribute(attr.name);
        }
        for (const attr of Array.from(next.attributes)) {
          if (existing.getAttribute(attr.name) !== attr.value) existing.setAttribute(attr.name, attr.value);
        }
        patchChildren(existing, next);
      } else if (existing.nodeValue !== next.nodeValue) existing.nodeValue = next.nodeValue;
    }
    retained.add(existing);
    cursor = existing.nextSibling;
  }
  // Remove every obsolete node, including nodes skipped by keyed moves.
  for (const child of Array.from(parent.childNodes)) {
    if (!retained.has(child)) child.remove();
  }
}

function updatePage(container, html) {
  const viewKey = `${currentView.type}:${currentView.nodeId || ""}`;
  if (container.dataset.view !== viewKey) {
    container.innerHTML = html;
    container.dataset.view = viewKey;
    return;
  }
  const template = document.createElement("template");
  template.innerHTML = html;
  patchChildren(container, template.content);
}

// Master Render
function render() {
  if (!currentData) return;

  renderSecurityHeader(currentData);
  for (const link of document.querySelectorAll(".view-tab")) {
    const active = link.dataset.view === currentView.type;
    link.classList.toggle("btn-active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }

  const mainContainer = document.getElementById("organizations-container");
  const ribbon = document.querySelector(".summary-ribbon");
  const toolbar = document.getElementById("search-toolbar");

  if (currentView.type === "detail") {
    // Hide summary ribbon and search toolbar on detail page
    if (ribbon) ribbon.style.display = "none";
    if (toolbar) toolbar.style.display = "none";
    renderDetailPage(currentView.nodeId, mainContainer);
  } else if (currentView.type === "network") {
    if (ribbon) ribbon.style.display = "none";
    if (toolbar) toolbar.style.display = "none";
    renderNetworkPage(mainContainer);
  } else if (currentView.type === "calendar") {
    if (ribbon) ribbon.style.display = "none";
    if (toolbar) toolbar.style.display = "flex";
    renderCalendarPage(mainContainer);
  } else {
    // Show summary ribbon and search toolbar on overview page
    if (ribbon) ribbon.style.display = "grid";
    if (toolbar) toolbar.style.display = "flex";
    renderSummaryRibbon(currentData.summary);
    renderOverviewPage(currentData.organizations, mainContainer);
  }
}

function renderSecurityHeader(data) {
  const clientIpElem = document.getElementById("client-ip-badge");
  if (clientIpElem && data.client_ip) {
    clientIpElem.textContent = data.client_ip;
  }
}

function renderSummaryRibbon(summary) {
  if (!summary) return;

  document.getElementById("sum-online-nodes").textContent = `${summary.online_nodes} / ${summary.total_nodes}`;
  document.getElementById("sum-total-gpus").textContent = summary.total_gpus;
  document.getElementById("sum-cluster-vram").textContent = `${summary.used_vram_gb.toFixed(0)} / ${summary.total_vram_gb.toFixed(0)} GB`;
  document.getElementById("sum-cpu-cores").textContent = summary.total_cpu_cores;
  document.getElementById("sum-my-jobs").textContent = summary.my_running_jobs;
  document.getElementById("sum-kaggle-rem").textContent = `${summary.kaggle_gpu_remaining_hours.toFixed(1)}h`;
}

// ==========================================
// 1. OVERVIEW PAGE
// ==========================================
function renderOverviewPage(orgs, container) {
  if (!container) return;

  let html = "";
  let totalVisibleNodes = 0;

  orgs.forEach((org) => {
    let orgHasMatchingNodes = false;
    let clustersHtml = "";

    org.clusters.forEach((cluster) => {
      const filteredNodes = cluster.nodes.filter((node) => {
        // My Jobs Only filter: only show nodes where you have active jobs
        if (myJobsOnlyFilter && node.my_jobs_count === 0) {
          return false;
        }
        // Search query filter
        if (searchQuery) {
          const matchName = node.name.toLowerCase().includes(searchQuery);
          const matchDesc = node.description.toLowerCase().includes(searchQuery);
          const matchJobs = node.jobs.some(
            (j) =>
              j.name.toLowerCase().includes(searchQuery) ||
              j.user.toLowerCase().includes(searchQuery) ||
              j.id.toLowerCase().includes(searchQuery)
          );
          const matchGPU = node.gpus.some((g) => g.name.toLowerCase().includes(searchQuery));
          if (!matchName && !matchDesc && !matchJobs && !matchGPU) {
            return false;
          }
        }
        return true;
      });

      if (filteredNodes.length > 0) {
        orgHasMatchingNodes = true;
        totalVisibleNodes += filteredNodes.length;
        clustersHtml += `
          <section class="cluster-section" data-key="cluster:${escapeHtml(cluster.id)}">
            <div class="cluster-header">
              <h3>${escapeHtml(cluster.name)}</h3>
              <span class="cluster-desc">${escapeHtml(cluster.description)}</span>
            </div>
            <div class="cards-grid">
              ${filteredNodes.map((node) => renderOverviewCard(node)).join("")}
            </div>
          </section>
        `;
      }
    });

    if (orgHasMatchingNodes) {
      html += `
        <div class="org-section" data-key="org:${escapeHtml(org.id)}">
          <div class="org-header">
            <div class="org-title">
              <h2>${escapeHtml(org.name)}</h2>
              <span class="badge">${escapeHtml(org.description)}</span>
            </div>
          </div>
          ${clustersHtml}
        </div>
      `;
    }
  });

  if (!html) {
    if (myJobsOnlyFilter) {
      html = `
        <div style="text-align: center; padding: 60px 24px; background: rgba(15, 23, 42, 0.45); border-radius: 14px; border: 1px dashed var(--border-color); margin: 20px 0;">
          <div style="font-size: 38px; margin-bottom: 12px;">⭐</div>
          <h3 style="font-size: 18px; font-weight: 600; color: #f1f5f9; margin-bottom: 8px;">No Active Jobs Found</h3>
          <p style="font-size: 14px; color: var(--text-dim); max-width: 520px; margin: 0 auto 20px auto;">
            You currently have no active running jobs across the configured resources.
          </p>
          <button class="btn btn-primary" onclick="document.getElementById('btn-my-jobs').click();">
            Show All Cluster Nodes
          </button>
        </div>
      `;
    } else {
      html = `
        <div style="text-align: center; padding: 50px 20px; color: var(--text-dim);">
          <p style="font-size: 15px; margin-bottom: 8px;">No compute resources matched "${escapeHtml(searchQuery)}".</p>
          <p style="font-size: 13px;">Try adjusting or clearing the search query.</p>
        </div>
      `;
    }
  }

  updatePage(container, html);
}

function renderOverviewCard(node) {
  const isOffline = node.status === "OFFLINE";
  const statusLower = node.status.toLowerCase();

  let icon = "🖥️";
  if (node.type === "gpu") icon = "⚡";
  else if (node.type === "cpu") icon = "🖧";
  else if (node.type === "kaggle") {
    icon = node.id === "kaggle-tpu" ? "🧬" : "☁️";
  }

  const myActiveJobs = node.jobs.filter(
    (j) => j.is_my_job && ["RUNNING", "R", "MIXED", "PD", "PENDING", "QUEUED"].includes(j.state)
  );
  const otherActiveJobs = node.jobs.filter(
    (j) => !j.is_my_job && ["RUNNING", "R", "MIXED", "PD", "PENDING", "QUEUED"].includes(j.state)
  );

  return `
    <div class="node-card ${isOffline ? "offline" : ""}" data-node-id="${escapeHtml(node.id)}">
      <!-- Card Top Header -->
      <div class="card-header">
        <div class="card-title-group">
          <div class="node-avatar">${icon}</div>
          <div class="node-info">
            <h4>
              <span class="node-name">${escapeHtml(node.name)}</span>
              <span class="node-role-pill">${escapeHtml(node.role || node.type)}</span>
            </h4>
            <div class="node-subtitle">${escapeHtml(node.description || node.ip || "")}</div>
          </div>
        </div>
        <div>
          <span class="status-pill ${statusLower}">${escapeHtml(node.status)}</span>
        </div>
      </div>

      <!-- Compact Key Metrics Summary Bar -->
      ${renderCardMetricsBar(node)}

      <!-- Card Footer -->
      <div class="card-footer">
        <div class="jobs-tag ${myActiveJobs.length > 0 ? "my-jobs-active" : ""}">
          ${
            myActiveJobs.length > 0
              ? `⭐ ${myActiveJobs.length} active job${myActiveJobs.length > 1 ? "s" : ""}`
              : otherActiveJobs.length > 0
              ? `👥 ${otherActiveJobs.length} active job${otherActiveJobs.length > 1 ? "s" : ""}`
              : `<span style="color: var(--text-dim);">Idle (0 jobs)</span>`
          }
        </div>
        <div class="view-details-link">
          <span>View Details</span> <span>→</span>
        </div>
      </div>
    </div>
  `;
}

function renderCardMetricsBar(node) {
  if (node.status === "OFFLINE") {
    return `
      <div style="font-size: 12px; color: #f87171; padding: 8px 12px; background: rgba(239, 68, 68, 0.08); border-radius: 6px;">
        Unreachable · SSH connection timed out
      </div>
    `;
  }

  // Kaggle Accelerator Cards
  if (node.type === "kaggle" && node.kaggle_quota) {
    const kq = node.kaggle_quota;
    const isTPU = node.id === "kaggle-tpu";
    const usedHrs = isTPU ? kq.tpu_time_used_hours : kq.gpu_time_used_hours;
    const allowedHrs = isTPU ? kq.tpu_time_allowed_hours : kq.gpu_time_allowed_hours;
    const remHrs = Math.max(allowedHrs - usedHrs, 0);
    const pct = allowedHrs > 0 ? Math.min(Math.round((usedHrs / allowedHrs) * 100), 100) : 0;

    return `
      <div class="compact-metrics-bar">
        <div class="compact-metric-item" style="grid-column: span 2;">
          <div class="compact-metric-label">
            <span>Free Quota</span>
            <span class="compact-metric-val">${remHrs.toFixed(1)}h left (${allowedHrs.toFixed(0)}h)</span>
          </div>
          <div class="progress-track">
            <div class="progress-fill" style="width: ${pct}%; background: ${getProgressColor(pct)};"></div>
          </div>
        </div>
        <div class="compact-metric-item">
          <div class="compact-metric-label">
            <span>Reset</span>
            <span class="compact-metric-val" style="color: #38bdf8;">${escapeHtml(kq.refresh_countdown || "Soon")}</span>
          </div>
        </div>
      </div>
    `;
  }

  // Standard GPU / CPU / Workstation Node
  const cpuPct = Math.min(Math.max(node.cpu_util_pct, 0), 100);
  const memPct = Math.min(Math.max(node.mem_util_pct, 0), 100);
  const hasGpus = node.gpus && node.gpus.length > 0;

  return `
    <div class="compact-metrics-bar">
      <!-- CPU -->
      <div class="compact-metric-item">
        <div class="compact-metric-label">
          <span>CPU</span>
          <span class="compact-metric-val">${cpuPct.toFixed(0)}%</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill" style="width: ${cpuPct}%; background: ${getProgressColor(cpuPct)};"></div>
        </div>
      </div>

      <!-- RAM -->
      <div class="compact-metric-item">
        <div class="compact-metric-label">
          <span>RAM</span>
          <span class="compact-metric-val">${memPct.toFixed(0)}%</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill" style="width: ${memPct}%; background: ${getProgressColor(memPct)};"></div>
        </div>
      </div>

      <!-- GPU / Cores -->
      ${
        hasGpus
          ? `
        <div class="compact-metric-item">
          <div class="compact-metric-label">
            <span>${node.gpus.length} GPUs</span>
            <span class="compact-metric-val">${node.avg_gpu_util_pct.toFixed(0)}% Util</span>
          </div>
          <div class="progress-track">
            <div class="progress-fill" style="width: ${Math.min(node.total_vram_util_pct, 100)}%; background: ${getProgressColor(node.total_vram_util_pct)};"></div>
          </div>
        </div>
      `
          : `
        <div class="compact-metric-item">
          <div class="compact-metric-label">
            <span>Cores</span>
            <span class="compact-metric-val">${node.cpu_count}c</span>
          </div>
          <div class="progress-track">
            <div class="progress-fill" style="width: 100%; background: rgba(255,255,255,0.12);"></div>
          </div>
        </div>
      `
      }
    </div>
  `;
}

// ==========================================
// 2. DETAIL PAGE (PER RESOURCE)
// ==========================================
function renderDetailPage(nodeId, container) {
  const result = findNodeById(nodeId);
  if (!result) {
    updatePage(container, `
      <div style="text-align: center; padding: 60px 20px;">
        <h3>Resource Not Found</h3>
        <p style="color: var(--text-dim); margin-top: 8px;">The resource "${escapeHtml(nodeId)}" could not be located.</p>
        <button class="btn btn-primary" style="margin-top: 16px;" onclick="navigateToOverview()">← Back to Dashboard</button>
      </div>
    `);
    return;
  }

  const { node, cluster, org } = result;
  const isOffline = node.status === "OFFLINE";
  const statusLower = node.status.toLowerCase();

  let icon = "🖥️";
  if (node.type === "gpu") icon = "⚡";
  else if (node.type === "cpu") icon = "🖧";
  else if (node.type === "kaggle") icon = node.id === "kaggle-tpu" ? "🧬" : "☁️";

  const myActiveJobs = node.jobs.filter(
    (j) => j.is_my_job && ["RUNNING", "R", "MIXED", "PD", "PENDING", "QUEUED"].includes(j.state)
  );
  const otherActiveJobs = node.jobs.filter(
    (j) => !j.is_my_job && ["RUNNING", "R", "MIXED", "PD", "PENDING", "QUEUED"].includes(j.state)
  );

  const cpuPct = Math.min(Math.max(node.cpu_util_pct, 0), 100);
  const memPct = Math.min(Math.max(node.mem_util_pct, 0), 100);

  updatePage(container, `
    <div class="detail-view">
      
      <!-- Top Navigation -->
      <div class="detail-nav-bar">
        <button class="btn btn-back" onclick="navigateToOverview()">
          <span>←</span> Back to Dashboard
        </button>
        <div style="display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--text-muted);">
          <span>${escapeHtml(org.name)}</span>
          <span>/</span>
          <span>${escapeHtml(cluster.name)}</span>
          <span>/</span>
          <span style="color: #fff; font-weight: 600;">${escapeHtml(node.name)}</span>
        </div>
      </div>

      <!-- Hero Banner -->
      <div class="node-hero">
        <div class="hero-main">
          <div class="hero-avatar">${icon}</div>
          <div class="hero-titles">
            <h2>
              ${escapeHtml(node.name)}
              <span class="status-pill ${statusLower}">${escapeHtml(node.status)}</span>
            </h2>
            <p>${escapeHtml(node.description || node.role || "")}</p>
          </div>
        </div>

        <div class="hero-meta-pills">
          <div class="meta-pill">🏷️ ${escapeHtml(node.role || node.type)}</div>
          ${node.ip ? `<div class="meta-pill">🌐 ${escapeHtml(node.ip)}</div>` : ""}
          ${node.uptime ? `<div class="meta-pill">⏱️ ${escapeHtml(node.uptime)}</div>` : ""}
          <div class="meta-pill">🔄 Updated: ${escapeHtml(node.last_updated || "Live")}</div>
        </div>
      </div>

      <!-- Key Stat Cards Grid -->
      <div class="detail-stats-grid">
        <!-- CPU Stat Card -->
        <div class="detail-stat-card">
          <div class="label">CPU Utilization</div>
          <div class="value">${cpuPct.toFixed(1)}%</div>
          <div class="progress-track" style="margin: 4px 0;">
            <div class="progress-fill" style="width: ${cpuPct}%; background: ${getProgressColor(cpuPct)};"></div>
          </div>
          <div class="sub">
            <span>${node.cpu_count} Logical Cores</span> · <span>Load: ${node.cpu_load_1m.toFixed(1)}</span>
          </div>
        </div>

        <!-- RAM Stat Card -->
        <div class="detail-stat-card">
          <div class="label">Memory (RAM)</div>
          <div class="value">${memPct.toFixed(1)}%</div>
          <div class="progress-track" style="margin: 4px 0;">
            <div class="progress-fill" style="width: ${memPct}%; background: ${getProgressColor(memPct)};"></div>
          </div>
          <div class="sub">
            <span>${formatBytesGB(node.mem_used_mb)} used</span> of <span>${formatBytesGB(node.mem_total_mb)}</span>
          </div>
        </div>

        <!-- Accelerators Stat Card -->
        <div class="detail-stat-card">
          <div class="label">${node.type === "kaggle" ? "Cloud Accelerator" : "GPU Accelerators"}</div>
          <div class="value">${node.type === "kaggle" ? (node.id === "kaggle-tpu" ? "TPU v3-8" : "2x T4 / P100") : `${node.gpus.length} GPUs`}</div>
          <div class="sub" style="margin-top: 6px;">
            ${node.type === "kaggle" ? `Remaining: ${node.kaggle_quota ? (node.id === "kaggle-tpu" ? node.kaggle_quota.tpu_time_allowed_hours - node.kaggle_quota.tpu_time_used_hours : node.kaggle_quota.gpu_time_remaining_hours).toFixed(1) : 0}h` : `Total VRAM: ${formatBytesGB(node.total_vram_total_mb)} (${node.avg_gpu_util_pct.toFixed(0)}% Avg Util)`}
          </div>
        </div>

        <!-- Active Jobs Stat Card -->
        <div class="detail-stat-card">
          <div class="label">Active Jobs</div>
          <div class="value" style="color: ${myActiveJobs.length > 0 ? "#fbbf24" : "#fff"};">
            ${myActiveJobs.length + otherActiveJobs.length} Jobs
          </div>
          <div class="sub" style="margin-top: 6px;">
            <span>${myActiveJobs.length} of my jobs</span> · <span>${otherActiveJobs.length} jobs from ${teammateCount(otherActiveJobs)} teammates</span>
          </div>
        </div>
      </div>

      <!-- In-Depth Metrics Sections -->
      ${node.type === "kaggle" ? renderKaggleDetailSection(node) : renderStandardDetailSections(node, myActiveJobs, otherActiveJobs)}

    </div>
  `);
}

function teammateCount(jobs) {
  return new Set(jobs.map((job) => (job.user || "").trim().toLowerCase())
    .filter((user) => user && user !== "unknown")).size;
}

function jobGpuLabel(job) {
  const indices = [...new Set((job.gpu_processes || []).flatMap((process) => process.gpu_indices || []))].sort((a, b) => a - b);
  if (indices.length) return indices.map((index) => `GPU #${index}`).join(", ");
  if (["PD", "PENDING", "QUEUED"].includes(job.state)) return "Not assigned (queued)";
  return "Device not reported";
}

function renderStandardDetailSections(node, myActiveJobs, otherActiveJobs) {
  const showGpuDevices = node.type === "gpu" || node.type === "workstation" || node.gpus?.length > 0;
  return `
    <!-- 1. GPU Accelerators Section -->
    ${
      node.gpus && node.gpus.length > 0
        ? `
      <div class="detail-section" data-key="gpus">
        <div class="section-header">
          <h3>⚡ Installed GPU Accelerators (${node.gpus.length})</h3>
          <span style="font-size: 13px; color: var(--text-dim);">${formatBytesGB(node.total_vram_used_mb)} / ${formatBytesGB(node.total_vram_total_mb)} Total VRAM</span>
        </div>
        <div class="detail-gpus-grid">
          ${node.gpus.map((gpu) => {
            const vramPct = Math.min(Math.max(gpu.memory_util_pct, 0), 100);
            const utilPct = Math.min(Math.max(gpu.utilization_gpu, 0), 100);
            const isBusy = utilPct > 10;
            return `
              <div class="gpu-card" data-key="gpu:${gpu.index}">
                <div class="gpu-card-top">
                  <div class="gpu-card-name">GPU #${gpu.index}: ${escapeHtml(gpu.name)}</div>
                  <span class="gpu-util-tag ${isBusy ? "active" : ""}">${utilPct.toFixed(0)}% Compute</span>
                </div>
                <div>
                  <div style="display: flex; justify-content: space-between; font-size: 11.5px; color: var(--text-muted); margin-bottom: 4px;">
                    <span>VRAM Usage</span>
                    <span style="font-family: var(--font-mono); color: #fff;">${formatBytesGB(gpu.memory_used_mb)} / ${formatBytesGB(gpu.memory_total_mb)} (${vramPct.toFixed(0)}%)</span>
                  </div>
                  <div class="progress-track" style="height: 6px;">
                    <div class="progress-fill" style="width: ${vramPct}%; background: ${getProgressColor(vramPct)};"></div>
                  </div>
                </div>
                <div class="gpu-card-details">
                  <span>🌡️ Temp: ${gpu.temperature_c ? `${gpu.temperature_c}°C` : "N/A"}</span>
                  <span>⚡ Power: ${gpu.power_draw_w ? `${gpu.power_draw_w.toFixed(0)}W` : "N/A"}</span>
                  <span>💾 Free: ${formatBytesGB(gpu.memory_free_mb)}</span>
                </div>
              </div>
            `;
          }).join("")}
        </div>
      </div>
    `
        : ""
    }

    <!-- 2. CPU & Memory Details -->
    <div class="detail-section" data-key="host">
      <div class="section-header">
        <h3>🖧 Host Compute & Memory Subsystem</h3>
        <span style="font-size: 13px; color: var(--text-dim);">${node.cpu_count} Cores · ${formatBytesGB(node.mem_total_mb)} RAM</span>
      </div>
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px;">
        <div style="background: rgba(0,0,0,0.25); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px 18px;">
          <div style="font-size: 12px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); margin-bottom: 8px;">Load Average</div>
          <div style="display: flex; justify-content: space-between; font-size: 13px;">
            <span>1-minute load: <strong>${node.cpu_load_1m.toFixed(2)}</strong></span>
            <span>5-minute load: <strong>${node.cpu_load_5m.toFixed(2)}</strong></span>
            <span>15-minute load: <strong>${node.cpu_load_15m.toFixed(2)}</strong></span>
          </div>
        </div>
        <div style="background: rgba(0,0,0,0.25); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px 18px;">
          <div style="font-size: 12px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); margin-bottom: 8px;">Memory Breakdown</div>
          <div style="display: flex; justify-content: space-between; font-size: 13px;">
            <span>Used: <strong>${formatBytesGB(node.mem_used_mb)}</strong></span>
            <span>Available: <strong>${formatBytesGB(node.mem_avail_mb)}</strong></span>
            <span>Total: <strong>${formatBytesGB(node.mem_total_mb)}</strong></span>
          </div>
        </div>
      </div>
    </div>

    <div class="detail-section" data-key="disks">
      <div class="section-header"><h3>💾 Disk Storage</h3></div>
      <div class="disk-grid">
        ${(node.disks || []).length ? node.disks.map((disk) => {
          const pct = Math.min(Math.max(disk.usage_pct, 0), 100);
          return `<div class="disk-card" data-key="disk:${escapeHtml(disk.mountpoint)}">
            <div class="disk-heading"><strong>${escapeHtml(disk.mountpoint)}</strong><span>${pct.toFixed(1)}%</span></div>
            <div class="disk-meta">${escapeHtml(disk.device)} · ${escapeHtml(disk.fstype)}</div>
            <div class="progress-track"><div class="progress-fill" style="width: ${pct}%; background: ${getProgressColor(pct)};"></div></div>
            <div class="disk-meta">${disk.used_gb.toFixed(1)} / ${disk.total_gb.toFixed(1)} GB used · ${disk.free_gb.toFixed(1)} GB available</div>
          </div>`;
        }).join("") : `<p class="disk-meta">Disk usage unavailable.</p>`}
      </div>
    </div>

    <!-- 3. Active Running Jobs Section -->
    <div class="detail-section" data-key="jobs">
      <div class="section-header">
        <h3>📋 Jobs on this Resource (${node.jobs.length})</h3>
        <div style="display: flex; gap: 8px;">
          ${myActiveJobs.length > 0 ? `<span class="jobs-tag my-jobs-active">⭐ ${myActiveJobs.length} Mine</span>` : ""}
          <span class="jobs-tag teammate-count">${teammateCount(otherActiveJobs)} Teammates</span>
        </div>
      </div>

      ${
        node.jobs.length === 0
          ? `
        <div style="text-align: center; padding: 32px 20px; color: var(--text-dim); font-size: 14px;">
          No active compute jobs currently running on this node.
        </div>
      `
          : `
        <div class="jobs-table-container">
          <table class="jobs-table">
            <thead>
              <tr>
                <th>Job ID</th>
                <th>Name</th>
                <th>User</th>
                <th>State</th>
                <th>Runtime</th>
                ${showGpuDevices ? "<th>GPU Devices</th>" : ""}
                <th>Resource Allocation</th>
                <th>Details / Command</th>
              </tr>
            </thead>
            <tbody>
              ${node.jobs.map((job) => `
                <tr data-key="job:${escapeHtml(job.type)}:${escapeHtml(job.id)}" class="${job.is_my_job ? "my-job-row" : ""}">
                  <td style="font-family: var(--font-mono); font-weight: 600;">
                    ${job.is_my_job ? "⭐ " : ""}${escapeHtml(job.id)}
                  </td>
                  <td style="font-weight: 500; color: #fff;">${escapeHtml(job.name)}</td>
                  <td>
                    <span class="job-user-badge ${job.is_my_job ? "my-badge" : ""}">
                      ${escapeHtml(job.user)}
                    </span>
                  </td>
                  <td>
                    <span class="status-pill ${job.state === "RUNNING" ? "online" : "mixed"}">
                      ${escapeHtml(job.state)}
                    </span>
                  </td>
                  <td style="font-family: var(--font-mono); color: var(--text-muted);">${escapeHtml(job.time)}</td>
                  ${showGpuDevices ? `<td class="job-gpu-devices">${escapeHtml(jobGpuLabel(job))}</td>` : ""}
                  <td>${escapeHtml(job.resources)}</td>
                  <td class="job-details-cell">
                    <div>${escapeHtml(job.command || job.nodes || "")}</div>
                    ${job.type === "slurm" && job.gpu_processes?.length ? `<div class="job-process-list">
                      ${job.gpu_processes.map((process) => `<div data-key="process:${escapeHtml(process.pid)}" title="${escapeHtml(process.command)}">GPU process PID ${escapeHtml(process.pid)} · ${escapeHtml(process.command.split("/").pop())} · ${process.memory_used_mb.toFixed(0)} MiB${process.gpu_indices?.length ? ` · ${process.gpu_indices.map((index) => `GPU #${index}`).join(", ")}` : ""}</div>`).join("")}
                    </div>` : ""}
                  </td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `
      }
    </div>
  `;
}

function renderKaggleDetailSection(node) {
  const kq = node.kaggle_quota;
  if (!kq) {
    return `<div class="detail-section"><p>No quota information found.</p></div>`;
  }

  const isTPU = node.id === "kaggle-tpu";
  const usedHrs = isTPU ? kq.tpu_time_used_hours : kq.gpu_time_used_hours;
  const allowedHrs = isTPU ? kq.tpu_time_allowed_hours : kq.gpu_time_allowed_hours;
  const remHrs = Math.max(allowedHrs - usedHrs, 0);
  const pct = allowedHrs > 0 ? Math.min(Math.round((usedHrs / allowedHrs) * 100), 100) : 0;

  return `
    <!-- Kaggle Quota Progress -->
    <div class="detail-section">
      <div class="section-header">
        <h3>☁️ Free Accelerator Quota (${isTPU ? "Google Cloud TPU v3-8" : "2x NVIDIA T4 / P100"})</h3>
        <span class="quota-countdown">⏳ Quota resets in ${escapeHtml(kq.refresh_countdown || "Soon")}</span>
      </div>

      <div style="background: rgba(0,0,0,0.25); border: 1px solid var(--border-color); border-radius: 10px; padding: 20px;">
        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px;">
          <div>
            <span style="font-size: 28px; font-weight: 700; font-family: var(--font-mono); color: #38bdf8;">${remHrs.toFixed(1)} Hours</span>
            <span style="font-size: 14px; color: var(--text-muted); margin-left: 8px;">remaining of ${allowedHrs.toFixed(0)} hours weekly limit</span>
          </div>
          <div style="font-size: 14px; font-family: var(--font-mono); color: var(--text-dim);">${usedHrs.toFixed(1)}h consumed (${pct}%)</div>
        </div>
        <div class="progress-track" style="height: 10px;">
          <div class="progress-fill" style="width: ${pct}%; background: ${getProgressColor(pct)};"></div>
        </div>
      </div>
    </div>

    <!-- Kaggle Notebook Runs -->
    <div class="detail-section">
      <div class="section-header">
        <h3>📓 Notebook Kernels (@${escapeHtml(kq.username)})</h3>
        <span style="font-size: 13px; color: var(--text-dim);">${node.jobs.length} Notebooks</span>
      </div>

      ${
        node.jobs.length === 0
          ? `<p style="color: var(--text-dim);">No recent kernels recorded.</p>`
          : `
        <div class="jobs-table-container">
          <table class="jobs-table">
            <thead>
              <tr>
                <th>Kernel Reference</th>
                <th>Title</th>
                <th>Last Run</th>
                <th>Status</th>
                <th>Direct Link</th>
              </tr>
            </thead>
            <tbody>
              ${node.jobs.map((j) => `
                <tr data-key="job:${escapeHtml(j.id)}">
                  <td style="font-family: var(--font-mono); font-weight: 600; color: #fff;">${escapeHtml(j.id)}</td>
                  <td>${escapeHtml(j.name)}</td>
                  <td style="font-family: var(--font-mono); color: var(--text-muted);">${escapeHtml(j.time)}</td>
                  <td>
                    <span class="status-pill ${j.state === "RUNNING" ? "online" : "idle"}">${escapeHtml(j.state)}</span>
                  </td>
                  <td>
                    ${j.url ? `<a href="${j.url}" target="_blank" style="color: #38bdf8; text-decoration: none; font-weight: 500;">Open on Kaggle ↗</a>` : "-"}
                  </td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `
      }
    </div>
  `;
}

// Calendar shows the jobs currently returned by the probes; it does not infer
// future reservations or completion times from elapsed runtime.
function calendarDayKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function calendarJobs() {
  const events = new Map();
  for (const org of currentData.organizations) {
    for (const cluster of org.clusters) {
      for (const node of cluster.nodes) {
        for (const job of node.jobs) {
          const scope = job.type === "kaggle" ? "kaggle" : job.type === "slurm" ? cluster.id : node.id;
          const key = `${scope}:${job.type}:${job.id}`;
          if (!events.has(key)) events.set(key, {key, job, nodes: [], cluster: cluster.name});
          const entry = events.get(key);
          if (!entry.nodes.some((n) => n.id === node.id)) entry.nodes.push(node);
        }
      }
    }
  }
  return Array.from(events.values()).filter(({job, nodes, cluster}) => {
    if (myJobsOnlyFilter && !job.is_my_job) return false;
    if (calendarResource && !nodes.some((node) => node.id === calendarResource)) return false;
    const text = [job.id, job.name, job.user, job.state, cluster, ...nodes.map((n) => n.name)].join(" ").toLowerCase();
    return !searchQuery || text.includes(searchQuery);
  }).sort((a, b) => (a.job.started_at || "").localeCompare(b.job.started_at || "") || a.key.localeCompare(b.key));
}

// One lane per job, with one bar spanning every intersected calendar day.
function calendarJobSpan(entry, days, now = new Date()) {
  const start = new Date(entry.job.started_at || "");
  if (!Number.isFinite(start.getTime())) return null;
  const running = ["RUNNING", "R", "MIXED"].includes(entry.job.state);
  const reportedEnd = new Date(entry.job.ended_at || "");
  const scheduledEnd = new Date(entry.job.scheduled_end_at || "");
  const expectedEnd = Number.isFinite(scheduledEnd.getTime()) ? new Date(Math.max(scheduledEnd.getTime(), now.getTime())) : now;
  const end = Number.isFinite(reportedEnd.getTime()) ? reportedEnd : running ? expectedEnd : start;
  const last = new Date(Math.max(start.getTime(), end.getTime()));
  const columns = [];
  days.forEach((day, index) => {
    const next = new Date(day); next.setDate(next.getDate() + 1);
    // A finished interval ending exactly at midnight excludes the following day.
    if (start < next && (last > day || start.getTime() === last.getTime() && calendarDayKey(start) === calendarDayKey(day))) {
      columns.push(index + 1);
    }
  });
  if (!columns.length) return null;
  const weekEnd = new Date(days[6]); weekEnd.setDate(weekEnd.getDate() + 1);
  return {column: columns[0], span: columns.length, before: start < days[0], after: last > weekEnd};
}

function renderCalendarEvent(entry, placement = null) {
  const {job, nodes, key} = entry;
  const start = job.started_at ? new Date(job.started_at) : null;
  const running = ["RUNNING", "R", "MIXED"].includes(job.state);
  const formatTime = (date) => date.toLocaleString(undefined, {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});
  const end = job.ended_at ? new Date(job.ended_at) : null;
  const scheduledEnd = job.scheduled_end_at ? new Date(job.scheduled_end_at) : null;
  const endLabel = end && Number.isFinite(end.getTime()) ? `Ended: ${formatTime(end)}`
    : scheduledEnd && Number.isFinite(scheduledEnd.getTime()) ? `Scheduled end (time limit): ${formatTime(scheduledEnd)}`
    : running ? "End time unknown · running" : "End time unavailable";
  const timeLabel = start && Number.isFinite(start.getTime())
    ? `${formatTime(start)}${end && Number.isFinite(end.getTime()) ? " → " + formatTime(end) : running ? " → running" : ""}`
    : "Start time unavailable";
  const resource = job.type === "kaggle" ? "Kaggle · accelerator unreported" : nodes.map((n) => n.name).join(", ");
  return `<article class="calendar-event ${placement ? "calendar-bar" : ""} ${job.is_my_job ? "owned" : ""}" data-key="event:${escapeHtml(key)}"${placement ? ` style="grid-column: ${placement.column} / span ${placement.span};"` : ""}>
    <div class="calendar-event-top"><strong>${escapeHtml(job.name || job.id)}</strong><span class="status-pill ${running ? "online" : "mixed"}">${escapeHtml(job.state)}</span>${job.is_my_job ? '<span title="My job">⭐</span>' : ""}</div>
    <span class="calendar-time">${escapeHtml(timeLabel)}</span>
    <span class="calendar-end">${escapeHtml(endLabel)}</span>
    <span class="calendar-meta">${escapeHtml(job.user)} · ${escapeHtml(job.id)} · ${escapeHtml(resource)}</span>
    ${job.timing_source ? `<span class="calendar-meta">${escapeHtml(job.timing_source)}</span>` : ""}
    ${placement?.before || placement?.after ? `<span class="calendar-continuation">${placement.before ? "← Started before this week" : ""}${placement.before && placement.after ? " · " : ""}${placement.after ? "Continues into next week →" : ""}</span>` : ""}
    <a href="#/node/${encodeURIComponent(nodes[0].id)}">View resource →</a>
  </article>`;
}

function renderCalendarPage(container) {
  const week = new Date(calendarDate);
  week.setHours(0, 0, 0, 0);
  week.setDate(week.getDate() - (week.getDay() + 6) % 7);
  const days = Array.from({length: 7}, (_, index) => {
    const date = new Date(week); date.setDate(date.getDate() + index); return date;
  });
  const entries = calendarJobs();
  const undated = entries.filter(({job}) => !job.started_at || !Number.isFinite(new Date(job.started_at).getTime()));
  const timeline = entries.map((entry) => ({entry, placement: calendarJobSpan(entry, days)})).filter(({placement}) => placement);
  const today = calendarDayKey(new Date());
  const nodes = currentData.organizations.flatMap((org) => org.clusters.flatMap((cluster) => cluster.nodes));
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  updatePage(container, `<section class="calendar-view">
    <div class="calendar-header">
      <div><h2>Calendar</h2><p>All resources · ${escapeHtml(zone)} · ${entries.length} jobs in current snapshot</p></div>
      <div class="calendar-controls">
        <button class="btn" data-calendar-action="previous" aria-label="Previous week">←</button>
        <button class="btn" data-calendar-action="today">Today</button>
        <button class="btn" data-calendar-action="next" aria-label="Next week">→</button>
        <label>Date <input id="calendar-date" class="select-input" type="date" value="${calendarDayKey(calendarDate)}"></label>
        <label>Resource <select id="calendar-resource" class="select-input"><option value="">All resources</option>${nodes.map((node) => `<option value="${escapeHtml(node.id)}" ${calendarResource === node.id ? "selected" : ""}>${escapeHtml(node.name)}</option>`).join("")}</select></label>
      </div>
    </div>
    <p class="calendar-note">${week.toLocaleDateString(undefined, {month: "long", day: "numeric", year: "numeric"})} – ${days[6].toLocaleDateString(undefined, {month: "long", day: "numeric", year: "numeric"})}. SLURM scheduled ends reflect time limits; jobs may finish earlier. Running jobs without a deadline extend through today. Unknown end times are labeled. Completed jobs appear only when returned by a probe.</p>
    <div class="calendar-scroll" data-key="week-scroll"><div class="calendar-timeline">
      <div class="calendar-week">
        ${days.map((day, index) => `<div class="calendar-day ${calendarDayKey(day) === today ? "is-today" : ""}" data-key="day:${calendarDayKey(day)}">
          <h3>${day.toLocaleDateString(undefined, {weekday: "short", month: "short", day: "numeric"})}<span>${timeline.filter(({placement}) => index + 1 >= placement.column && index + 1 < placement.column + placement.span).length}</span></h3>
        </div>`).join("")}
      </div>
      <div class="calendar-lanes">
        ${timeline.length ? timeline.map(({entry, placement}) => `<div class="calendar-timeline-row" data-key="lane:${escapeHtml(entry.key)}">${renderCalendarEvent(entry, placement)}</div>`).join("") : '<p class="calendar-empty calendar-week-empty">No dated jobs this week.</p>'}
      </div>
    </div></div>
    <section class="detail-section" data-key="undated-jobs"><div class="section-header"><h3>Queued / time unavailable (${undated.length})</h3></div>
      <div class="calendar-undated">${undated.length ? undated.map((entry) => renderCalendarEvent(entry)).join("") : '<p class="calendar-empty">All jobs have a known date.</p>'}</div>
    </section>
    ${!entries.length ? '<p class="calendar-empty">No jobs match the current filters.</p>' : ""}
  </section>`);
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderNetworkPage(container) {
  const network = currentData.network || {};
  if (!network.enabled) {
    updatePage(container, `<section class="detail-section"><h2>Network</h2><p class="network-note">Network monitoring is disabled. Configure probe sources and destinations to monitor links between your resources.</p></section>`);
    return;
  }
  const sources = network.sources || [];
  const targets = network.targets || [];
  const links = network.links || [];
  const byPair = new Map(links.map((link) => [`${link.source_id}:${link.target_id}`, link]));
  const labels = {reachable: "Reachable", degraded: "Partial replies", no_response: "No reply", source_unavailable: "Source unavailable", probe_error: "Probe unavailable"};
  const healthy = links.filter((link) => link.status === "reachable").length;
  const noReply = links.filter((link) => link.status === "no_response" || link.status === "degraded").length;
  const unknown = links.length - healthy - noReply;
  const number = (value, digits = 1) => Number.isFinite(value) ? value.toFixed(digits) : "—";
  const sampled = network.checked_at ? new Date(network.checked_at).toLocaleString() : "Waiting for first sample";
  const issues = links.filter((link) => link.status !== "reachable");
  const sourceNames = new Map(sources.map((source) => [source.id, source.name]));
  const targetNames = new Map(targets.map((target) => [target.id, target.name]));
  updatePage(container, `<section class="network-view">
    <div class="calendar-header"><div><h2>Network</h2><p class="network-note">Directional connectivity between resources</p></div>
      <span class="status-pill ${network.stale ? "mixed" : "online"}">${network.stale ? "Waiting / stale" : "Live observations"}</span></div>
    <div class="detail-stats-grid">
      <div class="detail-stat-card"><div class="label">Reachable links</div><div class="value">${healthy} / ${links.length}</div></div>
      <div class="detail-stat-card"><div class="label">No / partial replies</div><div class="value">${noReply}</div></div>
      <div class="detail-stat-card"><div class="label">Unmeasured links</div><div class="value">${unknown}</div></div>
    </div>
    <p class="network-note">Last sample: ${escapeHtml(sampled)} · every ${number(network.interval_seconds, 0)}s · ${number(network.attempts, 0)} attempts per link${network.checking ? " · Checking now…" : ""}${network.stale ? " · These results are not current." : ""}</p>
    <p class="network-note">Rows are probe sources; columns are destinations. ICMP shows round-trip latency and packet loss. TCP shows connection latency and failed connections. No reply can mean routing or firewall restrictions; it does not prove the node is offline. These checks do not measure bandwidth.</p>
    <div class="detail-section network-matrix-section" data-key="network-matrix"><div class="jobs-table-container"><table class="jobs-table network-matrix">
      <thead><tr><th scope="col">From ↓ / To →</th>${targets.map((target) => `<th scope="col">${escapeHtml(target.name)}<span class="network-method">${target.mode === "tcp" ? "TCP" : "ICMP"}</span></th>`).join("")}</tr></thead>
      <tbody>${sources.map((source) => `<tr data-key="source:${escapeHtml(source.id)}"><th scope="row">${escapeHtml(source.name)}</th>${targets.map((target) => {
        if (source.id === target.id) return '<td class="network-self">Self</td>';
        const link = byPair.get(`${source.id}:${target.id}`);
        if (!link) return '<td><span class="network-note">Pending</span></td>';
        const color = link.status === "reachable" ? "good" : ["degraded", "no_response"].includes(link.status) ? "warning" : "unknown";
        const lossLabel = link.mode === "tcp" ? "failed" : "loss";
        return `<td><div class="network-cell ${color}" title="${escapeHtml(link.error || labels[link.status] || "Unknown")}"><strong>${Number.isFinite(link.latency_ms) ? `${number(link.latency_ms)} ms` : escapeHtml(labels[link.status] || "Unknown")}</strong><span>${Number.isFinite(link.loss_pct) ? `${number(link.loss_pct)}% ${lossLabel}` : "No measurement"}</span></div></td>`;
      }).join("")}</tr>`).join("")}</tbody>
    </table></div></div>
    ${!sources.length || !targets.length ? '<p class="network-note">Add at least one source and one destination to monitor connectivity.</p>' : ""}
    <section class="detail-section" data-key="network-issues"><div class="section-header"><h3>Links to check (${issues.length})</h3></div>
      ${issues.length ? `<div class="network-issues">${issues.map((link) => `<div class="network-issue" data-key="issue:${escapeHtml(link.source_id)}:${escapeHtml(link.target_id)}"><strong>${escapeHtml(sourceNames.get(link.source_id) || link.source_id)} → ${escapeHtml(targetNames.get(link.target_id) || link.target_id)}</strong><span>${escapeHtml(labels[link.status] || "Unknown")} · ${escapeHtml(link.error || (link.mode === "tcp" ? "TCP connection unsuccessful" : "ICMP replies incomplete or blocked"))}</span></div>`).join("")}</div>` : '<p class="network-note">No issues in the current sample.</p>'}
    </section>
  </section>`);
}
