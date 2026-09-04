#!/usr/bin/env python3
"""Poke Claude Code so it refreshes the subscription usage numbers.

Spawns a real interactive Claude Code session in a hidden console window with a
throwaway prompt, waits until statusline.py has written this session's
rate_limits to state.json, then kills the session.

Usage:  python poke.py            (uses config.json settings)
        python poke.py --visible  (show the console window, for debugging)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.environ.get("CLAUDE_USAGE_STATE_FILE", os.path.join(HERE, "state.json"))
CONFIG_FILE = os.path.join(HERE, "config.json")

DEFAULT_PROMPT = "reply with the word cat, nothing else"
DEFAULT_MODEL = "haiku"
DEFAULT_TIMEOUT = 90

# Env vars that would make the child session bill an API key or refuse to nest.
STRIP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def fmt_pct(v):
    """Format a percentage without float noise: 49 -> '49%', 23.4999999 -> '23.5%'."""
    if v is None:
        return "?"
    r = round(float(v), 2)
    return f"{int(r)}%" if r == int(r) else f"{r:g}%"


def read_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def find_claude():
    exe = shutil.which("claude")
    if exe:
        return exe
    for cand in (os.path.expanduser("~/.local/bin/claude.exe"), os.path.expanduser("~/.local/bin/claude")):
        if os.path.exists(cand):
            return cand
    return "claude"


def kill_tree(proc):
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def poke(prompt=DEFAULT_PROMPT, model=DEFAULT_MODEL, timeout=DEFAULT_TIMEOUT, visible=False, log=None):
    """Run one throwaway session. Returns (ok: bool, message: str)."""
    log = log or (lambda _m: None)
    sid = str(uuid.uuid4())
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
    cmd = [find_claude(), "--model", model, "--session-id", sid, prompt]

    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_CONSOLE if visible else subprocess.CREATE_NO_WINDOW

    log(f"spawning: {' '.join(cmd[:-1])} <prompt>")
    try:
        proc = subprocess.Popen(cmd, cwd=HERE, env=env, creationflags=flags)
    except OSError as e:
        return False, f"could not start claude: {e}"

    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                return False, f"claude exited early (code {proc.returncode})"
            st = read_state()
            if st and st.get("session_id") == sid and (st.get("rate_limits") or {}):
                r = st["rate_limits"]
                fh = fmt_pct((r.get("five_hour") or {}).get("used_percentage"))
                wk = fmt_pct((r.get("seven_day") or {}).get("used_percentage"))
                return True, f"refreshed: 5h {fh}, week {wk}"
            time.sleep(0.5)
        return False, f"timed out after {timeout}s waiting for rate_limits"
    finally:
        kill_tree(proc)


def load_poke_config():
    cfg = {"poke_prompt": DEFAULT_PROMPT, "poke_model": DEFAULT_MODEL, "poke_timeout_seconds": DEFAULT_TIMEOUT}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg.update({k: v for k, v in data.items() if k in cfg and v is not None})
    except (OSError, ValueError):
        pass
    return cfg


def main():
    ap = argparse.ArgumentParser(description="Poke Claude Code to refresh usage numbers")
    ap.add_argument("--visible", action="store_true", help="show the console window")
    args = ap.parse_args()
    cfg = load_poke_config()
    t0 = time.time()
    ok, msg = poke(cfg["poke_prompt"], cfg["poke_model"], float(cfg["poke_timeout_seconds"]),
                   visible=args.visible, log=print)
    print(f"{'OK' if ok else 'FAIL'}: {msg} ({time.time() - t0:.1f}s)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
