# Forge releases: developer notes

How Forge becomes a download for Windows, macOS and Linux, and how to change
what goes in. The user-facing instructions are `README.txt` (copied into
every download, with the per-system notes filled in) and the source tree's
`README.md` (made from `source/README.md`).

## The three pieces

| Piece | Files | Job |
| --- | --- | --- |
| Launcher | `forge_portable.py`, `hub/portable.js`, `forge_core.py`, `forge_serve.py` | Serves the hub on `http://127.0.0.1:8400`, opens a window, starts each app's backend on first use (through `forge_serve.py`), stops them all on close. |
| Registry | `release/release.json` | What each system gets: apps, features (native, replaced, fallback or cut), packages, assets, data folders, scrub rules, targets. |
| Builder | `release/build.py`, `release/launch/`, `release/source/` | Picks the files from git, checks them for personal data, adds a Python and the packages per system, writes the archives. |

`forge.py` (the GTK Forge on the Linux desktop it grew up on) is not part of
a release and is not changed by it. `forge_core.py` reads the same manifests
by the same rules, without GTK; `forge.py` still keeps its own copy of that
code and starts its backends with plain uvicorn, without `forge_serve.py`'s
guard. Moving it onto `forge_core.py` is a change of its own, because it
needs a restart of the Forge in daily use. The module docstrings of
`forge_portable.py`, `forge_serve.py` and `release/build.py` explain the
internals: the bridge and its safety checks, data folders per system, what
each build check does.

## What keeps the launcher safe

Everything listens on 127.0.0.1 only, but a web page in any browser on the
same computer can still send requests there, so:

- The hub answers only requests whose `Host` is this computer's own name
  (127.0.0.1, localhost, [::1]); the bridge also needs the per-launch token
  in an `X-Forge` header and an `Origin` of the hub itself.
- Each app backend runs through `forge_serve.py`: the same `Host` rule for
  every request and WebSocket (so a site that points its own name at
  127.0.0.1, "DNS rebinding", gets 403 instead of Terminal's shell), and it
  ends when its launcher ends, even when the launcher is killed outright.
  A port some other program holds is never taken for the app.
- File links (`/forge/file`, `/forge/track`) carry a token of their own,
  never the bridge's. Each folder hands out only its own kinds of file
  (wallpapers: pictures and video, the music folder: audio), paths are
  checked after resolving links, network shares (`\\host`, `//host`) are
  refused before any lookup, and only pages on this computer may read the
  answers (CORS).
- Changes come only from Forge's own pages: an app backend refuses any
  request but GET, HEAD and OPTIONS, and any WebSocket, whose `Origin` is
  another site or `null` (or that says `Sec-Fetch-Site: cross-site` with no
  `Origin`), so a site cannot post a plain-text body that FastAPI reads as
  JSON.
- The hub's per-request scripts (`status.js` lists the apps, `theme.js`
  holds the file token) are handed out only with the bridge token, which the
  hub page writes into their script tags, however the path is written
  (`/hub//status.js`); the copies forge.py writes into `hub/` are never
  served.
- No other site may frame Forge: every answer from the hub and the app
  backends carries `Content-Security-Policy: frame-ancestors 'self'
  http://127.0.0.1:* http://localhost:*`, and the hub acts on a message only
  from one of its app frames or a page on this computer, so a site that opens
  the hub in a popup cannot post it "open Terminal".

## Everyday jobs

Run the portable launcher from a checkout (each app uses its own `.venv` when
there is one, else the Python running the launcher):

```sh
python3 forge_portable.py                    # open Forge
python3 forge_portable.py --window browser   # in a browser tab
python3 forge_portable.py --as-system macos  # the hub as macOS would show it
```

Check it without touching your own Forge: move `HOME`, unset the XDG
variables and shift every port so nothing clashes with a Forge already
running.

```sh
env -u XDG_CONFIG_HOME -u XDG_CACHE_HOME -u XDG_DATA_HOME -u XDG_STATE_HOME \
    HOME=/tmp/forge-check python3 forge_portable.py --smoke --port-offset 1000
```

`--smoke` starts every app, checks the hub and each app's page answer, that
every script, style sheet, picture and import-map module a page names is
served, and that each app refuses a request addressed to another name; then
it stops everything and exits 0 or 1 (`--report file.json` keeps the
results).

Tests (any virtualenv with pytest; the launcher tests start a real launcher
with no apps, on a free port, with `HOME` moved):

```sh
python -m pytest tests/test_release.py
```

Build. Files come from git `HEAD`, so commit first, or pass
`--from worktree` to include uncommitted files:

```sh
python3 release/build.py --check-only --from worktree   # pick and check files only (seconds)
python3 release/build.py                                # all four targets, outputs/release/<version>/
python3 release/build.py --target windows-x64 --out /tmp/forge-win
python3 release/build.py --source-tree --out /tmp/forge-src   # a tree for a public git repository
```

An output folder that already holds a target is never overwritten: pick
another `--out` or move the old one away first.

Smoke a download the way a user runs it:

```sh
tar xzf forge-<version>-linux-x64.tar.gz -C /tmp/run
HOME=/tmp/run-home /tmp/run/Forge/forge --smoke --port-offset 1000

# Windows, under Wine, in a prefix of its own (never your usual one)
WINEPREFIX=/tmp/forge-wine wine runtime/python.exe forge_portable.py --smoke --port-offset 2000
```

## Adding an app to the release

1. The app must not write into its own folder or straight into the home
   folder. Give each place it writes an environment variable whose default
   keeps today's behaviour (for example `COSMOS_DATA`, `ARCADE_DATA`).
2. Add its entry under `apps` in `release/release.json`:
   - `linux`, `windows`, `macos`: `native`, or `cut: <why>` (a cut app is
     left out of that system's download and never started there);
   - `env`: the variables from step 1, with placeholders the launcher fills
     in: `{data}`, `{config}`, `{cache}`, `{state}`, `{logs}`, `{port:<app>}`;
   - `packages`: every package it needs, pinned (`name==version`); the
     builder refuses an unpinned one. Packages that only come as source go
     in `packages.source_only` and are built into wheels once;
   - `assets` / `downloads`: files kept outside git, each download with its
     URL, SHA-256 and credit (credits go into `THIRD-PARTY.txt`).
   - starting data the repo does not hold as files (art, worlds, content
     made by a script) goes in the app's manifest field `seed` (README.md):
     the launcher runs those scripts before the app's first start, so a
     fresh install never opens on an empty library.
3. Run `build.py --check-only --from worktree` and the tests. The tests
   fail when an app folder has no registry entry, so a new app is never
   shipped or left out by accident.

An app that should stay out gets `"include": false` and a `why`.

## Cutting or replacing a hub feature

Each entry under `features` says what the feature is and, per system,
`native`, `replaced: <how>`, `fallback: <what instead>` or `cut: <why>`.
For a feature that is not native the launcher removes what would be left
broken:

- `settings` / `settings_groups`: hidden in the Settings app;
- `hide`: CSS selectors hidden in the hub;
- `theme`: theme values forced for that system;
- `widgets`: home widgets taken out of the widget menu;
- `readme: false`: left out of README.txt (internal only).

The tests check that every selector, setting and widget named here really
exists, so a renamed control cannot silently come back as a dead button.

## Installing (0.2)

**Linux.** The download stays a `.tar.gz`. `./Forge/forge --install`
(the `forge` launcher hands `--install` and `--uninstall` to
`release/launch/forge_installer.py`, shipped at the bundle's top) copies the
folder to `~/.local/share/forge-release/app` (new copy beside the old, then
a swap; a marker file `.forge-install.json` says the folder is the
installer's), writes the menu entry `local.forge.Forge.desktop` (a name no
other launcher uses, so the owner's own `forge.desktop` is never touched;
`StartupWMClass=forge_portable.py` ties the window to it) and starts Forge;
other options after `--install` go to that Forge (`--port-offset 10000`
keeps a check off the real ports). `forge --uninstall` removes the program
and the entry and keeps the user's things; `--uninstall --remove-data` lists
the release's own folders (named `forge-release`, plus WebKit's
`forge_portable.py` cache and web storage), asks for "yes", moves them to
the Trash (else deletes), and never touches a data place the user chose
elsewhere. Tests: `tests/test_release_install.py`.

**Windows.** `release/launch/forge.iss` is an Inno Setup 6 script for
`Forge-Setup-<version>.exe`: per-user (no administrator prompt) into
`%LOCALAPPDATA%\Programs\Forge`, Start menu entry, optional desktop icon,
"Start Forge now" at the end; the uninstaller keeps `%APPDATA%\Forge` and
`%LOCALAPPDATA%\Forge` unless the user says yes (default no). The build
makes it when Inno Setup's `ISCC.exe` is found under Wine (`FORGE_ISCC`,
else the Wine prefix's Program Files or the user's Programs folder), and the
Windows README then gains the setup steps; without it the zip is the whole
Windows download and its README says so. **Inno Setup is not installed on
this laptop** (it needs the owner's yes), so the script has never been
compiled or run. To add it: install Inno Setup 6 from jrsoftware.org into a
Wine prefix of its own, then build with `WINEPREFIX=<that prefix>`.
`launch_problems()` already checks that the script and every icon and
picture it names are in `release/launch/`.

## What keeps personal data out

1. `ship` and `leave_out` pick the files (handoff docs, tests, the owner's
   own tools and data stay out); apps marked `include: false` never ship.
2. `scrub` rewrites home-folder paths in comments and examples, then any
   `forbid` match left in any file stops the build. More rules in the same
   form live in a private file outside the repo
   (`~/.config/forge/release-scrub.json`, named by `scrub.private`): the
   owner's name and personal figures, swapped for neutral words, with the
   name itself forbidden. A build whose registry names that file and cannot
   find it stops (the public source tree's registry names none).
   `shared/` ships by an allowlist in `ship` (each file named), and a
   `/shared/<file>` that a shipped page names but the build leaves out stops
   the build too.
3. Forge Backup's clean-copy checker (`apps/backup/clean.py`, the one that
   guards the public GitHub copy) reads every shipped file for secrets,
   personal data and this computer's real tokens. A tree without it (the
   public source tree) skips this check and says so.
4. The bundled Python and packages are read for real key formats, private
   keys and this computer's known values (`third_party.skip` names the two
   patterns that only ever matched documentation examples there).

## Checked on 2026-10-28 (0.2.0, built from the working tree)

- Linux x64: `--smoke` 108 passed, 0 failed (18 apps) in a scratch home;
  nothing written into the program folder. `./Forge/forge --install` in a
  private off-screen GNOME session: the menu entry shows in the search with
  Forge's icon, Forge starts and its window sits under that icon in the
  dash; `--uninstall` takes both out and keeps the user's folders
  (pictures in `docs/library/release/pictures/2026-10-28-*`).
- Windows x64 zip under Wine 11, started through `forge-console.cmd`:
  `--smoke` 83 passed, 0 failed (13 apps), nothing written into the
  program folder. The setup program: not built (no Inno Setup).

## Checked earlier (2026-10-09; smoke counts from the build of 44cb4c7)

- Linux x64: built from `HEAD`, unpacked, run with `HOME` moved: `--smoke`
  86 passed, 0 failed (15 apps); the same in the Freedesktop 25.08 runtime
  through Flatpak, with no network; the GTK WebKit window in a private
  off-screen GNOME session; screenshots of the hub, an app inside it and
  Settings, also as Windows and macOS show them (`--as-system`).
- Windows x64: built on Linux, run under Wine 11 in a scratch prefix:
  `--smoke` 81 passed, 0 failed (every app but Terminal, cut on Windows);
  the Windows readers for CPU, memory, battery and drives return real
  numbers there.
- The source tree: its tests pass in a bare Python, and a Linux build made
  from it has the same file list as one made from this repository.
- macOS (arm64 and x64): built on Linux, layout of `Forge.app` checked.
  Never run on a Mac.
- The GitHub workflow (`source/build.yml`) builds and smokes every target on
  GitHub's own runners when started by hand. It has never run.

## Not decided yet

- Licence (`licence` in the registry; empty means all rights reserved).
- Code signing: a Windows certificate, an Apple developer account and
  notarisation. Until then both systems warn on first start.
- Where the downloads are published.
