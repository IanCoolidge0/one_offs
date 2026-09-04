#!/usr/bin/env python3
"""Always-on-top desktop widget showing Claude subscription usage limits.

Polls state.json (written by statusline.py every time Claude Code refreshes its
status line) on a configurable heartbeat and renders the 5-hour and 7-day
windows as progress bars with reset countdowns.

Usage:  pythonw widget.py            (no console window)
        python  widget.py --test 3   (run 3 seconds then exit; for smoke tests)

Controls: drag anywhere to move (position is saved), right-click for menu.
Config lives in config.json next to this file and is re-read live.
"""
import argparse
import json
import os
import sys
import threading
import time
import tkinter as tk

import poke

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "config.json")

DEFAULTS = {
    "heartbeat_seconds": 2,
    "stale_after_seconds": 600,
    "opacity": 0.92,
    "always_on_top": True,
    "x": 40,
    "y": 40,
    "width": 300,
    "font_family": "Segoe UI",
    "font_size": 10,
    "state_file": None,
    "poke_on_refresh": True,
    "poke_prompt": poke.DEFAULT_PROMPT,
    "poke_model": poke.DEFAULT_MODEL,
    "poke_timeout_seconds": poke.DEFAULT_TIMEOUT,
    "auto_poke_after_seconds": 1800,
}

BG = "#1e1e24"
FG = "#e6e6ea"
DIM = "#8a8a94"
TRACK = "#33333c"
GREEN = "#4caf50"
YELLOW = "#f5b942"
RED = "#e5533d"
GREY = "#6b6b75"

WINDOWS = (("five_hour", "5-hour"), ("seven_day", "Weekly"))


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if v is not None})
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass


def fmt_countdown(resets_at) -> str:
    if not resets_at:
        return ""
    secs = int(resets_at - time.time())
    if secs <= 0:
        return "resetting..."
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d:
        return f"resets in {d}d {h}h"
    if h:
        return f"resets in {h}h {m:02d}m"
    return f"resets in {m}m {s:02d}s"


def fmt_ago(secs: float) -> str:
    secs = int(secs)
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    return f"{secs // 3600}h {(secs % 3600) // 60}m ago"


def color_for(pct: float) -> str:
    if pct >= 80:
        return RED
    if pct >= 50:
        return YELLOW
    return GREEN


class Widget:
    def __init__(self, root, test_seconds=None):
        self.root = root
        self.cfg = load_config()
        self.cfg_mtime = self._mtime(CONFIG_FILE)
        self.test_deadline = time.time() + test_seconds if test_seconds else None
        self.drag_origin = None
        self.after_id = None
        self.poking = False
        self.last_poke_at = 0.0
        self.notice = None  # (text, color, expires_at) shown in the footer

        root.overrideredirect(True)
        root.configure(bg=BG)
        root.attributes("-topmost", bool(self.cfg["always_on_top"]))
        root.attributes("-alpha", float(self.cfg["opacity"]))
        root.geometry(f"+{int(self.cfg['x'])}+{int(self.cfg['y'])}")

        fam = self.cfg["font_family"]
        size = int(self.cfg["font_size"])
        self.font_bold = (fam, size, "bold")
        self.font_small = (fam, max(7, size - 2))

        self.frame = tk.Frame(root, bg=BG, padx=12, pady=10)
        self.frame.pack(fill="both", expand=True)

        bar_width = int(self.cfg["width"]) - 24
        self.title = tk.Label(self.frame, text="Claude usage", bg=BG, fg=DIM, font=self.font_small, anchor="w", wraplength=bar_width, justify="left")
        self.title.grid(row=0, column=0, sticky="we")

        self.refresh_btn = tk.Label(self.frame, text="↻", bg=BG, fg=DIM, font=(fam, size + 2), cursor="hand2", padx=4)
        self.refresh_btn.grid(row=0, column=1, sticky="e")
        self.refresh_btn.bind("<Button-1>", self.on_refresh_click)
        self.refresh_btn.bind("<Enter>", lambda _e: self.refresh_btn.configure(fg=FG))
        self.refresh_btn.bind("<Leave>", lambda _e: self.refresh_btn.configure(fg=DIM))
        self.refresh_btn.bind("<Button-3>", self.on_menu)

        self.rows = {}
        for i, (key, label) in enumerate(WINDOWS):
            r = 1 + i * 3
            name = tk.Label(self.frame, text=label, bg=BG, fg=FG, font=self.font_bold, anchor="w")
            name.grid(row=r, column=0, sticky="w", pady=(6, 0))
            pct = tk.Label(self.frame, text="--", bg=BG, fg=FG, font=self.font_bold, anchor="e")
            pct.grid(row=r, column=1, sticky="e", pady=(6, 0))
            bar = tk.Canvas(self.frame, width=bar_width, height=10, bg=TRACK, highlightthickness=0, bd=0)
            bar.grid(row=r + 1, column=0, columnspan=2, sticky="we", pady=(3, 0))
            fill = bar.create_rectangle(0, 0, 0, 10, fill=GREEN, width=0)
            reset = tk.Label(self.frame, text="", bg=BG, fg=DIM, font=self.font_small, anchor="w", wraplength=bar_width, justify="left")
            reset.grid(row=r + 2, column=0, columnspan=2, sticky="w")
            self.rows[key] = {"name": name, "pct": pct, "bar": bar, "fill": fill, "reset": reset}

        self.footer = tk.Label(self.frame, text="waiting for Claude Code...", bg=BG, fg=DIM, font=self.font_small, anchor="w", wraplength=bar_width, justify="left")
        self.footer.grid(row=8, column=0, columnspan=2, sticky="we", pady=(8, 0))
        self.frame.columnconfigure(0, weight=1)

        for w in self._all_widgets():
            w.bind("<ButtonPress-1>", self.on_press)
            w.bind("<B1-Motion>", self.on_drag)
            w.bind("<ButtonRelease-1>", self.on_release)
            w.bind("<Button-3>", self.on_menu)

        self.menu = tk.Menu(root, tearoff=0)
        self.menu.add_command(label="Refresh now", command=self.tick)
        self.menu.add_command(label="Toggle always on top", command=self.toggle_topmost)
        self.menu.add_separator()
        for secs in (1, 2, 5, 10, 30, 60):
            self.menu.add_command(label=f"Heartbeat: {secs}s", command=lambda s=secs: self.set_heartbeat(s))
        self.menu.add_separator()
        self.menu.add_command(label="Open config.json", command=self.open_config)
        self.menu.add_command(label="Quit", command=self.quit)

        self.tick()

    # ---- helpers -----------------------------------------------------------
    def _all_widgets(self):
        out = [self.root, self.frame, self.title, self.footer]
        for row in self.rows.values():
            out += [row["name"], row["pct"], row["bar"], row["reset"]]
        return out

    @staticmethod
    def _mtime(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0.0

    def state_path(self):
        return self.cfg.get("state_file") or os.path.join(HERE, "state.json")

    def read_state(self):
        try:
            with open(self.state_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    # ---- heartbeat ---------------------------------------------------------
    def tick(self):
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None

        if self.test_deadline and time.time() >= self.test_deadline:
            self.root.destroy()
            return

        mtime = self._mtime(CONFIG_FILE)
        if mtime != self.cfg_mtime:
            self.cfg_mtime = mtime
            self.cfg = load_config()
            self.root.attributes("-topmost", bool(self.cfg["always_on_top"]))
            self.root.attributes("-alpha", float(self.cfg["opacity"]))

        state = self.read_state()
        self.render(state)
        self.maybe_auto_poke(state)

        hb = max(0.25, float(self.cfg.get("heartbeat_seconds", 2)))
        self.after_id = self.root.after(int(hb * 1000), self.tick)

    def render(self, state):
        now = time.time()
        rate = (state or {}).get("rate_limits") or {}
        updated = (state or {}).get("updated_at")
        stale = updated is None or (now - updated) > float(self.cfg["stale_after_seconds"])

        for key, _label in WINDOWS:
            row = self.rows[key]
            win = rate.get(key) or {}
            pct = win.get("used_percentage")
            resets_at = win.get("resets_at")
            bar_w = row["bar"].winfo_width()
            if bar_w <= 1:
                bar_w = int(self.cfg["width"]) - 24
            if pct is None:
                row["pct"].configure(text="--", fg=DIM)
                row["bar"].coords(row["fill"], 0, 0, 0, 10)
                row["reset"].configure(text="no data" if not state else "window not reported")
                continue
            pct = float(pct)
            color = GREY if stale else color_for(pct)
            row["pct"].configure(text=f"{pct:.0f}%", fg=DIM if stale else FG)
            row["bar"].coords(row["fill"], 0, 0, int(bar_w * min(pct, 100) / 100), 10)
            row["bar"].itemconfigure(row["fill"], fill=color)
            row["reset"].configure(text=fmt_countdown(resets_at))

        if self.notice and self.notice[2] > now:
            self.footer.configure(text=self.notice[0], fg=self.notice[1])
        elif state is None:
            self.footer.configure(text="waiting for Claude Code...", fg=DIM)
        elif not rate:
            self.footer.configure(text="no rate_limits yet (needs Pro/Max + first reply)", fg=DIM)
        else:
            txt = f"updated {fmt_ago(now - updated)}" if updated else "updated: unknown"
            if stale:
                txt += "   stale"
            self.footer.configure(text=txt, fg=YELLOW if stale else DIM)

    # ---- interaction -------------------------------------------------------
    def on_press(self, e):
        self.drag_origin = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def on_drag(self, e):
        if self.drag_origin:
            x = e.x_root - self.drag_origin[0]
            y = e.y_root - self.drag_origin[1]
            self.root.geometry(f"+{x}+{y}")

    def on_release(self, _e):
        if self.drag_origin:
            self.drag_origin = None
            self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
            self._save()

    def on_refresh_click(self, _e):
        if self.poking:
            return "break"
        if not bool(self.cfg.get("poke_on_refresh", True)):
            self.refresh_btn.configure(fg=GREEN)
            self.tick()
            self.root.after(250, lambda: self.refresh_btn.configure(fg=DIM))
            return "break"
        self.start_poke("poking Claude Code...")
        return "break"

    def log(self, msg):
        try:
            with open(os.path.join(HERE, "poke.log"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
        except OSError:
            pass

    def start_poke(self, notice):
        if self.poking:
            return
        self.poking = True
        self.last_poke_at = time.time()
        self.log(notice)
        self.refresh_btn.configure(fg=YELLOW)
        self.set_notice(notice, YELLOW, 3600)
        threading.Thread(target=self._poke_worker, daemon=True).start()

    def maybe_auto_poke(self, state):
        """Poke automatically once the data is older than auto_poke_after_seconds.

        Backs off by the same interval after any attempt, so a failing poke does
        not retry on every heartbeat. 0 disables.
        """
        threshold = float(self.cfg.get("auto_poke_after_seconds") or 0)
        if threshold <= 0 or self.poking:
            return
        now = time.time()
        updated = (state or {}).get("updated_at") or 0
        if now - updated < threshold or now - self.last_poke_at < threshold:
            return
        self.start_poke("auto-poking (data stale)...")

    def _poke_worker(self):
        ok, msg = poke.poke(
            str(self.cfg.get("poke_prompt") or poke.DEFAULT_PROMPT),
            str(self.cfg.get("poke_model") or poke.DEFAULT_MODEL),
            float(self.cfg.get("poke_timeout_seconds") or poke.DEFAULT_TIMEOUT),
        )
        self.root.after(0, self._poke_done, ok, msg)

    def _poke_done(self, ok, msg):
        self.poking = False
        self.log(("OK  " if ok else "FAIL ") + msg)
        self.refresh_btn.configure(fg=GREEN if ok else RED)
        self.root.after(600, lambda: self.refresh_btn.configure(fg=DIM))
        self.set_notice(msg, GREEN if ok else RED, 4 if ok else 12)
        self.tick()

    def set_notice(self, text, color, seconds):
        self.notice = (text, color, time.time() + seconds)

    def on_menu(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def _save(self):
        save_config(self.cfg)
        self.cfg_mtime = self._mtime(CONFIG_FILE)

    def toggle_topmost(self):
        self.cfg["always_on_top"] = not bool(self.cfg["always_on_top"])
        self.root.attributes("-topmost", self.cfg["always_on_top"])
        self._save()

    def set_heartbeat(self, secs):
        self.cfg["heartbeat_seconds"] = secs
        self._save()
        self.tick()

    def open_config(self):
        try:
            os.startfile(CONFIG_FILE)
        except (OSError, AttributeError):
            pass

    def quit(self):
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(description="Claude usage desktop widget")
    ap.add_argument("--test", type=float, metavar="SECONDS", help="run for N seconds then exit")
    args = ap.parse_args()

    root = tk.Tk()
    root.title("Claude usage")
    Widget(root, test_seconds=args.test)
    root.mainloop()


if __name__ == "__main__":
    sys.exit(main())
