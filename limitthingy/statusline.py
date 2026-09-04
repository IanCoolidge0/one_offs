#!/usr/bin/env python3
"""Claude Code status line script.

Claude Code pipes session JSON to stdin. This script:
  1. writes the rate_limits block (5-hour / 7-day windows) to state.json so the
     desktop widget (widget.py) can poll it, and
  2. prints a one-line status for Claude Code's own footer.

Configured in ~/.claude/settings.json as:
  "statusLine": {"type": "command", "command": "python C:/Users/cooli/one_offs/limitthingy/statusline.py"}
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.environ.get("CLAUDE_USAGE_STATE_FILE", os.path.join(HERE, "state.json"))


def write_state(data: dict) -> None:
    rate = data.get("rate_limits") or {}
    if not rate:
        # A session's first status line run (before its first API response) has no
        # rate_limits. Keep the last good numbers rather than wiping them.
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                if json.load(f).get("rate_limits"):
                    return
        except (OSError, ValueError):
            pass
    state = {
        "updated_at": time.time(),
        "session_id": data.get("session_id"),
        "model": (data.get("model") or {}).get("display_name"),
        "cwd": data.get("cwd"),
        "rate_limits": rate,
    }
    # Atomic replace so the widget never reads a half-written file.
    tmp = f"{STATE_FILE}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def dump_raw(data: dict) -> None:
    """Keep the last full payload Claude Code sent, for debugging / discovering fields."""
    path = os.path.join(HERE, "last_input.json")
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def fmt_reset(resets_at) -> str:
    if not resets_at:
        return ""
    secs = int(resets_at - time.time())
    if secs <= 0:
        return "resetting"
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return f"{d}d{h}h"
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m"


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        data = {}

    write_state(data)
    dump_raw(data)

    model = (data.get("model") or {}).get("display_name") or "Claude"
    cwd = data.get("cwd") or ""
    dirname = cwd.replace("\\", "/").rstrip("/").split("/")[-1] if cwd else ""
    ctx = (data.get("context_window") or {}).get("used_percentage")

    parts = [f"[{model}]"]
    if dirname:
        parts.append(dirname)
    if ctx is not None:
        parts.append(f"ctx {int(ctx)}%")

    rate = data.get("rate_limits") or {}
    for key, label in (("five_hour", "5h"), ("seven_day", "wk")):
        w = rate.get(key) or {}
        pct = w.get("used_percentage")
        if pct is None:
            continue
        reset = fmt_reset(w.get("resets_at"))
        parts.append(f"{label} {pct:.0f}%" + (f" ({reset})" if reset else ""))

    print(" | ".join(parts))


if __name__ == "__main__":
    main()
