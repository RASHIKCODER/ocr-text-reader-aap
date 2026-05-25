"""
server.py — Web dashboard + REST API
Run alongside main.py in a separate thread
"""
from flask import Flask, jsonify, render_template_string, Response
import threading
import time

app = Flask(__name__)

# ── Frame buffer shared between main loop and Flask ──────────
# Both threads hold a reference to this same object.
class _FrameBuf:
    def __init__(self):
        self._jpeg = None
        self._lock = threading.Lock()
    def write(self, data: bytes):
        with self._lock:
            self._jpeg = data
    def read(self):
        with self._lock:
            return self._jpeg

frame_buf = _FrameBuf()   # imported by main.py

# Shared state — injected from main.py
_state = {
    "rois": [],
    "db":   None,
}

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OCR Vision — Factory Dashboard</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;400;600;700&display=swap');

  :root {
    --bg:      #0a0c10;
    --panel:   #111318;
    --border:  #1e2330;
    --accent:  #00e5ff;
    --accent2: #ff6b35;
    --green:   #00ff88;
    --text:    #c8d0e0;
    --dim:     #4a5568;
    --danger:  #ff3b5c;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Barlow', sans-serif;
    font-size: 14px;
    min-height: 100vh;
  }

  /* scanline effect */
  body::before {
    content:'';
    position:fixed; inset:0; pointer-events:none; z-index:999;
    background: repeating-linear-gradient(
      0deg, transparent, transparent 2px,
      rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px
    );
  }

  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 28px;
    border-bottom: 1px solid var(--border);
    background: var(--panel);
  }

  .logo {
    font-family: 'Share Tech Mono', monospace;
    font-size: 20px;
    color: var(--accent);
    letter-spacing: 3px;
  }
  .logo span { color: var(--accent2); }

  .status-dot {
    width: 10px; height: 10px; border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 8px var(--green);
    animation: pulse 2s infinite;
    display: inline-block; margin-right: 8px;
  }

  @keyframes pulse {
    0%,100% { opacity:1; } 50% { opacity:0.4; }
  }

  .grid {
    display: grid;
    grid-template-columns: 1fr 380px;
    grid-template-rows: auto 1fr;
    gap: 16px;
    padding: 16px 28px;
    height: calc(100vh - 65px);
  }

  .panel {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 4px;
    overflow: hidden;
  }

  .panel-header {
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    letter-spacing: 2px;
    color: var(--accent);
    display: flex; justify-content: space-between; align-items: center;
  }

  /* Camera feed */
  .camera-panel {
    grid-row: 1 / 3;
  }

  #camera-feed {
    width: 100%; height: calc(100% - 40px);
    object-fit: contain;
    background: #000;
    display: block;
  }

  /* Stats */
  .stats-grid {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 10px; padding: 14px;
  }

  .stat-box {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 12px;
    text-align: center;
  }

  .stat-box .val {
    font-family: 'Share Tech Mono', monospace;
    font-size: 28px;
    color: var(--accent);
    line-height: 1;
  }

  .stat-box .lbl {
    font-size: 10px;
    letter-spacing: 1px;
    color: var(--dim);
    margin-top: 4px;
  }

  /* ROI list */
  .roi-list { padding: 10px; overflow-y: auto; max-height: 300px; }

  .roi-item {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 3px;
    margin-bottom: 6px;
    transition: border-color 0.2s;
  }

  .roi-item:hover { border-color: var(--accent); }

  .roi-dot {
    width: 8px; height: 8px; border-radius: 50%;
    flex-shrink: 0;
  }

  .roi-name {
    font-family: 'Share Tech Mono', monospace;
    font-size: 12px;
    color: var(--accent);
    flex: 1;
  }

  .roi-count {
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    color: var(--green);
  }

  /* Log */
  .log-panel { grid-column: 2; }

  #log-table {
    width: 100%; border-collapse: collapse;
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
  }

  #log-table th {
    text-align: left; padding: 6px 10px;
    color: var(--dim); letter-spacing: 1px;
    border-bottom: 1px solid var(--border);
    font-weight: 400;
  }

  #log-table td {
    padding: 5px 10px;
    border-bottom: 1px solid rgba(30,35,48,0.5);
    color: var(--text);
  }

  #log-table tr:hover td { background: rgba(0,229,255,0.03); }

  .tag-roi {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 2px;
    font-size: 10px;
    border: 1px solid;
    color: var(--accent);
    border-color: var(--accent);
  }

  .log-body { overflow-y: auto; max-height: 340px; }

  .no-data {
    text-align:center; padding:30px;
    color: var(--dim); font-family: 'Share Tech Mono', monospace;
    font-size: 12px;
  }
</style>
</head>
<body>
<header>
  <div class="logo">OCR<span>.</span>VISION <span style="font-size:12px;color:var(--dim)">FACTORY INTELLIGENCE</span></div>
  <div style="display:flex;align-items:center;gap:20px">
    <div style="font-family:'Share Tech Mono',monospace;font-size:11px;color:var(--dim)" id="clock"></div>
    <div><span class="status-dot"></span><span style="font-size:12px;color:var(--green)">SYSTEM ONLINE</span></div>
  </div>
</header>

<div class="grid">
  <!-- Camera -->
  <div class="panel camera-panel">
    <div class="panel-header">
      <span>▶ LIVE CAMERA FEED</span>
      <span id="fps-label" style="color:var(--dim)">--</span>
    </div>
    <img id="camera-feed" src="/video_feed" alt="Camera Feed">
  </div>

  <!-- Stats -->
  <div class="panel">
    <div class="panel-header">◈ DETECTION STATS</div>
    <div class="stats-grid">
      <div class="stat-box">
        <div class="val" id="stat-total">--</div>
        <div class="lbl">TOTAL DETECTIONS</div>
      </div>
      <div class="stat-box">
        <div class="val" id="stat-today">--</div>
        <div class="lbl">TODAY</div>
      </div>
      <div class="stat-box">
        <div class="val" id="stat-rois">--</div>
        <div class="lbl">ACTIVE ROIs</div>
      </div>
      <div class="stat-box">
        <div class="val" id="stat-last">--</div>
        <div class="lbl">LAST DETECT (s)</div>
      </div>
    </div>

    <div class="panel-header" style="margin-top:4px">◈ ROI STATUS</div>
    <div class="roi-list" id="roi-list">
      <div class="no-data">No ROIs configured</div>
    </div>
  </div>

  <!-- Log -->
  <div class="panel log-panel">
    <div class="panel-header">
      <span>◈ DETECTION LOG</span>
      <span style="color:var(--dim)">LAST 1 HOUR</span>
    </div>
    <div class="log-body">
      <table id="log-table">
        <thead>
          <tr>
            <th>TIME</th>
            <th>ROI</th>
            <th>TEXT</th>
          </tr>
        </thead>
        <tbody id="log-body">
          <tr><td colspan="3" class="no-data">Loading...</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<script>
  // Clock
  const clock = document.getElementById('clock');
  setInterval(() => {
    clock.textContent = new Date().toLocaleTimeString('en-IN', {hour12: false});
  }, 1000);

  // ROI colors (match Python)
  const ROI_COLORS = [
    '#ffa500','#0000ff','#ffff00','#ff00ff',
    '#00ff00','#8000ff','#0080ff','#ff8000'
  ];

  let lastDetectTime = null;

  async function refresh() {
    try {
      const [statsRes, logsRes, roisRes] = await Promise.all([
        fetch('/api/stats'), fetch('/api/logs?hours=1'), fetch('/api/rois')
      ]);
      const stats = await statsRes.json();
      const logs  = await logsRes.json();
      const rois  = await roisRes.json();

      // Stats
      document.getElementById('stat-total').textContent = stats.total ?? '--';
      document.getElementById('stat-today').textContent = stats.today ?? '--';
      document.getElementById('stat-rois').textContent  = rois.length;

      if (logs.length > 0) {
        lastDetectTime = new Date(logs[0].timestamp);
      }
      if (lastDetectTime) {
        const secs = Math.round((Date.now() - lastDetectTime) / 1000);
        document.getElementById('stat-last').textContent = secs;
      }

      // ROI list
      const roiList = document.getElementById('roi-list');
      if (rois.length === 0) {
        roiList.innerHTML = '<div class="no-data">No ROIs configured</div>';
      } else {
        roiList.innerHTML = rois.map((r,i) => `
          <div class="roi-item">
            <div class="roi-dot" style="background:${ROI_COLORS[i % ROI_COLORS.length]};box-shadow:0 0 6px ${ROI_COLORS[i % ROI_COLORS.length]}"></div>
            <div class="roi-name">roi_${r.id}</div>
            <div style="font-size:10px;color:var(--dim);flex:1">${r.topic}</div>
            <div class="roi-count">${r.confirmed} ✓</div>
          </div>
        `).join('');
      }

      // Log table
      const tbody = document.getElementById('log-body');
      if (logs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="no-data">No detections yet</td></tr>';
      } else {
        tbody.innerHTML = logs.slice(0, 100).map(l => `
          <tr>
            <td>${l.timestamp.split('T')[1] ?? l.timestamp}</td>
            <td><span class="tag-roi">${l.roi_name}</span></td>
            <td>${l.text}</td>
          </tr>
        `).join('');
      }
    } catch(e) {
      console.error('Refresh error', e);
    }
  }

  refresh();
  setInterval(refresh, 3000);
</script>
</body>
</html>
"""


def init_server(state: dict):
    """Inject shared state from main.py (rois + db only)."""
    _state["rois"] = state.get("rois", [])
    _state["db"]   = state.get("db")


@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)


@app.route("/video_feed")
def video_feed():
    def gen():
        last = None
        while True:
            jpeg = frame_buf.read()
            if jpeg and jpeg is not last:
                last = jpeg
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                       + jpeg + b"\r\n")
            time.sleep(0.033)   # ~30 fps cap
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/stats")
def api_stats():
    db = _state.get("db")
    if db is None:
        return jsonify({"total": 0, "today": 0})
    return jsonify(db.stats())


@app.route("/api/logs")
def api_logs():
    from flask import request
    hours = int(request.args.get("hours", 1))
    roi_id = request.args.get("roi_id", type=int)
    db = _state.get("db")
    if db is None:
        return jsonify([])
    return jsonify(db.recent(hours=hours, roi_id=roi_id))


@app.route("/api/rois")
def api_rois():
    rois = _state.get("rois", [])
    return jsonify([
        {
            "id":        r["id"],
            "topic":     r["topic"],
            "rect":      list(r["rect"]),
            "confirmed": len(r["confirmed"]),
        }
        for r in rois
    ])


def run_server(host="0.0.0.0", port=5000):
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host=host, port=port, threaded=True, use_reloader=False)