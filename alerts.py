"""
alerts.py — Email alert system
Two alert types:
  1. OBSTRUCTION  — ROI suddenly goes dark/blocked (haath, object)
  2. NO TEXT      — ROI was working but text stopped appearing
"""
import smtplib
import threading
import numpy as np
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime


# ── Obstruction detection thresholds ─────────────────────────
# If mean brightness of ROI drops below this → blocked
DARK_THRESHOLD    = 40       # 0–255, lower = more sensitive
# How many consecutive dark frames before alert fires
DARK_FRAMES_NEEDED = 8       # ~at FRAME_SKIP=5 this is ~2–3 sec of dark


class AlertManager:
    def __init__(self, cfg):
        self.enabled   = cfg.getboolean("ALERTS", "enabled",    fallback=False)
        self.host      = cfg.get("ALERTS", "smtp_host",         fallback="smtp.gmail.com")
        self.port      = cfg.getint("ALERTS", "smtp_port",      fallback=587)
        self.user      = cfg.get("ALERTS", "smtp_user",         fallback="")
        self.password  = cfg.get("ALERTS", "smtp_password",     fallback="")
        self.alert_to  = cfg.get("ALERTS", "alert_to",          fallback="")
        self.no_text_s = cfg.getint("ALERTS", "no_text_alert_seconds", fallback=10)

        # ── Per-ROI state ─────────────────────────────────────
        # No-text tracking
        self._last_detected : dict = {}   # roi_id → datetime
        self._no_text_alerted: dict = {}  # roi_id → bool

        # Obstruction tracking
        self._dark_count    : dict = {}   # roi_id → consecutive dark frames
        self._obs_alerted   : dict = {}   # roi_id → bool (prevent spam)
        self._obs_cleared   : dict = {}   # roi_id → bool (cleared state)

    # ── PUBLIC API ────────────────────────────────────────────

    def on_detection(self, roi_id: int):
        """Call whenever a text is confirmed in an ROI — resets no-text timer."""
        self._last_detected[roi_id]   = datetime.now()
        self._no_text_alerted[roi_id] = False

    def check_obstruction(self, roi_id: int, roi_crop) -> bool:
        """
        Call every OCR frame with the raw (non-preprocessed) ROI crop.
        Returns True if obstruction is detected.
        Fires alert email automatically after DARK_FRAMES_NEEDED frames.
        """
        if roi_crop is None or roi_crop.size == 0:
            return False

        gray       = roi_crop if len(roi_crop.shape) == 2 \
                     else __import__('cv2').cvtColor(roi_crop, __import__('cv2').COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))
        is_dark    = brightness < DARK_THRESHOLD

        count = self._dark_count.get(roi_id, 0)

        if is_dark:
            count += 1
            self._dark_count[roi_id] = count

            # Fire alert after enough dark frames
            if count >= DARK_FRAMES_NEEDED and not self._obs_alerted.get(roi_id, False):
                self._obs_alerted[roi_id] = True
                self._obs_cleared[roi_id] = False
                self._send_async(
                    subject=f"[OCR ALERT] roi_{roi_id} — Camera BLOCKED / Obstructed!",
                    body=(
                        f"⚠️  OBSTRUCTION DETECTED\n"
                        f"{'='*40}\n"
                        f"ROI ID   : roi_{roi_id}\n"
                        f"Time     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"Brightness: {brightness:.1f} (threshold: {DARK_THRESHOLD})\n\n"
                        f"The camera view appears to be blocked by an object or hand.\n"
                        f"Please check the camera immediately.\n"
                    )
                )
            return True

        else:
            # Camera cleared — reset and send recovery alert if was blocked
            if self._obs_alerted.get(roi_id, False) \
                    and not self._obs_cleared.get(roi_id, False):
                self._obs_cleared[roi_id] = True
                self._send_async(
                    subject=f"[OCR ALERT] roi_{roi_id} — Camera RESTORED ✓",
                    body=(
                        f"✅  OBSTRUCTION CLEARED\n"
                        f"{'='*40}\n"
                        f"ROI ID   : roi_{roi_id}\n"
                        f"Time     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        f"Camera view has been restored. System is back to normal.\n"
                    )
                )
                self._obs_alerted[roi_id] = False

            self._dark_count[roi_id] = 0
            return False

    def check_no_text_alerts(self, rois: list):
        """
        Call periodically. Fires alert if text was detected before
        but has stopped for no_text_s seconds.
        """
        if not self.enabled:
            return
        now = datetime.now()
        for r in rois:
            rid  = r["id"]
            last = self._last_detected.get(rid)

            # Never detected anything yet — start the clock now
            if last is None:
                self._last_detected[rid] = now
                continue

            elapsed = (now - last).total_seconds()

            # Skip if ROI is obstructed (separate alert handles that)
            if self._obs_alerted.get(rid, False):
                continue

            if elapsed > self.no_text_s \
                    and not self._no_text_alerted.get(rid, False):
                self._no_text_alerted[rid] = True
                self._send_async(
                    subject=f"[OCR ALERT] roi_{rid} — No Text Detected!",
                    body=(
                        f"⚠️  NO TEXT DETECTED\n"
                        f"{'='*40}\n"
                        f"ROI ID      : roi_{rid}\n"
                        f"MQTT Topic  : {r['topic']}\n"
                        f"Last detect : {last.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"Elapsed     : {int(elapsed)} seconds\n\n"
                        f"No text has been detected in this ROI for over "
                        f"{self.no_text_s} seconds.\n"
                        f"Please check the production line / camera position.\n"
                    )
                )

    def send_custom(self, subject: str, body: str):
        self._send_async(subject, body)

    # ── INTERNAL ──────────────────────────────────────────────

    def _send_async(self, subject: str, body: str):
        t = threading.Thread(target=self._send, args=(subject, body), daemon=True)
        t.start()

    def _send(self, subject: str, body: str):
        if not self.enabled:
            print(f"[ALERT] (disabled) Would send: {subject}")
            return
        if not self.user or not self.alert_to:
            print(f"[ALERT] Email not configured — skipping: {subject}")
            return
        try:
            msg = MIMEMultipart()
            msg["From"]    = self.user
            msg["To"]      = self.alert_to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(self.host, self.port, timeout=15) as server:
                server.starttls()
                server.login(self.user, self.password)
                server.sendmail(self.user, self.alert_to, msg.as_string())
            print(f"[ALERT] ✓ Email sent → {subject}")
        except Exception as e:
            print(f"[ALERT] ✗ Email failed: {e}")
