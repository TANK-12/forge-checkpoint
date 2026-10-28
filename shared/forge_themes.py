"""Themes and home layouts: the whole look of Forge, picked in one click.

A theme bundles everything that makes Forge look one way: the hub look
(hub/looks/<look>.css), the home layout, colours for the hub and every app,
the font, outlines and corners, the wallpaper (a still picture and a live
scene), the widget style, particles, an optional companion (a cat that walks
across the apps), and optional colour files for Hyprland and the terminal.
Picking one is one click in Settings or Alt+T in the hub; Undo puts back
what was there before.

Everything is found by scanning, so adding one is one new file:

    shared/themes/<id>.json      a theme shipped with Forge; an optional
                                 shared/themes/<id>.css beside it styles the
                                 hub and the apps (scoped under
                                 html[data-forge-theme="<id>"])
    ~/.local/share/forge/themes/<id>.json
                                 the user's own ("Save my look as a theme")
    shared/themes/walls/<file>   pictures the themes bring, named
                                 "forge:<file>" in the wallpaper setting
    shared/layouts/<id>.json     a home screen layout
    shared/live/<id>.js          a live wallpaper scene (shared/forge_live.js)
    shared/companions/<id>.js    a companion, such as the cat

A theme file (every field optional except label):

    {"label": "Cosy", "about": "one line", "tags": ["cosy", "dark"],
     "order": 40, "look": "classic", "layout": "forge", "mode": "dark",
     "colours": {"accent", "bg", "panel", "panel_2", "border", "text",
                 "muted"},           hex; the panels need all six
     "font": "serif",                a key of forge_theme.FONTS, or
     "font_stack": "\"Noto Serif\", Georgia, serif",
     "wallpaper": "forge:embers.jpg" (or a list: the first one there wins;
                  "" follows the desktop's picture),
     "live": "embers", "companion": "cat",
     "settings": {"radius": 20, ...},  any theme-owned setting (THEMED)
     "desktop": {"hyprland": {...}, "terminal": {...}}}

Standard library only. forge_theme imports this module for the lists; the
functions that save settings import forge_theme when they run.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()
THEMES_DIR = Path(os.environ.get("FORGE_THEMES", HERE / "themes"))
USER_THEMES_DIR = Path(
    os.environ.get("FORGE_USER_THEMES", HOME / ".local/share/forge/themes")
)
WALLS_DIR = THEMES_DIR / "walls"
LAYOUTS_DIR = Path(os.environ.get("FORGE_LAYOUTS", HERE / "layouts"))
LIVE_DIR = Path(os.environ.get("FORGE_LIVE", HERE / "live"))
COMPANIONS_DIR = Path(os.environ.get("FORGE_COMPANIONS", HERE / "companions"))
DESKTOP_OUT = Path(os.environ.get("FORGE_THEME_DESKTOP", HOME / ".config/forge/theme"))
PERF_TIERS_FILE = Path(os.environ.get("FORGE_PERF_TIERS", HERE / "perf" / "tiers.json"))

DEFAULT_THEME = "forge"
MAX_FILE = 256 * 1024
DEFAULT_LAYOUT = "forge"
WALL_PREFIX = "forge:"
WALL_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
SURFACE_KEYS = ("bg", "panel", "panel_2", "border", "text", "muted")

# The settings a layout decides: reset to their defaults, then set from the
# layout, whenever a layout (or a theme, which names one) is picked.
LAYOUT_KEYS = ("home_clock", "greeting", "widgets", "tile_width")

# The settings a theme owns. Picking a theme puts every one of them back to
# its default first, so nothing of the theme before lingers (snow from a
# winter theme in a business one), then applies the new theme's values.
# Personal choices stay out on purpose: sizes, keys, music, the visualiser,
# animations on or off, power and battery limits, hidden apps.
THEMED = (
    "theme",
    "layout",
    "look",
    "wallpaper",
    "live_wallpaper",
    "companion",
    "accent",
    "theme_source",
    "tint",
    "contrast",
    "font",
    "icon_style",
    "glass_style",
    "glass_strength",
    "glass",
    "dim",
    "wall_blur",
    "gaps",
    "radius",
    "border",
    "behind_apps",
    "shadows",
    "particles",
    "wall_3d",
    "wall_parallax",
    "wall_tint",
    "widget_look",
    "motion",
) + LAYOUT_KEYS

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# A CSS font-family list: names, quotes, commas and spaces only.
_FONT_STACK = re.compile(r"^[\w\s\",'-]{1,160}$")


def plain_id(text) -> bool:
    return isinstance(text, str) and bool(_ID.match(text))


def _text(value, limit: int) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, str) else ""


def _hex(value) -> str:
    return value.lower() if isinstance(value, str) and _HEX.match(value) else ""


def _dict(raw: dict, key: str) -> dict:
    value = raw.get(key)
    return value if isinstance(value, dict) else {}


def _list(raw: dict, key: str) -> list:
    value = raw.get(key)
    return value if isinstance(value, list) else []


def _read_json(path: Path) -> dict | None:
    try:
        if path.stat().st_size > MAX_FILE:  # a theme is a few hundred bytes
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _header(path: Path, tag: str) -> dict | None:
    """`/* <tag>: Label | about */` from a file's first line, or None."""
    try:
        with path.open(encoding="utf-8") as f:
            first = f.readline()
    except (OSError, UnicodeDecodeError):
        return None
    head = first.strip().removeprefix("/*").removesuffix("*/").strip()
    if not head.lower().startswith(tag + ":"):
        return None
    label, _, about = head[len(tag) + 1 :].partition("|")
    return {"label": label.strip() or path.stem, "about": about.strip()}


def _scripts(folder: Path, tag: str) -> dict[str, dict]:
    found = {}
    for path in sorted(folder.glob("*.js")) if folder.is_dir() else []:
        head = _header(path, tag) if plain_id(path.stem) else None
        if head:
            found[path.stem] = head
    return found


def list_live(directory: Path | None = None) -> dict[str, dict]:
    """Every live wallpaper scene, {id: {label, about}}."""
    return _scripts(directory or LIVE_DIR, "live")


def list_companions(directory: Path | None = None) -> dict[str, dict]:
    """Every companion, {id: {label, about}}."""
    return _scripts(directory or COMPANIONS_DIR, "companion")


# --- performance tiers ---------------------------------------
# shared/forge_perf.js decides the tier in the hub; these are the registry
# halves it reads: the tiers themselves (shared/perf/tiers.json) and the
# "lighter" fallback each theme and layout declares.

PERF_TIERS = ("full", "balanced", "light")
# what a tier or a fallback may lay over the theme: display settings only,
# nothing that is saved, nothing a locked look (Business) holds
LIGHTER_SETTINGS = {
    "particles_shown",
    "particles",
    "particle_amount",
    "particle_fps",
    "visualiser_shown",
    "shadows",
    "wall_3d",
    "wall_3d_beat",
    "ambient_drift",
    "lite_effects",
    "max_fps",
    "glass_style",
    "motion",
    "border",
    "dim",
    "radius",
}
PERF_CSS = ("no-blur", "calm")
LIVE_RULES = ("", "still", "off")
COMPANION_RULES = ("", "still", "off")


def _rule_value(value):
    """A setting rule: a plain value, {"min": n} or {"scale": f}; None if not."""
    if isinstance(value, bool) or (isinstance(value, str) and len(value) <= 40):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict) and len(value) == 1:
        (op, n), *_ = value.items()
        if op in ("min", "scale") and isinstance(n, (int, float)):
            if not isinstance(n, bool) and n >= 0:
                return {op: n}
    return None


def _rules(raw, allowed=LIGHTER_SETTINGS) -> dict:
    out = {}
    for k, v in (raw if isinstance(raw, dict) else {}).items():
        clean = _rule_value(v) if k in allowed else None
        if clean is not None:
            out[k] = clean
    return out


def _live_rule(value):
    """ "", "still", "off" or {fps, res} factors between 0 and 1."""
    if value in LIVE_RULES:
        return value
    if isinstance(value, dict):
        out = {
            k: float(v)
            for k, v in value.items()
            if k in ("fps", "res")
            and isinstance(v, (int, float))
            and not isinstance(v, bool)
            and 0 < v <= 1
        }
        return out or None
    return None


def _clean_tier_block(raw) -> dict:
    """One tier of a theme's or layout's "lighter": its settings, and the
    theme's own word for its live wallpaper and companion."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {"settings": _rules(raw.get("settings"))}
    live = _live_rule(raw.get("live"))
    if "live" in raw and live is not None:
        out["live"] = live
    if raw.get("companion") in COMPANION_RULES and "companion" in raw:
        out["companion"] = raw["companion"]
    return out


def clean_lighter(raw) -> dict:
    """A "lighter" block: {"balanced": {...}, "light": {...}}, cleaned."""
    raw = raw if isinstance(raw, dict) else {}
    return {t: _clean_tier_block(raw[t]) for t in PERF_TIERS[1:] if t in raw}


def list_tiers(path: Path | None = None) -> dict[str, dict]:
    """The performance tiers, cleaned, full first. A missing or broken file
    gives three tiers that change nothing (the hub then stays as set)."""
    raw = _read_json(path or PERF_TIERS_FILE) or {}
    out = {}
    for order, tid in enumerate(PERF_TIERS):
        block = raw.get(tid)
        block = block if isinstance(block, dict) else {}
        live = _live_rule(block.get("live", ""))
        comp = block.get("companion", "")
        out[tid] = {
            "id": tid,
            "label": _text(block.get("label"), 40) or tid.title(),
            "about": _text(block.get("about"), 400),
            "order": order,
            "settings": _rules(block.get("settings")) if tid != "full" else {},
            "css": [c for c in _list(block, "css") if c in PERF_CSS],
            "live": live if live is not None and tid != "full" else "",
            "companion": comp if comp in COMPANION_RULES and tid != "full" else "",
        }
    return out


def machine() -> dict:
    """Processor threads and memory, for the tier's start (the hub's
    WebKit has no navigator.deviceMemory)."""
    out: dict = {"cores": os.cpu_count() or 0, "memory_gb": 0}
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    out["memory_gb"] = round(int(line.split()[1]) / 1024 / 1024, 1)
                    break
    except (OSError, ValueError, IndexError):
        pass
    return out


# --- layouts --------------------------------------------------------------

# What a layout may ask of the home screen, each with its allowed values;
# the first value is what a layout gets when it does not say.
HOME_RULES = {
    "hero": ("big", "small", "none"),  # the clock and greeting block
    # one row + "N more" / every tile / one grid with no headings / none
    # until a search or a section chip asks
    "sections": ("rows", "all", "flat", "none"),
    "tiles": ("big", "compact", "list", "icons"),
    "recent": (True, False),  # Jump back in
    "chips": (True, False),  # the section chips under the search
    "align": ("left", "center"),
}


def _clean_layout(lid: str, raw: dict) -> dict:
    home_raw = _dict(raw, "home")
    home = {}
    for key, allowed in HOME_RULES.items():
        value = home_raw.get(key, allowed[0])
        home[key] = value if value in allowed else allowed[0]
    settings = _dict(raw, "settings")
    return {
        "id": lid,
        "label": _text(raw.get("label"), 40) or lid,
        "about": _text(raw.get("about"), 200),
        "order": raw.get("order") if isinstance(raw.get("order"), int) else 50,
        "home": home,
        "settings": {k: v for k, v in settings.items() if k in LAYOUT_KEYS},
        "lighter": _clean_layout_lighter(raw.get("lighter")),
    }


def _clean_layout_lighter(raw) -> dict:
    """A layout's "lighter": per tier, home rules and settings it changes."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for tier in PERF_TIERS[1:]:
        block = raw.get(tier)
        if not isinstance(block, dict):
            continue
        home_raw = _dict(block, "home")
        out[tier] = {
            "home": {
                k: v
                for k, v in home_raw.items()
                if k in HOME_RULES and v in HOME_RULES[k]
            },
            "settings": _rules(
                block.get("settings"), LIGHTER_SETTINGS | set(LAYOUT_KEYS)
            ),
        }
    return out


def list_layouts(directory: Path | None = None) -> dict[str, dict]:
    """Every home layout, cleaned, in their own order (then by label)."""
    found = []
    folder = directory or LAYOUTS_DIR
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        raw = _read_json(path) if plain_id(path.stem) else None
        if raw and isinstance(raw.get("label"), str):
            found.append(_clean_layout(path.stem, raw))
    found.sort(key=lambda x: (x["order"], x["label"].lower()))
    return {x["id"]: x for x in found}


def layout(lid: str, directory: Path | None = None) -> dict:
    """A layout by id; the default one (or a bare one) when it is not there."""
    layouts = list_layouts(directory)
    if lid in layouts:
        return layouts[lid]
    if DEFAULT_LAYOUT in layouts:
        return layouts[DEFAULT_LAYOUT]
    return _clean_layout(DEFAULT_LAYOUT, {"label": "Forge"})


# --- themes -----------------------------------------------------------------


def _clean_theme(tid: str, raw: dict, mine: bool) -> dict:
    colours_raw = _dict(raw, "colours")
    colours = {k: _hex(colours_raw.get(k)) for k in ("accent",) + SURFACE_KEYS}
    colours = {k: v for k, v in colours.items() if v}
    stack = raw.get("font_stack")
    walls = raw.get("wallpaper", "")
    walls = walls if isinstance(walls, list) else [walls]
    tags = _list(raw, "tags")
    settings = _dict(raw, "settings")
    desktop = _dict(raw, "desktop")
    css = raw.get("css", tid)
    return {
        "id": tid,
        "label": _text(raw.get("label"), 40) or tid,
        "about": _text(raw.get("about"), 200),
        "tags": [t for t in (_text(x, 20).lower() for x in tags) if t][:8],
        "order": raw.get("order") if isinstance(raw.get("order"), int) else 50,
        "mine": mine,
        "look": raw.get("look") if plain_id(raw.get("look")) else "classic",
        "layout": raw.get("layout") if plain_id(raw.get("layout")) else "",
        "mode": "light" if raw.get("mode") == "light" else "dark",
        "colours": colours,
        "font": raw.get("font") if plain_id(raw.get("font")) else "",
        "font_stack": (
            stack if isinstance(stack, str) and _FONT_STACK.match(stack) else ""
        ),
        "wallpaper": [w for w in walls if isinstance(w, str)][:6],
        # the look draws a solid background: its card shows no picture
        "solid": raw.get("solid") is True,
        "live": raw.get("live") if plain_id(raw.get("live")) else "",
        "companion": raw.get("companion") if plain_id(raw.get("companion")) else "",
        "settings": {
            k: v for k, v in settings.items() if k in THEMED and k not in _TOP_LEVEL
        },
        # the stylesheet: its own beside it, or a shipped theme's by id
        "css": css if plain_id(css) and (THEMES_DIR / f"{css}.css").is_file() else "",
        "desktop": _clean_desktop(desktop),
        # the plain variant at each performance tier
        "lighter": clean_lighter(raw.get("lighter")),
    }


def _clean_desktop(desktop: dict) -> dict:
    """The "desktop" block: Hyprland and terminal values as plain words and
    numbers, the terminal's palette as a list of words; anything else is
    dropped (desktop_files checks each colour and number again)."""
    out: dict = {}
    for name in ("hyprland", "terminal"):
        block = desktop.get(name)
        if not isinstance(block, dict):
            continue
        out[name] = {
            k: v
            for k, v in block.items()
            if isinstance(k, str)
            and k != "palette"
            and isinstance(v, (str, int, float))
            and not isinstance(v, bool)
        }
        palette = block.get("palette")
        if name == "terminal" and isinstance(palette, list):
            out[name]["palette"] = [c for c in palette if isinstance(c, str)][:16]
    return out


# Theme fields that set a setting of their own; a theme's "settings" may not
# set these behind their backs.
_TOP_LEVEL = {
    "theme",
    "layout",
    "look",
    "wallpaper",
    "live_wallpaper",
    "companion",
    "accent",
    "font",
}


def list_themes(
    directory: Path | None = None, user_directory: Path | None = None
) -> dict[str, dict]:
    """Every theme, cleaned: Forge's own, then the user's saved ones. A saved
    one with the id of a shipped one is skipped (the shipped one wins)."""
    found: dict[str, dict] = {}
    for folder, mine in (
        (directory or THEMES_DIR, False),
        (user_directory or USER_THEMES_DIR, True),
    ):
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            if path.stem in found or not plain_id(path.stem):
                continue
            raw = _read_json(path)
            if raw and isinstance(raw.get("label"), str):
                found[path.stem] = _clean_theme(path.stem, raw, mine)
    ordered = sorted(
        found.values(), key=lambda t: (t["mine"], t["order"], t["label"].lower())
    )
    return {t["id"]: t for t in ordered}


def get_theme(tid: str) -> dict | None:
    return list_themes().get(tid) if plain_id(tid) else None


def theme_look(theme: dict) -> str:
    """The look a theme puts on: its own, or Classic when that one is gone."""
    return theme["look"] if theme["look"] in _ft().list_looks() else "classic"


def active_theme(settings: dict) -> dict | None:
    """The theme in use: the one picked last, while its look is still the
    look in use. Picking another look by hand takes the theme's stylesheet,
    colours and font off until its look is picked again."""
    theme = get_theme(settings.get("theme", ""))
    return theme if theme and theme_look(theme) == settings.get("look") else None


def next_theme(settings: dict, step: int = 1) -> str:
    """The theme after the one in use, in the switcher's order, round and
    round (Alt+Shift+T). Raises KeyError when there are none."""
    ids = list(list_themes())
    if not ids:
        raise KeyError("")
    now = active_theme(settings)
    at = ids.index(now["id"]) if now else -1
    return ids[(at + step) % len(ids)]


def surfaces(theme: dict | None) -> dict | None:
    """The theme's panel colours when it gives all six, else None."""
    colours = (theme or {}).get("colours") or {}
    if all(colours.get(k) for k in SURFACE_KEYS):
        return {k: colours[k] for k in SURFACE_KEYS}
    return None


def list_walls(directory: Path | None = None) -> list[str]:
    folder = directory or WALLS_DIR
    if not folder.is_dir():
        return []
    return sorted(
        p.name
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in WALL_TYPES and not p.name.startswith(".")
    )


def wall_path(name: str, directory: Path | None = None) -> Path | None:
    """A shipped theme picture by its "forge:<file>" name, only when it is
    one of the files in the folder (matched, never joined)."""
    if not isinstance(name, str) or not name.startswith(WALL_PREFIX):
        return None
    file = name[len(WALL_PREFIX) :]
    if file in list_walls(directory):
        return (directory or WALLS_DIR) / file
    return None


def theme_wallpaper(theme: dict, exists) -> str:
    """The first of the theme's wallpapers that is really there ("" follows
    the desktop). `exists(name)` says whether a wallpaper name resolves."""
    for name in theme["wallpaper"]:
        if name == "" or exists(name):
            return name
    return ""


# --- picking -------------------------------------------------------------------


def _ft():
    import forge_theme

    return forge_theme


def theme_changes(theme: dict, settings_spec: dict) -> dict:
    """The settings a theme sets: every themed key at its default, then the
    theme's layout, then the theme's own values."""
    ft = _ft()
    changes = {k: settings_spec[k]["default"] for k in THEMED if k in settings_spec}
    lay = layout(theme["layout"] or DEFAULT_LAYOUT)
    changes["layout"] = lay["id"]
    changes.update(lay["settings"])
    changes.update(theme["settings"])
    changes["theme"] = theme["id"]
    changes["look"] = theme_look(theme)
    changes["wallpaper"] = theme_wallpaper(
        theme, lambda n: ft.wallpaper_path(n) is not None
    )
    changes["live_wallpaper"] = theme["live"] if theme["live"] in list_live() else ""
    changes["companion"] = (
        theme["companion"] if theme["companion"] in list_companions() else ""
    )
    changes["accent"] = theme["colours"].get("accent", "")
    if surfaces(theme):
        changes["theme_source"] = "theme"
    if theme["font_stack"]:
        changes["font"] = "theme"
    elif theme["font"] in ft.FONTS:
        changes["font"] = theme["font"]
    return changes


def _snapshot(settings: dict, keys) -> dict:
    return {k: settings[k] for k in keys if k in settings}


def pick(tid: str, path: Path | None = None) -> dict:
    """Switch to theme `tid` and return the saved settings. What was there
    before is kept in theme_undo for Undo. The very first pick also saves
    the look as it was as a theme of the user's own, so it is never lost.
    Raises KeyError for an unknown theme and forge_lock.Locked while a locked
    look (Business) is on and shut."""
    ft = _ft()
    theme = get_theme(tid)
    if theme is None:
        raise KeyError(tid)
    before = ft.load(path)
    changes = theme_changes(theme, ft.SETTINGS)
    # Still picked by hand is a comfort choice, like Animations off: a theme
    # does not undo it. Still that came with the last theme goes with it.
    last = get_theme(before.get("theme", ""))
    last_motion = theme_changes(last, ft.SETTINGS).get("motion") if last else None
    if before.get("motion") == "still" and last_motion != "still":
        changes.pop("motion", None)
    if all(ft._clean(k, v) == before.get(k) for k, v in changes.items()):
        _desktop(before)
        return before  # already on as it is: Undo keeps what it had
    changes["theme_undo"] = _snapshot(before, changes)
    if not active_theme(before):
        # his own look, not a theme: keep a copy unless one is kept already
        ft.forge_lock.check(ft.look_rules(before["look"])["locked"])
        raw = _look_now(OWN_LOOK, before)
        if not any(t["mine"] and _same_look(raw, t) for t in list_themes().values()):
            save_current(OWN_LOOK, before)
    saved = ft.save(changes, path)
    _desktop(saved)
    return saved


OWN_LOOK = "My look before themes"


def _desktop(saved: dict) -> None:
    """The desktop files are extra: a folder that cannot be written does not
    undo a pick that is already saved."""
    try:
        write_desktop(saved)
    except OSError:
        pass


def pick_layout(lid: str, path: Path | None = None) -> dict:
    """Switch the home layout only; Undo puts the old one back."""
    ft = _ft()
    lay = list_layouts().get(lid)
    if lay is None:
        raise KeyError(lid)
    before = ft.load(path)
    changes = {k: ft.SETTINGS[k]["default"] for k in LAYOUT_KEYS}
    changes.update(lay["settings"])
    changes["layout"] = lid
    changes["theme_undo"] = _snapshot(before, changes)
    return ft.save(changes, path)


def pick_forge_layout(lid: str, path: Path | None = None) -> dict:
    """Switch the Forge layout (forge_theme.FORGE_LAYOUTS: "new" or "classic",
    the hub's Show all apps button). Not a theme pick, so Undo is untouched;
    the button flips it back."""
    ft = _ft()
    if lid not in ft.FORGE_LAYOUTS:
        raise KeyError(lid)
    return ft.save({"forge_layout": lid}, path)


def undo(path: Path | None = None) -> dict:
    """Put back the settings from before the last theme or layout pick."""
    ft = _ft()
    before = ft.load(path)
    snap = before.get("theme_undo") or {}
    if not snap:
        return before
    saved = ft.save({**snap, "theme_undo": {}}, path)
    _desktop(saved)
    return saved


def _same_look(raw: dict, theme: dict) -> bool:
    """Whether a saved theme already keeps the look `raw` would keep."""
    mine = _clean_theme(theme["id"], raw, True)
    skip = ("label", "about", "tags", "order")
    return all(mine[k] == theme[k] for k in mine if k not in skip)


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32].strip("-")
    return slug or "my-look"


def _look_now(label: str, settings: dict) -> dict:
    """The theme file that would keep the look in `settings`."""
    ft = _ft()
    current = active_theme(settings)
    raw: dict = {
        "label": label,
        # the look kept by the first theme pick was not saved from Settings
        # (critic round H, Relay task 405)
        "about": (
            "Kept on %s, before the first theme"
            if label == OWN_LOOK
            else "Saved from Settings on %s"
        )
        % time.strftime("%Y-%m-%d"),
        "tags": ["mine"],
        "look": settings["look"],
        "layout": settings.get("layout") or DEFAULT_LAYOUT,
        "mode": current["mode"] if current else "dark",
        "wallpaper": settings["wallpaper"],
        "live": settings.get("live_wallpaper", ""),
        "companion": settings.get("companion", ""),
        "settings": {
            k: settings[k] for k in THEMED if k in settings and k not in _TOP_LEVEL
        },
    }
    colours = {"accent": settings["accent"]} if settings["accent"] else {}
    if current and settings.get("theme_source") == "theme":
        colours.update(current["colours"])
        if settings["accent"]:
            colours["accent"] = settings["accent"]
    if colours:
        raw["colours"] = colours
    if settings["font"] == "theme" and current:
        raw["font_stack"] = current["font_stack"]
    elif settings["font"] in ft.FONTS:
        raw["font"] = settings["font"]
    if current and current["css"]:
        raw["css"] = current["css"]
    return raw


def save_current(
    name: str, settings: dict | None = None, directory: Path | None = None
) -> str:
    """Write the look in use now as a theme of the user's own and return its
    id. Never overwrites: a taken id gets a number."""
    settings = settings or _ft().load()
    folder = directory or USER_THEMES_DIR
    label = _text(name, 40) or "My look"
    base = _slug(label)
    taken = set(list_themes(user_directory=folder))
    tid, n = base, 2
    while tid in taken or (folder / f"{tid}.json").exists():
        tid, n = f"{base}-{n}", n + 1
    raw = _look_now(label, settings)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{tid}.json"
    tmp = out.with_name(f".{tid}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    tmp.replace(out)
    return tid


# --- what the hub and the apps get ----------------------------------------------


def extras(settings: dict, wall_link=None) -> dict:
    """The theme's part of forge_theme.theme(): its id, mode and stylesheet,
    the layout's home rules, the live wallpaper and companion, and the lists
    the hub's quick switcher (Alt+T) shows. `wall_link(name)` turns a
    wallpaper name into a link the hub can show, or "" (for the previews)."""
    themes = list_themes()
    theme = active_theme(settings)
    ft = _ft()
    locked = ft.forge_lock.is_locked(ft.look_rules(settings.get("look", ""))["locked"])
    seen: dict[str, str] = {}

    def link(name: str) -> str:  # each picture looked up once, the desktop's too
        if name not in seen:
            seen[name] = wall_link(name) if wall_link else ""
        return seen[name]

    lay = layout(settings.get("layout", ""))
    own = settings.get("theme_source") == "theme" and surfaces(theme)
    return {
        "theme": theme["id"] if theme else "",
        "theme_label": theme["label"] if theme else "",
        "theme_css": theme["css"] if theme else "",
        # light panels only come with the theme's own colours
        "theme_mode": theme["mode"] if theme and own else "dark",
        "layout_id": lay["id"],
        "layout_home": lay["home"],
        "live_wallpaper": settings.get("live_wallpaper", ""),
        "companion": settings.get("companion", ""),
        # Undo is refused while a locked look (Business) is on and shut
        "theme_can_undo": bool(settings.get("theme_undo")) and not locked,
        # the performance tier's registry halves (shared/forge_perf.js)
        "perf_tiers": list_tiers(),
        "theme_lighter": theme["lighter"] if theme else {},
        "layout_lighter": lay.get("lighter", {}),
        "glass_lighter": {
            k: v["lighter"] for k, v in ft.list_glass().items() if v.get("lighter")
        },
        "motion_lighter": {
            k: v["lighter"] for k, v in ft.list_motion().items() if v.get("lighter")
        },
        "perf_machine": machine(),
        "themes": [preview(t, link) for t in themes.values()],
        "layouts": [
            {k: x[k] for k in ("id", "label", "about", "home")}
            for x in list_layouts().values()
        ],
    }


def preview(theme: dict, wall_link=None) -> dict:
    """What a picker card needs to draw a theme without loading it."""
    colours = dict(_NEUTRAL)
    colours.update(theme["colours"])
    wall = ""
    if wall_link:
        # "" is the desktop's picture, which `wall_link` may know
        for name in theme["wallpaper"] or [""]:
            if name == "" and theme["solid"]:
                break
            wall = wall_link(name)
            if wall or name == "":
                break
    return {
        "id": theme["id"],
        "label": theme["label"],
        "about": theme["about"],
        "tags": theme["tags"],
        "mine": theme["mine"],
        "mode": theme["mode"],
        "look": theme["look"],
        "layout": theme["layout"] or DEFAULT_LAYOUT,
        "live": theme["live"],
        "companion": theme["companion"],
        "colours": colours,
        "wall": wall,
        "radius": theme["settings"].get("radius"),
        "font_stack": theme["font_stack"],
    }


_NEUTRAL = {
    "accent": "#6ea8fe",
    "bg": "#0f1115",
    "panel": "#171a21",
    "panel_2": "#1e222b",
    "border": "#2a2f3a",
    "text": "#e7e9ee",
    "muted": "#8b93a3",
}


# --- the desktop (optional) -----------------------------------------------------


def _rgb(hex_colour: str) -> str:
    return hex_colour.lstrip("#").lower()


def desktop_colours(theme: dict | None, data: dict) -> dict:
    """Colours for Hyprland and the terminal: the theme's "desktop" block,
    filled in from the colours Forge is drawn with now (`data` is the
    theme() output: accent and surfaces)."""
    s = data.get("surfaces") or _NEUTRAL
    accent = data.get("accent") or _NEUTRAL["accent"]
    own = (theme or {}).get("desktop") or {}
    hypr = {
        "active_border": accent,
        "inactive_border": s.get("border", _NEUTRAL["border"]),
        "rounding": data.get("radius", 12),
        "gaps_in": max(2, int(data.get("gaps", 10)) // 2),
        "gaps_out": data.get("gaps", 10),
        "border_size": 2,
    }
    hypr.update({k: v for k, v in (own.get("hyprland") or {}).items() if k in hypr})
    term = {
        "background": s.get("bg", _NEUTRAL["bg"]),
        "foreground": s.get("text", _NEUTRAL["text"]),
        "cursor": accent,
        "selection": s.get("panel_2", _NEUTRAL["panel_2"]),
        "palette": [],
    }
    term.update({k: v for k, v in (own.get("terminal") or {}).items() if k in term})
    return {"hyprland": hypr, "terminal": term}


# --- readable colours ---------------------------------------
#
# Every page is drawn with one set of colour tokens taken from the theme's six
# surface colours. Apps used to keep their own dark "raised" panels, so a light
# theme's dark text landed on them (Mission in Meadow: 1.1:1). The hub now
# sends the whole set, derived here, and every text colour is held to a
# minimum contrast against every surface it is drawn on, so a theme (shipped
# or saved by the owner) cannot make text unreadable.

# One row per token: (CSS token, surfaces key, how see-through in an app).
# "bg", "panel" and "panel_2" take that glass rule from Settings > Glass, a
# number is a fixed alpha, None is solid. Adding a shared token is one row.
SURFACE_TOKENS = (
    ("--bg", "bg", "bg"),
    ("--panel", "panel", "panel"),
    ("--panel-2", "panel_2", "panel_2"),
    ("--surface", "surface", "panel"),
    ("--raise", "raise", "panel"),
    ("--raise-2", "raise_2", "panel_2"),
    ("--border", "border", None),
    ("--text", "text", None),
    ("--muted", "muted", None),
    ("--faint", "faint", None),
    ("--hair", "text", 0.09),
    ("--hair-2", "text", 0.14),
    ("--good", "good", None),
    ("--warn", "warn", None),
    ("--bad", "bad", None),
    ("--on-bad", "on_bad", None),
)

# Where text sits, and the contrast each text colour must keep there (WCAG:
# 4.5:1 is readable body text, 7:1 comfortable, 3:1 large or secondary text).
PANEL_KEYS = ("panel", "panel_2", "surface", "raise", "raise_2")
READABLE = {
    "text": {"panels": 7.0, "bg": 4.5},
    "muted": {"panels": 4.5, "bg": 3.0},
    "faint": {"panels": 3.0, "bg": 3.0},
    "good": {"panels": 3.0, "bg": 3.0},
    "warn": {"panels": 3.0, "bg": 3.0},
    "bad": {"panels": 3.0, "bg": 3.0},
}
# the accent is drawn as text too (links, tags, the active tab): held a little
# over 3:1 on the panels so its tinted pills (accent on 14% accent) still read
ACCENT_READABLE = {"panels": 3.5, "bg": 3.0}
# the semantic colours of shared/forge.css, before they are made readable
SEMANTIC = {"good": "#59d499", "warn": "#f2a154", "bad": "#f2637d"}


def _channels(colour: str) -> tuple[float, float, float]:
    return tuple(int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5))  # type: ignore[return-value]


def luminance(colour: str) -> float:
    """WCAG relative luminance of a #rrggbb colour."""

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in _channels(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two #rrggbb colours (1 to 21)."""
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def mix(a: str, b: str, t: float) -> str:
    """#rrggbb `t` of the way from a to b."""
    ca, cb = _channels(a), _channels(b)
    return "#" + "".join(
        f"{round((x + (y - x) * t) * 255):02x}" for x, y in zip(ca, cb)
    )


def readable(colour: str, needs) -> str:
    """`colour`, moved towards black or white just far enough that it keeps
    each (background, minimum contrast) in `needs`; unchanged when it does.
    When no step reaches every minimum, the step with the best worst margin."""
    needs = list(needs)

    def margin(c: str) -> float:
        return min(contrast(c, back) / need for back, need in needs)

    if margin(colour) >= 1:
        return colour
    best, best_margin = colour, margin(colour)
    for step in range(1, 21):
        for end in ("#000000", "#ffffff"):
            moved = mix(colour, end, step / 20)
            m = margin(moved)
            if m >= 1:
                return moved
            if m > best_margin:
                best, best_margin = moved, m
    return best


def on_colour(*fills: str) -> str:
    """The text colour that reads best on every one of `fills` (buttons in
    the accent and its darker partner)."""
    dark = "#0b1220"
    worst = {c: min(contrast(c, f) for f in fills) for c in (dark, "#ffffff")}
    return dark if worst[dark] >= worst["#ffffff"] else "#ffffff"


def finish_surfaces(s: dict) -> dict:
    """The six surface colours plus the ones derived from them (the raised
    panels apps draw cards and boxes with, faint text and the semantic
    colours), every text colour held readable on every surface."""
    out = {k: s[k] for k in SURFACE_KEYS}
    out["surface"] = mix(s["bg"], s["panel"], 0.5)
    out["raise"] = mix(s["panel"], s["panel_2"], 0.35)
    out["raise_2"] = mix(s["panel_2"], s["text"], 0.06)
    out["faint"] = mix(s["muted"], s["panel"], 0.25)
    out.update(SEMANTIC)
    for key, need in READABLE.items():
        wants = [(out[k], need["panels"]) for k in PANEL_KEYS]
        out[key] = readable(out[key], wants + [(out["bg"], need["bg"])])
    # text on a badge filled with the warning red
    out["on_bad"] = on_colour(out["bad"])
    return out


def readable_accent(accent: str, s: dict) -> str:
    """The accent moved just far enough to read as text on every surface of
    `s` (finish_surfaces' output); a theme's own accent is kept when it does."""
    need = ACCENT_READABLE
    return readable(
        accent,
        [(s[k], need["panels"]) for k in PANEL_KEYS] + [(s["bg"], need["bg"])],
    )


def _int(value, low: int, high: int, fallback: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return fallback


def desktop_files(colours: dict) -> dict[str, str]:
    """The include files' text: Hyprland, kitty and foot. Bad colours fall
    back to the defaults rather than reaching a config."""
    h, t = colours["hyprland"], colours["terminal"]
    pick = lambda v, d: _hex(v) or d  # noqa: E731
    active = pick(h["active_border"], _NEUTRAL["accent"])
    inactive = pick(h["inactive_border"], _NEUTRAL["border"])
    bg, fg = pick(t["background"], _NEUTRAL["bg"]), pick(
        t["foreground"], _NEUTRAL["text"]
    )
    cursor, sel = pick(t["cursor"], active), pick(t["selection"], _NEUTRAL["panel_2"])
    palette = [c for c in (_hex(x) for x in t.get("palette") or []) if c][:16]
    note = "# Written by Forge (Settings > Themes). Changes when the theme does.\n"
    hypr = (
        note
        + "general {\n"
        + f"    col.active_border = rgb({_rgb(active)})\n"
        + f"    col.inactive_border = rgb({_rgb(inactive)})\n"
        + f"    border_size = {_int(h['border_size'], 0, 8, 2)}\n"
        + f"    gaps_in = {_int(h['gaps_in'], 0, 40, 5)}\n"
        + f"    gaps_out = {_int(h['gaps_out'], 0, 60, 10)}\n"
        + "}\n"
        + "decoration {\n"
        + f"    rounding = {_int(h['rounding'], 0, 40, 12)}\n"
        + "}\n"
    )
    kitty = note + "".join(
        f"{k} {v}\n"
        for k, v in (
            ("background", bg),
            ("foreground", fg),
            ("cursor", cursor),
            ("selection_background", sel),
            ("active_border_color", active),
        )
    )
    kitty += "".join(f"color{i} {c}\n" for i, c in enumerate(palette))
    foot = note + "[colors]\n" + f"background={_rgb(bg)}\nforeground={_rgb(fg)}\n"
    foot += "".join(
        f"{'regular' if i < 8 else 'bright'}{i % 8}={_rgb(c)}\n"
        for i, c in enumerate(palette)
    )
    return {"hyprland.conf": hypr, "kitty.conf": kitty, "foot.ini": foot}


def write_desktop(settings: dict, out: Path | None = None) -> list[Path]:
    """Write the desktop include files when Settings asks for them
    (theme_desktop "files"). Only these files in ~/.config/forge/theme/ are
    ever written; the user's own configs include them if they want to."""
    if settings.get("theme_desktop") != "files":
        return []
    ft = _ft()
    data = ft.theme(settings)
    files = desktop_files(desktop_colours(active_theme(settings), data))
    folder = out or DESKTOP_OUT
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in files.items():
        path = folder / name
        tmp = path.with_name(f".{name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        written.append(path)
    return written
