"""
db.py — SQLite logging for OCR detections
"""
import sqlite3
import threading
from datetime import datetime, timedelta


class Database:
    def __init__(self, db_path: str, retention_days: int = 30):
        self.db_path       = db_path
        self.retention_days = retention_days
        self._lock         = threading.Lock()
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._lock, self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS detections (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp  TEXT    NOT NULL,
                    roi_id     INTEGER NOT NULL,
                    roi_name   TEXT    NOT NULL,
                    topic      TEXT    NOT NULL,
                    text       TEXT    NOT NULL,
                    confidence REAL    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS roi_config (
                    id        INTEGER PRIMARY KEY,
                    roi_name  TEXT NOT NULL,
                    x1 INTEGER, y1 INTEGER,
                    x2 INTEGER, y2 INTEGER,
                    topic     TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_ts    ON detections(timestamp);
                CREATE INDEX IF NOT EXISTS idx_roi   ON detections(roi_id);
                CREATE INDEX IF NOT EXISTS idx_topic ON detections(topic);
            """)

    def log(self, roi_id: int, roi_name: str, topic: str,
            text: str, confidence: float):
        ts = datetime.now().isoformat(timespec='seconds')
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO detections "
                "(timestamp, roi_id, roi_name, topic, text, confidence) "
                "VALUES (?,?,?,?,?,?)",
                (ts, roi_id, roi_name, topic, text, confidence)
            )

    def save_roi_config(self, rois: list):
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM roi_config")
            for r in rois:
                x1, y1, x2, y2 = r["rect"]
                conn.execute(
                    "INSERT INTO roi_config "
                    "(id, roi_name, x1, y1, x2, y2, topic, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (r["id"], f"roi_{r['id']}", x1, y1, x2, y2,
                     r["topic"], datetime.now().isoformat(timespec='seconds'))
                )

    def recent(self, hours: int = 1, roi_id: int = None) -> list:
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        with self._lock, self._conn() as conn:
            if roi_id:
                rows = conn.execute(
                    "SELECT * FROM detections WHERE timestamp > ? AND roi_id = ? "
                    "ORDER BY timestamp DESC LIMIT 500",
                    (since, roi_id)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM detections WHERE timestamp > ? "
                    "ORDER BY timestamp DESC LIMIT 500",
                    (since,)
                ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        with self._lock, self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
            today = conn.execute(
                "SELECT COUNT(*) FROM detections WHERE timestamp > ?",
                (datetime.now().date().isoformat(),)
            ).fetchone()[0]
            per_roi = conn.execute(
                "SELECT roi_name, COUNT(*) as cnt FROM detections "
                "GROUP BY roi_name ORDER BY cnt DESC"
            ).fetchall()
            top_texts = conn.execute(
                "SELECT text, COUNT(*) as cnt FROM detections "
                "GROUP BY text ORDER BY cnt DESC LIMIT 10"
            ).fetchall()
        return {
            "total":    total,
            "today":    today,
            "per_roi":  [dict(r) for r in per_roi],
            "top_texts": [dict(r) for r in top_texts],
        }

    def purge_old(self):
        cutoff = (datetime.now() - timedelta(days=self.retention_days)).isoformat()
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM detections WHERE timestamp < ?", (cutoff,))
