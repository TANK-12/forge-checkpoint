<!-- Template: python3 release/build.py --source-tree fills in the @...@
fields and writes this as the source tree's README.md. -->
# Forge

@SUMMARY@

Forge is a home screen and a set of small apps that run on your own
computer. Each app is its own little web server; Forge starts an app the
first time you open it and stops them all when you close Forge. Nothing is
sent anywhere unless an app says so: a few can look things up on the web
when you ask them to.

It runs on Windows, macOS and Linux and brings its own Python, so there is
nothing else to install and no administrator rights are needed.

Version @VERSION@.

## The apps

@APPS@

## Install

Download the file for your system from the Releases page.

### Windows 10 and 11

1. Unzip `forge-@VERSION@-windows-x64.zip` anywhere (Documents is fine).
2. Double-click `Forge.cmd` in the `Forge` folder.
3. Windows may say "Windows protected your PC" because this release is not
   signed: choose **More info**, then **Run anyway**.

Forge opens in a Microsoft Edge window without tabs. `forge-console.cmd`
does the same with a console window that shows the log.

### macOS 11 or later

1. Double-click `forge-@VERSION@-macos-arm64.tar.gz` (Apple silicon) or
   `forge-@VERSION@-macos-x64.tar.gz` (Intel) to unpack it, then drag
   `Forge.app` into Applications.
2. The first time, macOS refuses an app that is not signed: open
   **System Settings**, **Privacy & Security**, and choose **Open Anyway**
   next to Forge.

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

With Python 3.14 (the version the downloads carry and the tests use):

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python forge_portable.py
```

On Windows use `.venv\Scripts\pip` and `.venv\Scripts\python`.
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
first time. The GitHub workflow `.github/workflows/build.yml` does the same
when started from the Actions tab, then starts every app of each download on
its own system.

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
