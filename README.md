# OCR Vision — Factory Intelligence System

Real-time text detection from cameras with MQTT integration,
web dashboard, data logging, and email alerts.

---

## Quick Start

### 1. Install
```bash
pip install -r requirements.txt
```

### 2. Configure
Edit `config.ini` with your MQTT broker, camera, and email settings.

### 3. Run
```bash
# Linux / Mac
./start.sh

# Windows
start.bat

# Direct
python main.py
```

### 4. Open Dashboard
```
http://localhost:5000
```

---

## Controls (Camera Window)

| Key | Action |
|-----|--------|
| `N` | Draw new ROI (click + drag) |
| `D` | Delete last ROI |
| `C` | Clear all ROIs |
| `S` | Save screenshot |
| `Q` | Quit |

---

## Features

- **Unlimited ROIs** — each gets its own MQTT topic (`ocr/detections/roi_1`, etc.)
- **Smart filtering** — eliminates false/garbage text detections
- **Web Dashboard** — live camera feed, detection log, stats
- **SQLite Logging** — every detection saved with timestamp
- **Email Alerts** — notified if a ROI stops detecting text
- **Auto-purge** — old data cleaned up automatically
- **Screenshot** — save annotated frames anytime

---

## MQTT Topics

```
ocr/detections/roi_1   ← ROI 1 detections
ocr/detections/roi_2   ← ROI 2 detections
ocr/detections/roi_N   ← ROI N detections
```

---

## File Structure

```
ocr_system/
├── main.py          ← Main application
├── server.py        ← Web dashboard + REST API
├── db.py            ← SQLite database manager
├── alerts.py        ← Email alert system
├── config.ini       ← All settings (edit this)
├── requirements.txt ← Python dependencies
├── start.sh         ← Linux/Mac auto-start
├── start.bat        ← Windows auto-start
├── data/            ← SQLite database (auto-created)
└── screenshots/     ← Saved screenshots (auto-created)
```

---

## REST API

| Endpoint | Description |
|----------|-------------|
| `GET /api/stats` | Total detections, today's count |
| `GET /api/logs?hours=1` | Recent detections log |
| `GET /api/rois` | Active ROI list |
| `GET /video_feed` | MJPEG camera stream |
