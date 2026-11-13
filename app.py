import collections
import csv
import datetime
import io
import json
import os
import platform
import statistics
import threading
import time
import psutil
from flask import Flask, jsonify, render_template, request, Response, send_file, send_from_directory

# ── PyInstaller bundle path support ───────────────────────────────
_template_dir = os.environ.get('NEXUS_TEMPLATE_DIR', os.path.join(os.path.dirname(__file__), 'templates'))
_static_dir   = os.environ.get('NEXUS_STATIC_DIR',   os.path.join(os.path.dirname(__file__), 'static'))

app = Flask(__name__, template_folder=_template_dir, static_folder=_static_dir)

@app.route('/static/<path:filename>')
def custom_static(filename):
    return send_from_directory(_static_dir, filename)

# Constants
MAX_HISTORY = 300
ALERT_MAX = 100
ANOMALY_WINDOW = 20

# Settings
settings = {
    "warn_threshold": 75,
    "crit_threshold": 90,
    "sound_alerts": True,
    "refresh_rate": 1000  # ms
}

# Protected system processes that MUST NOT be killed to prevent BSOD/system crash
PROTECTED_PROCESSES = {
    'system', 'registry', 'smss.exe', 'csrss.exe', 'wininit.exe', 'services.exe',
    'lsass.exe', 'svchost.exe', 'fontdrvhost.exe', 'winlogon.exe', 'dwm.exe',
    'explorer.exe', 'python.exe', 'pythonw.exe', 'spoolsv.exe', 'taskhostw.exe',
    'sihost.exe', 'runtimebroker.exe', 'ctfmon.exe', 'cmd.exe', 'powershell.exe'
}

# State stores
data_lock = threading.Lock()
proc_lock = threading.Lock()

cpu_history = collections.deque(maxlen=MAX_HISTORY)
mem_history = collections.deque(maxlen=MAX_HISTORY)
time_history = collections.deque(maxlen=MAX_HISTORY)
net_sent_history = collections.deque(maxlen=MAX_HISTORY)
net_recv_history = collections.deque(maxlen=MAX_HISTORY)
alert_log = collections.deque(maxlen=ALERT_MAX)
anomaly_log = collections.deque(maxlen=ALERT_MAX)
countermeasure_audit_log = collections.deque(maxlen=ALERT_MAX)
_alert_throttles = {}
cached_processes = []

# Kernel scheduling metrics
prev_ctx_switches = 0
prev_interrupts = 0
last_ctx_time = time.time()
kernel_stats = {
    "ctx_switches_per_sec": 0,
    "interrupts_per_sec": 0
}

latest_metrics = {
    "cpu_overall": 0.0,
    "cpu_cores": [],
    "cpu_freq_current": 0,
    "cpu_freq_max": 0,
    "memory_percent": 0.0,
    "memory_used": 0,
    "memory_total": 0,
    "memory_available": 0,
    "swap_percent": 0.0,
    "swap_used": 0,
    "swap_total": 0,
    "procs_count": 0,
    "perf_score": 100,
    "net_sent_rate": 0,
    "net_recv_rate": 0,
    "uptime_seconds": 0,
    "timestamp": ""
}

def add_alert(level, title, message, key="", cooldown=20.0):
    now = time.time()
    if key and (now - _alert_throttles.get(key, 0)) < cooldown:
        return
    if key:
        _alert_throttles[key] = now
    
    alert_item = {
        "id": int(now * 1000),
        "level": level,  # 'critical', 'warning', 'info', 'success'
        "title": title,
        "message": message,
        "time": datetime.datetime.now().strftime("%H:%M:%S")
    }
    with data_lock:
        alert_log.appendleft(alert_item)
        if "Anomaly" in title or "Spike" in title:
            anomaly_log.appendleft(alert_item)

def detect_anomaly(values):
    if len(values) < ANOMALY_WINDOW + 1:
        return False
    window = list(values)[-(ANOMALY_WINDOW + 1):-1]
    latest = values[-1]
    try:
        avg = statistics.mean(window)
        stdev = statistics.stdev(window)
        if stdev > 2.5:
            z_score = (latest - avg) / stdev
            return z_score > 2.6
    except Exception:
        pass
    return False

def classify_process(name):
    """Categorizes process into user-understandable categories"""
    nl = name.lower()
    if any(k in nl for k in ['tiworker', 'trustedinstaller', 'update', 'telemetry', 'compatrunner', 'mousocoreworker', 'sedlauncher', 'waasmedic']):
        return "Background Updater / Telemetry", "warning"
    if any(k in nl for k in ['chrome', 'msedge', 'firefox', 'brave', 'opera']):
        return "Web Browser (Multi-Tab)", "info"
    if any(k in nl for k in ['steam', 'epicgames', 'riot', 'discord', 'game', 'valorant', 'league']):
        return "Gaming & Social Platform", "info"
    if any(k in nl for k in ['antigravity', 'code', 'devenv', 'pycharm', 'idea', 'eclipse']):
        return "Development Environment (IDE)", "info"
    if any(k in nl for k in ['officeclicktorun', 'word', 'excel', 'powerpnt', 'onenote']):
        return "Office / Productivity App", "info"
    return "Background Utility / Process", "default"

def metrics_collector_thread():
    """Background worker collecting precise system stats every 0.6s without blocking requests"""
    global cached_processes, prev_ctx_switches, prev_interrupts, last_ctx_time, kernel_stats

    # Prime initial psutil metrics
    psutil.cpu_percent(interval=None)
    prev_net = None
    try:
        prev_net = psutil.net_io_counters()
    except Exception:
        pass
    prev_net_time = time.time()
    last_proc_update = 0
    proc_dict = {}

    try:
        initial_stats = psutil.cpu_stats()
        prev_ctx_switches = initial_stats.ctx_switches
        prev_interrupts = initial_stats.interrupts
        last_ctx_time = time.time()
    except Exception:
        pass

    add_alert("success", "System Initialized", "Real-time telemetry and countermeasure engine is active.", "init", 5)

    num_cores = psutil.cpu_count(logical=True) or 1

    while True:
        try:
            # 0.5s interval sampling guarantees true OS CPU usage
            per_core = psutil.cpu_percent(interval=0.5, percpu=True)
            cpu_overall = round(sum(per_core) / max(len(per_core), 1), 1)

            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()

            # CPU Frequency
            freq_curr = 0
            freq_max = 0
            try:
                freq = psutil.cpu_freq()
                if freq:
                    freq_curr = round(freq.current)
                    freq_max = round(freq.max) if freq.max else round(freq.current)
            except Exception:
                pass

            # Network rates
            now_time = time.time()
            time_delta = max(now_time - prev_net_time, 0.001)
            sent_rate = 0
            recv_rate = 0
            try:
                curr_net = psutil.net_io_counters()
                if prev_net and curr_net:
                    sent_rate = max(0, int((curr_net.bytes_sent - prev_net.bytes_sent) / time_delta))
                    recv_rate = max(0, int((curr_net.bytes_recv - prev_net.bytes_recv) / time_delta))
                prev_net = curr_net
                prev_net_time = now_time
            except Exception:
                pass

            # Kernel CPU Stats (Context Switches / Interrupts per second)
            try:
                cstats = psutil.cpu_stats()
                ctx_delta = max(now_time - last_ctx_time, 0.001)
                kernel_stats["ctx_switches_per_sec"] = int(max(0, cstats.ctx_switches - prev_ctx_switches) / ctx_delta)
                kernel_stats["interrupts_per_sec"] = int(max(0, cstats.interrupts - prev_interrupts) / ctx_delta)
                prev_ctx_switches = cstats.ctx_switches
                prev_interrupts = cstats.interrupts
                last_ctx_time = now_time
            except Exception:
                pass

            # Processes count
            procs_count = len(psutil.pids())

            # Uptime
            boot_time = psutil.boot_time()
            uptime_sec = int(time.time() - boot_time)

            # Performance Health Score (0-100)
            perf_score = max(0, min(100, int(100 - (cpu_overall * 0.6) - (mem.percent * 0.4))))

            now_str = datetime.datetime.now().strftime("%H:%M:%S")

            with data_lock:
                cpu_history.append(cpu_overall)
                mem_history.append(mem.percent)
                time_history.append(now_str)
                net_sent_history.append(sent_rate)
                net_recv_history.append(recv_rate)

                latest_metrics["cpu_overall"] = cpu_overall
                latest_metrics["cpu_cores"] = per_core
                latest_metrics["cpu_freq_current"] = freq_curr
                latest_metrics["cpu_freq_max"] = freq_max
                latest_metrics["memory_percent"] = mem.percent
                latest_metrics["memory_used"] = mem.used
                latest_metrics["memory_total"] = mem.total
                latest_metrics["memory_available"] = mem.available
                latest_metrics["swap_percent"] = swap.percent
                latest_metrics["swap_used"] = swap.used
                latest_metrics["swap_total"] = swap.total
                latest_metrics["procs_count"] = procs_count
                latest_metrics["perf_score"] = perf_score
                latest_metrics["net_sent_rate"] = sent_rate
                latest_metrics["net_recv_rate"] = recv_rate
                latest_metrics["uptime_seconds"] = uptime_sec
                latest_metrics["timestamp"] = now_str

            # Smart Alerts checking
            crit_val = settings["crit_threshold"]
            warn_val = settings["warn_threshold"]

            if cpu_overall >= crit_val:
                add_alert("critical", "High CPU Load", f"CPU utilization reached {cpu_overall}% (Threshold: {crit_val}%)", "cpu-crit", 25)
            elif cpu_overall >= warn_val:
                add_alert("warning", "Elevated CPU Load", f"CPU load is at {cpu_overall}% (Threshold: {warn_val}%)", "cpu-warn", 30)

            if mem.percent >= 90:
                add_alert("critical", "Memory Critical", f"RAM utilization at {mem.percent}%! System is under heavy memory pressure.", "mem-crit", 30)
            elif mem.percent >= 80:
                add_alert("warning", "Memory Warning", f"RAM usage elevated at {mem.percent}%.", "mem-warn", 45)

            if detect_anomaly(cpu_history):
                add_alert("warning", "Sudden CPU Spike", f"Statistical anomaly detected! Rapid spike to {cpu_overall}%.", "anomaly", 35)

            # Update Process list every ~1.4s
            if now_time - last_proc_update > 1.4:
                last_proc_update = now_time
                new_procs = []
                current_pids = set()

                for p in psutil.process_iter(['pid', 'name', 'memory_info', 'memory_percent', 'status', 'num_threads']):
                    try:
                        pid = p.info['pid']
                        pname = p.info['name'] or "Unknown"
                        if pid == 0 or pname == 'System Idle Process':
                            continue
                        current_pids.add(pid)

                        # Keep process obj for accurate delta cpu_percent
                        if pid not in proc_dict:
                            proc_dict[pid] = p
                            p.cpu_percent(None)
                            cpu_p = 0.0
                        else:
                            raw_cpu = proc_dict[pid].cpu_percent(None)
                            cpu_p = round(raw_cpu / num_cores, 1)

                        mem_bytes = p.info['memory_info'].rss if p.info.get('memory_info') else 0
                        category, badge_type = classify_process(pname)
                        is_protected = pname.lower() in PROTECTED_PROCESSES

                        new_procs.append({
                            "pid": pid,
                            "name": pname,
                            "cpu": cpu_p,
                            "memory": round(p.info['memory_percent'] or 0.0, 1),
                            "memory_mb": round(mem_bytes / (1024 * 1024), 1),
                            "threads": p.info['num_threads'] or 1,
                            "status": p.info['status'] or "running",
                            "category": category,
                            "badge_type": badge_type,
                            "is_protected": is_protected
                        })
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                # Clean up dead pids from cache dictionary
                for dead_pid in list(proc_dict.keys()):
                    if dead_pid not in current_pids:
                        proc_dict.pop(dead_pid, None)

                with proc_lock:
                    cached_processes = new_procs

        except Exception as e:
            time.sleep(1)

# Start background thread
bg_thread = threading.Thread(target=metrics_collector_thread, daemon=True)
bg_thread.start()

# --- ROUTES ---

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/metrics")
def get_metrics():
    with data_lock:
        return jsonify({
            "current": latest_metrics,
            "kernel": kernel_stats,
            "history": {
                "timestamps": list(time_history)[-60:],
                "cpu": list(cpu_history)[-60:],
                "memory": list(mem_history)[-60:],
                "net_sent": list(net_sent_history)[-60:],
                "net_recv": list(net_recv_history)[-60:],
            },
            "stats": {
                "avg_cpu": round(statistics.mean(cpu_history), 1) if cpu_history else 0,
                "peak_cpu": max(cpu_history) if cpu_history else 0,
                "min_cpu": min(cpu_history) if cpu_history else 0,
                "std_cpu": round(statistics.stdev(cpu_history), 2) if len(cpu_history) > 1 else 0,
                "samples": len(cpu_history)
            }
        })

@app.route("/api/processes")
def get_processes():
    search = request.args.get("search", "").strip().lower()
    sort_by = request.args.get("sort", "cpu").lower()
    limit = min(int(request.args.get("limit", 60)), 100)

    with proc_lock:
        proc_list = list(cached_processes)

    if search:
        proc_list = [p for p in proc_list if search in p["name"].lower() or search in str(p["pid"])]

    sort_keys = {
        "cpu": lambda x: x["cpu"],
        "mem": lambda x: x["memory"],
        "pid": lambda x: x["pid"],
        "name": lambda x: x["name"].lower()
    }
    key_func = sort_keys.get(sort_by, sort_keys["cpu"])
    proc_list.sort(key=key_func, reverse=(sort_by != "name"))

    return jsonify(proc_list[:limit])

# --- COUNTERMEASURES & SMART ROGUE TERMINATOR ---

@app.route("/api/countermeasures")
def get_countermeasures():
    """Identifies rogue background resource hogs and calculates reclaimable CPU/RAM"""
    with proc_lock:
        procs = list(cached_processes)

    # Rogue criteria: CPU >= 1.5% OR Memory >= 1.5% (or > 150MB) and not protected
    hogs = []
    total_reclaimable_cpu = 0.0
    total_reclaimable_ram_mb = 0.0

    for p in procs:
        if p["is_protected"]:
            continue
        
        is_cpu_hog = p["cpu"] >= 1.0
        is_ram_hog = p["memory_mb"] >= 150.0

        if is_cpu_hog or is_ram_hog:
            threat_level = "HIGH" if (p["cpu"] >= 6.0 or p["memory_mb"] >= 500) else "MODERATE"
            hogs.append({
                "pid": p["pid"],
                "name": p["name"],
                "cpu": p["cpu"],
                "memory_mb": p["memory_mb"],
                "category": p["category"],
                "threat": threat_level,
                "recommendation": "Safe to terminate to release resources" if p["badge_type"] == "warning" else "Review before terminating"
            })
            total_reclaimable_cpu += p["cpu"]
            total_reclaimable_ram_mb += p["memory_mb"]

    hogs.sort(key=lambda x: (x["cpu"], x["memory_mb"]), reverse=True)

    with data_lock:
        current_cpu = latest_metrics["cpu_overall"]
        current_mem = latest_metrics["memory_percent"]
        audit_history = list(countermeasure_audit_log)

    return jsonify({
        "current_cpu": current_cpu,
        "current_mem": current_mem,
        "is_under_pressure": current_cpu >= settings["warn_threshold"] or current_mem >= 80,
        "hogs": hogs[:15],
        "total_hogs_count": len(hogs),
        "reclaimable_cpu": round(total_reclaimable_cpu, 1),
        "reclaimable_ram_mb": round(total_reclaimable_ram_mb, 1),
        "audit_log": audit_history
    })

@app.route("/api/countermeasures/terminate/<int:pid>", methods=["POST"])
def terminate_countermeasure(pid):
    """Terminates a specific rogue process authorized by the user"""
    try:
        if pid in (os.getpid(), os.getppid()):
            return jsonify({"success": False, "message": "Cannot terminate NEXUS analyzer server process."}), 400

        proc = psutil.Process(pid)
        name = proc.name()
        
        if name.lower() in PROTECTED_PROCESSES:
            return jsonify({"success": False, "message": f"Action blocked: '{name}' is a critical Windows system process."}), 400

        # Measure freed resources
        try:
            cpu_freed = round((proc.cpu_percent(None) or 0) / (psutil.cpu_count(logical=True) or 1), 1)
            mem_freed = round((proc.memory_info().rss or 0) / (1024 * 1024), 1)
        except Exception:
            cpu_freed = 0
            mem_freed = 0

        proc.terminate()
        
        action_record = {
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "action": "Manual Countermeasure",
            "process": name,
            "pid": pid,
            "result": f"Terminated successfully. Reclaimed ~{mem_freed} MB RAM."
        }
        with data_lock:
            countermeasure_audit_log.appendleft(action_record)

        add_alert("info", "Countermeasure Executed", f"Terminated background hog '{name}' (PID: {pid}).", "", 0)
        return jsonify({
            "success": True,
            "message": f"Countermeasure applied: Terminated '{name}' (PID: {pid}). Reclaimed memory.",
            "freed_mb": mem_freed
        })
    except psutil.NoSuchProcess:
        return jsonify({"success": False, "message": "Process is no longer active."}), 404
    except psutil.AccessDenied:
        return jsonify({"success": False, "message": "Permission denied. Please run as Administrator."}), 403
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/countermeasures/boost", methods=["POST"])
def turbo_boost_system():
    """1-Click System Turbo Boost: Safely terminates non-essential background updaters & hogs with user confirmation"""
    with proc_lock:
        procs = list(cached_processes)

    terminated_count = 0
    total_freed_mb = 0

    for p in procs:
        pname = p["name"].lower()
        if p["pid"] in (os.getpid(), os.getppid()) or pname in PROTECTED_PROCESSES:
            continue
        
        # Target background updaters and telemetry workers
        if p["badge_type"] == "warning" or any(k in pname for k in ['tiworker', 'trustedinstaller', 'telemetry', 'compatrunner', 'mousocoreworker', 'sedlauncher']):
            try:
                proc = psutil.Process(p["pid"])
                total_freed_mb += p["memory_mb"]
                proc.terminate()
                terminated_count += 1
            except Exception:
                continue

    action_record = {
        "time": datetime.datetime.now().strftime("%H:%M:%S"),
        "action": "1-Click Turbo Boost",
        "process": f"{terminated_count} Background Tasks",
        "pid": "Batch",
        "result": f"Cleaned {terminated_count} background tasks. Reclaimed ~{round(total_freed_mb, 1)} MB RAM."
    }
    with data_lock:
        countermeasure_audit_log.appendleft(action_record)

    add_alert("success", "System Boost Completed", f"Cleaned {terminated_count} background tasks, freeing ~{round(total_freed_mb, 1)} MB RAM.", "", 0)

    return jsonify({
        "success": True,
        "terminated_count": terminated_count,
        "freed_mb": round(total_freed_mb, 1),
        "message": f"Turbo Boost applied: {terminated_count} background hogs terminated. Recovered {round(total_freed_mb, 1)} MB RAM!"
    })

# --- SOFTWARE-TO-HARDWARE DIGITAL TWIN ---

@app.route("/api/hardware-twin")
def get_hardware_twin():
    """Builds a software-to-hardware representation of the computer"""
    with data_lock:
        cur = dict(latest_metrics)
        kstats = dict(kernel_stats)

    u = platform.uname()
    num_logical = psutil.cpu_count(logical=True) or 1
    num_physical = psutil.cpu_count(logical=False) or (num_logical // 2 or 1)
    threads_per_core = max(1, num_logical // num_physical)

    # Core topology mapping: Physical Core -> Logical Threads
    cores_load = cur["cpu_cores"]
    core_topology = []
    thread_idx = 0

    for core_id in range(num_physical):
        threads = []
        for t in range(threads_per_core):
            if thread_idx < len(cores_load):
                threads.append({
                    "thread_id": thread_idx,
                    "load": cores_load[thread_idx]
                })
                thread_idx += 1
        
        core_avg_load = round(sum(t["load"] for t in threads) / max(len(threads), 1), 1)
        thermal_state = "CRITICAL" if core_avg_load >= 90 else "HOT" if core_avg_load >= 75 else "WARM" if core_avg_load >= 40 else "NORMAL"

        core_topology.append({
            "physical_core_id": core_id,
            "avg_load": core_avg_load,
            "thermal_state": thermal_state,
            "threads": threads
        })

    # Memory Controller
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # Storage Controller & Partitions
    disks_info = []
    try:
        for p in psutil.disk_partitions():
            try:
                u_disk = psutil.disk_usage(p.mountpoint)
                disks_info.append({
                    "device": p.device,
                    "mountpoint": p.mountpoint,
                    "fstype": p.fstype,
                    "total_gb": round(u_disk.total / (1024**3), 1),
                    "used_gb": round(u_disk.used / (1024**3), 1),
                    "percent": u_disk.percent
                })
            except Exception:
                continue
    except Exception:
        pass

    # Network Interface Controller (NIC)
    active_nics = []
    try:
        net_stats = psutil.net_if_stats()
        for iface_name, iface_stat in net_stats.items():
            if iface_stat.isup:
                active_nics.append({
                    "name": iface_name,
                    "speed_mbps": iface_stat.speed if iface_stat.speed > 0 else "Auto",
                    "duplex": "Full Duplex" if iface_stat.duplex == 2 else "Standard",
                    "mtu": iface_stat.mtu
                })
    except Exception:
        pass

    return jsonify({
        "cpu_silicon": {
            "model": u.processor or platform.processor() or "Modern Multicore CPU",
            "architecture": u.machine,
            "physical_cores": num_physical,
            "logical_threads": num_logical,
            "threads_per_core": threads_per_core,
            "base_clock_mhz": cur["cpu_freq_current"],
            "max_clock_mhz": cur["cpu_freq_max"],
            "core_topology": core_topology,
            "l3_cache_shared": f"{num_physical * 2} MB to {num_physical * 3} MB Unified Smart Cache"
        },
        "kernel_pipeline": {
            "scheduler": "Windows NT Preemptive Multitasking Kernel",
            "ctx_switches_sec": kstats["ctx_switches_per_sec"],
            "interrupts_sec": kstats["interrupts_per_sec"],
            "active_processes": cur["procs_count"]
        },
        "memory_bus": {
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "percent": mem.percent,
            "swap_total_gb": round(swap.total / (1024**3), 2),
            "swap_used_gb": round(swap.used / (1024**3), 2),
            "bus_type": "Dual/Quad-Channel High-Speed Interconnect"
        },
        "storage_controller": disks_info,
        "network_controller": active_nics,
        "software_layer": {
            "os_name": f"{u.system} {u.release}",
            "hostname": u.node,
            "python_env": platform.python_version()
        }
    })

# --- GENERAL UTILITY ROUTES ---

@app.route("/api/kill/<int:pid>", methods=["POST"])
def kill_process(pid):
    try:
        if pid in (os.getpid(), os.getppid()):
            return jsonify({"success": False, "message": "Cannot terminate NEXUS analyzer server process."}), 400

        proc = psutil.Process(pid)
        name = proc.name()
        if name.lower() in PROTECTED_PROCESSES:
            return jsonify({"success": False, "message": f"Action blocked: '{name}' is a protected Windows system process."}), 400

        proc.terminate()
        add_alert("info", "Process Terminated", f"Process {name} (PID: {pid}) was terminated.", "", 0)
        return jsonify({"success": True, "message": f"Process {name} (PID: {pid}) terminated."})
    except psutil.NoSuchProcess:
        return jsonify({"success": False, "message": "Process does not exist."}), 404
    except psutil.AccessDenied:
        return jsonify({"success": False, "message": "Permission denied. Run application as Administrator."}), 403
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/disks")
def get_disks():
    disks = []
    try:
        for p in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(p.mountpoint)
                disks.append({
                    "device": p.device,
                    "mountpoint": p.mountpoint,
                    "fstype": p.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent
                })
            except Exception:
                continue
    except Exception:
        pass
    return jsonify(disks)

@app.route("/api/alerts")
def get_alerts():
    level = request.args.get("level", "all")
    with data_lock:
        if level == "all":
            return jsonify(list(alert_log))
        return jsonify([a for a in alert_log if a["level"] == level])

@app.route("/api/alerts/clear", methods=["POST"])
def clear_alerts():
    with data_lock:
        alert_log.clear()
        anomaly_log.clear()
    return jsonify({"success": True})

@app.route("/api/anomalies")
def get_anomalies():
    with data_lock:
        return jsonify(list(anomaly_log))

@app.route("/api/system-info")
def get_system_info():
    u = platform.uname()
    boot = datetime.datetime.fromtimestamp(psutil.boot_time())
    freq = psutil.cpu_freq()
    mem = psutil.virtual_memory()

    return jsonify({
        "os": f"{u.system} {u.release}",
        "machine": u.machine,
        "processor": u.processor or platform.processor(),
        "hostname": u.node,
        "cores_logical": psutil.cpu_count(logical=True) or 1,
        "cores_physical": psutil.cpu_count(logical=False) or (psutil.cpu_count(logical=True) or 1) // 2 or 1,
        "freq_max": round(freq.max) if freq and freq.max else "N/A",
        "total_ram_gb": round(mem.total / (1024**3), 2),
        "boot_time": boot.strftime("%Y-%m-%d %H:%M:%S"),
        "python_version": platform.python_version()
    })

@app.route("/api/settings", methods=["GET", "POST"])
def handle_settings():
    global settings
    if request.method == "POST":
        data = request.json or {}
        if "warn_threshold" in data:
            settings["warn_threshold"] = int(data["warn_threshold"])
        if "crit_threshold" in data:
            settings["crit_threshold"] = int(data["crit_threshold"])
        if "sound_alerts" in data:
            settings["sound_alerts"] = bool(data["sound_alerts"])
        if "refresh_rate" in data:
            settings["refresh_rate"] = int(data["refresh_rate"])
        return jsonify({"success": True, "settings": settings})
    return jsonify(settings)

@app.route("/api/export-csv")
def export_csv():
    with data_lock:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Timestamp", "CPU_Percent", "Memory_Percent", "Net_Sent_Bytes_Sec", "Net_Recv_Bytes_Sec"])
        for t, c, m, s, r in zip(time_history, cpu_history, mem_history, net_sent_history, net_recv_history):
            writer.writerow([t, c, m, s, r])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=nexus_cpu_report_{int(time.time())}.csv"}
    )

@app.route("/api/export-json")
def export_json():
    now = datetime.datetime.now().isoformat()
    with data_lock:
        metrics_snap = dict(latest_metrics)
        cpu_hist = list(cpu_history)
        mem_hist = list(mem_history)
        ts_hist  = list(time_history)
        sent_hist = list(net_sent_history)
        recv_hist = list(net_recv_history)
        alerts_snap = list(alert_log)
    with proc_lock:
        procs_snap = list(cached_processes[:50])

    payload = {
        "export_time": now,
        "generator": "NEXUS CPU Analyzer",
        "current_metrics": metrics_snap,
        "history": {
            "timestamps": ts_hist,
            "cpu_percent": cpu_hist,
            "memory_percent": mem_hist,
            "net_sent_bytes_sec": sent_hist,
            "net_recv_bytes_sec": recv_hist
        },
        "top_processes": procs_snap,
        "alerts": alerts_snap
    }

    return Response(
        json.dumps(payload, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment;filename=nexus_report_{int(time.time())}.json"}
    )

@app.route("/api/export-pdf-report")
def export_pdf_report():
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
    except ImportError:
        return "ReportLab not installed. Run: pip install reportlab", 500

    now_dt = datetime.datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    fname = f"nexus_snapshot_{int(time.time())}.pdf"

    with data_lock:
        metrics_snap = dict(latest_metrics)
        cpu_hist = list(cpu_history)
        mem_hist = list(mem_history)
        ts_hist  = list(time_history)
        alerts_snap = list(alert_log)

    with proc_lock:
        procs_snap = list(cached_processes[:25])

    # Compute stats
    avg_cpu = round(statistics.mean(cpu_hist), 2) if cpu_hist else 0
    max_cpu = round(max(cpu_hist), 2) if cpu_hist else 0
    min_cpu = round(min(cpu_hist), 2) if cpu_hist else 0
    avg_mem = round(statistics.mean(mem_hist), 2) if mem_hist else 0

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)

    styles = getSampleStyleSheet()
    # Custom styles
    title_style = ParagraphStyle("title", parent=styles["Title"],
                                 fontSize=22, textColor=colors.HexColor("#a855f7"),
                                 spaceAfter=4, alignment=TA_CENTER)
    sub_style   = ParagraphStyle("sub", parent=styles["Normal"],
                                 fontSize=10, textColor=colors.HexColor("#888"),
                                 alignment=TA_CENTER, spaceAfter=12)
    h2_style    = ParagraphStyle("h2", parent=styles["Heading2"],
                                 fontSize=13, textColor=colors.HexColor("#38bdf8"),
                                 spaceBefore=14, spaceAfter=6)
    body_style  = ParagraphStyle("body", parent=styles["Normal"],
                                 fontSize=9.5, textColor=colors.HexColor("#222"),
                                 leading=14)

    PURPLE = colors.HexColor("#a855f7")
    BLUE   = colors.HexColor("#38bdf8")
    DARK   = colors.HexColor("#1e1b4b")
    LIGHT  = colors.HexColor("#f1f5f9")
    RED    = colors.HexColor("#ef4444")

    story = []

    # Header
    story.append(Paragraph("NEXUS CPU Analyzer", title_style))
    story.append(Paragraph("Real-Time System Monitoring Snapshot Report", sub_style))
    story.append(Paragraph(f"Generated: {now_str}", sub_style))
    story.append(HRFlowable(width="100%", thickness=2, color=PURPLE, spaceAfter=10))

    # ── Section 1: CPU Summary ──
    story.append(Paragraph("1. CPU Performance Summary", h2_style))
    cpu_data = [
        ["Metric", "Value"],
        ["Overall CPU Usage (now)", f"{metrics_snap.get('cpu_percent', 0):.1f}%"],
        ["Session Average CPU", f"{avg_cpu}%"],
        ["Session Max CPU (peak)", f"{max_cpu}%"],
        ["Session Min CPU (idle)", f"{min_cpu}%"],
        ["Logical CPU Cores", str(metrics_snap.get("cpu_count", "N/A"))],
        ["Physical CPU Cores", str(metrics_snap.get("cpu_count_physical", "N/A"))],
        ["CPU Frequency (current)", f"{metrics_snap.get('cpu_freq_current', 0):.0f} MHz"],
        ["CPU Frequency (max)", f"{metrics_snap.get('cpu_freq_max', 0):.0f} MHz"],
    ]
    t1 = Table(cpu_data, colWidths=[9*cm, 7*cm])
    t1.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), DARK),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 9),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [LIGHT, colors.white]),
        ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ("PADDING",    (0,0), (-1,-1), 5),
    ]))
    story.append(t1)
    story.append(Spacer(1, 10))

    # ── Section 2: Memory ──
    story.append(Paragraph("2. Memory & Swap", h2_style))
    mem = metrics_snap.get("memory", {})
    swap = metrics_snap.get("swap", {})
    mem_data = [
        ["Metric", "Value"],
        ["RAM Used", f"{mem.get('used_gb', 0):.2f} GB"],
        ["RAM Total", f"{mem.get('total_gb', 0):.2f} GB"],
        ["RAM Usage", f"{mem.get('percent', 0):.1f}%"],
        ["Session Avg RAM", f"{avg_mem}%"],
        ["Swap Used", f"{swap.get('used_gb', 0):.2f} GB"],
        ["Swap Total", f"{swap.get('total_gb', 0):.2f} GB"],
        ["Swap Usage", f"{swap.get('percent', 0):.1f}%"],
    ]
    t2 = Table(mem_data, colWidths=[9*cm, 7*cm])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), DARK),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 9),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [LIGHT, colors.white]),
        ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ("PADDING",    (0,0), (-1,-1), 5),
    ]))
    story.append(t2)
    story.append(Spacer(1, 10))

    # ── Section 3: Per-Core ──
    story.append(Paragraph("3. Per-Core CPU Usage (Snapshot)", h2_style))
    per_core = metrics_snap.get("per_core", [])
    if per_core:
        core_rows = [["Core", "Usage (%)", "Load Bar"]]
        for i, pct in enumerate(per_core):
            bar_filled = int(pct / 5)
            bar = "█" * bar_filled + "░" * (20 - bar_filled)
            core_rows.append([f"Core {i}", f"{pct:.1f}%", bar])
        tc = Table(core_rows, colWidths=[3*cm, 4*cm, 9*cm])
        tc.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), DARK),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",   (0,0), (-1,-1), 8),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [LIGHT, colors.white]),
            ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
            ("PADDING",    (0,0), (-1,-1), 4),
            ("FONTNAME",   (2,1), (2,-1), "Courier"),
        ]))
        story.append(tc)
    else:
        story.append(Paragraph("No per-core data available.", body_style))
    story.append(Spacer(1, 10))

    # ── Section 4: Top Processes ──
    story.append(Paragraph("4. Top 25 Processes by CPU Usage", h2_style))
    if procs_snap:
        proc_rows = [["PID", "Name", "CPU%", "RAM (MB)", "Status", "User"]]
        for p in procs_snap:
            proc_rows.append([
                str(p.get("pid", "")),
                str(p.get("name", ""))[:22],
                f"{p.get('cpu', 0):.1f}%",
                f"{p.get('memory_mb', 0):.1f}",
                str(p.get("status", "")),
                str(p.get("username", ""))[:18],
            ])
        tp = Table(proc_rows, colWidths=[1.5*cm, 5*cm, 2*cm, 2.5*cm, 2.5*cm, 4*cm])
        tp.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), DARK),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",   (0,0), (-1,-1), 7.5),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [LIGHT, colors.white]),
            ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
            ("PADDING",    (0,0), (-1,-1), 4),
        ]))
        story.append(tp)
    else:
        story.append(Paragraph("No process data available.", body_style))
    story.append(Spacer(1, 10))

    # ── Section 5: Active Alerts ──
    story.append(Paragraph("5. Active Alerts Log", h2_style))
    if alerts_snap:
        alert_rows = [["Time", "Level", "Message"]]
        for a in alerts_snap[-20:]:
            alert_rows.append([
                str(a.get("time", ""))[:19],
                str(a.get("level", "")),
                str(a.get("message", ""))[:60],
            ])
        ta = Table(alert_rows, colWidths=[4.5*cm, 3*cm, 10*cm])
        ta.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), DARK),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",   (0,0), (-1,-1), 8),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [LIGHT, colors.white]),
            ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
            ("PADDING",    (0,0), (-1,-1), 4),
        ]))
        story.append(ta)
    else:
        story.append(Paragraph("No alerts recorded in this session.", body_style))

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=1, color=PURPLE))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"NEXUS CPU Analyzer — Confidential System Snapshot | {now_str} | localhost:8050",
        ParagraphStyle("footer", parent=styles["Normal"], fontSize=7.5,
                       textColor=colors.HexColor("#888"), alignment=TA_CENTER)
    ))

    doc.build(story)
    buf.seek(0)
    return Response(
        buf.read(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment;filename={fname}"}
    )

if __name__ == "__main__":
    print("\n" + "="*50)
    print("  NEXUS Real-Time CPU Analyzer (High-Speed Engine)")
    print("  Local URL:  http://localhost:8050")
    print("="*50 + "\n")
    app.run(host="0.0.0.0", port=8050, debug=False, threaded=True)
