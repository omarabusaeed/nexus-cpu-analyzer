/**
 * NEXUS PRO - Real-Time Performance Monitor & Hardware Digital Twin
 * High-Speed Vanilla JS Telemetry Engine
 */

let refreshIntervalMs = 1000;
let pollTimer = null;
let activeTab = 'dashboard';
let charts = {};
let pendingKillPid = null;
let pendingKillName = '';
let pendingKillType = 'process';
let soundAlertsEnabled = true;
let warnThreshold = 75;
let critThreshold = 90;
let knownAlertIds = new Set();

// ─── INITIALIZATION ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  initCharts();
  setupProcessControls();
  setupCountermeasureControls();
  setupSettingsForm();
  setupAlertControls();
  
  // Initial immediate fetch
  fetchMetrics();
  fetchCountermeasures();
  fetchHardwareTwin();
  fetchProcesses();
  fetchDisks();
  fetchAlerts();
  fetchSystemInfo();

  // Start polling
  startPolling();

  // Responsive chart resize listener
  window.addEventListener('resize', () => {
    Object.values(charts).forEach(c => {
      if (c && typeof c.resize === 'function') c.resize();
    });
  });
});

// ─── INSTANT TAB SWITCHING ───────────────────────────────────
function setupTabs() {
  const tabButtons = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');

  tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-tab');
      if (!targetId || targetId === activeTab) return;

      tabButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      tabContents.forEach(content => {
        if (content.id === `tab-${targetId}`) {
          content.classList.add('active');
        } else {
          content.classList.remove('active');
        }
      });

      activeTab = targetId;

      // Handle resize and immediate data loading on tab switch
      if (activeTab === 'dashboard') {
        if (charts.telemetry) charts.telemetry.resize();
        if (charts.network) charts.network.resize();
      } else if (activeTab === 'countermeasures') {
        fetchCountermeasures();
      } else if (activeTab === 'hardware-twin') {
        fetchHardwareTwin();
      } else if (activeTab === 'cores') {
        if (charts.coresBar) charts.coresBar.resize();
      } else if (activeTab === 'processes') {
        fetchProcesses();
      } else if (activeTab === 'memory') {
        fetchDisks();
      } else if (activeTab === 'alerts') {
        fetchAlerts();
      } else if (activeTab === 'history') {
        fetchAnomalies();
      } else if (activeTab === 'settings') {
        fetchSystemInfo();
      }
    });
  });

  // Emergency banner direct action
  const bannerBtn = document.getElementById('banner-action-btn');
  if (bannerBtn) {
    bannerBtn.addEventListener('click', () => {
      const cmTabBtn = document.querySelector('.tab-btn[data-tab="countermeasures"]');
      if (cmTabBtn) cmTabBtn.click();
    });
  }
}

// ─── POLLING LOOP ────────────────────────────────────────────
function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => {
    fetchMetrics();
    
    // Always check countermeasures to update banner
    fetchCountermeasures();

    if (activeTab === 'hardware-twin') {
      fetchHardwareTwin();
    } else if (activeTab === 'processes') {
      fetchProcesses();
    } else if (activeTab === 'alerts') {
      fetchAlerts();
    }
  }, refreshIntervalMs);
}

// ─── CHARTS SETUP (CHART.JS) ─────────────────────────────────
function initCharts() {
  const chartFont = { family: "'Plus Jakarta Sans', sans-serif", size: 10 };
  const gridStyle = { color: 'rgba(255, 255, 255, 0.04)', drawBorder: false };

  // 1. CPU & RAM Telemetry Chart
  const ctxTelem = document.getElementById('chart-telemetry');
  if (ctxTelem) {
    charts.telemetry = new Chart(ctxTelem, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'CPU %',
            data: [],
            borderColor: '#00f2fe',
            backgroundColor: 'rgba(0, 242, 254, 0.08)',
            borderWidth: 2,
            tension: 0.35,
            fill: true,
            pointRadius: 0
          },
          {
            label: 'RAM %',
            data: [],
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.04)',
            borderWidth: 2,
            borderDash: [4, 4],
            tension: 0.35,
            fill: true,
            pointRadius: 0
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { intersect: false, mode: 'index' },
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: gridStyle, ticks: { ...chartFont, color: '#4b586e', maxTicksLimit: 10 } },
          y: { grid: gridStyle, ticks: { ...chartFont, color: '#4b586e', callback: v => v + '%' }, min: 0, max: 100 }
        }
      }
    });
  }

  // 2. Network Chart
  const ctxNet = document.getElementById('chart-network');
  if (ctxNet) {
    charts.network = new Chart(ctxNet, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Upload (KB/s)',
            data: [],
            borderColor: '#38bdf8',
            backgroundColor: 'rgba(56, 189, 248, 0.08)',
            borderWidth: 2,
            tension: 0.3,
            fill: true,
            pointRadius: 0
          },
          {
            label: 'Download (KB/s)',
            data: [],
            borderColor: '#a855f7',
            backgroundColor: 'rgba(168, 85, 247, 0.08)',
            borderWidth: 2,
            tension: 0.3,
            fill: true,
            pointRadius: 0
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { intersect: false, mode: 'index' },
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: gridStyle, ticks: { ...chartFont, color: '#4b586e', maxTicksLimit: 8 } },
          y: { grid: gridStyle, ticks: { ...chartFont, color: '#4b586e', callback: v => (v / 1024).toFixed(1) + ' MB' } }
        }
      }
    });
  }

  // 3. Per-Core Bar Chart
  const ctxCores = document.getElementById('chart-cores-bar');
  if (ctxCores) {
    charts.coresBar = new Chart(ctxCores, {
      type: 'bar',
      data: {
        labels: [],
        datasets: [{
          data: [],
          backgroundColor: '#00f2fe',
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false }, ticks: { ...chartFont, color: '#8494ab' } },
          y: { grid: gridStyle, ticks: { ...chartFont, color: '#4b586e', callback: v => v + '%' }, min: 0, max: 100 }
        }
      }
    });
  }
}

// ─── FETCH METRICS ───────────────────────────────────────────
async function fetchMetrics() {
  try {
    const res = await fetch('/api/metrics');
    if (!res.ok) return;
    const data = await res.json();
    const cur = data.current;

    // 1. Navbar KPIs
    document.getElementById('nav-cpu').textContent = cur.cpu_overall + '%';
    document.getElementById('nav-mem').textContent = cur.memory_percent + '%';
    document.getElementById('nav-procs').textContent = cur.procs_count;
    document.getElementById('nav-uptime').textContent = formatSeconds(cur.uptime_seconds);

    // 2. Stat Cards
    updateStatCards(cur);

    // 3. Circular Gauge
    updateGauge(cur.cpu_overall);

    // 4. Update Charts
    if (data.history) {
      updateCharts(data.history);
    }

    // 5. Update Cores Grid
    if (cur.cpu_cores && cur.cpu_cores.length > 0) {
      updateCoresGrid(cur.cpu_cores, cur.cpu_freq_current);
    }

    // 6. Update Memory Specs
    updateMemoryTab(cur);

    // 7. Update Session Stats (History tab)
    if (data.stats) {
      updateStatsTab(data.stats);
    }

  } catch (err) {
    console.error('Error fetching metrics:', err);
  }
}

function updateStatCards(cur) {
  // CPU Card
  const valCpu = document.getElementById('val-cpu');
  const barCpu = document.getElementById('bar-cpu');
  valCpu.textContent = cur.cpu_overall + '%';
  valCpu.className = 'card-value ' + getColorClass(cur.cpu_overall);
  barCpu.style.width = Math.min(cur.cpu_overall, 100) + '%';
  barCpu.className = 'progress-fill ' + getFillClass(cur.cpu_overall);
  document.getElementById('sub-cpu').textContent = `${cur.cpu_cores.length} Logical Threads Active`;

  // RAM Card
  const valMem = document.getElementById('val-mem');
  const barMem = document.getElementById('bar-mem');
  valMem.textContent = cur.memory_percent + '%';
  valMem.className = 'card-value ' + getColorClass(cur.memory_percent);
  barMem.style.width = Math.min(cur.memory_percent, 100) + '%';
  barMem.className = 'progress-fill ' + getFillClass(cur.memory_percent);
  const usedGb = (cur.memory_used / (1024**3)).toFixed(1);
  const totalGb = (cur.memory_total / (1024**3)).toFixed(1);
  document.getElementById('sub-mem').textContent = `${usedGb} GB / ${totalGb} GB Used`;

  // Score Card
  const valScore = document.getElementById('val-score');
  const barScore = document.getElementById('bar-score');
  valScore.textContent = cur.perf_score;
  barScore.style.width = cur.perf_score + '%';
  if (cur.perf_score > 75) {
    valScore.className = 'card-value text-emerald';
    barScore.className = 'progress-fill fill-emerald';
    document.getElementById('sub-score').textContent = 'System in Optimal State';
  } else if (cur.perf_score > 40) {
    valScore.className = 'card-value text-amber';
    barScore.className = 'progress-fill fill-amber';
    document.getElementById('sub-score').textContent = 'Moderate Resource Load';
  } else {
    valScore.className = 'card-value text-crimson';
    barScore.className = 'progress-fill fill-crimson';
    document.getElementById('sub-score').textContent = 'Heavy Workload Warning';
  }

  // Frequency
  document.getElementById('val-freq').textContent = cur.cpu_freq_current ? `${cur.cpu_freq_current} MHz` : 'Dynamic';
  document.getElementById('sub-freq').textContent = cur.cpu_freq_max ? `Max Clock: ${cur.cpu_freq_max} MHz` : 'Active Scaling';

  // Active Procs
  document.getElementById('val-procs').textContent = cur.procs_count;
}

function updateGauge(cpu) {
  const circle = document.getElementById('gauge-circle');
  const text = document.getElementById('gauge-text');
  const sub = document.getElementById('gauge-sub');
  
  text.textContent = Math.round(cpu) + '%';
  
  const offset = 440 - (440 * Math.min(cpu, 100)) / 100;
  circle.style.strokeDashoffset = offset;

  if (cpu >= critThreshold) {
    circle.style.stroke = '#ef4444';
    text.className = 'gauge-pct text-crimson';
    sub.textContent = 'High Load — Cores heavily loaded';
  } else if (cpu >= warnThreshold) {
    circle.style.stroke = '#f59e0b';
    text.className = 'gauge-pct text-amber';
    sub.textContent = 'Moderate Load — Elevated tasks';
  } else {
    circle.style.stroke = '#00f2fe';
    text.className = 'gauge-pct text-cyan';
    sub.textContent = 'Optimal — Resource usage normal';
  }
}

function updateCharts(history) {
  if (charts.telemetry) {
    charts.telemetry.data.labels = history.timestamps;
    charts.telemetry.data.datasets[0].data = history.cpu;
    charts.telemetry.data.datasets[1].data = history.memory;
    charts.telemetry.update('none');
  }

  if (charts.network) {
    charts.network.data.labels = history.timestamps;
    charts.network.data.datasets[0].data = history.net_sent;
    charts.network.data.datasets[1].data = history.net_recv;
    charts.network.update('none');
  }
}

function updateCoresGrid(cores, freq) {
  const container = document.getElementById('cores-grid');
  document.getElementById('cores-count-badge').textContent = `${cores.length} Cores Online`;

  if (charts.coresBar) {
    charts.coresBar.data.labels = cores.map((_, i) => `Core ${i}`);
    charts.coresBar.data.datasets[0].data = cores;
    charts.coresBar.data.datasets[0].backgroundColor = cores.map(c => getHexColor(c));
    charts.coresBar.update('none');
  }

  let html = '';
  cores.forEach((pct, i) => {
    const colClass = getColorClass(pct);
    const fillClass = getFillClass(pct);
    html += `
      <div class="core-tile">
        <div class="core-num">CORE ${i}</div>
        <div class="core-pct ${colClass}">${Math.round(pct)}%</div>
        <div class="core-freq-label">${freq ? freq + ' MHz' : 'Active'}</div>
        <div class="core-bar-track">
          <div class="core-bar-fill ${fillClass}" style="width: ${pct}%"></div>
        </div>
      </div>
    `;
  });
  container.innerHTML = html;
}

function updateMemoryTab(cur) {
  const totalGb = (cur.memory_total / (1024**3)).toFixed(1);
  const usedGb = (cur.memory_used / (1024**3)).toFixed(1);
  const availGb = (cur.memory_available / (1024**3)).toFixed(1);

  const elTotal = document.getElementById('mem-total');
  if (elTotal) elTotal.textContent = totalGb + ' GB';
  const elUsed = document.getElementById('mem-used');
  if (elUsed) elUsed.textContent = usedGb + ' GB';
  const elAvail = document.getElementById('mem-avail');
  if (elAvail) elAvail.textContent = availGb + ' GB';
  const elSwap = document.getElementById('swap-val');
  if (elSwap) elSwap.textContent = cur.swap_percent + '%';

  const barUsed = document.getElementById('bar-mem-used');
  const barFree = document.getElementById('bar-mem-free');
  if (barUsed) barUsed.style.width = cur.memory_percent + '%';
  if (barFree) barFree.style.width = (100 - cur.memory_percent) + '%';
}

function updateStatsTab(stats) {
  const elAvg = document.getElementById('stat-avg');
  if (elAvg) elAvg.textContent = stats.avg_cpu + '%';
  const elPeak = document.getElementById('stat-peak');
  if (elPeak) elPeak.textContent = stats.peak_cpu + '%';
  const elMin = document.getElementById('stat-min');
  if (elMin) elMin.textContent = stats.min_cpu + '%';
  const elStd = document.getElementById('stat-std');
  if (elStd) elStd.textContent = stats.std_cpu;
  const elSamples = document.getElementById('stat-samples');
  if (elSamples) elSamples.textContent = stats.samples;
}

// ─── COUNTERMEASURES & SMART HOG TERMINATOR ──────────────────
function setupCountermeasureControls() {
  const refreshBtn = document.getElementById('btn-refresh-countermeasures');
  if (refreshBtn) refreshBtn.addEventListener('click', fetchCountermeasures);

  const turboBtn = document.getElementById('btn-turbo-boost');
  if (turboBtn) {
    turboBtn.addEventListener('click', async () => {
      if (confirm('Authorize 1-Click System Boost?\nThis will safely terminate background updaters & telemetry hogs to release CPU and RAM.')) {
        try {
          const res = await fetch('/api/countermeasures/boost', { method: 'POST' });
          const data = await res.json();
          alert(data.message);
          fetchCountermeasures();
          fetchProcesses();
        } catch (err) {
          alert('Failed to execute boost: ' + err);
        }
      }
    });
  }
}

async function fetchCountermeasures() {
  try {
    const res = await fetch('/api/countermeasures');
    if (!res.ok) return;
    const data = await res.json();

    // 1. Dashboard Emergency Banner
    const banner = document.getElementById('hog-alert-banner');
    const badge = document.getElementById('countermeasures-badge');
    
    if (data.hogs && data.hogs.length > 0 && (data.is_under_pressure || data.hogs[0].cpu >= 4.0)) {
      const topHog = data.hogs[0];
      document.getElementById('banner-text').textContent = 
        `'${topHog.name}' (PID: ${topHog.pid}) is consuming ${topHog.cpu}% CPU in background. Reclaimable: ${data.reclaimable_cpu}% CPU & ${data.reclaimable_ram_mb} MB RAM.`;
      banner.style.display = 'flex';
      
      badge.textContent = data.hogs.length;
      badge.style.display = 'inline-block';
    } else {
      banner.style.display = 'none';
      if (data.hogs && data.hogs.length > 0) {
        badge.textContent = data.hogs.length;
        badge.style.display = 'inline-block';
      } else {
        badge.style.display = 'none';
      }
    }

    // 2. Reclaimable Metrics
    const rCpu = document.getElementById('reclaim-cpu-val');
    const rRam = document.getElementById('reclaim-ram-val');
    if (rCpu) rCpu.textContent = data.reclaimable_cpu + '%';
    if (rRam) rRam.textContent = data.reclaimable_ram_mb + ' MB';

    // 3. Countermeasures Table
    const tbody = document.getElementById('countermeasures-table-body');
    if (tbody) {
      if (!data.hogs || data.hogs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-emerald">✅ All background processes are operating within normal limits. No rogue hogs detected.</td></tr>';
      } else {
        let html = '';
        data.hogs.forEach(h => {
          const threatBadge = h.threat === 'HIGH' ? 'status-danger' : 'status-warn';
          html += `
            <tr>
              <td class="proc-pid-cell">${h.pid}</td>
              <td class="proc-name-cell"><strong>${h.name}</strong></td>
              <td><span class="badge-status ${threatBadge}">${h.category}</span></td>
              <td><span class="inline-val text-crimson">${h.cpu}%</span></td>
              <td><span class="inline-val text-amber">${h.memory_mb} MB</span></td>
              <td><span style="font-size:11px; color:#8494ab;">${h.recommendation}</span></td>
              <td style="text-align: center;">
                <button class="btn btn-xs btn-danger" onclick="promptCountermeasureKill(${h.pid}, '${h.name.replace(/'/g, "\\'")}')">
                  ⚡ Terminate & Cool
                </button>
              </td>
            </tr>
          `;
        });
        tbody.innerHTML = html;
      }
    }

    // 4. Audit Log
    const auditEl = document.getElementById('countermeasure-audit-list');
    if (auditEl && data.audit_log) {
      if (data.audit_log.length === 0) {
        auditEl.innerHTML = '<div class="empty-state">No countermeasures executed in this session.</div>';
      } else {
        let aHtml = '';
        data.audit_log.forEach(a => {
          aHtml += `
            <div class="audit-card">
              <div>
                <div class="audit-proc">🛡️ ${a.action}: ${a.process}</div>
                <div class="audit-detail">${a.result}</div>
              </div>
              <div class="audit-time">${a.time}</div>
            </div>
          `;
        });
        auditEl.innerHTML = aHtml;
      }
    }

  } catch (err) {
    console.error('Error fetching countermeasures:', err);
  }
}

window.promptCountermeasureKill = function(pid, name) {
  pendingKillPid = pid;
  pendingKillName = name;
  pendingKillType = 'countermeasure';
  document.getElementById('modal-title-text').textContent = 'Execute Countermeasure?';
  document.getElementById('modal-desc-text').innerHTML = 
    `You are authorizing the immediate termination of background process <strong>${name}</strong> (PID: ${pid}) to release CPU/RAM load.`;
  document.getElementById('kill-modal').classList.add('open');
};

// ─── HARDWARE DIGITAL TWIN ───────────────────────────────────
async function fetchHardwareTwin() {
  try {
    const res = await fetch('/api/hardware-twin');
    if (!res.ok) return;
    const data = await res.json();

    // 1. Title & Header
    document.getElementById('twin-cpu-name').textContent = data.cpu_silicon.model;
    document.getElementById('twin-cpu-sub').textContent = 
      `${data.cpu_silicon.physical_cores} Physical Cores &bull; ${data.cpu_silicon.logical_threads} Hardware Threads &bull; ${data.cpu_silicon.architecture} Architecture &bull; ${data.cpu_silicon.base_clock_mhz} MHz Clock`;
    document.getElementById('twin-cache-info').textContent = data.cpu_silicon.l3_cache_shared;

    // 2. Silicon Cores Die Grid
    const dieGrid = document.getElementById('silicon-cores-grid');
    if (dieGrid && data.cpu_silicon.core_topology) {
      let dieHtml = '';
      data.cpu_silicon.core_topology.forEach(c => {
        let threadsHtml = '';
        c.threads.forEach(t => {
          const colClass = getColorClass(t.load);
          threadsHtml += `
            <div class="die-thread-cell">
              <div class="die-thread-label">TH-${t.thread_id}</div>
              <div class="die-thread-load ${colClass}">${Math.round(t.load)}%</div>
            </div>
          `;
        });

        dieHtml += `
          <div class="die-core-box thermal-${c.thermal_state}">
            <div class="die-core-header">
              <span>PHYSICAL CORE ${c.physical_core_id}</span>
              <span class="badge-status ${c.thermal_state === 'NORMAL' ? 'status-normal' : c.thermal_state === 'WARM' ? 'status-info' : 'status-danger'}">${c.thermal_state} (${c.avg_load}%)</span>
            </div>
            <div class="die-threads-container">
              ${threadsHtml}
            </div>
          </div>
        `;
      });
      dieGrid.innerHTML = dieHtml;
    }

    // 3. Kernel Pipeline
    document.getElementById('twin-ctx-switches').textContent = data.kernel_pipeline.ctx_switches_sec.toLocaleString() + ' /s';
    document.getElementById('twin-interrupts').textContent = data.kernel_pipeline.interrupts_sec.toLocaleString() + ' /s';
    document.getElementById('twin-active-threads').textContent = data.kernel_pipeline.active_processes + ' Tasks';

    // 4. Memory Bus
    document.getElementById('twin-ram-total').textContent = `${data.memory_bus.used_gb} GB / ${data.memory_bus.total_gb} GB`;
    document.getElementById('twin-swap-used').textContent = `${data.memory_bus.swap_used_gb} GB (${data.memory_bus.swap_total_gb} GB Total)`;
    document.getElementById('twin-ram-pct').textContent = data.memory_bus.percent + '% Active';

    // 5. Storage & PCIe Controller
    document.getElementById('twin-disk-count').textContent = data.storage_controller.length + ' Drives Online';
    if (data.network_controller && data.network_controller.length > 0) {
      document.getElementById('twin-nic-speed').textContent = data.network_controller[0].speed_mbps + ' Mbps';
      document.getElementById('twin-nic-duplex').textContent = data.network_controller[0].duplex;
    }

  } catch (err) {
    console.error('Error fetching hardware twin:', err);
  }
}

// ─── PROCESSES TABLE ─────────────────────────────────────────
function setupProcessControls() {
  const searchInput = document.getElementById('proc-search-input');
  const sortSelect = document.getElementById('proc-sort-select');
  const refreshBtn = document.getElementById('btn-refresh-procs');

  let debounceTimer;
  searchInput.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(fetchProcesses, 250);
  });

  sortSelect.addEventListener('change', fetchProcesses);
  refreshBtn.addEventListener('click', fetchProcesses);

  // Setup modal buttons
  document.getElementById('btn-cancel-kill').addEventListener('click', closeModal);
  document.getElementById('btn-confirm-kill').addEventListener('click', executeKill);
}

async function fetchProcesses() {
  const search = document.getElementById('proc-search-input').value;
  const sort = document.getElementById('proc-sort-select').value;
  const tbody = document.getElementById('proc-table-body');

  try {
    const res = await fetch(`/api/processes?search=${encodeURIComponent(search)}&sort=${sort}&limit=50`);
    if (!res.ok) return;
    const procs = await res.json();

    if (procs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4">No matching processes found.</td></tr>';
      return;
    }

    let html = '';
    procs.forEach(p => {
      const cpuCol = getColorClass(p.cpu);
      const memCol = getColorClass(p.memory);

      html += `
        <tr>
          <td class="proc-pid-cell">${p.pid}</td>
          <td class="proc-name-cell" title="${p.name}">${p.name}</td>
          <td>
            <div class="inline-metric">
              <div class="inline-bar-bg">
                <div class="inline-bar-fill" style="width: ${Math.min(p.cpu, 100)}%; background: ${getHexColor(p.cpu)}"></div>
              </div>
              <span class="inline-val ${cpuCol}">${p.cpu}%</span>
            </div>
          </td>
          <td>
            <div class="inline-metric">
              <div class="inline-bar-bg">
                <div class="inline-bar-fill" style="width: ${Math.min(p.memory, 100)}%; background: ${getHexColor(p.memory)}"></div>
              </div>
              <span class="inline-val ${memCol}">${p.memory}%</span>
            </div>
          </td>
          <td>${p.threads}</td>
          <td>
            <span class="badge-status ${p.status === 'running' ? 'status-normal' : 'status-info'}">
              ${p.status}
            </span>
          </td>
          <td style="text-align: center;">
            <button class="btn btn-xs btn-outline" onclick="promptKillProcess(${p.pid}, '${p.name.replace(/'/g, "\\'")}')">
              Terminate
            </button>
          </td>
        </tr>
      `;
    });
    tbody.innerHTML = html;

  } catch (err) {
    console.error('Error fetching processes:', err);
  }
}

// ─── PROCESS TERMINATION MODAL ───────────────────────────────
window.promptKillProcess = function(pid, name) {
  pendingKillPid = pid;
  pendingKillName = name;
  pendingKillType = 'process';
  document.getElementById('modal-title-text').textContent = 'Authorize Process Termination';
  document.getElementById('modal-desc-text').innerHTML = 
    `Are you sure you want to terminate process <strong>${name}</strong> (PID: ${pid})?`;
  document.getElementById('kill-modal').classList.add('open');
};

function closeModal() {
  document.getElementById('kill-modal').classList.remove('open');
  pendingKillPid = null;
  pendingKillName = '';
  pendingKillType = 'process';
}

async function executeKill() {
  if (!pendingKillPid) return;
  const pid = pendingKillPid;
  const endpoint = (pendingKillType === 'countermeasure')
    ? `/api/countermeasures/terminate/${pid}`
    : `/api/kill/${pid}`;
  closeModal();

  try {
    const res = await fetch(endpoint, { method: 'POST' });
    const data = await res.json();
    alert(data.message);
    fetchProcesses();
    fetchCountermeasures();
  } catch (err) {
    alert('Failed to terminate process: ' + err);
  }
}

// ─── STORAGE & DISKS ─────────────────────────────────────────
async function fetchDisks() {
  try {
    const res = await fetch('/api/disks');
    if (!res.ok) return;
    const disks = await res.json();

    const quickList = document.getElementById('quick-disk-list');
    const fullList = document.getElementById('full-disk-list');

    if (!disks || disks.length === 0) {
      if (quickList) quickList.innerHTML = '<div class="empty-state">No drives detected</div>';
      return;
    }

    let qHtml = '';
    let fHtml = '<table class="data-table"><thead><tr><th>DEVICE</th><th>MOUNT</th><th>TYPE</th><th>USED / TOTAL</th><th>USAGE</th></tr></thead><tbody>';

    disks.forEach(d => {
      const usedGb = (d.used / (1024**3)).toFixed(1);
      const totalGb = (d.total / (1024**3)).toFixed(1);
      const col = getHexColor(d.percent);

      qHtml += `
        <div class="disk-row-card">
          <div class="disk-row-head">
            <span>💾 ${d.device} (${d.mountpoint})</span>
            <span style="color: ${col}">${d.percent}%</span>
          </div>
          <div class="progress-track">
            <div class="progress-fill" style="width: ${d.percent}%; background: ${col}"></div>
          </div>
          <div class="card-sub" style="margin-top: 6px;">${usedGb} GB used of ${totalGb} GB</div>
        </div>
      `;

      fHtml += `
        <tr>
          <td><strong>${d.device}</strong></td>
          <td>${d.mountpoint}</td>
          <td>${d.fstype}</td>
          <td>${usedGb} GB / ${totalGb} GB</td>
          <td>
            <div class="inline-metric">
              <div class="inline-bar-bg" style="width: 120px;">
                <div class="inline-bar-fill" style="width: ${d.percent}%; background: ${col}"></div>
              </div>
              <span class="inline-val" style="color:${col}">${d.percent}%</span>
            </div>
          </td>
        </tr>
      `;
    });

    fHtml += '</tbody></table>';

    if (quickList) quickList.innerHTML = qHtml;
    if (fullList) fullList.innerHTML = fHtml;

  } catch (err) {
    console.error('Error fetching disks:', err);
  }
}

// ─── ALERTS SYSTEM ───────────────────────────────────────────
function setupAlertControls() {
  const filterSelect = document.getElementById('alert-filter-select');
  const clearBtn = document.getElementById('btn-clear-alerts');

  filterSelect.addEventListener('change', fetchAlerts);
  clearBtn.addEventListener('click', async () => {
    await fetch('/api/alerts/clear', { method: 'POST' });
    fetchAlerts();
    fetchAnomalies();
  });
}

async function fetchAlerts() {
  const filter = document.getElementById('alert-filter-select').value;
  const listEl = document.getElementById('alerts-list');
  const counter = document.getElementById('alert-counter');

  try {
    const res = await fetch(`/api/alerts?level=${filter}`);
    if (!res.ok) return;
    const alerts = await res.json();

    if (counter) {
      if (alerts.length > 0) {
        counter.textContent = alerts.length;
        counter.style.display = 'inline-block';
      } else {
        counter.style.display = 'none';
      }
    }

    if (!listEl) return;
    if (alerts.length === 0) {
      listEl.innerHTML = '<div class="empty-state">No events recorded. System running normally.</div>';
      return;
    }

    alerts.forEach(a => {
      if (a.level === 'critical' && !knownAlertIds.has(a.id) && soundAlertsEnabled) {
        playBeep();
      }
      knownAlertIds.add(a.id);
    });

    const icons = {
      critical: '🔴',
      warning: '🟠',
      info: '🔵',
      success: '🟢'
    };

    let html = '';
    alerts.forEach(a => {
      html += `
        <div class="alert-card ${a.level}">
          <div class="alert-icon-wrapper">${icons[a.level] || '⚪'}</div>
          <div class="alert-content-wrapper">
            <div class="alert-title-text">${a.title}</div>
            <div class="alert-msg-text">${a.message}</div>
            <div class="alert-timestamp">Logged at: ${a.time}</div>
          </div>
        </div>
      `;
    });
    listEl.innerHTML = html;

  } catch (err) {
    console.error('Error fetching alerts:', err);
  }
}

async function fetchAnomalies() {
  const anomEl = document.getElementById('anomaly-items-list');
  if (!anomEl) return;

  try {
    const res = await fetch('/api/anomalies');
    if (!res.ok) return;
    const anoms = await res.json();

    if (anoms.length === 0) {
      anomEl.innerHTML = '<div class="empty-state">No anomalous spikes detected (Z &lt; 2.6).</div>';
      return;
    }

    let html = '';
    anoms.forEach(a => {
      html += `
        <div class="alert-card warning">
          <div class="alert-icon-wrapper">⚡</div>
          <div class="alert-content-wrapper">
            <div class="alert-title-text">${a.title}</div>
            <div class="alert-msg-text">${a.message}</div>
            <div class="alert-timestamp">${a.time}</div>
          </div>
        </div>
      `;
    });
    anomEl.innerHTML = html;

  } catch (err) {
    console.error('Error fetching anomalies:', err);
  }
}

// ─── SETTINGS & SYSTEM INFO ──────────────────────────────────
function setupSettingsForm() {
  const form = document.getElementById('settings-form');
  const warnSlider = document.getElementById('input-warn');
  const critSlider = document.getElementById('input-crit');
  const refreshSelect = document.getElementById('select-refresh');
  const soundCheck = document.getElementById('check-sound');

  warnSlider.addEventListener('input', e => {
    document.getElementById('val-slider-warn').textContent = e.target.value + '%';
  });

  critSlider.addEventListener('input', e => {
    document.getElementById('val-slider-crit').textContent = e.target.value + '%';
  });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    warnThreshold = parseInt(warnSlider.value);
    critThreshold = parseInt(critSlider.value);
    refreshIntervalMs = parseInt(refreshSelect.value);
    soundAlertsEnabled = soundCheck.checked;

    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        warn_threshold: warnThreshold,
        crit_threshold: critThreshold,
        refresh_rate: refreshIntervalMs,
        sound_alerts: soundAlertsEnabled
      })
    });

    const fb = document.getElementById('save-feedback');
    fb.style.display = 'inline';
    setTimeout(() => { fb.style.display = 'none'; }, 2000);

    startPolling();
  });
}

async function fetchSystemInfo() {
  const container = document.getElementById('sysinfo-content');
  if (!container) return;

  try {
    const res = await fetch('/api/system-info');
    if (!res.ok) return;
    const info = await res.json();

    const rows = [
      ['Operating System', info.os],
      ['Processor (CPU)', info.processor],
      ['Machine Architecture', info.machine],
      ['Physical CPU Cores', info.cores_physical],
      ['Logical CPU Threads', info.cores_logical],
      ['Max Clock Rating', info.freq_max + ' MHz'],
      ['Total Installed RAM', info.total_ram_gb + ' GB'],
      ['Network Hostname', info.hostname],
      ['System Boot Timestamp', info.boot_time],
      ['Python Runtime', 'Python ' + info.python_version]
    ];

    let html = '';
    rows.forEach(([label, val]) => {
      html += `
        <div class="stat-row">
          <span class="stat-name">${label}</span>
          <span class="stat-num">${val}</span>
        </div>
      `;
    });
    container.innerHTML = html;

  } catch (err) {
    console.error('Error fetching sysinfo:', err);
  }
}

// ─── AUDIO BEEP NOTIFICATION ─────────────────────────────────
function playBeep() {
  try {
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();

    osc.type = 'sine';
    osc.frequency.setValueAtTime(880, audioCtx.currentTime);
    gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.3);

    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.3);
  } catch (e) {}
}

// ─── HELPERS ─────────────────────────────────────────────────
function getColorClass(pct) {
  if (pct >= critThreshold) return 'text-crimson';
  if (pct >= warnThreshold) return 'text-amber';
  if (pct >= 50) return 'text-cyan';
  return 'text-emerald';
}

function getFillClass(pct) {
  if (pct >= critThreshold) return 'fill-crimson';
  if (pct >= warnThreshold) return 'fill-amber';
  if (pct >= 50) return 'fill-cyan';
  return 'fill-emerald';
}

function getHexColor(pct) {
  if (pct >= critThreshold) return '#ef4444';
  if (pct >= warnThreshold) return '#f59e0b';
  if (pct >= 50) return '#00f2fe';
  return '#10b981';
}

function formatSeconds(sec) {
  if (!sec || isNaN(sec) || sec < 0) sec = 0;
  const h = Math.floor(sec / 3600).toString().padStart(2, '0');
  const m = Math.floor((sec % 3600) / 60).toString().padStart(2, '0');
  const s = Math.floor(sec % 60).toString().padStart(2, '0');
  return `${h}:${m}:${s}`;
}


// ─── EXPORT DROPDOWN ─────────────────────────────────────────
function toggleExportMenu(e) {
  e.stopPropagation();
  const menu = document.getElementById('export-menu');
  if (menu) menu.classList.toggle('open');
}

// Close export menu when clicking outside
document.addEventListener('click', function(e) {
  const menu = document.getElementById('export-menu');
  if (menu && !e.target.closest('.export-dropdown')) {
    menu.classList.remove('open');
  }
});
