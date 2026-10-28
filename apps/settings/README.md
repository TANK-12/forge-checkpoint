# Settings

How Forge looks and behaves: the wallpaper, the accent colour, the glass, the
gaps and corners, animations, the clock and what Forge opens on. Runs at
<http://127.0.0.1:8441> inside Forge, or standalone:

```
FORGE_SHARED_DIR=~/Forge/shared \
  .venv/bin/python -m uvicorn web_app:app --host 127.0.0.1 --port 8441
```

## How it fits

This app owns no theme logic. Everything lives in **`shared/forge_theme.py`**,
because `forge.py` needs the same code at launch:

| What | Where |
|---|---|
| The settings, with defaults and limits | `forge_theme.SETTINGS` - one line per setting |
| The user's choices | `~/.config/forge/settings.json` |
| Wallpaper copies, blurred copies, palettes, thumbnails | `~/.cache/forge/` - safe to delete |
| The theme the hub reads at launch | `hub/theme.js`, a script global like `status.js` |

A change travels two ways at once:

1. **Live.** The page saves it, gets the resulting theme back and posts
   `{forge: "theme", theme}` to the hub. The hub restyles itself and passes
   the part an app needs to every open app, where `shared/forge_chrome.js`
   applies it. Nothing restarts.
2. **Next launch.** Saving also rewrites `hub/theme.js`.

The hub finds this app through `"role": "settings"` in `forge_app.json`, not by
its name, so the gear in the top bar keeps working if the app is renamed.

## Wallpaper

By default Forge **follows the desktop wallpaper**, read from
`~/.local/state/caelestia/wallpaper/path.txt`. Picking one here stops following.
The picker lists `~/Pictures/Wallpapers`. A thumbnail is only served for a name
in that listing, never for a path built from the URL.

The originals are 5-28 MB. Forge draws a 2560 px JPEG copy (about 200 KB) and
a pre-blurred copy for behind apps, both made once per picture with ImageMagick
in about 0.3 s. Without ImageMagick the original is used unblurred.

**The whole Wallpapers browser lives here** (2026-10-28, Relay task 423).
This backend imports `apps/wallpapers/web_app.py` and mounts it at
`/wallpapers/`, and starts its index thread in its own lifespan; "Browse all
wallpapers" in this section opens it in a frame (`wallpapers/?embed=1`).
`#wallpapers` (and `#wallpapers/favourites`) opens the section with the
browser open, which is where the hub sends anyone opening the Wallpapers app
(its manifest's `"inside"`). Themes go both ways: the browser's new theme is
passed up to the hub, the hub's themes are passed down to the browser (also
on its `ready`). Without `apps/wallpapers` (a release) there is no browser,
no button and no favourites (`wall_browser` false in `/api/settings`).

Thumbnails are warmed in a background thread when this backend starts: current
wallpaper first, one at a time, at `nice 15`. Measured: the first 21 (the first
rows of the grid) were ready 5 s after start. Cached, so later launches do
nothing.

## Colour

Taken from the wallpaper's own palette (`magick ... -colors 8`), not by running
matugen - matugen applies its templates, so running it would rewrite the
desktop's theme too. The most saturated colour wins, weighted a little by how
common it is, and is lifted to a lightness that reads on dark glass. A grey
wallpaper gets the default blue rather than an invented hue.

## System (2026-10-19)

The **System** section holds the laptop's own settings: Wi-Fi, Bluetooth,
sound, display, battery, notifications, the clock and the RAM auto-close
rules. Moved here from the Claude app. One module per panel in
`system_settings/`, listed in `system_settings/panels.json` (adding a panel is
one module plus one entry); routes under `/api/system`, which need
`X-Forge: 1` and a local Host; drawn by `static/system.js`. Details in WIP.md.

## Layout

The Layout section (in the section list, just above About) sets how Settings
itself looks: the section list as a sidebar, tabs or one long page, comfortable
or compact spacing, normal or wide, and which sections are pinned to the top
(the star beside each one). Kept in this browser's localStorage under
`forge.settings.layout`. Until 2026-09-27 this was a pop-up behind a Layout
button in the header; the owner found it floating over the top right, so it
became a section. Checked by `tests/browser/settings_sections_harness.js`
(run with `tests/browser/run.sh`).

## Resets and Pick for my machine (2026-10-24, Relay task 323)

Resets come in three layers, and all of them go the same way (`resets.py`,
`static/resets.js`): the page asks the backend what would change
(`POST /api/reset/preview`), shows that in a dialog that asks first, then runs
it (`POST /api/reset`), which keeps a copy of `settings.json` (and the
auto-close rules when they are part of it) in `~/.config/forge/backups/`.
The toast after a reset has Undo (`POST /api/reset/undo`), and About lists the
kept copies with Put back.

- **One page**: the button at the foot of every page (generated sections and
  the Wallpaper and Colour cards) says how many of its settings differ and is
  disabled at "All at default". System panels that name a group in
  `system_settings/panels.json` (`"reset"`) get one too: Auto-close (all rules
  back to default), Wi-Fi (forget saved networks, the one in use kept unless
  unticked), Bluetooth (remove paired devices), Display and Notifications.
- **Groups** (the Reset page): settings that belong together, declared in
  `reset_groups.json` by sections and keys: Visual effects, Power and frame
  rates, Wi-Fi and Bluetooth, Look and size, Bar, dock, home and widgets, Auto-close
  rules, Keyboard shortcuts. A new group is one entry there.
- **Everything**: Reset all settings at the foot of About. It does not run the
  System forget steps, and it keeps what he made rather than chose (app
  folders, hidden and archived apps, saved size mixes, company profiles:
  `keep_on_reset_all` in `reset_groups.json`).

Forgetting networks or devices cannot be undone; the dialog lists each as a
tick box and says so. While the Business look is locked every reset, undo and
pick answers 423 and the password prompt opens (`Business.ask`), then runs it.

The auto-close table's per-app "reset" shows only when that row differs from
its default (`shared/forge_autoclose.py`: `custom` compares with the default,
and saving a rule drops values equal to the default).

**Pick for my machine** (`shared/forge_machine.py`, rules and levels in
`shared/machine_profiles.json`) reads the CPU, GPU, RAM, battery and the CPU's
RAPL power limits, and picks a visual level (Light, Balanced, Rich, Full) and a
power choice (Saver, Balanced, Performance). Either pick can be changed before
Apply; it sets Forge's keys, Forge Desktop's `desktop_*` keys, or both, through
the same dialog, backup and Undo. Forge Desktop's own settings window has the
same button (`desktop/host/core.py` `pick_machine`, with Undo). "Power" means
Forge's own power use (frame-rate caps, battery twins, GPU ease, the low
battery saver); CPU watt caps stay in the Power app, shown here as read-only.

## App options (2026-10-26, Relay task 357)

Each app's own options, beside Forge's. An app opts in with
`apps/NAME/options.json` (shape and checks in `shared/forge_options.py`: a
label, the app's settings file, and options of kind bool, int, number,
choice or text with defaults and limits). Settings draws them with the
same rows as its own cards, saves each change into the app's own file
(never Forge's settings.json or the hub's theme.js), counts them in
Changed from default, and finds them in the search. A change that drops
data (a shorter keep time) asks first. The Business lock refuses saves
with 423 like any other. The section says how many apps have no
`options.json` yet. `python3 shared/forge_options.py check` checks every
file. API: `GET /api/options`, `POST /api/options/NAME` (both need
`X-Forge: 1` and a local Host). Reset all and the reset groups cover
Forge's own settings only: app options keep their values and are reset one
at a time from their own row.

## About, edition and licence (2026-10-26, Relay task 357)

The top of the About card shows Forge's edition (from
`shared/forge_editions.json` and a licence file, through
`shared/forge_edition.py`), the version, and a signed licence's licensee,
seats, dates and id. "Add a licence file" sends the file's text to
`POST /api/about/licence`; `shared/forge_licence.py` checks it offline
against `shared/forge_licence_keys.json` and refuses a bad one without
writing anything. "Remove licence" asks first and keeps the old file
renamed. Both are refused with 423 while the Business lock is shut. "Make a
support report" writes a new zip of the newest log lines to Downloads with
the home folder, user name, emails and keys scrubbed out
(`shared/forge_diag.py`); the card says where it went. Editions are
declared, not enforced: every feature still works in every edition.

## Business (2026-10-23)

The Business card turns on the Business look (`hub/looks/business.css` and
`business.json`): a plain dark slate hub with flat panels, no particles,
music, visualiser, 3D wallpaper or animations, and the active company's logo
in a footer strip under the app list. Those overrides are applied in
`forge_theme.theme()` only; the saved settings are untouched, so the old
choices come back when another look is picked.

While Business is the look and a password is set, every settings save is
refused (`forge_theme.save` raises `forge_lock.Locked`, answered as 423 here,
in Wallpapers and in Power; the hub shows a toast). That covers leaving the
look too. The page greys every other section, shows a banner, and a refused
change opens the password prompt and is sent again once it unlocks. The
password opens a 10-minute window; "Lock now" shuts it early; five wrong tries
make the next one wait 30 s. With no password set nothing locks.

"Back to my old look (<look>)" (2026-10-24) sits in the Business card
whenever Business is on, on the locked banner, and in the password prompt.
Picking a locked look from an open one stores the open one in the custom
setting `look_before_lock` (`forge_theme.save`); `forge_theme.look_to_go_back`
gives it back while it still exists and does not lock, else the default
(Classic). `/api/lock` replies carry it as `back_look` and `back_label`. While
locked the button asks for the password first ("Unlock and go back"), then
saves `look`; a change or reset the lock had refused is dropped, not saved on
the way out. Reset all leaves `look_before_lock` alone.

Routes (all POSTs need `X-Forge: 1` and a local Host): `GET /api/lock`
(status, never the hash), `POST /api/lock/unlock` {password},
`POST /api/lock/relock`, `POST /api/lock/password` {current, new},
`POST /api/business/logo` {data: data URL; png, jpg, webp or svg, 4 MB max,
locked like any save}, `GET /api/business/logo/<sha16>.<ext>`. Company
profiles are the settings `business_companies` [{id, name, logo}] and
`business_company` (the active id). Set the password from a shell without it
showing: `python3 ~/Forge/shared/forge_lock.py set`.

The System section's actions are refused too. The hub is sent
`look_open_until` when the window opens or shuts, so its own changes follow
the same window. A logo is served with a sandboxing CSP, so an SVG cannot run
script as this site.

It is a lock against someone at the screen, not against someone with a shell.


```
.venv/bin/python -m pytest tests -q
```

68 tests, no network. ImageMagick is used for real where a test needs it.
The browser checks (headless Flatpak Chrome, each on a scratch backend with
a scratch config; run them with `~/Forge/apps/files/.venv/bin/python`, which
has websockets): `tests/check_settings_ui.py` (wallpaper, Changed from
default, no needless re-renders, dark first paint) and
`tests/check_system_ui.py` (the System section) and
`tests/check_business_ui.py` (the Business look and its lock). Details in WIP.md.

## Speed and detail, and `also` (2026-09-27)

A setting in `shared/forge_theme.py` may carry `"also": [GROUP, ...]`: the same control is drawn again in those cards, after the card's own settings, labelled "<its group>: <label>". Both controls follow one setting. Speed and detail uses it to collect every frame-rate and particle-detail slider. The page re-reads the settings on every theme message from the hub (a change made in the Power app, or the charger being plugged in or pulled out) and marks the plugged-in or battery row that is in use now, from the theme's `power_pairs`.

## Sliders applied on release (2026-10-07)

A field whose spec in `shared/forge_theme.py` says `"apply": "release"` (App
size, Text size, Icon size) only previews while its slider is dragged: the
number and preset name update, and `"preview": "text_size"` shows the size on
this page through `ForgeChrome.previewTextSize`. Nothing is saved or sent to
the hub until release (`change`), then once. App size zooms the whole Forge
window, this page included, so applying it mid-drag moved the slider under
the pointer and the size flip-flopped. The Preset slider works the same way.
Drag check: `tests/browser/check_size_drag.py` in the Forge root;
measurements in `docs/library/forge/2026-10-07-size-sliders.md`.

## Changed from default (2026-10-19/20)

The button under the search box counts the settings changed from their
defaults and, pressed, shows only those rows across every section, like a
search. Each changed row (a dot row, or a Forge key of your own) has a ↺
that puts that one setting back; the row stays where it is until the view
is opened again. Typing a search, Esc or picking a section leaves the view;
Esc works wherever the focus is (the button just pressed, a ↺, nothing)
except inside a box being typed in, such as a Forge key, where it is that
box's own.
Wallpaper and Colour count through `data-settings` on their cards.

## Bluetooth switched off at the radio (2026-10-20)

When rfkill blocks the Bluetooth radio (airplane mode, the quick settings),
Dell's adapter disappears and `bluetoothctl` only says "No default controller
available". The Bluetooth panel now reads `rfkill -J` and says "Bluetooth is
off" in plain words with a **Turn Bluetooth on** button (`unblock`: `rfkill
unblock bluetooth`, wait up to 6 s for the adapter, power it on). A hardware
or BIOS block is named, with no button. The power switch also lifts a soft
block before `power on`.
