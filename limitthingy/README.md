# limitthingy

A tiny always-on-top desktop widget showing your Claude subscription usage
(5-hour window and weekly window) in near real time.

## How it works

1. Claude Code runs `statusline.py` every time its status line refreshes
   (each assistant reply, and when a limit window resets). Claude Code pipes it
   session JSON that includes `rate_limits.five_hour` and `rate_limits.seven_day`.
2. `statusline.py` writes those numbers to `state.json` and prints a normal
   status line for Claude Code's footer.
3. `widget.py` polls `state.json` on a configurable heartbeat and draws two bars.

The numbers are account-wide, so usage from the web app is included the next
time any Claude Code session gets a reply. The widget cannot see changes while
every Claude Code session is idle; the footer shows how old the data is.

## Setup

`~/.claude/settings.json` needs:

```json
"statusLine": {
  "type": "command",
  "command": "python C:/Users/cooli/one_offs/limitthingy/statusline.py"
}
```

Then run `start-widget.bat` (or `pythonw widget.py`). To start it with Windows,
put a shortcut to `start-widget.bat` in `shell:startup`.

## Config (`config.json`, re-read live)

| key                   | meaning                                                |
|-----------------------|--------------------------------------------------------|
| `heartbeat_seconds`   | how often the widget re-reads `state.json`             |
| `stale_after_seconds` | grey out bars when the data is older than this         |
| `opacity`             | 0 to 1                                                 |
| `always_on_top`       | true/false (also toggled from the right-click menu)    |
| `x`, `y`              | window position (saved automatically after dragging)   |
| `width`               | widget width in pixels                                 |
| `state_file`          | override path to `state.json` (null = next to scripts) |
| `poke_on_refresh`     | top-right button spawns a throwaway session (true) or just re-reads the file (false) |
| `poke_prompt`, `poke_model`, `poke_timeout_seconds` | what the throwaway session is asked, which model (default haiku), how long to wait |
| `auto_poke_after_seconds` | poke automatically once the data is older than this (default 1800; 0 disables) |

Right-click the widget for heartbeat presets, refresh, and quit. Drag to move.

## Poking

The status line only refreshes when a Claude Code session gets a reply, so the
widget can "poke": `poke.py` launches a real Claude Code session in a hidden
console with a throwaway prompt ("reply with the word cat, nothing else"), waits
for that session's numbers to land in `state.json`, then kills it. It takes
about five seconds and uses Haiku to keep the cost negligible. The top-right
button does this on click, and the widget does it automatically when the data
is older than `auto_poke_after_seconds`. Attempts are logged to `poke.log`.

A poke leaves no local transcript. It is started with
`--settings '{"disableRemoteControl": true}'` so it does not auto-connect to
Remote Control; without that, every poke shows up as a one-line "cat" session in
the claude.ai/code history. It does rotate one ~100 KB backup of `~/.claude.json`
(Claude Code keeps the last five).

`ANTHROPIC_API_KEY` is stripped from the spawned session so it uses your
claude.ai login rather than an API key.
