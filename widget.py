"""Usage Deck: always-on-top token-usage widget (Claude Code + Codex), Apple-style dark UI.
Reads local logs only; no API calls. Auto-refreshes every REFRESH_MS."""
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

HOME = Path.home()
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or HOME / ".claude") / "projects"
CLAUDE_CREDENTIALS = CLAUDE_DIR.parent / ".credentials.json"
CODEX_DIR = Path(os.environ.get("CODEX_HOME") or HOME / ".codex") / "sessions"
BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
CONFIG = BASE / "config.json"
LOGOS = BASE / "logos"
EDGES = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
REFRESH_MS = 30_000
PURE_BLACK = "#000000"  # background used by the "Pure black" style
GLASS_ACCENT = (3, 0)  # (3 = plain blur, stays dark | 4, 0xB0000000 = stronger acrylic blur but lifts blacks to grey)
GLASS_ALPHA = 0.78  # lower = more of the blurred background shows
DEFAULTS = {"x": None, "y": None, "w": 300, "compact": False,
            "glass": True,                              # true = glass, false = pure black
            "show_claude": None, "show_codex": None,   # null = auto (show if its log folder exists)
            "claude_5h_cap": None,          # null = your own peak 5h window
            "claude_7d_cap": 30_000_000,    # edit to taste (Claude logs have no official limit)
            "time_format": "24h"}           # "24h" or "12h" (am/pm)

KEY = "#010203"  # transparent colour key for rounded corners
BG, BORDER, TRACK = "#0e0e0f", "#2c2c2e", "#262628"
FG, DIM = "#f2f2f7", "#98989d"
ORANGE, BLUE, RED, YELLOW, LIGHT_GREEN = "#ff9f0a", "#0a84ff", "#ff453a", "#febc2e", "#28c840"
FONT = "Segoe UI"

_claude_cache, _codex_cache = {}, {}


def load_cfg():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG.read_text()))
    except (OSError, ValueError):
        pass
    return cfg


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def recent_files(root, days=8):
    cutoff = time.time() - days * 86400
    for p in root.rglob("*.jsonl"):
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_mtime >= cutoff:
            yield p, st.st_mtime, st.st_size


def fmt(n):
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    if n >= 1_000:
        return f"{n / 1e3:.0f}k"
    return str(int(n))


def scan_claude():
    """[(ts, tokens)] for assistant messages (input + output + cache writes)."""
    merged = {}
    for p, mtime, size in recent_files(CLAUDE_DIR):
        hit = _claude_cache.get(p)
        if hit and hit[0] == (mtime, size):
            events = hit[1]
        else:
            events = {}
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if '"usage"' not in line:
                            continue
                        try:
                            d = json.loads(line)
                        except ValueError:
                            continue
                        m = d.get("message") or {}
                        u = m.get("usage")
                        ts = d.get("timestamp")
                        if d.get("type") != "assistant" or not u or not ts:
                            continue
                        key = m.get("id") or d.get("uuid")
                        tok = (u.get("input_tokens", 0) + u.get("output_tokens", 0)
                               + u.get("cache_creation_input_tokens", 0))
                        if key not in events or tok >= events[key][1]:
                            events[key] = (parse_ts(ts), tok)
            except OSError:
                pass
            _claude_cache[p] = ((mtime, size), events)
        for k, v in events.items():
            if k not in merged or v[1] >= merged[k][1]:
                merged[k] = v
    return list(merged.values())


def scan_claude_limits():
    """Official Claude subscription usage. Never estimate limits from local logs."""
    global _last_good_rl
    try:
        auth = json.loads(CLAUDE_CREDENTIALS.read_text(encoding="utf-8"))["claudeAiOauth"]
        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={"Authorization": f"Bearer {auth['accessToken']}",
                     "anthropic-beta": "oauth-2025-04-20",
                     "User-Agent": "claude-code"})
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.load(response)
        _last_good_rl = data
        return data
    except urllib.error.HTTPError as e:
        reason = {401: "token expired", 403: "token expired", 429: "rate limited"}.get(e.code, f"HTTP {e.code}")
    except (OSError, ValueError, KeyError):
        reason = "offline"
    # Keep showing the last good reading, flagged stale, instead of blanking the bars.
    return dict(_last_good_rl or {}, _stale=reason)


_last_good_rl = None


def scan_codex():
    """([(ts, tokens)], latest_rate_limits_or_None)."""
    deltas, latest = [], None
    for p, mtime, size in recent_files(CODEX_DIR):
        hit = _codex_cache.get(p)
        if hit and hit[0] == (mtime, size):
            file_deltas, rl = hit[1]
        else:
            file_deltas, rl, prev = [], None, 0
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if "token_count" not in line:
                            continue
                        try:
                            d = json.loads(line)
                        except ValueError:
                            continue
                        pl = d.get("payload") or {}
                        if pl.get("type") != "token_count":
                            continue
                        ts = parse_ts(d["timestamp"])
                        info = pl.get("info")
                        if info:
                            t = info["total_token_usage"]
                            cur = (t.get("input_tokens", 0) - t.get("cached_input_tokens", 0)
                                   + t.get("output_tokens", 0))
                            if cur > prev:
                                file_deltas.append((ts, cur - prev))
                                prev = cur
                        if pl.get("rate_limits"):
                            rl = (ts, pl["rate_limits"])
            except OSError:
                pass
            _codex_cache[p] = ((mtime, size), (file_deltas, rl))
        deltas += file_deltas
        if rl and (latest is None or rl[0] > latest[0]):
            latest = rl
    return deltas, (latest[1] if latest else None)


def window_sum(events, since):
    return sum(t for ts, t in events if ts >= since)


def fmt_time(dt, weekly, fmt12):
    t = dt.strftime("%#I:%M %p") if fmt12 else dt.strftime("%H:%M")
    return f"{dt:%a} {t}" if weekly else t


def window_reset(events, since, span):
    """When the oldest event still inside the window falls out (i.e. window resets)."""
    ts_in_window = [ts for ts, _ in events if ts >= since]
    return (min(ts_in_window) + span).astimezone() if ts_in_window else None


def peak_window(events, hours):
    """Largest token total inside any rolling window of `hours`."""
    ev = sorted(events)
    best = lo = tot = 0
    span = timedelta(hours=hours)
    for ts, t in ev:
        tot += t
        while ev[lo][0] < ts - span:
            tot -= ev[lo][1]
            lo += 1
        best = max(best, tot)
    return best


def collect(claude=True, codex=True):
    now = datetime.now().astimezone()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    h5, d7 = now - timedelta(hours=5), now - timedelta(days=7)
    c_ev = scan_claude() if claude else []
    c_rl = scan_claude_limits() if claude else None
    x_ev, rl = scan_codex() if codex else ([], None)
    return {
        "claude": [window_sum(c_ev, today), window_sum(c_ev, h5), window_sum(c_ev, d7)],
        "claude_rl": c_rl,
        "claude_peak5h": peak_window(c_ev, 5),
        "claude_reset5": window_reset(c_ev, h5, timedelta(hours=5)),
        "claude_reset7": window_reset(c_ev, d7, timedelta(days=7)),
        "codex": [window_sum(x_ev, today), window_sum(x_ev, h5), window_sum(x_ev, d7)],
        "rl": rl,
        "now": now,
    }


def svg_to_png(svg, png, size):
    """Render an SVG to a transparent PNG with headless Edge (no extra packages)."""
    edge = next((e for e in EDGES if Path(e).exists()), None)
    if not edge:
        return False
    tmp = Path(tempfile.mkdtemp())
    html = tmp / "r.html"
    html.write_text(f'<html><body style="margin:0;background:transparent"><img src="{svg.as_uri()}" '
                    f'width="{size}" height="{size}"></body></html>')
    try:
        subprocess.run([edge, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--user-data-dir={tmp / 'p'}", "--default-background-color=00000000",
                        f"--window-size={size},{size}", f"--screenshot={png}", html.as_uri()],
                       timeout=40, creationflags=0x08000000, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return png.exists()


def stale(src, out):
    return not out.exists() or src.stat().st_mtime > out.stat().st_mtime


def ensure_logo(name, size):
    """logos/<name>.svg or .png -> PNG path (or None)."""
    svg, png = LOGOS / f"{name}.svg", LOGOS / f"{name}.png"
    if svg.exists():
        out = LOGOS / f".{name}_{size}.png"
        if stale(svg, out) and not svg_to_png(svg, out, size):
            return png if png.exists() else None
        return out
    return png if png.exists() else None


def ensure_icon():
    """logos/app.svg or app.png -> logos/app.ico (PNG-in-ICO). Returns path or None."""
    ico = LOGOS / "app.ico"
    src = ensure_logo("app", 256)
    if not src:
        return ico if ico.exists() else None
    if stale(src, ico):
        data = src.read_bytes()
        ico.write_bytes(struct.pack("<HHH", 0, 1, 1)
                        + struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(data), 22) + data)
    return ico


def rrect(cv, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


class Widget:
    PAD, MIN_W, MAX_W = 18, 260, 640

    def __init__(self):
        self.cfg = load_cfg()
        self.data = None
        self.hover = False
        self.busy = False
        self.mode = None
        r = self.root = tk.Tk()
        r.title("Token Usage")
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.attributes("-alpha", GLASS_ALPHA if self.cfg["glass"] else 1.0)
        r.configure(bg=self.bg)
        self.cv = tk.Canvas(r, bg=self.bg, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<ButtonPress-1>", self.press)
        self.cv.bind("<B1-Motion>", self.motion)
        self.cv.bind("<ButtonRelease-1>", self.release)
        self.cv.bind("<Motion>", self.hover_check)
        self.cv.bind("<Leave>", lambda e: self.set_hover(False))
        self.cv.bind("<Button-3>", self.menu)
        r.bind("<Map>", self.on_map)

        import tkinter.font as tkfont
        fams = set(tkfont.families())
        self.font = next((f for f in ("SF Pro Display", "SF Pro Text", "Segoe UI Variable Display", "Segoe UI")
                          if f in fams), "Segoe UI")
        self.logos = {}
        for n in ("claude", "codex"):
            p = ensure_logo(n, 20)
            try:
                self.logos[n] = tk.PhotoImage(file=str(p)) if p else None
            except tk.TclError:
                self.logos[n] = None
        try:
            ico = ensure_icon()
            if ico:
                r.iconbitmap(default=str(ico))
        except (OSError, tk.TclError):
            pass
        self.draw()
        r.update_idletasks()
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        x = self.cfg["x"] if self.cfg["x"] is not None else sw - self.cfg["w"] - 24
        y = self.cfg["y"] if self.cfg["y"] is not None else sh - self.h - 64
        self.cfg["x"] = max(0, min(x, sw - self.cfg["w"] - 8))  # keep on-screen
        self.cfg["y"] = max(0, min(y, sh - 120))
        r.geometry(f"+{self.cfg['x']}+{self.cfg['y']}")
        r.after(200, self.taskbar)
        self.refresh()

    # ---- data ----
    def enabled(self, name):
        v = self.cfg.get(f"show_{name}")
        if v is not None:
            return bool(v)
        return (CLAUDE_DIR if name == "claude" else CODEX_DIR).parent.exists()

    def refresh(self):
        self.root.after(REFRESH_MS, self.refresh)
        self.fetch()

    def fetch(self):
        if self.busy:
            return
        self.busy = True

        def work():
            try:
                d = collect(self.enabled("claude"), self.enabled("codex"))
                self.root.after(0, lambda: self.got(d))
            except Exception:
                self.busy = False
        threading.Thread(target=work, daemon=True).start()

    def got(self, d):
        self.busy = False
        self.data = d
        self.draw()
        self.root.update_idletasks()
        top = min(self.root.winfo_y(), self.root.winfo_screenheight() - self.h - 48)
        self.root.geometry(f"+{self.root.winfo_x()}+{max(0, top)}")

    # ---- drawing ----
    def text(self, x, y, s, size=9, fill=FG, anchor="w", weight="normal"):
        self.cv.create_text(x, y, text=s, fill=fill, anchor=anchor, font=(self.font, size, weight))

    def bar(self, y, w, frac, color, left, right):
        p = self.PAD
        self.text(p, y, left, 9, DIM)
        self.text(w - p, y, right, 9, FG, "e")
        y += 15
        x2 = w - p
        self.cv.create_line(p, y, x2, y, width=6, capstyle="round", fill=TRACK)
        frac = max(0.0, min(frac, 1.0))
        if frac > 0:
            self.cv.create_line(p, y, p + max(0.001, (x2 - p) * frac), y, width=6,
                                capstyle="round", fill=RED if frac >= 0.85 else color)
        return y + 18

    def row(self, y, w, left, right):
        self.text(self.PAD, y, left, 9, DIM)
        self.text(w - self.PAD, y, right, 9, FG, "e")
        return y + 18

    def section(self, y, title, color, logo=None):
        if logo:
            self.cv.create_image(self.PAD + 10, y, image=logo)
            self.text(self.PAD + 26, y, title, 11, FG, weight="bold")
        else:
            self.cv.create_oval(self.PAD, y - 4, self.PAD + 8, y + 4, fill=color, outline="")
            self.text(self.PAD + 15, y, title, 11, FG, weight="bold")
        return y + 22

    def draw(self):
        cv, w, p = self.cv, self.cfg["w"], self.PAD
        compact, d = self.cfg["compact"], self.data
        cv.delete("all")
        rrect(cv, 1, 1, w - 1, 9999, 12, fill=self.bg, outline=BORDER)  # trimmed after height known
        bg_id = cv.find_all()[-1]

        for i, (col, glyph) in enumerate(((RED, "×"), (YELLOW, "–"), (LIGHT_GREEN, "+"))):
            cx = p - 2 + i * 20 + 6
            cv.create_oval(cx - 6, 12, cx + 6, 24, fill=col, outline="")
            if self.hover:
                k, ink = 3, "#4a2a00"
                if i == 0:
                    cv.create_line(cx - k, 18 - k, cx + k + 1, 18 + k + 1, fill=ink, width=1.6)
                    cv.create_line(cx - k, 18 + k, cx + k + 1, 18 - k - 1, fill=ink, width=1.6)
                else:
                    cv.create_line(cx - k, 18, cx + k + 1, 18, fill=ink, width=1.6)
                    if i == 2:
                        cv.create_line(cx, 18 - k, cx, 18 + k + 1, fill=ink, width=1.6)
        self.text(w - 16, 18, "Token Usage", 9, DIM, "e")
        y = 46

        if d is None:
            self.text(p, y, "loading…", 9, DIM)
            y += 24
        else:
            now = d["now"]
            c = d["claude"]
            fmt12 = self.cfg.get("time_format") == "12h"
            if self.enabled("claude"):
                y = self.section(y, "Claude Code", ORANGE, self.logos.get("claude"))
                c_rl = d.get("claude_rl") or {}
                for name, label, weekly in (("five_hour", "5-hour limit", False),
                                            ("seven_day", "Weekly limit", True)):
                    win = c_rl.get(name)
                    stale = c_rl.get("_stale")
                    if not win or win.get("utilization") is None:
                        y = self.row(y, w, label, f"n/a ({stale})" if stale else "n/a")
                        continue
                    pct = float(win["utilization"])
                    reset = parse_ts(win["resets_at"]).astimezone() if win.get("resets_at") else None
                    tail = f"resets {fmt_time(reset, weekly, fmt12)}" if reset else ""
                    if stale:
                        tail = f"{tail} · stale: {stale}".lstrip(" ·")
                    y = self.bar(y, w, pct / 100, ORANGE, label, f"{pct:.0f}% · {tail}".rstrip(" ·"))
                if not compact:
                    y = self.row(y, w, "Today", fmt(c[0]))
                y += 8

            if self.enabled("codex"):
                x = d["codex"]
                rl = d["rl"] or {}
                y = self.section(y, "Codex", BLUE, self.logos.get("codex"))
                for name, label, weekly in (("primary", "5-hour limit", False), ("secondary", "Weekly limit", True)):
                    win = rl.get(name)
                    if not win:
                        y = self.row(y, w, label, "n/a")
                        continue
                    pct = win.get("used_percent", 0)
                    reset = datetime.fromtimestamp(win["resets_at"]).astimezone() if win.get("resets_at") else None
                    if reset and reset < now:
                        pct, tail = 0, "reset"
                    elif reset:
                        tail = f"resets {fmt_time(reset, weekly, fmt12)}"
                    else:
                        tail = ""
                    y = self.bar(y, w, pct / 100, BLUE, label, f"{pct:.0f}% · {tail}".rstrip(" ·"))
                if not compact:
                    y = self.row(y, w, "Today", fmt(x[0]))
                    y = self.row(y, w, "7 days", fmt(x[2]))
                y += 4

        if d is not None and not (self.enabled("claude") or self.enabled("codex")):
            self.text(p, y, "Nothing selected", 10, FG, weight="bold")
            self.text(p, y + 20, "Right-click to choose what to show.", 9, DIM)
            y += 40

        h = self.h = int(y + 16)
        cv.coords(bg_id, *self._rrect_pts(1, 1, w - 1, h - 1, 12))
        for k in range(3):  # resize grip
            cv.create_line(w - 8 - k * 4, h - 6, w - 6, h - 8 - k * 4, fill=DIM, width=1)
        self.grip = (w - 26, h - 26, w, h)
        cv.config(width=w, height=h)
        self.root.geometry(f"{w}x{h}")

    @staticmethod
    def _rrect_pts(x1, y1, x2, y2, r):
        return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
                x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]

    # ---- interaction ----
    def light_at(self, x, y):
        if 10 <= y <= 26:
            for i in range(3):
                cx = self.PAD - 2 + i * 20 + 6
                if abs(x - cx) <= 7:
                    return i
        return None

    def set_hover(self, v):
        if v != self.hover:
            self.hover = v
            self.draw()

    def hover_check(self, e):
        self.set_hover(10 <= e.y <= 26 and self.PAD - 8 <= e.x <= self.PAD + 50)

    def press(self, e):
        gx1, gy1, gx2, gy2 = self.grip
        light = self.light_at(e.x, e.y)
        if light is not None:
            self.mode = ("light", light)
        elif gx1 <= e.x <= gx2 and gy1 <= e.y <= gy2:
            self.mode = ("resize", e.x_root, self.cfg["w"])
        else:
            self.mode = ("drag", e.x, e.y)

    def motion(self, e):
        m = self.mode
        if not m:
            return
        if m[0] == "drag":
            self.root.geometry(f"+{self.root.winfo_x() + e.x - m[1]}+{self.root.winfo_y() + e.y - m[2]}")
        elif m[0] == "resize":
            self.cfg["w"] = max(self.MIN_W, min(self.MAX_W, m[2] + e.x_root - m[1]))
            self.draw()

    def release(self, e):
        m, self.mode = self.mode, None
        if m and m[0] == "light" and self.light_at(e.x, e.y) == m[1]:
            (self.root.destroy, self.minimize, self.toggle_compact)[m[1]]()
            if m[1] == 0:
                return
        self.save()

    def toggle_compact(self):
        self.cfg["compact"] = not self.cfg["compact"]
        self.draw()

    def minimize(self):
        import ctypes
        u = ctypes.windll.user32
        u.ShowWindow(u.GetParent(self.root.winfo_id()) or self.root.winfo_id(), 6)  # SW_MINIMIZE

    def on_map(self, e):
        if e.widget is self.root and not self.root.overrideredirect():
            self.root.after(60, self._restore_frameless)

    def _restore_frameless(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.taskbar()

    @staticmethod
    def lighten(c, k=0.45):
        rgb = [int(c[i:i + 2], 16) for i in (1, 3, 5)]
        return "#%02x%02x%02x" % tuple(int(v + (255 - v) * k) for v in rgb)

    def region(self, w, h):
        """Clip the real window to a large-radius rounded rectangle."""
        try:
            import ctypes
            u = ctypes.windll.user32
            hwnd = u.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, 52, 52)
            u.SetWindowRgn(hwnd, rgn, True)
        except Exception:
            pass

    @property
    def bg(self):
        return BG if self.cfg["glass"] else PURE_BLACK

    def set_style(self, glass):
        self.cfg["glass"] = bool(glass)
        self.root.attributes("-alpha", GLASS_ALPHA if glass else 1.0)
        self.root.configure(bg=self.bg)
        self.cv.configure(bg=self.bg)
        self.glass()
        self.save()
        self.draw()

    def glass(self):
        """Acrylic blur-behind + rounded corners (Win10 1803+/Win11)."""
        try:
            import ctypes
            from ctypes import Structure, byref, c_int, c_size_t, c_uint, c_void_p, sizeof
            u = ctypes.windll.user32
            hwnd = u.GetParent(self.root.winfo_id()) or self.root.winfo_id()

            class ACCENT(Structure):
                _fields_ = [("State", c_int), ("Flags", c_int), ("Color", c_uint), ("Anim", c_int)]

            class WCA(Structure):
                _fields_ = [("Attr", c_int), ("Data", c_void_p), ("Size", c_size_t)]

            acc = ACCENT(*(GLASS_ACCENT[0], 0, GLASS_ACCENT[1], 0) if self.cfg["glass"] else (0, 0, 0, 0))
            u.SetWindowCompositionAttribute(hwnd, byref(WCA(19, ctypes.addressof(acc), sizeof(acc))))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, byref(c_int(2)), 4)  # rounded
        except Exception:
            pass

    def taskbar(self):
        """Give the frameless window a taskbar button (so it can be pinned)."""
        try:
            import ctypes
            u = ctypes.windll.user32
            hwnd = u.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            ex = u.GetWindowLongW(hwnd, -20)
            u.SetWindowLongW(hwnd, -20, (ex & ~0x80) | 0x40000)  # -TOOLWINDOW +APPWINDOW
            u.SetWindowLongW(hwnd, -16, u.GetWindowLongW(hwnd, -16) | 0x20000 | 0x80000)  # min box + sysmenu: taskbar click minimizes
            self.root.withdraw()
            self.root.after(30, self.root.deiconify)
            self.root.after(120, self.glass)
        except Exception:
            pass

    def menu(self, e):
        m = tk.Menu(self.root, tearoff=0)
        vc, vx = tk.BooleanVar(value=self.enabled("claude")), tk.BooleanVar(value=self.enabled("codex"))
        m.add_checkbutton(label="Show Claude Code", variable=vc, command=lambda: self.set_show("claude", vc.get()))
        m.add_checkbutton(label="Show Codex", variable=vx, command=lambda: self.set_show("codex", vx.get()))
        m.add_separator()
        vs = tk.StringVar(value="glass" if self.cfg["glass"] else "black")
        m.add_radiobutton(label="Glass", variable=vs, value="glass", command=lambda: self.set_style(True))
        m.add_radiobutton(label="Pure black", variable=vs, value="black", command=lambda: self.set_style(False))
        m.add_separator()
        vt = tk.StringVar(value=self.cfg.get("time_format", "24h"))
        m.add_radiobutton(label="24-hour time", variable=vt, value="24h", command=lambda: self.set_time_format("24h"))
        m.add_radiobutton(label="12-hour time (AM/PM)", variable=vt, value="12h", command=lambda: self.set_time_format("12h"))
        m.add_separator()
        m.add_command(label="Refresh now", command=self.fetch)
        m.add_command(label="Compact / Full", command=self.toggle_compact)
        m.add_command(label="Minimize", command=self.minimize)
        m.add_separator()
        m.add_command(label="Quit", command=self.root.destroy)
        m.tk_popup(e.x_root, e.y_root)

    def set_time_format(self, fmt):
        self.cfg["time_format"] = fmt
        self.save()
        self.draw()

    def set_show(self, name, on):
        self.cfg[f"show_{name}"] = bool(on)
        self.save()
        self.draw()
        self.fetch()

    def save(self):
        self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
        try:
            CONFIG.write_text(json.dumps(self.cfg, indent=2))
        except OSError:
            pass


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UsageDeck.App")
    except Exception:
        pass
    Widget().root.mainloop()
