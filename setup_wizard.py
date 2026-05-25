"""
setup_wizard.py — First-time setup GUI
Automatically runs if config.ini is missing or incomplete.
"""
import tkinter as tk
from tkinter import ttk, messagebox
import configparser
import threading
import smtplib
from pathlib import Path


BG       = "#0d1117"
PANEL    = "#161b22"
BORDER   = "#30363d"
ACCENT   = "#00e5ff"
TEXT     = "#e6edf3"
DIM      = "#8b949e"
GREEN    = "#3fb950"
RED      = "#f85149"
FONT     = ("Consolas", 10)
FONT_LG  = ("Consolas", 13, "bold")
FONT_SM  = ("Consolas", 9)


class SetupWizard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("OCR Vision — First Time Setup")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        # Center window
        w, h = 560, 680
        sw   = self.root.winfo_screenwidth()
        sh   = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        self._build()
        self._load_existing()

    # ── UI BUILD ──────────────────────────────────────────────

    def _build(self):
        # Header
        hdr = tk.Frame(self.root, bg="#0a0e14", pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="OCR VISION SYSTEM",
                 font=("Consolas", 16, "bold"),
                 fg=ACCENT, bg="#0a0e14").pack()
        tk.Label(hdr, text="Initial Configuration",
                 font=FONT_SM, fg=DIM, bg="#0a0e14").pack()

        # Scrollable body
        canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(self.root, orient="vertical",
                               command=canvas.yview)
        self.body = tk.Frame(canvas, bg=BG, padx=24, pady=10)
        self.body.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=self.body, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # Sections
        self.vars = {}
        self._section("MQTT Broker", [
            ("broker",     "Broker Address",  "mqtt.sar-analytic.in"),
            ("port",       "Port",            "1883"),
            ("username",   "Username",        "mqtt"),
            ("password",   "Password",        "mqtt",  True),
            ("base_topic", "Base Topic",      "ocr/detections"),
        ])

        self._section("Camera", [
            ("source", "Camera Source (0=webcam, or RTSP URL)", "0"),
            ("width",  "Width",   "1280"),
            ("height", "Height",  "720"),
        ])

        self._section("OCR Settings", [
            ("confidence_threshold", "Confidence Threshold (0.5–0.9)", "0.65"),
            ("min_text_length",      "Min Text Length",                "3"),
            ("frame_skip",           "Frame Skip (higher=faster)",     "5"),
            ("confirm_frames",       "Confirm Frames (anti-flicker)",  "3"),
        ])

        self._section("Email Alerts", [
            ("smtp_host",     "SMTP Host",          "smtp.gmail.com"),
            ("smtp_port",     "SMTP Port",          "587"),
            ("smtp_user",     "Your Email Address", ""),
            ("smtp_password", "App Password",       "", True),
            ("alert_to",      "Send Alerts To",     ""),
            ("no_text_alert_seconds",
                              "Alert if no text for (seconds)", "30"),
        ])

        # Email alerts toggle
        self.alerts_enabled = tk.BooleanVar(value=True)
        tf = tk.Frame(self.body, bg=BG)
        tf.pack(fill="x", pady=(0,10))
        tk.Checkbutton(tf, text="Enable Email Alerts",
                       variable=self.alerts_enabled,
                       bg=BG, fg=TEXT, selectcolor=PANEL,
                       activebackground=BG, activeforeground=ACCENT,
                       font=FONT, command=self._toggle_email).pack(side="left")

        # Test email button
        self.test_btn = tk.Button(
            tf, text="Test Email",
            command=self._test_email,
            bg=PANEL, fg=ACCENT, font=FONT_SM,
            relief="flat", padx=10, cursor="hand2",
            activebackground=BORDER, activeforeground=ACCENT
        )
        self.test_btn.pack(side="right")

        self.email_status = tk.Label(self.body, text="",
                                     font=FONT_SM, bg=BG)
        self.email_status.pack(fill="x")

        self._section("Dashboard Server", [
            ("host", "Host (0.0.0.0 = all interfaces)", "0.0.0.0"),
            ("port_server", "Dashboard Port", "5000"),
        ])

        # Save button
        btn_frame = tk.Frame(self.root, bg=BG, pady=14)
        btn_frame.pack(fill="x", padx=24)

        self.save_btn = tk.Button(
            btn_frame, text="SAVE & LAUNCH",
            command=self._save,
            bg=ACCENT, fg="#000", font=("Consolas", 11, "bold"),
            relief="flat", pady=10, cursor="hand2",
            activebackground="#00b8cc", activeforeground="#000"
        )
        self.save_btn.pack(fill="x")

        self.status_lbl = tk.Label(btn_frame, text="",
                                   font=FONT_SM, bg=BG)
        self.status_lbl.pack(pady=4)

    def _section(self, title: str, fields: list):
        # Section header
        hdr = tk.Frame(self.body, bg=BORDER, height=1)
        hdr.pack(fill="x", pady=(14, 0))
        tk.Label(self.body, text=f"  {title}  ",
                 font=("Consolas", 10, "bold"),
                 fg=ACCENT, bg=BG).pack(anchor="w", pady=(4, 6))

        for field in fields:
            key, label = field[0], field[1]
            default    = field[2] if len(field) > 2 else ""
            secret     = field[3] if len(field) > 3 else False

            row = tk.Frame(self.body, bg=BG)
            row.pack(fill="x", pady=3)

            tk.Label(row, text=label, font=FONT_SM,
                     fg=DIM, bg=BG, width=32, anchor="w").pack(side="left")

            var = tk.StringVar(value=default)
            self.vars[key] = var

            show = "*" if secret else ""
            entry = tk.Entry(row, textvariable=var, show=show,
                             font=FONT, fg=TEXT, bg=PANEL,
                             insertbackground=ACCENT,
                             relief="flat", bd=0,
                             highlightthickness=1,
                             highlightbackground=BORDER,
                             highlightcolor=ACCENT)
            entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(8,0))

    def _toggle_email(self):
        # Could disable email fields visually — kept simple for now
        pass

    # ── LOAD EXISTING CONFIG ──────────────────────────────────

    def _load_existing(self):
        if not Path("config.ini").exists():
            return
        cfg = configparser.ConfigParser()
        cfg.read("config.ini")

        mapping = {
            "broker":      ("MQTT",    "broker"),
            "port":        ("MQTT",    "port"),
            "username":    ("MQTT",    "username"),
            "password":    ("MQTT",    "password"),
            "base_topic":  ("MQTT",    "base_topic"),
            "source":      ("CAMERA",  "source"),
            "width":       ("CAMERA",  "width"),
            "height":      ("CAMERA", "height"),
            "confidence_threshold": ("OCR", "confidence_threshold"),
            "min_text_length":      ("OCR", "min_text_length"),
            "frame_skip":           ("OCR", "frame_skip"),
            "confirm_frames":       ("OCR", "confirm_frames"),
            "smtp_host":     ("ALERTS", "smtp_host"),
            "smtp_port":     ("ALERTS", "smtp_port"),
            "smtp_user":     ("ALERTS", "smtp_user"),
            "smtp_password": ("ALERTS", "smtp_password"),
            "alert_to":      ("ALERTS", "alert_to"),
            "no_text_alert_seconds": ("ALERTS", "no_text_alert_seconds"),
            "host":        ("SERVER",  "host"),
            "port_server": ("SERVER",  "port"),
        }
        for var_key, (section, opt) in mapping.items():
            try:
                val = cfg.get(section, opt)
                if var_key in self.vars:
                    self.vars[var_key].set(val)
            except Exception:
                pass

        try:
            en = cfg.getboolean("ALERTS", "enabled", fallback=True)
            self.alerts_enabled.set(en)
        except Exception:
            pass

    # ── TEST EMAIL ────────────────────────────────────────────

    def _test_email(self):
        self.email_status.config(text="Sending test email...", fg=DIM)
        self.test_btn.config(state="disabled")

        def do_test():
            try:
                host  = self.vars["smtp_host"].get()
                port  = int(self.vars["smtp_port"].get())
                user  = self.vars["smtp_user"].get()
                pwd   = self.vars["smtp_password"].get()
                to    = self.vars["alert_to"].get()

                if not user or not pwd or not to:
                    raise ValueError("Fill email fields first")

                with smtplib.SMTP(host, port, timeout=10) as s:
                    s.starttls()
                    s.login(user, pwd)
                    from email.mime.text import MIMEText
                    msg = MIMEText("OCR Vision test email — configuration successful!")
                    msg["Subject"] = "[OCR Vision] Test Alert"
                    msg["From"]    = user
                    msg["To"]      = to
                    s.sendmail(user, to, msg.as_string())

                self.root.after(0, lambda: self.email_status.config(
                    text="✓ Test email sent successfully!", fg=GREEN))
            except Exception as e:
                self.root.after(0, lambda: self.email_status.config(
                    text=f"✗ Failed: {e}", fg=RED))
            finally:
                self.root.after(0, lambda: self.test_btn.config(state="normal"))

        threading.Thread(target=do_test, daemon=True).start()

    # ── SAVE ─────────────────────────────────────────────────

    def _save(self):
        v = {k: var.get().strip() for k, var in self.vars.items()}

        # Basic validation
        errors = []
        if not v["broker"]:
            errors.append("MQTT Broker is required")
        if not v["port"].isdigit():
            errors.append("MQTT Port must be a number")
        try:
            float(v["confidence_threshold"])
        except ValueError:
            errors.append("Confidence must be a number (e.g. 0.65)")
        if self.alerts_enabled.get():
            if not v["smtp_user"]:
                errors.append("Email address is required when alerts enabled")
            if not v["alert_to"]:
                errors.append("Alert recipient email is required")

        if errors:
            messagebox.showerror("Validation Error", "\n".join(errors))
            return

        cfg = configparser.ConfigParser()
        cfg["MQTT"] = {
            "broker":     v["broker"],
            "port":       v["port"],
            "username":   v["username"],
            "password":   v["password"],
            "base_topic": v["base_topic"],
        }
        cfg["CAMERA"] = {
            "source": v["source"],
            "width":  v["width"],
            "height": v["height"],
        }
        cfg["OCR"] = {
            "confidence_threshold": v["confidence_threshold"],
            "min_text_length":      v["min_text_length"],
            "frame_skip":           v["frame_skip"],
            "confirm_frames":       v["confirm_frames"],
            "language":             "en",
        }
        cfg["ALERTS"] = {
            "enabled":               str(self.alerts_enabled.get()).lower(),
            "smtp_host":             v["smtp_host"],
            "smtp_port":             v["smtp_port"],
            "smtp_user":             v["smtp_user"],
            "smtp_password":         v["smtp_password"],
            "alert_to":              v["alert_to"],
            "no_text_alert_seconds": v["no_text_alert_seconds"],
        }
        cfg["LOGGING"] = {
            "db_path":        "data/detections.db",
            "retention_days": "30",
        }
        cfg["SERVER"] = {
            "host": v["host"],
            "port": v["port_server"],
        }

        with open("config.ini", "w") as f:
            cfg.write(f)

        self.status_lbl.config(text="✓ Config saved! Launching...", fg=GREEN)
        self.root.after(800, self.root.destroy)

    def run(self) -> bool:
        """Returns True if user completed setup, False if closed."""
        self.root.mainloop()
        return Path("config.ini").exists()


def needs_setup() -> bool:
    """Check if setup wizard should run."""
    if not Path("config.ini").exists():
        return True
    cfg = configparser.ConfigParser()
    cfg.read("config.ini")
    # Re-run if email not configured
    try:
        user = cfg.get("ALERTS", "smtp_user", fallback="")
        if not user or user == "your@email.com":
            return True
    except Exception:
        return True
    return False


if __name__ == "__main__":
    wizard = SetupWizard()
    wizard.run()
