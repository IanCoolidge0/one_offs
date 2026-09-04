#!/usr/bin/env python3
"""One-time setup on a machine: point Claude Code's status line at this checkout.

Run:  python install.py
Then start the widget with start-widget.bat (Windows) or `pythonw widget.py`.
Re-run after moving the folder. Backs up settings.json first.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
SETTINGS = os.path.join(CONFIG_DIR, "settings.json")


def main():
    script = os.path.join(HERE, "statusline.py").replace("\\", "/")
    command = f"python {script}"

    settings = {}
    if os.path.exists(SETTINGS):
        shutil.copy2(SETTINGS, SETTINGS + ".bak-limitthingy")
        with open(SETTINGS, "r", encoding="utf-8") as f:
            settings = json.load(f)

    old = settings.get("statusLine")
    settings["statusLine"] = {"type": "command", "command": command}
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

    if not os.path.exists(os.path.join(HERE, "config.json")):
        shutil.copy2(os.path.join(HERE, "config.example.json"), os.path.join(HERE, "config.json"))
        print("created config.json from config.example.json")

    print(f"statusLine -> {command}")
    if old and old != settings["statusLine"]:
        print(f"replaced previous statusLine: {old}")
    print(f"backup: {SETTINGS}.bak-limitthingy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
