# Terminal

Real shells inside Forge (A17 in `sessions/2026-09-26-S9-terminal-files-code.md`).
Port 8459, role `terminal`, section "system".

## Layout
- `ptyhost.py`: one `Term` per tab. The shell (`$SHELL -l`) runs on a pseudo-terminal
  started with `subprocess` + `setsid -c` (safe in a threaded server, and it gives the
  shell a controlling terminal so Ctrl+C, job control and resize work). Output is read on
  the asyncio loop; the last 256 KB is kept so a reloaded page gets its screen back.
  Closing a tab sends SIGHUP (and 1.5 s later SIGHUP again, then SIGTERM) to the shell's process group,
  addressed by the shell's pid (never `getpgid`, which is the backend's own group in the
  first moment after a start).
  Input the shell has not read yet waits in `Term.pending` and goes in as the tty takes
  it (`loop.add_writer`), so a big paste never blocks the backend. Ctrl+C while a paste
  is still queued drops the rest; if the program in front lets the tty handle Ctrl+C
  (ISIG on), `Term.interrupt` flushes the shell side's input and sends it SIGINT (read
  through the master fd); a raw-mode program gets the key itself, after the paste's end
  marker if the dropped part held it.
  The app's own `.venv` is scrubbed from the shell's PATH/VIRTUAL_ENV.
- `web_app.py`: `/api/terms` (list/create/delete, need `X-Forge: 1`) and `/ws/{id}`
  (needs the per-run token from `/api/session` **and** an Origin equal to this server).
- `static/`: xterm.js 6.0 + fit + web-links + search addons vendored in `static/vendor/`
  (MIT, licences kept beside them; the owner OK'd 2026-09-26).

## Keys
Ctrl+Shift+C copy, Ctrl+Shift+V paste, **plain Ctrl+V goes to the program** (Claude Code
pastes images that way), Ctrl+Shift+T / Ctrl+Shift+W new/close tab, Ctrl+Shift+F find in scrollback, Ctrl+PageUp/PageDown
switch, Ctrl+= / Ctrl+- text size, Ctrl+click opens a link, right-click menu, middle-click
a tab closes it, double-click a tab to rename it. Ctrl+0..9 and Ctrl+Tab belong to Forge
(caught by GTK).

A tab behind the one in front shows an accent dot when it prints something and an amber
dot when a program rings the bell. The gear opens the settings (text size, scrollback,
cursor style and blink, copy on select); they come from the `PREFS` list in
`static/app.js`, so a new setting is one entry there.

Links in: `#cwd=/some/folder` opens a new tab there (Files' "Open terminal here").

## Checks
- `.venv/bin/python -m pytest -q tests`: auth refusals, real shell I/O, resize,
  scrollback replay, exit, close, foreground program name.
- `.venv/bin/python tests/check_ui.py [--port N] [--shots DIR]`: headless Chrome via
  `~/Forge/tests/cdp_driver.py` against its own backend on N (default 18727, refused if
  in use): typing, Ctrl+V as byte 0x16 in raw mode, Ctrl+C, stty size, htop on the
  alternate screen, tabs, split panes, find, font size, reload reattach, exit, settings,
  tab names, activity and bell marks, closing a tab twice, and a backend stop/restart.
  Run it through `forge_ram.py run`. Both test files send the shells' history to
  /dev/null.
