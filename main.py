"""
main.py — OCR Vision System  |  Factory Intelligence Platform
Run: python main.py
Dashboard: http://localhost:5000
"""
import cv2
import easyocr

import paho.mqtt.client as mqtt
import time
import re
import threading
import configparser
import numpy as np
from collections import Counter
from datetime import datetime
from pathlib import Path

from db           import Database
from alerts       import AlertManager
from server       import init_server, run_server, frame_buf
from setup_wizard import SetupWizard, needs_setup

# ================================================================
#  SETUP WIZARD (runs if config missing or email not set)
# ================================================================
if needs_setup():
    print("[SETUP] Opening configuration wizard...")
    wizard = SetupWizard()
    ok     = wizard.run()
    if not ok:
        print("[SETUP] Setup cancelled. Exiting.")
        exit(0)
    print("[SETUP] Configuration saved!")

# ================================================================
#  LOAD CONFIG
# ================================================================
cfg = configparser.ConfigParser()
cfg.read("config.ini")

BROKER       = cfg.get("MQTT", "broker")
PORT         = cfg.getint("MQTT", "port")
USERNAME     = cfg.get("MQTT", "username")
PASSWORD     = cfg.get("MQTT", "password")
BASE_TOPIC   = cfg.get("MQTT", "base_topic")

CAM_SRC      = cfg.get("CAMERA", "source")
CAM_SRC      = int(CAM_SRC) if CAM_SRC.isdigit() else CAM_SRC
CAM_W        = cfg.getint("CAMERA", "width",  fallback=1280)
CAM_H        = cfg.getint("CAMERA", "height", fallback=720)

CONF_THRESH  = cfg.getfloat("OCR", "confidence_threshold", fallback=0.65)
MIN_LEN      = cfg.getint("OCR",   "min_text_length",      fallback=3)
FRAME_SKIP   = cfg.getint("OCR",   "frame_skip",           fallback=5)
CONFIRM_FRAMES = cfg.getint("OCR", "confirm_frames",       fallback=1)
LANGUAGE     = cfg.get("OCR",      "language",             fallback="en")

DB_PATH      = cfg.get("LOGGING",  "db_path",              fallback="data/detections.db")
RETAIN_DAYS  = cfg.getint("LOGGING","retention_days",      fallback=30)

MQTT_INTERVAL = 10
WINDOW_NAME   = "OCR Vision  |  N=New ROI  D=Delete  C=ClearAll  S=Screenshot  Q=Quit"

ROI_COLORS = [
    (0,   165, 255),
    (255, 0,   0  ),
    (0,   255, 255),
    (255, 0,   255),
    (0,   255, 0  ),
    (128, 0,   255),
    (0,   128, 255),
    (255, 128, 0  ),
]

# ================================================================
#  INIT SERVICES
# ================================================================
Path("data").mkdir(exist_ok=True)
Path("screenshots").mkdir(exist_ok=True)

db      = Database(DB_PATH, RETAIN_DAYS)
alertmgr = AlertManager(cfg)

mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(USERNAME, PASSWORD)
try:
    mqtt_client.connect(BROKER, PORT, 60)
    mqtt_client.loop_start()
    print(f"[MQTT] Connected → {BROKER}:{PORT}")
except Exception as e:
    print(f"[MQTT] Connection failed: {e} — running without MQTT")

reader = easyocr.Reader([LANGUAGE], gpu=False)
print("[OCR] EasyOCR ready")

# ================================================================
#  ROI STATE
# ================================================================
rois: list = []

drawing   = False
roi_start = (-1, -1)
roi_temp  = None
roi_mode  = False

shared_state = {
    "rois": rois,
    "db":   db,
}
init_server(shared_state)


def make_roi(rect):
    idx   = len(rois) + 1
    color = ROI_COLORS[(idx - 1) % len(ROI_COLORS)]
    rois.append({
        "id":            idx,
        "rect":          rect,
        "topic":         f"{BASE_TOPIC}/roi_{idx}",
        "color":         color,
        "frame_counter": Counter(),
        "confirmed":     set(),
        "last_boxes":    [],
        "last_seen":     None,
        "blocked":       False,
    })
    db.save_roi_config(rois)
    print(f"[ROI] roi_{idx} created → {BASE_TOPIC}/roi_{idx}")


def mouse_callback(event, x, y, flags, param):
    global drawing, roi_start, roi_temp, roi_mode
    if not roi_mode:
        return
    if event == cv2.EVENT_LBUTTONDOWN:
        drawing, roi_start, roi_temp = True, (x, y), None
    elif event == cv2.EVENT_MOUSEMOVE and drawing:
        roi_temp = (roi_start[0], roi_start[1], x, y)
    elif event == cv2.EVENT_LBUTTONUP:
        drawing  = False
        x1 = min(roi_start[0], x);  y1 = min(roi_start[1], y)
        x2 = max(roi_start[0], x);  y2 = max(roi_start[1], y)
        roi_temp = None;  roi_mode = False
        if (x2-x1) > 10 and (y2-y1) > 10:
            make_roi((x1, y1, x2, y2))
        else:
            print("[ROI] Too small — press N and try again")

# ================================================================
#  OCR HELPERS
# ================================================================

def preprocess(img):
    h, w = img.shape[:2]
    if w < 300 or h < 100:
        scale = max(300/w, 100/h)
        img   = cv2.resize(img, (int(w*scale), int(h*scale)),
                           interpolation=cv2.INTER_CUBIC)
    gray   = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray   = cv2.fastNlMeansDenoising(gray, h=10)
    kernel = np.array([[0,-1,0],[-1,5,-1],[0,-1,0]])
    gray   = cv2.filter2D(gray, -1, kernel)
    binary = cv2.adaptiveThreshold(gray, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 31, 10)
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)


def is_valid(text):
    t = text.strip()
    if len(t) < MIN_LEN:                                  return False
    if not re.search(r'[A-Za-z0-9]', t):                 return False
    if sum(c.isalnum() for c in t) / len(t) < 0.4:       return False
    if re.fullmatch(r'(.)\1{3,}', t):                    return False
    if len(t) > 4 and not re.search(r'[AEIOUaeiou]', t) \
            and re.fullmatch(r'[^0-9\s]+', t):           return False
    return True


def normalize(text):
    return re.sub(r'\s+', ' ', text.strip())


def run_ocr_on_roi(r, frame):
    x1, y1, x2, y2 = r["rect"]
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return

    # ── Obstruction / block check ────────────────────────────
    is_blocked   = alertmgr.check_obstruction(r["id"], crop)
    r["blocked"] = is_blocked
    if is_blocked:
        r["last_boxes"] = []   # clear stale detections
        return                 # skip OCR on blocked frame

    results     = reader.readtext(preprocess(crop))
    valid_texts = []
    boxes       = []

    for bbox, text, score in results:
        if score < CONF_THRESH:
            continue
        text = normalize(text)
        if not is_valid(text):
            continue
        valid_texts.append((text, score))
        abs_bbox = [[pt[0]+x1, pt[1]+y1] for pt in bbox]
        boxes.append((abs_bbox, text, score))

    # Decay — sirf wo keys jo is frame mein nahi aaye
    fc = r["frame_counter"]
    current_keys = {t for t, s in valid_texts}
    for k in list(fc.keys()):
        if k not in current_keys:
            fc[k] -= 1
            if fc[k] <= 0:
                del fc[k]

    # Confirm
    for text, score in valid_texts:
        fc[text] += 1
        if fc[text] >= CONFIRM_FRAMES:
            r["confirmed"].add(text)
            r["last_seen"] = datetime.now()
            alertmgr.on_detection(r["id"])
            db.log(r["id"], f"roi_{r['id']}", r["topic"], text, score)
            print(f"[DB] Logged: roi_{r['id']} → {text}")

    r["last_boxes"] = boxes

# ================================================================
#  DRAWING HELPERS
# ================================================================

def draw_rois(display, rois, confirmed_set_per_roi):
    for r in rois:
        x1, y1, x2, y2 = r["rect"]
        is_blocked = r.get("blocked", False)

        # Border: red pulsing if blocked, normal color otherwise
        color     = (0, 0, 255) if is_blocked else r["color"]
        thickness = 3           if is_blocked else 2
        cv2.rectangle(display, (x1,y1), (x2,y2), color, thickness)

        # Label
        label = f" roi_{r['id']} {'⚠ BLOCKED' if is_blocked else ''} "
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(display, (x1, y1-th-8), (x1+tw, y1), color, -1)
        cv2.putText(display, label, (x1, y1-4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,0,0), 1)

        # Blocked overlay on ROI area
        if is_blocked:
            overlay = display.copy()
            cv2.rectangle(overlay, (x1,y1), (x2,y2), (0,0,180), -1)
            cv2.addWeighted(overlay, 0.35, display, 0.65, 0, display)
            cx, cy = (x1+x2)//2, (y1+y2)//2
            cv2.putText(display, "BLOCKED", (cx-45, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,255), 2)
            return

        # OCR boxes
        for bbox, text, score in r["last_boxes"]:
            tl = tuple(map(int, bbox[0]))
            br = tuple(map(int, bbox[2]))
            bc = color if text in r["confirmed"] else (0, 200, 255)
            cv2.rectangle(display, tl, br, bc, 1)
            cv2.putText(display, f"{text} {score:.2f}",
                        (tl[0], tl[1]-5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48, bc, 1)


def draw_hud(display, rois, fps):
    h, w = display.shape[:2]

    # Top bar
    bar_h = 36
    overlay = display.copy()
    cv2.rectangle(overlay, (0,0), (w, bar_h), (10,12,16), -1)
    cv2.addWeighted(overlay, 0.85, display, 0.15, 0, display)

    ts  = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    cv2.putText(display, "OCR VISION SYSTEM", (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,229,255), 1)
    cv2.putText(display, ts, (w//2-80, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150,170,200), 1)
    cv2.putText(display, f"FPS:{fps:.1f}  ROIs:{len(rois)}",
                (w-170, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100,200,100), 1)

    # Bottom ROI summary
    if rois:
        summary_y = h - 10
        summary   = "  |  ".join(
            f"roi_{r['id']}: {len(r['confirmed'])} confirmed"
            for r in rois
        )
        cv2.putText(display, summary, (10, summary_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (130,140,160), 1)


# ================================================================
#  START DASHBOARD SERVER
# ================================================================
server_thread = threading.Thread(
    target=run_server,
    kwargs={
        "host": cfg.get("SERVER","host", fallback="0.0.0.0"),
        "port": cfg.getint("SERVER","port", fallback=5000),
    },
    daemon=True
)
server_thread.start()
print("[SERVER] Dashboard → http://localhost:5000")

# ================================================================
#  CAMERA
# ================================================================
cap = cv2.VideoCapture(CAM_SRC, cv2.CAP_FFMPEG)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAM_W)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)

cv2.namedWindow(WINDOW_NAME)
cv2.setMouseCallback(WINDOW_NAME, mouse_callback)

frame_count    = 0
last_send_time = time.time()
last_alert_check = time.time()
last_purge     = time.time()
fps_timer      = time.time()
fps            = 0.0

print("\nControls:")
print("  N → New ROI (draw)  |  D → Delete last  |  C → Clear all")
print("  S → Screenshot      |  Q → Quit")

# ================================================================
#  MAIN LOOP
# ================================================================
while True:
    ret, frame = cap.read()
    if not ret:
        print("[CAM] Frame read failed — retrying...")
        time.sleep(0.1)
        continue

    display     = frame.copy()
    frame_count += 1

    # FPS calc
    if frame_count % 30 == 0:
        fps       = 30.0 / (time.time() - fps_timer + 1e-9)
        fps_timer = time.time()

    # ── ROI drawing mode overlay ──────────────────────────────
    if roi_mode:
        ov = display.copy()
        cv2.rectangle(ov, (0,0), (display.shape[1], display.shape[0]), (0,0,0), -1)
        cv2.addWeighted(ov, 0.4, display, 0.6, 0, display)
        cv2.putText(display,
                    f"[ DRAW ROI_{len(rois)+1} ]  Click and drag — release to confirm",
                    (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,229,255), 2)
        if roi_temp:
            x1t,y1t,x2t,y2t = roi_temp
            cv2.rectangle(display, (x1t,y1t), (x2t,y2t), (0,229,255), 2)

    # ── OCR ───────────────────────────────────────────────────
    if frame_count % FRAME_SKIP == 0 and not roi_mode:
        for r in rois:
            run_ocr_on_roi(r, frame)

    # ── Draw ROIs + HUD ───────────────────────────────────────
    if not roi_mode:
        draw_rois(display, rois, None)

    draw_hud(display, rois, fps)

    # ── MQTT publish ──────────────────────────────────────────
    if time.time() - last_send_time > MQTT_INTERVAL:
        for r in rois:
            if r["confirmed"]:
                msg = ", ".join(sorted(r["confirmed"]))
                try:
                    mqtt_client.publish(r["topic"], msg)
                    print(f"[MQTT] {r['topic']} → {msg}")
                except Exception as e:
                    print(f"[MQTT] Publish error: {e}")
                r["confirmed"].clear()
        last_send_time = time.time()

    # ── Alert check ───────────────────────────────────────────
    if time.time() - last_alert_check > 10:
        alertmgr.check_no_text_alerts(rois)
        last_alert_check = time.time()

    # ── DB purge (daily) ─────────────────────────────────────
    if time.time() - last_purge > 86400:
        db.purge_old()
        last_purge = time.time()

    # ── Push frame to web dashboard ───────────────────────────
    _, jpeg = cv2.imencode(".jpg", display, [cv2.IMWRITE_JPEG_QUALITY, 75])
    frame_buf.write(jpeg.tobytes())

    # ── Show window ───────────────────────────────────────────
    cv2.imshow(WINDOW_NAME, display)
    key = cv2.waitKey(1) & 0xFF

    if key == ord('n'):
        roi_mode  = True
        drawing   = False
        roi_temp  = None
        print(f"[ROI] Draw mode → will create roi_{len(rois)+1}")

    elif key == ord('d'):
        if rois:
            removed = rois.pop()
            print(f"[ROI] Deleted roi_{removed['id']}")   
            for i, r in enumerate(rois):
                r["id"]    = i + 1
                r["topic"] = f"{BASE_TOPIC}/roi_{i+1}"
            db.save_roi_config(rois)
        else:
            print("[ROI] No ROI to delete")

    elif key == ord('c'):
        rois.clear()
        print("[ROI] All ROIs cleared")

    elif key == ord('s'):
        fname = f"screenshots/{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        cv2.imwrite(fname, display)
        print(f"[SCREENSHOT] Saved → {fname}")

    elif key == ord('q'):
        break

# ================================================================
#  CLEANUP
# ================================================================
cap.release()
cv2.destroyAllWindows()
mqtt_client.loop_stop()
mqtt_client.disconnect()
print("System stopped.")