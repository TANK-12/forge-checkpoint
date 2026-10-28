# Forge

One window for many small local apps: games, creative tools, readers and research helpers, each its own little web server.

Forge is a home screen and a set of small apps that run on your own
computer. Each app is its own little web server; Forge starts an app the
first time you open it and stops them all when you close Forge. Some apps fetch public information when requested; optional AI features
use the local Jan server. See each app and the release registry for its
network-dependent features.

Release downloads bring Python and their app packages. Optional AI and
external tools are separate. The source checkout needs Python and dependencies.

Version 0.2.0.

## Event checkpoint — 28 October 2026

This is a separately saved preview, focused on Mac and Windows. The app code
comes from the tested 0.2.0 candidate; ongoing development is kept elsewhere.
It contains 14 apps on Mac, 13 on Windows, and 18 on Linux. Suggested offline
starts: Arcade, Drift Peaks, Emberfield, Exo Lab and PrintForge. AI features
need a separately installed Jan and a model; no models or personal saves ship.

Mac packages are built and their structure checked on Linux, **not run on a
real Mac**. Windows is checked under Wine, **not on a real Windows PC**.
See [checkpoint evidence and limits](docs/CHECKPOINT.md),
[publication steps](docs/PUBLISH.md), and [licence placeholder](LICENSE).

## The apps

- **Afterglow**: Claude's after-hours toys, made for fun
- **Arcade**: Nine games, five experiments
- **Convert**: Images, sound and documents, re-saved (not on Windows, macOS)
- **Cosmos**: Map of the solar system, and gravity games
- **Dossier**: Sourced portfolios on people and countries
- **Drift Peaks**: An endless low-poly snowboard ride
- **Emberfield**: Farm the valley, raid the wilds
- **Exo Lab**: Exo-suit and mech test bench, plus a game
- **Files**: Browse, copy, move and preview your files (not on Windows, macOS)
- **Foresight**: Signals and plans built on Dossier's facts
- **Janhollow**: A space station that lives on its own
- **Loops**: Beats and loops on a step grid, saved as WAV (not on Windows, macOS)
- **Mint**: Where $300 a week could go, tested on real history with fake money
- **PixelForge**: Sprites and animation, shared
- **PrintForge**: Look over 3D-print files before you slice them
- **Settings**: Wallpaper, colours and how Forge looks
- **Terminal**: Your shell, in tabs, inside Forge (not on Windows)
- **Typeset**: Typst documents, CVs and letters to PDF (not on Windows, macOS)

## Install

Download the file for your system from the
[dated checkpoint release](https://github.com/TANK-12/forge-checkpoint/releases/tag/checkpoint-2026-10-28).

### macOS first — Apple silicon 11+, Intel 12+

1. In About This Mac, check whether the chip is Apple silicon (M1 or newer)
   or Intel. Download `forge-0.2.0-macos-arm64.tar.gz` for Apple silicon,
   or `forge-0.2.0-macos-x64.tar.gz` for Intel, plus `SHA256SUMS`.
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
sh scripts/install-macos.sh "$HOME/Downloads/forge-0.2.0-macos-arm64.tar.gz"
# Or, with the release attachment saved in Downloads:
sh "$HOME/Downloads/install-macos.sh" "$HOME/Downloads/forge-0.2.0-macos-arm64.tar.gz"
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
from Terminal. Mac hardware, Gatekeeper, native dialogs, audio and the WebKit
window still need a real-Mac shakedown. Use the matching archive, not Rosetta
as a substitute for the Apple silicon build.

### Windows 10 and 11 — x64

1. Download `forge-0.2.0-windows-x64.zip` and `SHA256SUMS`. Extract the zip
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
powershell -NoProfile -File .\scripts\install-windows.ps1 -Archive "$HOME\Downloads\forge-0.2.0-windows-x64.zip"
```

The helper defaults to `%LOCALAPPDATA%\Programs\Forge-checkpoint`. Its
native Windows execution is still unverified. For the downloaded attachment, substitute
`"$HOME\Downloads\install-windows.ps1"` for the script path.
The helper refuses to overwrite its destination. A failed copy may leave a
partial new folder; choose a new destination before retrying. The Mac helper
has the same partial-copy limit. Local execution policy may block it;
if so, use Explorer to extract the zip; do not weaken machine policy.

### Linux (x86-64)

```sh
tar xzf forge-0.2.0-linux-x64.tar.gz
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

- **Arcade**: Jan for its AI opponents
- **Dossier**: Jan
- **Foresight**: Jan
- **Janhollow**: Jan for its characters
- **PixelForge**: Jan

[Jan](https://jan.ai) is a free app that runs AI models on your computer.
Install it, download a model in it and turn on its local API server (port
1337); the apps above use it for their AI parts and run without it.

## What works differently on each system

Forge grew up on a Linux desktop. Everything a system cannot do is either
done another way, falls back to something simpler, or is cut from that
system's download with its controls hidden. `release/release.json` is the
list; the downloads' README.txt files carry the same notes.

### Linux

```
Done another way:
  Forge's own window: a GTK WebKit window through the system Python when it has one, else a Chrome-family browser in app mode, else a browser tab
  How the home screen talks to the launcher: HTTP requests and an event stream instead of WebKit's message channel

Falls back to something simpler:
  Full screen (F11 and the bar's button): the window's own full screen; Start full screen works in a window or app window
  Pop an app out into its own window: a second window of the same kind
  App size slider (whole-page zoom): the window's own zoom, Ctrl + and Ctrl -
  Forge's own keyboard shortcuts (caught before the page): the hub page and each app's page catch them and pass them to the hub (hub/portable.js, shared/forge_chrome.js); the keys cannot be changed, and Quit and Restart are not keys
  Wallpaper blur, small previews and colours taken from the wallpaper: made with ImageMagick when it is installed; without it the wallpaper shows sharp, previews are the full pictures and the theme keeps its own colours

Not in this version:
  Adding a YouTube link's audio to the music folder: needs yt-dlp and the GTK launcher
  Visualiser driven by the system's sound output: PipeWire capture lives in the GTK launcher
  Other players on the desktop in Now playing (MPRIS): D-Bus media control lives in the GTK launcher
  Live pictures of open apps in the overview: the overview shows each app's icon
  Lighter effects on battery: effects use the plugged-in values
  Start Forge at login: not set up for the release launcher yet
  PS5 controller as mouse and keys: reads the pad through Linux input devices
  2.5D wallpaper (the picture split into depth layers by local AI models): needs onnxruntime and two AI models that are not in the release
  Hiding Forge on close and resting while hidden, and particles and widgets on the desktop itself: needs the GTK launcher and a GNOME or Hyprland extension
  Settings for the computer itself (sound, Wi-Fi, Bluetooth, display, battery, notifications, the clock, closing idle apps) and Pick for my machine: they change the computer's own settings and were made for one laptop, not yet for any computer
```

### Windows

```
Done another way:
  Forge's own window: Microsoft Edge in app mode (a window without tabs), else WebView2 through pywebview, else a browser tab
  How the home screen talks to the launcher: HTTP requests and an event stream instead of WebKit's message channel
  CPU, memory, battery and drive numbers in the top bar and the home widgets: CPU, memory, battery and drives read from Windows itself

Falls back to something simpler:
  Full screen (F11 and the bar's button): the window's own full screen; Start full screen works in an app window
  Pop an app out into its own window: a second window of the same kind
  App size slider (whole-page zoom): the window's own zoom, Ctrl + and Ctrl -
  Forge's own keyboard shortcuts (caught before the page): the hub page and each app's page catch them and pass them to the hub (hub/portable.js, shared/forge_chrome.js); the keys cannot be changed, and Quit and Restart are not keys
  Wallpaper blur, small previews and colours taken from the wallpaper: made with ImageMagick when it is installed (magick on the PATH); without it the wallpaper shows sharp, previews are the full pictures and the theme keeps its own colours

Not in this version:
  Adding a YouTube link's audio to the music folder: needs yt-dlp and the GTK launcher
  Visualiser driven by the system's sound output: no portable capture
  Other players on the desktop in Now playing (MPRIS): Linux D-Bus only
  The Network and Jan home widgets: network speed and Jan's state are read from Linux's /proc
  Live pictures of open apps in the overview: the overview shows each app's icon
  Lighter effects on battery: effects use the plugged-in values
  Start Forge at login: not set up for the release launcher yet
  PS5 controller as mouse and keys: Linux input devices only
  2.5D wallpaper (the picture split into depth layers by local AI models): needs onnxruntime and two AI models that are not in the release
  Hiding Forge on close and resting while hidden, and particles and widgets on the desktop itself: Linux desktop only
  Settings for the computer itself (sound, Wi-Fi, Bluetooth, display, battery, notifications, the clock, closing idle apps) and Pick for my machine: they drive Linux system tools

Apps left out on this system:
  Convert: documents fetch a Linux build of pandoc (Linux only in this test build)
  Files: trash, restore and open use gio and xdg-open from the Linux desktop (Linux only in this test build)
  Loops: deleting a pattern uses gio trash (Linux only in this test build)
  Terminal: needs a Unix pseudo-terminal (pty), which Windows does not have
  Typeset: it fetches a Linux build of Typst, and Move to trash uses gio (Linux only in this test build)
```

### macOS

```
Done another way:
  Forge's own window: a WebKit window through pywebview, else Chrome or Edge in app mode, else a browser tab
  How the home screen talks to the launcher: HTTP requests and an event stream instead of WebKit's message channel

Falls back to something simpler:
  Full screen (F11 and the bar's button): the window's own full screen; Start full screen works in a window or app window
  Pop an app out into its own window: a second window of the same kind
  App size slider (whole-page zoom): the window's own zoom, Cmd + and Cmd -
  Wallpaper blur, small previews and colours taken from the wallpaper: made with ImageMagick when it is installed (brew install imagemagick); without it the wallpaper shows sharp, previews are the full pictures and the theme keeps its own colours

Not in this version:
  Adding a YouTube link's audio to the music folder: needs yt-dlp and the GTK launcher
  Visualiser driven by the system's sound output: no portable capture
  Forge's own keyboard shortcuts (caught before the page): Option and a letter types a character on a Mac
  Other players on the desktop in Now playing (MPRIS): Linux D-Bus only
  CPU, memory, battery and drive numbers in the top bar and the home widgets: no way to read them has been tried on a Mac yet
  The Network and Jan home widgets: network speed and Jan's state are read from Linux's /proc
  Live pictures of open apps in the overview: the overview shows each app's icon
  Lighter effects on battery: effects use the plugged-in values
  Start Forge at login: not set up for the release launcher yet
  PS5 controller as mouse and keys: Linux input devices only
  2.5D wallpaper (the picture split into depth layers by local AI models): needs onnxruntime and two AI models that are not in the release
  Hiding Forge on close and resting while hidden, and particles and widgets on the desktop itself: Linux desktop only
  Settings for the computer itself (sound, Wi-Fi, Bluetooth, display, battery, notifications, the clock, closing idle apps) and Pick for my machine: they drive Linux system tools

Apps left out on this system:
  Convert: documents fetch a Linux build of pandoc (Linux only in this test build)
  Files: trash, restore and open use gio and xdg-open from the Linux desktop (Linux only in this test build)
  Loops: deleting a pattern uses gio trash (Linux only in this test build)
  Typeset: it fetches a Linux build of Typst, and Move to trash uses gio (Linux only in this test build)
```

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
python3 release/build.py                    # every system, into outputs/release/0.2.0/
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
Linux machines without rebuilding the checkpoint.

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

No licence has been chosen yet, so all rights are reserved for now.
