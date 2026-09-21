# Token Widget

A small always-on-top Windows widget that shows your **Claude Code** and **Codex** usage at a glance.

![Token Widget](docs/screenshot.png)

- **Claude Code:** tokens for the last 5 hours and 7 days, plus today.
- **Codex:** your real 5-hour and weekly limit percentages with reset times, plus token totals.
- Refreshes every 30 seconds. Drag to move, drag the bottom-right grip to resize.
- Mac-style buttons: red closes, yellow minimizes, green toggles compact view.
- Pin it to the taskbar and set it to start with Windows.

## Privacy

Everything is read from local log files (`~/.claude/projects` and `~/.codex/sessions`).
There are **no network calls** and nothing is sent anywhere.

## Run

Requires Windows 10/11 and Python 3.9+ (no packages needed).

```
py widget.py
```

## Build a standalone .exe (pinnable)

```
build.bat
```

This produces `TokenWidget.exe`. Run it, right-click its taskbar button, and choose **Pin to taskbar**.
To start with Windows, run `powershell -ExecutionPolicy Bypass -File install-startup.ps1`.

## Customize

- **Logos / icon:** put `claude.svg`, `codex.svg` and `app.svg` (or PNGs) in `logos/`. SVGs are converted
  automatically using Microsoft Edge (already on Windows). `app.svg` becomes the window and `.exe` icon.
- **Settings:** `config.json` is created next to the app on first move. Keys: `w` (width),
  `compact`, `claude_5h_cap`, `claude_7d_cap`.
- **Look:** colors and the glass strength (`-alpha`, and the acrylic tint value) are at the top and in
  `glass()` in `widget.py`.

## Notes

- Claude Code's local logs don't include your plan limit, so the Claude bars show usage against a cap
  you can set (`claude_5h_cap` defaults to your own busiest 5-hour window, `claude_7d_cap` to 30M).
  They are not official limits. Codex percentages come from Codex's own logs and only update while Codex is used.
- Claude counts input, output and cache-write tokens; cache reads are excluded.

## Trademarks

The Claude and Codex logos in `logos/` are trademarks of their respective owners (Anthropic and OpenAI)
and are used only to identify the services. This project is not affiliated with or endorsed by them.
Replace them with your own if you prefer.

## License

MIT for the code. See [LICENSE](LICENSE). Logos are excluded from the MIT license.
