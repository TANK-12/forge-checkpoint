# Files

A file manager inside Forge (A18 in `sessions/2026-09-26-S9-terminal-files-code.md`).
Port 8458, section "system". Stdlib-only backend (FastAPI + uvicorn in its own `.venv`).

## Layout
- `fsops.py`: every rule. The path guard (`resolve()`: only home and the drive mount
  parents `/run/media/$USER`, `/media/$USER`, `/mnt`), trash-only removal (`gio trash`,
  no unlink/rmtree in the module; a test reads the source to keep it that way),
  copy/move jobs with byte progress, name search bounded by count and time,
  thumbnails (the desktop's own freedesktop cache when current, otherwise
  ffmpeg at nice 15 into `~/.cache/forge-files/thumbs/` as small JPEGs).
- `web_app.py`: thin HTTP layer. Every `/api` route needs `X-Forge: 1` or `?t=<token>`
  (token only for `<img>`/`<video>` src; fetched from `/api/session` with the header).
- `static/`: the page (`app.js`, `app.css`), shared Forge kit.

## Features
Sidebar from `~/.config/user-dirs.dirs` + `~/Forge` + mounted drives (rechecked every
10 s) + Trash; breadcrumb (double-click or Ctrl+L to type a path); back/forward/up
(also mouse side buttons); list and grid (Ctrl+G; Ctrl+wheel sizes tiles); sort by
name/size/type/modified; search (Ctrl+F); multi-select (click, Ctrl, Shift, rubber
band, Ctrl+A, type-ahead); copy/cut/paste (Ctrl+C/X/V, paths also go to the system
clipboard); rename (F2); new folder (Ctrl+Shift+N); move to trash (Delete); open with
the default app (Enter/double-click, `xdg-open`); drag and drop onto folders, sidebar
places and breadcrumb parts (Ctrl while dropping = copy); hidden files (Ctrl+H);
preview pane (F3): image, video, audio, text.
The open folder redraws by itself when something is added, removed or renamed
in it (a 3 s stamp check while the page is shown, `/api/stamp`), keeping
selection, scroll and thumbnails; Back/Forward return to the scroll place.
Drag in from outside Forge: `file://` links are copied as a normal job,
otherwise the files are uploaded (`/api/upload`, written to a hidden `.part`
and renamed into place; refused when the drive would drop under 256 MB free).
Rows dragged out carry `file://` links. Extract and compress show a percentage.

Links in: `#path=/folder`, `#select=/folder/file`, `#view=grid|list`.

More windows (2026-10-24): Ctrl+N, the ⧉ button in the bar, middle-click on a
folder or a sidebar place, "Open in new window" in a folder's menu and "New
window here" in the background menu open another Files window, each with its
own folder and Back/Forward history. In Forge it is a real native window
("Files 2 - Forge"), opened through the hub (`newWindow()` posts
`{forge: "window", hash}`; see the frontend contract in Forge's README);
closing it leaves the others open, closing Files in the hub closes them all.
Copy/Cut and Paste work between windows: the clipboard lives in the
backend (`/api/clip`, in memory, numbered by `seq`; `/api/stamp` carries the
number so other windows follow within a few seconds, and Paste asks for the
latest first). Dragging from one window into the other goes through the
drag-out/drop-in path (file:// links, copied), which is not yet tried between
two real Forge windows. In a plain browser a new window is a new tab. Sort
and view settings are shared through localStorage; the last folder remembered
for the next start is whichever window moved last.

## Checks
- `.venv/bin/python -m pytest -q tests` (unit + HTTP, includes a real `gio trash` into a
  sandbox trash via `XDG_DATA_HOME`).
- Pop-out windows: `tests/test_popout.py` in Forge (no display) and
  `/usr/bin/python3 tests/browser/check_popout_window.py` (a private headless
  GNOME; step 8 covers more windows of one app).
- `.venv/bin/python tests/check_ui.py`: drives the real page in headless Chrome
  (Flatpak) against a sandbox folder; prints PASS/FAIL lines.
  `FILES_CHECK_PORTS=18667,18668` pins the backend and Chrome ports.
