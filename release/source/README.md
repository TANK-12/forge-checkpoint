<!-- Template: python3 release/build.py --source-tree fills in the @...@
fields and writes this as the source tree's README.md. -->
# Forge

@SUMMARY@

Forge is a home screen and a set of small apps that run on your own
computer. Each app is its own little web server; Forge starts an app the
first time you open it and stops them all when you close Forge. Some apps fetch public information when requested; optional AI features
use the local Jan server. See each app and the release registry for its
network-dependent features.

Release downloads bring Python and their app packages. Optional AI and
external tools are separate. The source checkout needs Python and dependencies.

Version @VERSION@.

## Event checkpoint — 28 October 2026

This is a separately saved preview, focused on Mac and Windows. The app code
comes from the tested 0.2.0 candidate; ongoing development is kept elsewhere.
It contains 14 apps on Mac, 13 on Windows, and 18 on Linux. Suggested offline
starts: Arcade, Drift Peaks, Emberfield, Exo Lab and PrintForge. AI features
need a separately installed Jan and a model; no models or personal saves ship.

The saved downloads now pass on native hosted Apple silicon and Intel Macs
(**88/88 checks each**), Windows (**83/83**) and Linux (**108/108**), after
full Mac/Windows installation through the supplied helpers.
[Native run evidence](https://github.com/TANK-12/forge-checkpoint/actions/runs/40654815268).
Desktop windows, Gatekeeper and SmartScreen still need a person to test them.
See [checkpoint evidence and limits](docs/CHECKPOINT.md),
[publication steps](docs/PUBLISH.md), and [licence placeholder](LICENSE).

## The apps

@APPS@

## Install

Download the file for your system from the
[dated checkpoint release](https://github.com/TANK-12/forge-checkpoint/releases/tag/checkpoint-2026-10-28).

### macOS first — Apple silicon 11+, Intel 12+

1. In About This Mac, check whether the chip is Apple silicon (M1 or newer)
   or Intel. Download `forge-@VERSION@-macos-arm64.tar.gz` for Apple silicon,
   or `forge-@VERSION@-macos-x64.tar.gz` for Intel, plus `SHA256SUMS`.
2. Double-click the archive. Inside the extracted `Forge` folder, drag
   `Forge.app` to your Applications folder (or `~/Applications`). The
   download includes Python and the Mac window packages; Homebrew and sudo
   are not needed for the bundle.
3. Open Forge. This preview is unsigned and not notarised. If macOS blocks
   it, follow Apple's [Open Anyway instructions](https://support.apple.com/en-us/102445)
   in System Settings > Privacy & Security, after checking the download's
   origin. Do not disable Gatekeeper. A managed Mac may disallow the override.
4. Pick a writable place for your data in the welcome screen, choose a look,
   then open a game. Keep that data place when replacing the program later.

Optional checksum-checked install to `~/Applications`, using the script from
this repository or the matching release attachment:

```sh
sh scripts/install-macos.sh "$HOME/Downloads/forge-@VERSION@-macos-arm64.tar.gz"
# Or, with the release attachment saved in Downloads:
sh "$HOME/Downloads/install-macos.sh" "$HOME/Downloads/forge-@VERSION@-macos-arm64.tar.gz"
# Intel: substitute macos-x64. The script refuses to overwrite an existing app.
```

For a headless smoke check on a Mac (starts app servers, then stops them),
choose the path matching where you installed Forge:

```sh
"/Applications/Forge.app/Contents/MacOS/Forge" --smoke --report "$HOME/forge-smoke.json"
# Or, after using the helper:
"$HOME/Applications/Forge.app/Contents/MacOS/Forge" --smoke --report "$HOME/forge-smoke.json"
```

If the native window fails, run that same executable with `--window browser`
from Terminal. Gatekeeper, native dialogs, audio and the WebKit
window still need an interactive Mac shakedown. The installed backend
checks passed on both native Mac architectures. Use the matching archive, not Rosetta
as a substitute for the Apple silicon build.

### Windows 10 and 11 — x64

1. Download `forge-@VERSION@-windows-x64.zip` and `SHA256SUMS`. Extract the zip
   into a writable local folder such as `%LOCALAPPDATA%\Programs` (the zip creates a `Forge` subfolder);
   avoid a OneDrive-synced Documents folder for this preview.
2. Double-click `Forge.cmd` in the extracted `Forge` folder. Python is
   bundled. Forge first tries an Edge/Chrome-family app window, then
   a native window through WebView2, then a browser tab.
3. This zip is unsigned; inspect any Windows warning and the source before
   deciding whether to run it. No setup EXE or code-signing certificate is
   included. Windows security policy, including Smart App Control, may
   prevent unsigned programs from running.
4. Pick your data place on the welcome screen. `forge-console.cmd --smoke`
   checks the apps without opening a window; `forge-console.cmd` shows logs.

Optional checksum-checked copy from PowerShell, with the zip and SHA256SUMS
in the same folder:

```powershell
powershell -NoProfile -File .\scripts\install-windows.ps1 -Archive "$HOME\Downloads\forge-@VERSION@-windows-x64.zip"
```

The helper defaults to `%LOCALAPPDATA%\Programs\Forge-checkpoint`. Its
full archive installation and installed app smoke checks passed on a native
hosted Windows runner; normal and trailing-separator destinations also passed. For the downloaded attachment, substitute
`"$HOME\Downloads\install-windows.ps1"` for the script path.
The helper refuses to overwrite its destination. A failed copy may leave a
partial new folder; choose a new destination before retrying. The Mac helper
has the same partial-copy limit. Local execution policy may block it;
if so, use Explorer to extract the zip; do not weaken machine policy.

### Linux (x86-64)

```sh
tar xzf forge-@VERSION@-linux-x64.tar.gz
./Forge/forge
```

Forge opens in a GTK window when the system Python has GTK and WebKit
(Arch: `python-gobject webkit2gtk-4.1`; Debian and Ubuntu:
`python3-gi gir1.2-webkit2-4.1`), otherwise in Chrome, Chromium, Edge or
Brave without tabs, otherwise in your browser. It needs glibc 2.28 or later
(any distribution from 2019 on).

Settings, saves and app data live outside the Forge folder, so a newer
version can replace the folder without losing them. `README.txt` in each
download says where, and lists the launcher's options.

## Apps that need another program

@NEEDS@

[Jan](https://jan.ai) is a free app that runs AI models on your computer.
Install it, download a model in it and turn on its local API server (port
1337); the apps above use it for their AI parts and run without it.

## What works differently on each system

Forge grew up on a Linux desktop. Everything a system cannot do is either
done another way, falls back to something simpler, or is cut from that
system's download with its controls hidden. `release/release.json` is the
list; the downloads' README.txt files carry the same notes.

@SYSTEM_NOTES@

## Run from source

With Python 3.14 installed (the downloads bring their own Python):

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python forge_portable.py
```

On Windows use `py -3.14 -m venv .venv`, then `.venv\Scripts\pip` and
`.venv\Scripts\python`. On macOS use `python3.14` if `python3` is older.
The portable entry point is `forge_portable.py`. The daily GTK launcher,
Hyprland/end4 desktop shell, systemd services, power controls, Linux mounts
and desktop widgets are Linux-only and are not part of the Mac/Windows app.
Files, Convert, Loops and Typeset are omitted on Mac/Windows; Terminal is
omitted on Windows. Desktop installers under `install/` belong to daily
Linux Forge and are not included here.
`python forge_portable.py --help` lists the options; `--smoke` starts every
app, checks that each answers, and stops.

## Build the downloads

```sh
python3 -m pytest tests                     # the launcher and the builder
python3 release/build.py                    # every system, into outputs/release/@VERSION@/
python3 release/build.py --target linux-x64 # one system
```

All four downloads are built on Linux: the builder fetches a relocatable
Python for each system (python-build-standalone, checked against pinned
SHA-256 digests) and installs each system's packages from wheels with
[uv](https://docs.astral.sh/uv/). It needs git, uv and network access the
first time. The manual GitHub workflow `.github/workflows/build.yml` is designed to do the same
when started from the Actions tab, then start every app of each download on
its own system (not yet run). The separate **Check saved checkpoint** workflow downloads
this dated release and runs its smoke checks on hosted Mac, Windows and
Linux machines without rebuilding the checkpoint; its [installed-copy run](https://github.com/TANK-12/forge-checkpoint/actions/runs/40654815268) passed all four targets.

## How it fits together

- `forge_portable.py`: the launcher. It serves the home screen on
  `http://127.0.0.1:8400`, opens a window (a native one where the system has
  it, else a browser in app mode, else a tab) and starts each app's backend
  the first time it is opened.
- `forge_core.py`: finds the apps and runs their backends.
- `hub/`: the home screen.
- `shared/`: styling, scripts and Python helpers every app uses.
- `apps/<name>/`: one app each: `forge_app.json` (name, port, entry module),
  a FastAPI backend and its `static/` page.
- `groups/`, `sections/`: how the home screen groups the apps.
- `release/`: `release.json` (what each system gets), `build.py`, the launch
  scripts and these templates.

Apps are found, not listed: a new app is one folder in `apps/` with a
`forge_app.json`, plus its entry in `release/release.json`.

## Licence

@LICENCE@
