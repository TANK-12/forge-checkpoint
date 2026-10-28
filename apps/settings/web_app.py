"""Settings - how Forge looks and behaves.

A thin API over `shared/forge_theme.py`, which owns every setting, the
wallpaper rendering and the colour extraction. This app only reads and saves
them, serves wallpaper thumbnails for its picker, and rewrites `hub/theme.js`
so the next launch opens with the same look. The live change is sent by the
page straight to the hub with postMessage, so nothing waits on a restart.

The System section (Wi-Fi, Bluetooth, sound, display, battery, notifications,
clock and the RAM auto-close rules) is `system_settings/`, one module per
panel listed in `system_settings/panels.json`, behind /api/system. Those
routes change the laptop, so they need the header `X-Forge: 1` and a local
Host (a DNS-rebinding page can send the header but not the Host).

Resets come in layers (resets.py, reset_groups.json): one page, a group of
settings that belong together, or everything; each keeps a backup first and
can be undone. /api/machine is Pick for my machine (shared/forge_machine.py).

The Business look's password lock (shared/forge_lock.py) refuses saves with
423 while it is shut, resets and Pick for my machine included; /api/lock opens and shuts it and changes the password,
and /api/business/logo takes a company logo for the Business home screen.

/api/options lists every app's own options (apps/NAME/options.json, through
shared/forge_options.py) and saves them into that app's own file; it needs
X-Forge: 1 and a local Host, and the lock refuses it like any save.

/api/about (about_api.py) gives the version, edition and licence for the About
card, adds or removes a licence file (refused while the lock is shut) and
writes a scrubbed support report zip to Downloads.

Run standalone with:
    FORGE_SHARED_DIR=~/Forge/shared \\
    .venv/bin/python -m uvicorn web_app:app --host 127.0.0.1 --port 8441
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import importlib.util
import json
import os
import re
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR", ROOT.parent.parent / "shared"))
HUB_DIR = SHARED_DIR.parent / "hub"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

import about_api  # noqa: E402
import forge_autoclose  # noqa: E402
import forge_lock  # noqa: E402
import forge_machine  # noqa: E402
import forge_options  # noqa: E402
import forge_theme  # noqa: E402
import forge_themes  # noqa: E402
import forge_wallpapers  # noqa: E402
import resets  # noqa: E402
import system_settings  # noqa: E402  (its autoclose panel imports shared/)


def load_wallpapers_app(path: Path = ROOT.parent / "wallpapers" / "web_app.py"):
    """The Wallpapers app's own backend module, which Settings serves at
    /wallpapers/ so Settings > Wallpaper holds the whole browser (Relay task
    423; its manifest's "inside" sends anyone opening it here). None when the
    app is not installed beside this one (a release has none)."""
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("wallpapers_web_app", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # a broken Wallpapers app must not stop Settings
        print(f"settings: wallpapers browser not loaded: {exc!r}", file=sys.stderr)
        return None
    return module


wallpapers_app = load_wallpapers_app()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Thumbnails are made ahead of time, niced, so the wallpaper picker is
    # already full by the time anyone opens it. Cached, so only the first
    # launch does real work.
    current = forge_theme.chosen_wallpaper(forge_theme.load())
    threading.Thread(
        target=forge_theme.warm_thumbnails,
        kwargs={"first": [current.name] if current else []},
        daemon=True,
        name="thumbnails",
    ).start()
    # the browser's index (sizes and hidden copies), as its own backend did
    if wallpapers_app is not None:
        wallpapers_app.start_index()
    yield


app = FastAPI(title="Settings", lifespan=lifespan)


@app.exception_handler(forge_lock.Locked)
async def locked_handler(_request: Request, error: forge_lock.Locked):
    return JSONResponse({"detail": str(error), "locked": True}, status_code=423)


@app.get("/api/settings")
def get_settings():
    settings = forge_theme.load()
    desktop = forge_theme.desktop_wallpaper()
    return {
        "settings": settings,
        "fields": forge_theme.describe(),
        "theme": forge_theme.theme(settings),
        "config": str(forge_theme.CONFIG),
        "cache": str(forge_theme.CACHE),
        "wallpaper_dir": str(forge_theme.WALLPAPER_DIR),
        "desktop_wallpaper": desktop.name if desktop else "",
        "desktop_follow": forge_theme.desktop_follow_supported(),
        "roles": app_roles(),
        "wall_browser": wallpapers_app is not None,
        "current": current_wallpaper(settings),
    }


def current_wallpaper(settings: dict) -> dict:
    """The picture Forge shows now, for the page: its name in the wallpaper
    folder ("anime/moon.png"; "" when it is kept elsewhere, such as a desktop
    picture outside the folder) and a thumbnail address that works either
    way. The theme names it by the bare file name only, which matched no tile
    and no thumbnail for a picture in a sub-folder. The address carries the
    file's size and time, so a different picture is fetched anew."""
    source = forge_theme.chosen_wallpaper(settings)
    try:
        stat = source.stat() if source else None
    except OSError:  # gone since the desktop named it
        stat = None
    if source is None or stat is None:
        return {"name": "", "thumb": ""}
    folder = forge_theme.WALLPAPER_DIR
    name = ""
    for path, base in ((source, folder), (source.resolve(), folder.resolve())):
        try:
            name = path.relative_to(base).as_posix()
            break
        except ValueError:
            continue
    if name and forge_theme.wallpaper_path(name) is None:
        name = ""
    version = quote(f"{source.name}-{stat.st_size}-{int(stat.st_mtime)}")
    return {"name": name, "thumb": f"/api/current-wallpaper/thumb?v={version}"}


def app_roles(apps_dir: Path = ROOT.parent) -> list[str]:
    """The roles of the apps installed beside this one (their manifest's
    "role"): the page offers "Open Wallpapers" and the favourites, which are
    starred there, only when a wallpapers app is there (a release has none)."""
    roles = set()
    for manifest in apps_dir.glob("*/forge_app.json"):
        try:
            role = json.loads(manifest.read_text(encoding="utf-8")).get("role")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(role, str) and role:
            roles.add(role)
    return sorted(roles)


@app.post("/api/settings")
def save_settings(payload: dict | None = None):
    """Save the changed settings and return the theme they produce.

    Also rewrites hub/theme.js, so the next launch opens with this look.
    """
    settings = forge_theme.save(payload or {})
    if "start_at_login" in (payload or {}):
        forge_theme.set_autostart(settings["start_at_login"])
    if "theme_desktop" in (payload or {}):
        forge_themes.write_desktop(settings)
    data = forge_theme.theme(settings)
    forge_theme.write_theme_js(HUB_DIR, data)
    return {"settings": settings, "theme": data, "current": current_wallpaper(settings)}


@app.get("/api/wallpapers")
def wallpapers():
    return {
        "folder": str(forge_theme.WALLPAPER_DIR),
        "wallpapers": forge_theme.list_wallpapers(),
    }


@app.get("/api/favourites")
def favourite_wallpapers():
    """Wallpapers starred in the Wallpapers app, if they still exist."""
    known = {w["name"] for w in forge_theme.list_wallpapers()}
    return {"favourites": [n for n in forge_wallpapers.favourites() if n in known]}


# `:path` because a wallpaper in a sub-folder is named "anime/moon.png".
@app.get("/api/wallpapers/{name:path}/thumb")
def wallpaper_thumb(name: str):
    """A small preview. Only names the folder listing vouches for are served."""
    source = forge_theme.wallpaper_path(name)
    if source is None:
        raise HTTPException(404, "No wallpaper by that name")
    thumb = forge_theme.thumbnail(source)
    return FileResponse(thumb or source, headers={"Cache-Control": "max-age=604800"})


@app.get("/api/current-wallpaper/thumb")
def current_wallpaper_thumb():
    """The thumbnail of the picture Forge shows now, wherever it is kept: the
    desktop's picture can be outside the wallpaper folder, where the route
    above serves nothing. The path comes from the settings and the desktop,
    never from the URL (its `v` only tells one picture's address from
    another's)."""
    source = forge_theme.chosen_wallpaper(forge_theme.load())
    if source is None or not source.is_file():
        raise HTTPException(404, "No wallpaper now")
    thumb = forge_theme.thumbnail(source)
    return FileResponse(thumb or source, headers={"Cache-Control": "max-age=604800"})


# --- themes and home layouts (shared/forge_themes.py) -------------------------
# One file per theme in shared/themes/ and per layout in shared/layouts/. A
# pick saves through forge_theme.save, so while the Business look is locked
# it answers 423 like any settings save, and rewrites hub/theme.js.


def theme_wall(name: str) -> str:
    """A card's picture. The thumbnail route serves a theme's own pictures
    ("forge:<file>") as well as the wallpaper folder's; "" is the desktop's
    picture; nothing for one that is gone (the card shows the colours)."""
    if not name:
        desktop = forge_theme.desktop_wallpaper()
        return (
            f"/api/desktop-wallpaper/thumb?v={quote(desktop.name)}" if desktop else ""
        )
    if forge_theme.wallpaper_path(name) is not None:
        return f"/api/wallpapers/{quote(name, safe='')}/thumb"
    return ""


@app.get("/api/desktop-wallpaper/thumb")
def desktop_wallpaper_thumb():
    """The desktop's picture, for the cards of themes that follow it. The
    path comes from the desktop, never from the URL."""
    source = forge_theme.desktop_wallpaper()
    if source is None or not source.is_file():
        raise HTTPException(404, "No desktop wallpaper")
    thumb = forge_theme.thumbnail(source)
    return FileResponse(thumb or source, headers={"Cache-Control": "max-age=86400"})


def themes_list(settings: dict) -> dict:
    extra = forge_themes.extras(settings, theme_wall)
    keys = ("theme", "layout_id", "theme_can_undo", "themes", "layouts")
    return {k: extra[k] for k in keys}


def picked(settings: dict) -> dict:
    data = forge_theme.theme(settings)
    forge_theme.write_theme_js(HUB_DIR, data)
    return {
        "settings": settings,
        "theme": data,
        "current": current_wallpaper(settings),
        "themes": themes_list(settings),
    }


@app.get("/api/themes")
def get_themes():
    return themes_list(forge_theme.load())


@app.post("/api/themes/pick")
def pick_theme(payload: dict):
    try:
        return picked(forge_themes.pick(str(payload.get("id", ""))))
    except KeyError:
        raise HTTPException(404, "No theme by that name")


@app.post("/api/layouts/pick")
def pick_layout(payload: dict):
    try:
        return picked(forge_themes.pick_layout(str(payload.get("id", ""))))
    except KeyError:
        raise HTTPException(404, "No layout by that name")


@app.post("/api/themes/undo")
def undo_theme(payload: dict):
    """The JSON body is not used; asking for one keeps other sites' plain
    form posts out (as for /api/settings)."""
    return picked(forge_themes.undo())


@app.post("/api/themes/save")
def save_theme(payload: dict):
    """Keep the look in use now as a theme of his own. Saving a copy changes
    nothing, so the Business lock does not stop it."""
    tid = forge_themes.save_current(str(payload.get("name", "")))
    return {"id": tid, "themes": themes_list(forge_theme.load())}


# --- the Business look's lock and company logos -------------------------------


def look_locks() -> bool:
    return forge_theme.look_rules(forge_theme.load()["look"])["locked"]


def forge_only(x_forge: str | None = Header(default=None)) -> None:
    if x_forge != "1":
        raise HTTPException(403, "Send X-Forge: 1")


def local_host(host: str | None = Header(default=None)) -> None:
    """A DNS-rebinding page counts as same-origin and can send X-Forge, but
    its Host is its own name."""
    if (host or "").rsplit(":", 1)[0] not in ("127.0.0.1", "localhost"):
        raise HTTPException(403, "Local host only")


system_guarded = [Depends(forge_only), Depends(local_host)]


def cut_pages() -> set[str]:
    """The Settings pages (data-section ids) a release leaves out, such as
    the laptop's own System page (FORGE_CUT_PAGES, set by the portable
    launcher): the page is not served and its API answers 404."""
    return set(filter(None, os.environ.get("FORGE_CUT_PAGES", "").split(",")))


def page_shown(name: str):
    def check() -> None:
        if name in cut_pages():
            raise HTTPException(404, "That page is not in this version of Forge")

    return Depends(check)


def strip_sections(html: str, names: set[str]) -> str:
    """The page less each <section data-section="name"> card (none of them
    holds another section)."""
    for name in names:
        html = re.sub(
            rf'<section\b[^>]*\bdata-section="{re.escape(name)}"[^>]*>.*?</section>\s*',
            "",
            html,
            flags=re.S,
        )
    return html


def strip_keywords(html: str, section: str, words: set[str]) -> str:
    """The page with `words` taken out of one section's search keywords."""
    if not words:
        return html

    def keep(m: re.Match) -> str:
        kept = [w for w in m.group(2).split() if w not in words]
        return m.group(1) + " ".join(kept) + '"'

    pattern = (
        rf'(<section\b[^>]*\bdata-section="{re.escape(section)}"'
        r'[^>]*\bdata-keywords=")([^"]*)"'
    )
    return re.sub(pattern, keep, html, count=1)


# Version, edition, licence file and the support report (about_api.py).
app.include_router(about_api.make_router(system_guarded, look_locks))


# --- each app's own options (Settings > Apps, shared/forge_options.py) --------
# Saved only to the app's own file, never to Forge's settings.json or the
# hub's theme.js; the Business lock answers 423 like any settings save.


@app.get("/api/options", dependencies=system_guarded)
def get_options():
    return forge_options.describe_all()


@app.post("/api/options/{name}", dependencies=system_guarded)
def save_options(name: str, payload: dict | None = None):
    try:
        values = forge_options.save(name, payload or {})
    except forge_options.OptionError as error:
        missing = name not in {a["name"] for a in forge_options.describe_all()["apps"]}
        raise HTTPException(404 if missing else 400, str(error)) from error
    return {"name": name, "values": values}


def lock_reply() -> dict:
    """The lock's state for the page, with the look "Back to my old look"
    goes to (the one before Business, or the default)."""
    settings = forge_theme.load()
    back = forge_theme.look_to_go_back(settings)
    label = forge_theme.list_looks().get(back, {}).get("label", back.title())
    return {
        **forge_lock.status(look_locks()),
        "back_look": back,
        "back_label": label,
    }


@app.get("/api/lock", dependencies=system_guarded)
def lock_status():
    return lock_reply()


def _wrong(error: forge_lock.BadPassword) -> JSONResponse:
    return JSONResponse({"detail": str(error), "wait": error.wait}, status_code=403)


@app.post("/api/lock/unlock", dependencies=system_guarded)
def lock_open(payload: dict):
    try:
        forge_lock.unlock(str(payload.get("password") or ""))
    except forge_lock.BadPassword as error:
        return _wrong(error)
    return lock_reply()


@app.post("/api/lock/relock", dependencies=system_guarded)
def lock_shut():
    forge_lock.relock()
    return lock_reply()


@app.post("/api/lock/password", dependencies=system_guarded)
def lock_password(payload: dict):
    """Set or change the password; the current one is needed once one is set."""
    try:
        forge_lock.set_password(
            str(payload.get("new") or ""), str(payload.get("current") or "")
        )
    except forge_lock.BadPassword as error:
        return _wrong(error)
    except ValueError as error:
        raise HTTPException(400, str(error))
    return lock_reply()


# A logo's first bytes, for each type taken; anything else is refused.
LOGO_MAGIC = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".webp": (b"RIFF",),
}
LOGO_MAX = 4 * 1024 * 1024
LOGO_NAME = re.compile(r"^[0-9a-f]{16}\.(png|jpg|webp|svg)$")


def logo_type(data: bytes) -> str:
    for ext, heads in LOGO_MAGIC.items():
        if data.startswith(heads) and (ext != ".webp" or data[8:12] == b"WEBP"):
            return ext
    head = data[:512].lstrip().lower()
    if head.startswith(b"<svg") or (
        head.startswith(b"<?xml") and b"<svg" in data[:4096].lower()
    ):
        return ".svg"
    return ""


@app.post("/api/business/logo", dependencies=system_guarded)
def upload_logo(payload: dict):
    """Keep an uploaded logo (a data: URL) in the logo folder under a name
    made from its contents and return that name; the page then saves it into
    a company profile. Refused while Business is locked, like any change."""
    forge_lock.check(look_locks())
    text = str(payload.get("data") or "")
    _, _, encoded = text.partition("base64,")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "That file could not be read.")
    if not data or len(data) > LOGO_MAX:
        raise HTTPException(400, "A logo can be up to 4 MB.")
    ext = logo_type(data)
    if not ext:
        raise HTTPException(400, "A logo has to be a PNG, JPEG, WebP or SVG picture.")
    name = hashlib.sha256(data).hexdigest()[:16] + ext
    folder = forge_theme.LOGO_DIR
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    if not target.is_file():
        tmp = folder / f".{name}.tmp"
        tmp.write_bytes(data)
        tmp.replace(target)
    return {"logo": name}


@app.get("/api/business/logo/{name}")
def logo_file(name: str):
    target = forge_theme.LOGO_DIR / name
    if not LOGO_NAME.match(name) or not target.is_file():
        raise HTTPException(404, "No logo by that name")
    # an SVG can carry script: opened on its own it must not run as this site
    headers = {
        "Cache-Control": "max-age=604800",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(target, headers=headers)


# --- resets and Pick for my machine -------------------------------------------
# Both change many settings at once, so both keep a backup first (resets.py)
# and are refused while the Business look is locked, even when nothing would
# change. A reset that forgets Wi-Fi networks or Bluetooth devices changes the
# laptop, so these routes are guarded like the System ones.


def autoclose_registry() -> dict:
    return forge_autoclose.load_registry()


def save_changed(changes: dict) -> dict:
    """save_settings() with only what really changes, so a reset that leaves
    start_at_login as it is never rewrites the autostart entry."""
    now = forge_theme.load()
    return save_settings({k: v for k, v in changes.items() if now.get(k) != v})


def _plan(payload: dict) -> dict:
    try:
        return resets.plan(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/reset/groups")
def reset_groups():
    return {
        "groups": [
            {k: g[k] for k in ("id", "label", "about", "card") if k in g}
            for g in resets.load_groups()
        ],
        "kept": resets.kept_on_page_reset(),
        "backups": resets.backups(),
    }


@app.post("/api/reset/preview")
def reset_preview(payload: dict):
    plan = _plan(payload)
    custom = forge_autoclose.changed(autoclose_registry()) if plan["autoclose"] else []
    return resets.preview(plan, forge_theme.load(), custom)


@app.post("/api/reset", dependencies=system_guarded)
def reset_run(payload: dict):
    """Run one reset: {"section": name} | {"group": id} | {"all": true}, with
    "system": {"panel/action": {option: value}} naming the System actions to
    run (a group's actions not named there are skipped)."""
    plan = _plan(payload)
    forge_lock.check(look_locks())
    given = payload.get("system")
    chosen: dict = given if isinstance(given, dict) else {}
    steps = [s for s in plan["system"] if f"{s['panel']}/{s['action']}" in chosen]
    if not plan["keys"] and not plan["autoclose"] and not steps:
        raise HTTPException(400, "Nothing was chosen to reset")
    registry = autoclose_registry() if plan["autoclose"] else None
    defaults = {k: forge_theme.SETTINGS[k]["default"] for k in plan["keys"]}
    now = forge_theme.load()
    differ = [k for k, v in defaults.items() if now.get(k) != v]
    rules_differ = registry is not None and bool(forge_autoclose.changed(registry))
    ident = None  # nothing differs: no copy to keep
    if differ or rules_differ:
        rules = (
            forge_autoclose.load_rules(registry)
            if rules_differ and registry is not None
            else None
        )
        ident = resets.backup(plan["label"], rules, differ)
    result = save_changed(defaults)
    if rules_differ and registry is not None:
        forge_autoclose.reset_all(registry)
    done, failed = [], []
    for step in steps:
        body = resets.system_body(step, chosen[f"{step['panel']}/{step['action']}"])
        try:
            system_settings.act(step["panel"], step["action"], body)
            done.append(step["label"])
        except (KeyError, ValueError, system_settings.runner.CommandFailed) as exc:
            failed.append(f"{step['label']}: {exc}")
    return dict(result, backup=ident, label=plan["label"], done=done, failed=failed)


@app.post("/api/reset/undo", dependencies=system_guarded)
def reset_undo(payload: dict):
    """Put back the settings (and auto-close rules) a backup kept. It keeps a
    backup of its own first, so an undo can be undone too."""
    forge_lock.check(look_locks())
    try:
        data = resets.load_backup(payload.get("backup"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    old_rules = data.get("auto_close")
    registry = autoclose_registry() if isinstance(old_rules, dict) else None
    rules = forge_autoclose.load_rules(registry) if registry is not None else None
    ident = resets.backup(
        f"Undo of {data.get('label') or 'a reset'}",
        rules,
        resets.restored_keys(data),
    )
    result = save_changed(resets.restored(data))
    if registry is not None and isinstance(old_rules, dict):
        forge_autoclose.restore_rules(registry, old_rules)
    return dict(result, backup=ident, label=data.get("label", ""))


@app.get("/api/machine", dependencies=[page_shown("machine")])
def machine():
    found = forge_machine.detect()
    profiles = forge_machine.load_profiles()
    return {
        "machine": found,
        "pick": forge_machine.pick(found, profiles),
        "choices": forge_machine.summary(profiles),
    }


def _machine_changes(payload: dict) -> dict:
    targets = payload.get("targets", list(forge_machine.TARGETS))
    if not isinstance(targets, list):
        raise HTTPException(400, "targets must be a list")
    try:
        return forge_machine.changes(
            payload.get("visual"), payload.get("power"), targets
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/machine/preview", dependencies=[page_shown("machine")])
def machine_preview(payload: dict):
    now = forge_theme.load()
    out = []
    for key, value in _machine_changes(payload).items():
        if now.get(key) != value:
            spec = forge_theme.SETTINGS[key]
            out.append(
                {
                    "key": key,
                    "label": spec.get("label") or key,
                    "now": resets.shown(now.get(key), key),
                    "to": resets.shown(value, key),
                }
            )
    return {"changes": out}


@app.post("/api/machine/apply", dependencies=[*system_guarded, page_shown("machine")])
def machine_apply(payload: dict):
    wanted = _machine_changes(payload)
    forge_lock.check(look_locks())
    now = forge_theme.load()
    changes = {k: v for k, v in wanted.items() if now.get(k) != v}
    if not changes:
        raise HTTPException(400, "Nothing to change: it is already set that way")
    ident = resets.backup("Pick for my machine", None, sorted(changes))
    return dict(save_changed(changes), backup=ident, label="Pick for my machine")


# --- system -----------------------------------------------------------------
# The System section (static/system.js): panels listed in
# system_settings/panels.json. Guarded like the Claude app guarded them when
# they lived there: they change the laptop.


@app.get("/api/system/panels", dependencies=[*system_guarded, page_shown("system")])
def system_panels():
    return system_settings.panels()


@app.get("/api/system/{panel}", dependencies=[*system_guarded, page_shown("system")])
def system_status(panel: str):
    try:
        return system_settings.status(panel)
    except KeyError:
        raise HTTPException(404, f"No system panel called {panel}")


@app.post(
    "/api/system/{panel}/{action}", dependencies=[*system_guarded, page_shown("system")]
)
def system_action(panel: str, action: str, payload: dict):
    forge_lock.check(look_locks())  # System is a part of Settings, locked too
    try:
        return system_settings.act(panel, action, payload)
    except KeyError:
        raise HTTPException(404, f"No action {action} on {panel}")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except system_settings.runner.CommandFailed as exc:
        raise HTTPException(502, str(exc))


# --- static -----------------------------------------------------------------

if SHARED_DIR.is_dir():
    app.mount("/shared", StaticFiles(directory=str(SHARED_DIR)), name="shared")

if wallpapers_app is not None:

    @app.get("/wallpapers", include_in_schema=False)
    def wallpapers_page():
        return RedirectResponse("/wallpapers/")

    app.mount("/wallpapers", wallpapers_app.app, name="wallpapers")


@app.get("/")
def index():
    target = STATIC_DIR / "index.html"
    if not target.is_file():
        return JSONResponse({"error": "static/index.html is missing"}, status_code=500)
    cut, words = cut_pages(), resets.cut_words()
    if not cut and not words:
        return FileResponse(target)
    html = strip_sections(target.read_text(encoding="utf-8"), cut)
    return HTMLResponse(strip_keywords(html, "resets", words))


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
