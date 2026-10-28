"""How Forge looks: the wallpaper, the accent colour and the glass.

One module, shared by `forge.py` (which applies the theme at launch) and the
Settings app (which changes it). Standard library only; images are handled by
ImageMagick's `magick`, which is already on this machine for the desktop.

WHERE THINGS LIVE
    settings   ~/.config/forge/settings.json - the user's choices. Outside
               ~/Forge on purpose: user data never lives in the code folder.
    cache      ~/.cache/forge/ - wallpaper copies, blurred copies, thumbnails
               and palettes. Safe to delete; everything is regenerated.
    hub        hub/theme.js - the theme as a script global. The hub is loaded
               over file://, where fetch() of a sibling file is blocked, so the
               theme arrives exactly the way status.js does.

WHY THE WALLPAPER IS COPIED
    The wallpapers in ~/Pictures/Wallpapers are 4K-8K images of 5-28 MB.
    Painting one of those as a page background is a slow start on every
    launch. A 2560 px JPEG copy is about 200 KB and decodes instantly.

WHY THERE IS A BLURRED COPY
    Apps sit on frosted glass. Blurring live with `backdrop-filter` redraws on
    every frame and is heavy on this laptop's Iris Xe; blurring once with
    ImageMagick costs about 0.1 s and then nothing ever again.

WHERE THE COLOUR COMES FROM
    The wallpaper's own palette, the same idea as matugen on the desktop. It is
    computed here rather than by running matugen, because matugen applies its
    templates - running it would rewrite the desktop's theme as a side effect.
"""

from __future__ import annotations

import colorsys
import hashlib
import json
import os
import re
from urllib.parse import quote, unquote, urlsplit
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import forge_lock
import forge_themes

HOME = Path.home()
CONFIG = Path(os.environ.get("FORGE_CONFIG", HOME / ".config/forge/settings.json"))
CACHE = Path(os.environ.get("FORGE_CACHE", HOME / ".cache/forge"))
AUTOSTART = Path(
    os.environ.get("FORGE_AUTOSTART", HOME / ".config/autostart/forge.desktop")
)
FORGE_PY = Path(__file__).resolve().parents[1] / "forge.py"
WALLPAPER_DIR = Path(
    os.environ.get("FORGE_WALLPAPERS", HOME / "Pictures/Wallpapers")
).expanduser()
# The desktop shell records its current wallpaper here. Following it is the
# default, so Forge starts on the same picture as the desktop.
DESKTOP_WALLPAPER = Path(
    os.environ.get(
        "FORGE_DESKTOP_WALLPAPER", HOME / ".local/state/caelestia/wallpaper/path.txt"
    )
)
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
FALLBACK_ACCENT = "#6ea8fe"
# How the hub can look: one stylesheet per look in hub/looks/, found by
# scanning, so a new look is one new file. Its first line names it:
#     /* look: Material 3 | Tonal colours from the wallpaper, big rounded shapes */
LOOKS_DIR = Path(
    os.environ.get("FORGE_LOOKS", Path(__file__).resolve().parent.parent / "hub/looks")
)
LOOK_ORDER = ("classic",)  # listed first; the rest follow by name
# Company logos for a look that shows one (Business): uploaded in Settings.
LOGO_DIR = Path(
    os.environ.get("FORGE_LOGOS", HOME / ".local/share/forge/business/logos")
)
LOGO_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".svg"}


# The glass kinds (S26): one stylesheet per kind in shared/glass/, found the
# same way, first line "/* glass: Liquid | about */". "flat" has no file.
GLASS_DIR = Path(
    os.environ.get("FORGE_GLASS", Path(__file__).resolve().parent / "glass")
)
# How the hub moves (task 377): one stylesheet per motion style in
# shared/motion/, first line "/* motion: Label | about */", rules scoped under
# body.motion-<id>. Glide is the hub's own motion and needs no file.
MOTION_DIR = Path(
    os.environ.get("FORGE_MOTION", Path(__file__).resolve().parent / "motion")
)


def file_link(path: Path) -> str:
    """A link the hub and the apps can load a local file from. forge.py loads
    the hub over file://, so a file:// link; the portable launcher serves the
    hub over http and sets FORGE_FILE_BASE to its own file address instead
    (an http page may not load file:// links)."""
    base = os.environ.get("FORGE_FILE_BASE")
    if base:
        return base + quote(str(path), safe="")
    return path.as_uri()


_LIGHTER_LINE = re.compile(r"^/\*\s*lighter:(.*?)\*/\s*$", re.I)


def _lighter_line(line: str) -> dict:
    """`/* lighter: balanced=frosted, light=flat */` -> {"balanced": "frosted",
    "light": "flat"}: what a glass or motion style turns into at each
    performance tier (shared/forge_perf.js, Relay task 379)."""
    m = _LIGHTER_LINE.match(line.strip())
    if not m:
        return {}
    out = {}
    for part in re.split(r"[,\s]+", m.group(1).strip()):
        tier, _, kind = part.partition("=")
        if tier in ("balanced", "light") and re.fullmatch(r"[a-z0-9-]{1,40}", kind):
            out[tier] = kind
    return out


def _styles(folder: Path, tag: str) -> dict[str, dict]:
    """Each stylesheet in `folder` whose first line is `/* <tag>: Label | about */`;
    a second line `/* lighter: ... */` gives its "lighter" fallbacks."""
    found: dict[str, dict] = {}
    files = sorted(folder.glob("*.css")) if folder.is_dir() else []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").split("\n", 2)
        except OSError:
            continue
        head = lines[0].strip().removeprefix("/*").removesuffix("*/").strip()
        if not head.lower().startswith(tag + ":"):
            continue
        label, _, about = head[len(tag) + 1 :].partition("|")
        found[path.stem] = {"label": label.strip() or path.stem, "about": about.strip()}
        lighter = _lighter_line(lines[1]) if len(lines) > 1 else {}
        if lighter:
            found[path.stem]["lighter"] = lighter
    return found


def list_glass(directory: Path | None = None) -> dict[str, dict]:
    """Every glass kind's label and description, Flat (the look's own) first."""
    kinds: dict[str, dict] = {
        "flat": {"label": "Flat", "about": "The look's own panes, no blur."}
    }
    kinds.update(
        (k, v)
        for k, v in _styles(directory or GLASS_DIR, "glass").items()
        if k != "flat"
    )
    return kinds


def list_looks(directory: Path | None = None) -> dict[str, dict[str, str]]:
    """Every look's label and one-line description, Classic always present."""
    looks = _styles(directory or LOOKS_DIR, "look")
    looks.setdefault(
        "classic", {"label": "Classic", "about": "How Forge looked first."}
    )
    order = [k for k in LOOK_ORDER if k in looks] + sorted(
        k for k in looks if k not in LOOK_ORDER
    )
    return {k: looks[k] for k in order}


def list_motion(directory: Path | None = None) -> dict[str, dict]:
    """Every motion style's label and description, Glide (the hub's own) first."""
    kinds: dict[str, dict] = {
        "glide": {
            "label": "Glide",
            "about": "Forge's own: panes rise in softly, tiles lift on hover.",
            # the performance tier's fallback (the files' "lighter:" line)
            "lighter": {"light": "still"},
        }
    }
    kinds.update(
        (k, v)
        for k, v in _styles(directory or MOTION_DIR, "motion").items()
        if k != "glide"
    )
    return kinds


def look_rules(look: str, directory: Path | None = None) -> dict:
    """What a look asks of Forge beyond its stylesheet, from the optional
    sidecar beside it (hub/looks/<look>.json):
        "locked": true        settings need the password while it is chosen
                              (shared/forge_lock.py)
        "forces": {key: v}    settings it holds at a value while chosen; only
                              the theme the hub and apps see changes, the
                              saved settings keep his own choice for later
        "company_logo": true  the home screen shows the active company's logo
        "accent": "#rrggbb"   its accent when none is picked in Settings
                              (instead of one taken from the wallpaper)
    A look with no sidecar asks for nothing."""
    out: dict = {"locked": False, "forces": {}, "company_logo": False, "accent": ""}
    if not isinstance(look, str) or not look.replace("-", "").isalnum():
        return out
    try:
        raw = json.loads(
            ((directory or LOOKS_DIR) / f"{look}.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return out
    if not isinstance(raw, dict):
        return out
    out["locked"] = raw.get("locked") is True
    out["company_logo"] = raw.get("company_logo") is True
    accent = raw.get("accent")
    if isinstance(accent, str) and len(accent) == 7 and accent[0] == "#":
        out["accent"] = accent.lower()
    forces = raw.get("forces")
    if isinstance(forces, dict):
        # SETTINGS is defined below; this only runs once it exists.
        out["forces"] = {
            k: _clean(k, v)
            for k, v in forces.items()
            if k in SETTINGS and k != "look" and not SETTINGS[k].get("custom")
        }
    return out


def look_to_go_back(settings: dict) -> str:
    """The look "Back to my old look" picks: the one chosen before the
    locked look, while it is still there and does not lock itself, or else
    the default look."""
    before = settings.get("look_before_lock") or ""
    if before in list_looks() and not look_rules(before)["locked"]:
        return before
    return SETTINGS["look"]["default"]


def check_lock(path: Path | None = None) -> None:
    """Raise forge_lock.Locked when the stored look is locked and shut; for
    writers that change the background without going through save()."""
    forge_lock.check(look_rules(load(path)["look"])["locked"])


def active_company(settings: dict) -> dict:
    """The company profile picked in Settings > Business, with a file link
    to its logo when the file is still there; {} when none is picked."""
    pick = settings.get("business_company") or ""
    for company in settings.get("business_companies") or []:
        if company["id"] != pick:
            continue
        logo = LOGO_DIR / company["logo"] if company["logo"] else None
        return {
            "id": company["id"],
            "name": company["name"],
            "logo": file_link(logo) if logo and logo.is_file() else "",
        }
    return {}


def _choice(default: str, labels: dict[str, str], **extra) -> dict:
    return {
        "default": default,
        "kind": "choice",
        "choices": list(labels),
        "labels": labels,
        **extra,
    }


COLOURS, LAYOUT, BAR, HOME_SCREEN, FULL = (
    "Colours inside apps",
    "Glass and layout",
    "Top bar and dock",
    "Home screen",
    "Full screen",
)
SIZE = "Size"
KEYS = "Forge keys"
STARTUP = "Starting and closing"
ZEN = "Zen mode"
AMBIENT = "Background mode"
MUSIC = "Music and visualiser"
APPS = "Apps"
SPEED = "Speed and detail"
DESKTOP_PARTICLES = "On the desktop"
WIDGETS = "Widgets"

# The particle kinds, shared by the home screen and the desktop's own pick.
PARTICLE_LABELS = {
    "off": "Off",
    "auto": "Match the wallpaper",
    "soft": "Soft drift",
    "lively": "Lively",
    "embers": "Forge embers",
    "constellation": "Constellation",
    "petals": "Falling petals",
    "rain": "Rain",
    "snow": "Snow",
    "rays": "Light rays",
    "fireflies": "Fireflies",
    "dust": "Floating dust",
    "leaves": "Autumn leaves",
    "petalstorm": "Petal storm",
    "bubbles": "Bubbles",
    "stars": "Twinkling stars",
    "emberstorm": "Ember storm",
    "glitter": "Glitter",
    "lanterns": "Paper lanterns",
    "wisps": "Spirit wisps",
    "galaxy": "Galaxy",
}

# The visualiser styles (shared/forge_visual.js draws them), shared by the
# home screen, background mode, the desktop and the visualiser widget.
VISUALISER_LABELS = {
    "bars": "Bars",
    "ring": "Ring",
    "wave": "Wave",
    "mirror": "Mirror",
    "aurora": "Aurora",
    "orbit": "Orbit",
    "terrain": "Terrain",
    "spectrum": "Spectrum",
    "nebula": "Nebula",
}

# Forge's own keys: action -> keys, written the way people say them. forge.py
# catches these on the window, before the page, so they work inside every app;
# the hub_keys setting overrides any of them. Plain "f" is gone on purpose: it
# went full screen whenever it was pressed outside a text box.
HUB_KEYS = {
    "fullscreen": "Alt+F, F11",
    "prev-app": "Alt+Left",
    "next-app": "Alt+Right",
    **{f"app-{n}": f"Alt+{n}" for n in range(1, 10)},
    "overview": "Alt+Space",
    # the owner (2026-09-29): "alt h goes to desktop and alt s goes to settings"
    "home": "Alt+H",
    "settings": "Alt+S",
    "zen": "Alt+Z",
    "ambient": "Alt+B",
    "pulse": "Alt+V",
    # S25 (the owner, 2026-09-28): "a keybind to turn off animations and
    # particles in that order and then back, Alt+P to turn off particles and
    # Alt+M to turn off the visualiser"; in Alt+V, Alt+M opens the visuals popup
    "effects": "Alt+E",
    "particles-toggle": "Alt+P",
    "visualiser-toggle": "Alt+M",
    "visuals": "Alt+Shift+M",
    # the owner (2026-09-28): "what keybind is there to stop all animations,
    # make one": the Animations switch (Settings > Glass and layout)
    "animations": "Alt+A",
    # the owner (2026-10-07): "an Alt+W widget-only page and Alt+Q close apps"
    "widgets": "Alt+W",
    # Relay task 366: the theme switcher (shared/themes/, shared/layouts/)
    "themes": "Alt+T",
    "theme-next": "Alt+Shift+T",
    "close-app": "Alt+Q",
    # the help sheet for the app in front; caught by Forge's
    # window, so it works in Store apps too. An app that uses F1 itself says
    # "own_keys": ["F1"] in its manifest.
    "help": "F1",
    "quit": "Ctrl+Shift+Q",
    "restart": "Ctrl+Shift+R",
}
HUB_KEY_LABELS = {
    "fullscreen": "Full screen",
    "prev-app": "Previous open app",
    "next-app": "Next open app",
    **{f"app-{n}": f"Open app {n} on the bar" for n in range(1, 10)},
    "overview": "Show open apps",
    "home": "Home screen",
    "settings": "Settings",
    "zen": "Zen mode (leaving goes back to the app you were in)",
    "ambient": "Background mode (leaving goes back to the app you were in)",
    "pulse": "Background pulse (lights to the music)",
    "effects": "Visualiser off, then particles off, then both back",
    "particles-toggle": "Particles on or off",
    "visualiser-toggle": "Visualiser on or off (in Alt+V: visuals settings)",
    "visuals": "Visuals settings popup",
    "animations": "All animations off or on",
    "widgets": "Widgets page (press again to go back)",
    "themes": "Theme switcher (pick a theme or a home layout)",
    "theme-next": "Next theme, in one key",
    "close-app": "Close the open app",
    "help": "This help: what the app in front is for, and its keys",
    "quit": "Quit Forge",
    "restart": "Restart Forge",
}

# The size presets, smallest first. Text leads and layout follows slowly:
# the owner wants easier reading without everything growing huge. Saved
# customs (the size_presets setting) come after these.
SIZE_KEYS = ("ui_scale", "text_scale", "icon_scale")
SIZE_PRESETS = [
    {"name": "Small", "ui_scale": 0.9, "text_scale": 0.9, "icon_scale": 0.9},
    {"name": "Default", "ui_scale": 1.0, "text_scale": 1.0, "icon_scale": 1.0},
    {"name": "Comfortable", "ui_scale": 1.0, "text_scale": 1.15, "icon_scale": 1.1},
    {"name": "Large", "ui_scale": 1.1, "text_scale": 1.25, "icon_scale": 1.25},
    {"name": "Extra large", "ui_scale": 1.25, "text_scale": 1.4, "icon_scale": 1.4},
]

# The sharpest video the Browser's pages may pick, by its shorter side.
VIDEO_HEIGHTS = {
    "2160": "Any, up to 4K",
    "1440": "1440p",
    "1080": "1080p",
    "720": "720p",
    "480": "480p",
    "360": "360p",
}

# Settings with a battery twin (the owner, 2026-09-27: "more lod and frame rate
# options on battery and off battery"): plugged-in key -> (battery key, rule).
# "min": unplugged, the lower of the two applies, so the battery one can only
# lighten; "scale": unplugged, the plugged-in value is multiplied by the
# battery share. The theme carries this table as power_pairs, so the hub and
# the desktop particles (shared/forge_power.js) and forge.py (power_values
# below) apply the same rules without their own copy.
POWER_PAIRS: dict[str, tuple[str, str]] = {
    "max_fps": ("battery_fps", "min"),
    "particle_fps": ("battery_particle_fps", "min"),
    "desktop_particle_fps": ("battery_particle_fps", "min"),
    "particle_amount": ("battery_particles", "scale"),
    "desktop_particle_amount": ("battery_particles", "scale"),
    "video_fps": ("battery_video_fps", "min"),
    "video_height": ("battery_video_height", "min"),
    "smooth_scroll": ("battery_smooth_scroll", "min"),
}

# Every setting, its default, and how it is kept sane. Adding a setting is one
# entry here: the Settings app builds its form from what `describe()` returns
# (grouped by `group`, labelled by `label`), and `theme()` hands every value to
# the hub and the apps. `custom` marks the few with a hand-made control;
# `also` lists more groups whose card shows the same control (Speed and detail
# collects every frame rate and detail slider that way).
# `unit` tells the form how to print a number: percent (of 1), whole_percent
# (of 100), solid, px, ms, times.
# Forge's layouts (Settings > Apps > Layout, Relay task 386; not the
# home screen's tile layout, the "layout" setting of shared/forge_themes.py).
# Each names the settings it holds while chosen, like a look's "forces": only
# the theme the hub and apps see changes, the saved settings keep his choice.
# "places": false is the rule from before Phase 1 (task 383): an app joins a
# group only by its own manifest "group" line, never by a group file's
# "members" list, and no group opens as tabs (hub/index.html Layout).
FORGE_LAYOUTS: dict[str, dict] = {
    "new": {"label": "New (places with tabs)", "places": True, "forces": {}},
    # also the home screen's Show all apps button: every section opens too
    "classic": {
        "label": "Show all apps (Classic: every app its own tile)",
        "places": False,
        "forces": {
            "show_dev_apps": True,
            "app_text": "original",
            "app_mode": "remember",
        },
    },
}


SETTINGS: dict[str, dict] = {
    "wallpaper": {
        "label": "Wallpaper",
        "default": "",
        "kind": "text",
        "custom": True,
    },  # "" = desktop's
    # The theme and home layout picked in Settings > Themes (shared/forge_themes.py
    # scans shared/themes/ and shared/layouts/); "" = none picked yet.
    "theme": {"label": "Theme", "default": "", "kind": "id", "custom": True},
    "layout": {
        "label": "Home layout",
        "default": forge_themes.DEFAULT_LAYOUT,
        "kind": "id",
        "custom": True,
    },
    # What the last theme or layout pick replaced, for Undo.
    "theme_undo": {
        "label": "Undo for the last theme",
        "default": {},
        "kind": "snapshot",
        "custom": True,
    },
    # Also write colour files for Hyprland and the terminal (Themes card).
    "theme_desktop": _choice(
        "off",
        {
            "off": "Only Forge",
            "files": "Also write colour files for Hyprland and the terminal",
        },
        custom=True,
        label="Desktop colour files",
    ),
    "accent": {
        "label": "Accent colour",
        "default": "",
        "kind": "colour",
        "custom": True,
    },  # "" = wallpaper's
    "unify_accent": {
        "label": "Use this colour inside every app",
        "default": True,
        "kind": "bool",
        "custom": True,
    },
    # --- colours inside apps
    "theme_source": _choice(
        "wallpaper",
        {
            "wallpaper": "Follow the wallpaper",
            "neutral": "Plain dark grey",
            "theme": "The theme's own colours",
        },
        group=COLOURS,
        label="Panel colours",
        help="Tints every app's panels, borders and text with the wallpaper's colour.",
    ),
    "tint": {
        "default": 0.5,
        "kind": "number",
        "min": 0.0,
        "max": 1.0,
        "step": 0.05,
        "unit": "percent",
        "group": COLOURS,
        "label": "Wallpaper tint",
    },
    "contrast": _choice(
        "normal",
        {"normal": "Normal", "high": "High"},
        group=COLOURS,
        label="Text contrast",
    ),
    "font": _choice(
        "system",
        {
            "system": "Each app's own",
            "rubik": "Rubik",
            "inter": "Inter",
            "serif": "Serif",
            "mono": "Monospace",
            "theme": "The theme's font",
        },
        group=COLOURS,
        label="Font",
    ),
    "ui_scale": {
        "default": 1.0,
        "kind": "number",
        "min": 0.8,
        "max": 1.5,
        "step": 0.05,
        "unit": "times",
        "group": SIZE,
        "label": "App size",
        "help": "Everything in Forge, hub and apps, laid out bigger or smaller.",
        # Zooms the page that holds the slider: applied once, on release
        # (a slider applied mid-drag moved under the pointer and flip-flopped).
        "apply": "release",
    },
    "text_scale": {
        "default": 1.0,
        "kind": "number",
        "min": 0.8,
        "max": 1.5,
        "step": 0.05,
        "unit": "times",
        "group": SIZE,
        "label": "Text size",
        "help": "Only the letters, in the hub and every app; boxes stay as they are.",
        # While dragged only the Settings page itself shows the new size.
        "apply": "release",
        "preview": "text_size",
    },
    "icon_scale": {
        "default": 1.0,
        "kind": "number",
        "min": 0.8,
        "max": 1.6,
        "step": 0.05,
        "unit": "times",
        "group": SIZE,
        "label": "Icon size",
        "help": "App icons on the home screen, the bar and the dock.",
        "apply": "release",
    },
    # Overrides for Forge's own keys, {action: "Alt+X, F11"}; "" = default.
    "hub_keys": {
        "label": "Forge keys",
        "default": {},
        "kind": "keys",
        "custom": True,
        "group": KEYS,
        "defaults": HUB_KEYS,
        "labels": HUB_KEY_LABELS,
    },
    # Saved custom size presets, [{name, ui_scale, text_scale, icon_scale}].
    # Drawn by the Settings app as a presets slider in the Size card.
    "size_presets": {
        "label": "Size preset",
        "default": [],
        "kind": "presets",
        "custom": True,
        "group": SIZE,
        "sets": list(SIZE_KEYS),
    },
    # --- glass and layout
    "look": _choice(
        "classic",
        {k: v["label"] for k, v in list_looks().items()},
        group=LAYOUT,
        label="Look",
        help="The style of the whole hub: "
        + "; ".join(f"{v['label']}: {v['about']}" for v in list_looks().values())
        + ". Classic follows the corner, gap and border settings below; the other looks bring their own.",
    ),
    "icon_style": _choice(
        "new",
        {"new": "New", "classic": "Classic"},
        group=LAYOUT,
        label="Icons",
        help="How the app icons look on the home screen, the bar, the dock and the overview: "
        "New: drawn icons in one style, tinted with each app's colour; "
        "Classic: the emoji Forge had before them. Switches at once.",
    ),
    "glass_style": _choice(
        "flat",
        {k: v["label"] for k, v in list_glass().items()},
        group=LAYOUT,
        label="Glass",
        help="How the bar, dock, popups, app tiles, widgets and the frame round an open app are made: "
        + "; ".join(f"{v['label']}: {v['about']}" for v in list_glass().values())
        + " Frosted and Liquid blur what is behind them live, which costs a little battery; Speed and detail's lite mode turns the blur off.",
    ),
    "glass_strength": {
        "default": 0.6,
        "kind": "number",
        "min": 0.0,
        "max": 1.0,
        "step": 0.05,
        "unit": "percent",
        "group": LAYOUT,
        "label": "Glass strength",
        "help": "How much Frosted or Liquid glass blurs, how clear the panes are and how bright their edges catch the light.",
    },
    "glass": {
        "default": 0.62,
        "kind": "number",
        "min": 0.2,
        "max": 1.0,
        "step": 0.02,
        "unit": "solid",
        "group": LAYOUT,
        "label": "App background",
    },
    "dim": {
        "default": 0.18,
        "kind": "number",
        "min": 0.0,
        "max": 0.7,
        "step": 0.02,
        "unit": "percent",
        "group": LAYOUT,
        "label": "Darken the wallpaper",
    },
    "wall_blur": {
        "default": 0,
        "kind": "int",
        "min": 0,
        "max": 40,
        "unit": "px",
        "group": LAYOUT,
        "label": "Blur the wallpaper",
        "help": "Softens the wallpaper on the home screen. The wallpaper behind open apps has its own setting.",
    },
    "gaps": {
        "default": 10,
        "kind": "int",
        "min": 0,
        "max": 32,
        "unit": "px",
        "group": LAYOUT,
        "label": "Gaps",
    },
    "radius": {
        "default": 14,
        "kind": "int",
        "min": 0,
        "max": 28,
        "unit": "px",
        "group": LAYOUT,
        "label": "Rounded corners",
    },
    "border": _choice(
        "gradient",
        {
            "gradient": "Gradient",
            "accent": "Accent colour",
            "subtle": "Subtle",
            "none": "None",
        },
        group=LAYOUT,
        label="Window border",
    ),
    "behind_apps": _choice(
        "blurred",
        {"blurred": "Blurred", "sharp": "Sharp", "plain": "Plain dark"},
        group=LAYOUT,
        label="Wallpaper behind apps",
    ),
    "shadows": {"default": True, "kind": "bool", "group": LAYOUT, "label": "Shadows"},
    "animations": {
        "default": True,
        "kind": "bool",
        "group": LAYOUT,
        "label": "Animations",
    },
    "anim_speed": {
        "default": 240,
        "kind": "int",
        "min": 0,
        "max": 600,
        "step": 20,
        "unit": "ms",
        "group": LAYOUT,
        "label": "Animation length",
    },
    "motion": _choice(
        "glide",
        {k: v["label"] for k, v in list_motion().items()},
        group=LAYOUT,
        label="Motion style",
        help="How the home screen moves when it comes in and when you point at a tile: "
        + "; ".join(f"{v['label']}: {v['about']}" for v in list_motion().values())
        + " With Animations off, or reduced motion asked for by the desktop, nothing moves.",
        registry="motion",
    ),
    # --- top bar and dock
    "clock_24h": {
        "default": True,
        "kind": "bool",
        "group": BAR,
        "label": "24-hour clock",
    },
    "clock_seconds": {
        "default": False,
        "kind": "bool",
        "group": BAR,
        "label": "Seconds in the bar",
    },
    "bar_date": {
        "default": False,
        "kind": "bool",
        "group": BAR,
        "label": "Date in the bar",
    },
    "show_stats": {
        "default": True,
        "kind": "bool",
        "group": BAR,
        "label": "CPU, memory and battery",
    },
    # One bar is enough by default: the top bar. The dock waits at the bottom
    # edge and shows on hover; the other two are for anyone who wants it back.
    "dock": _choice(
        "hidden",
        {
            "hidden": "Only when the mouse touches the bottom edge",
            "auto": "On the home screen, hidden in apps",
            "always": "Always show",
            "off": "Off: never show the dock",
        },
        group=BAR,
        label="Dock",
    ),
    "dock_size": {
        "default": 46,
        "kind": "int",
        "min": 36,
        "max": 64,
        "step": 2,
        "unit": "px",
        "group": BAR,
        "label": "Dock icon size",
    },
    # --- home screen
    # The smart search: what answers a
    # question the plain rules (maths, the time, finding apps) cannot.
    "ask_answers": _choice(
        "web",
        {
            "web": "The web (short answer, online)",
            "auto": "Local model first, the web when it is unsure",
            "local": "Local model (Jan, offline)",
            "claude": "Claude (online, uses Claude usage)",
            "google": "Just open Google",
        },
        group=HOME_SCREEN,
        label="Questions are answered by",
        help="The search box on the home screen, and the magnifying glass in the top bar, answer sums, the time and which app does what by plain rules, with no model and no web. Any other question, sent with Enter, goes to this. The web gives a short answer from DuckDuckGo with a link to Google's own answer. Local uses the Jan model picked for Forge's ask role, loaded when asked and released when idle; when Jan is off or has no answer the web answers instead. Local first asks the model and goes to the web when the model is not sure. Google's AI overview cannot be read from here, so Just open Google opens that search in a browser.",
    ),
    "home_clock": {
        "default": True,
        "kind": "bool",
        "group": HOME_SCREEN,
        "label": "Big clock",
    },
    "greeting": {
        "default": True,
        "kind": "bool",
        "group": HOME_SCREEN,
        "label": "Greeting",
    },
    "tile_width": {
        "default": 236,
        "kind": "int",
        "min": 180,
        "max": 360,
        "step": 4,
        "unit": "px",
        "group": HOME_SCREEN,
        "label": "Tile width",
    },
    "open_on": _choice(
        "home",
        {"home": "the home screen", "last": "the last app I used"},
        group=HOME_SCREEN,
        label="Open Forge on",
    ),
    "start_apps": _choice(
        "demand",
        {
            "demand": "the first time I open each one",
            "launch": "all together when Forge opens",
        },
        group=HOME_SCREEN,
        label="Start apps",
        help="On demand makes Forge open lighter; an app's first open waits under a second.",
    ),
    # Off by default since 2026-10-28: the owner found some
    # thirty apps running that he had not opened. Start ahead and the hover
    # start below had started them; now only opening an app starts it.
    "prestart_apps": {
        "default": 0,
        "kind": "int",
        "min": 0,
        "max": 10,
        "group": HOME_SCREEN,
        "label": "Start ahead",
        "help": "When Forge opens, this many of the apps you used last start in the background, "
        "so they open at once. Left unused they sleep again like any app. 0 turns it off.",
    },
    "start_on_hover": {
        "default": False,
        "kind": "bool",
        "group": HOME_SCREEN,
        "label": "Start an app when the pointer rests on it",
        "help": "Starts an app's backend while the pointer or the keyboard rests on its tile, "
        "or as it is pressed, so it opens a little faster. Off: an app starts only when you "
        "open it.",
    },
    "app_sleep_minutes": {
        "default": 20,
        "kind": "int",
        "min": 0,
        "max": 240,
        "group": HOME_SCREEN,
        "label": "Stop unused apps after (minutes)",
        "help": "An app left unused this long stops its backend; opening it again starts it in "
        "about a second, with its page as you left it. Apps that must keep running (Relay, "
        "Power, Calendar and the like) are never stopped. 0 turns this off (an app's own rule "
        "in Settings > System still counts), and then nothing starts ahead either.",
    },
    "live_wallpaper": _choice(
        "",
        {"": "Off", **{k: v["label"] for k, v in forge_themes.list_live().items()}},
        group=HOME_SCREEN,
        label="Live wallpaper",
        help="A moving scene in place of the still picture on the home screen: "
        + "; ".join(
            f"{v['label']}: {v['about']}" for v in forge_themes.list_live().values()
        )
        + ". It rests while an app covers the home screen.",
        registry="live",
    ),
    "companion": _choice(
        "",
        {
            "": "None",
            **{k: v["label"] for k, v in forge_themes.list_companions().items()},
        },
        group=HOME_SCREEN,
        label="Companion",
        help="A little friend that wanders along the bottom of the window, over the apps too; it never gets in the way of a click.",
        registry="companions",
    ),
    "particles": _choice(
        "soft",
        PARTICLE_LABELS,
        group=HOME_SCREEN,
        label="Particles",
        help="Lights and weather over the wallpaper on the home screen. Match the wallpaper picks one from the picture's name, then its colours (petals for pink blossom, snow for pale winter, rain for dark blue, fireflies for green, dust or light rays for warm pictures). They follow the pointer a little, and a click throws sparks. Drawn on the home screen, and behind open apps unless that is turned off.",
    ),
    "particles_shown": {
        "default": True,
        "kind": "bool",
        "group": HOME_SCREEN,
        "label": "Show particles",
        "help": "Alt+P turns them off and on without losing the kind picked above. Alt+E turns the visualiser off, then the particles, then both back on.",
    },
    "particles_in_apps": {
        "default": True,
        "kind": "bool",
        "group": HOME_SCREEN,
        "label": "Particles behind open apps",
        "help": "Keep them drawing behind an open app, where the wallpaper shows around it and through it. Off stops them while an app is open, which saves a little power.",
    },
    "desktop_particles": {
        "default": False,
        "kind": "bool",
        "group": HOME_SCREEN,
        "label": "Particles on the desktop",
        "help": "The same particles on your normal desktop, behind every window; clicks go straight through. On GNOME this needs the Forge desktop particles extension and one log out and back in; on Hyprland also turn on On the desktop > On Hyprland too.",
    },
    # the desktop's own particles page (the owner, 2026-09-27: "the extension
    # for the particles on the desktop should also have settings")
    "desktop_particle_kind": _choice(
        "same",
        {
            "same": "Same as the home screen",
            **{k: v for k, v in PARTICLE_LABELS.items() if k != "off"},
        },
        group=DESKTOP_PARTICLES,
        label="Particles on the desktop",
        help="Which particles the normal desktop shows, when Home screen > Particles on the desktop is on.",
    ),
    "desktop_particle_amount": {
        "default": 1.0,
        "kind": "number",
        "min": 0.25,
        "max": 2.5,
        "step": 0.25,
        "unit": "times",
        "group": DESKTOP_PARTICLES,
        "also": [SPEED],
        "label": "Amount",
        "help": "How many there are on the desktop. Fewer use less power.",
    },
    "desktop_particle_fps": {
        "default": 30,
        "kind": "int",
        "min": 1,
        "max": 60,
        "step": 1,
        "unit": "fps",
        "group": DESKTOP_PARTICLES,
        "also": [SPEED],
        "label": "Frame rate",
        "help": "How many times a second they move. 30 looks smooth and uses about half the power of 60; the frame rate cap under Speed and detail still applies when it is lower.",
    },
    "desktop_particles_rest": {
        "default": True,
        "kind": "bool",
        "group": DESKTOP_PARTICLES,
        "label": "Only while the desktop shows",
        "help": "They stop a few seconds after windows cover the whole desktop, and start again as soon as any of it shows. Off keeps them moving all the time.",
    },
    "desktop_all_screens": {
        "default": True,
        "kind": "bool",
        "group": DESKTOP_PARTICLES,
        "label": "On every screen",
        "help": "With more than one screen plugged in, each one shows the particles, the visualiser and its own widgets behind its windows, so a screen Forge is not on is a scenery screen to pop apps onto (right-click an app > Pop out). Off keeps them to the main screen.",
    },
    "desktop_widgets": {
        "default": False,
        "kind": "bool",
        "group": DESKTOP_PARTICLES,
        "label": "Widgets on the desktop",
        "help": "Your widgets on the normal desktop, behind every window, with their own layout. The Widgets button in the corner of the desktop adds, moves and removes them. Runs without Forge open.",
    },
    "desktop_edit_button": {
        "default": True,
        "kind": "bool",
        "group": DESKTOP_PARTICLES,
        "label": "Widgets button in the corner",
        "help": "A small button at the bottom right of the desktop that starts editing the desktop's widgets. Off hides it; the extension's top bar menu can still start editing.",
    },
    "desktop_panel_icon": {
        "default": True,
        "kind": "bool",
        "group": DESKTOP_PARTICLES,
        "label": "Button in the top bar",
        "help": "The Forge extension's button beside the clock on GNOME: switches for the desktop's particles, widgets and visualiser, Edit desktop widgets, and these settings.",
    },
    # the owner, 2026-09-28: Super's overview made the desktop vanish
    "desktop_in_overview": {
        "default": True,
        "kind": "bool",
        "group": DESKTOP_PARTICLES,
        "label": "Keep them in the overview",
        "help": "When Super zooms out to show your desktops, the particles, widgets and visualiser zoom out with each desktop instead of vanishing. GNOME only.",
    },
    # the owner, 2026-09-28: on GNOME and Hyprland, off by default on Hyprland
    "desktop_on_hyprland": {
        "default": False,
        "kind": "bool",
        "group": DESKTOP_PARTICLES,
        "label": "On Hyprland too",
        "help": "Shows the desktop's particles, widgets and visualiser when you log in to Hyprland as well. Off by default; they start within a few seconds of turning this on.",
    },
    "desktop_widget_scale": {
        "default": 1.0,
        "kind": "number",
        "min": 0.75,
        "max": 1.5,
        "step": 0.05,
        "unit": "times",
        "group": DESKTOP_PARTICLES,
        "label": "Desktop widget size",
    },
    "desktop_visualiser": _choice(
        "off",
        {"off": "Off", **VISUALISER_LABELS},
        group=DESKTOP_PARTICLES,
        label="Visualiser on the desktop",
        help="Draws whatever the laptop is playing on the normal desktop, behind every window. Reads the sound with cava only while something draws.",
    ),
    "desktop_visualiser_size": {
        "default": 1.0,
        "kind": "number",
        "min": 0.5,
        "max": 2.0,
        "step": 0.1,
        "unit": "times",
        "group": DESKTOP_PARTICLES,
        "label": "Desktop visualiser size",
    },
    "desktop_visualiser_fps": {
        "default": 30,
        "kind": "int",
        "min": 10,
        "max": 60,
        "step": 5,
        "unit": "fps",
        "group": DESKTOP_PARTICLES,
        "also": [SPEED],
        "label": "Desktop visualiser frame rate",
    },
    "wall_parallax": {
        "default": 1.0,
        "kind": "number",
        "min": 0,
        "max": 5,
        "step": 0.5,
        "unit": "%",
        "group": HOME_SCREEN,
        "label": "Wallpaper follows the pointer",
        "help": "How far the picture shifts against the pointer, as a share of the screen. 0 keeps it still; it also stays still when animations are off.",
    },
    "wall_3d": {
        "default": False,
        "kind": "bool",
        "group": HOME_SCREEN,
        "label": "2.5D wallpaper",
        "help": "The character (or, in a landscape, the nearest part of it) is cut out of the picture once, in the background, and floats in front: it moves further than the sky as the pointer moves, the particles fly between them, and it pumps on the beat in Alt+V. Uses the models PanelForge already has; about 8 seconds of CPU per new wallpaper.",
    },
    "wall_3d_depth": {
        "default": 1.0,
        "kind": "number",
        "min": 0.0,
        "max": 3.0,
        "step": 0.1,
        "unit": "times",
        "group": HOME_SCREEN,
        "label": "2.5D depth",
        "help": "How much further the cut-out moves than the picture behind it.",
    },
    "wall_3d_beat": {
        "default": True,
        "kind": "bool",
        "group": HOME_SCREEN,
        "label": "2.5D moves to the beat (Alt+V)",
    },
    "wall_3d_mode": _choice(
        "depth",
        {"depth": "Real depth (3D)", "layers": "Two layers"},
        group=HOME_SCREEN,
        label="2.5D style",
        help="Real depth bends the whole picture by its depth map on the graphics chip, so every part moves by how near it is, like a 3D photo, with the cut-out and the particles in front. Two layers moves only the cut-out against the rest, which costs almost nothing.",
    ),
    "wall_3d_drift": {
        "default": True,
        "kind": "bool",
        "group": HOME_SCREEN,
        "label": "2.5D drifts on its own",
        "help": "The view sways slowly round the picture even when the pointer is still. Stops on battery and while the GPU is busy.",
    },
    "wall_tint": {
        "default": True,
        "kind": "bool",
        "group": HOME_SCREEN,
        "label": "Time-of-day tint",
        "help": "A light colour over the wallpaper that follows the clock: rose at dawn, clear by day, gold in the early evening, violet at dusk, blue at night.",
    },
    "wall_tint_strength": {
        "default": 1.0,
        "kind": "number",
        "min": 0,
        "max": 2.0,
        "step": 0.1,
        "unit": "times",
        "group": HOME_SCREEN,
        "label": "Tint strength",
        "help": "How strong the time-of-day tint is: 1 is the usual, 0 none, 2 twice as strong.",
    },
    "particle_amount": {
        "default": 1.0,
        "kind": "number",
        "min": 0.25,
        "max": 2.5,
        "step": 0.25,
        "unit": "times",
        "group": HOME_SCREEN,
        "also": [SPEED],
        "label": "Particle amount",
    },
    # more sliders (the owner, 2026-09-27: "basically everything have a slider
    # like fps and level of power used for particles"); defaults keep the look
    "particle_size": {
        "default": 1.0,
        "kind": "number",
        "min": 0.5,
        "max": 2.5,
        "step": 0.25,
        "unit": "times",
        "group": HOME_SCREEN,
        "label": "Particle size",
    },
    "particle_speed": {
        "default": 1.0,
        "kind": "number",
        "min": 0.25,
        "max": 3.0,
        "step": 0.25,
        "unit": "times",
        "group": HOME_SCREEN,
        "label": "Particle speed",
    },
    "particle_fps": {
        "default": 30,
        "kind": "int",
        "min": 5,
        "max": 60,
        "step": 5,
        "unit": "fps",
        "group": HOME_SCREEN,
        "also": [SPEED],
        "label": "Particle frame rate",
        "help": "How often the particles are drawn. Lower uses less power and moves them more slowly; 60 is the full rate. The frame rate cap under Speed and detail applies on top.",
    },
    "particle_fps_in_apps": {
        "default": 10,
        "kind": "int",
        "min": 5,
        "max": 60,
        "step": 5,
        "unit": "fps",
        "group": HOME_SCREEN,
        "also": [SPEED],
        "label": "Particle frame rate behind apps",
        "help": "How often the particles are drawn behind an open app, when Particles behind open apps is on. Each frame there redraws the whole window under the app, so a low rate keeps apps smooth. It never goes above Particle frame rate.",
    },
    # home widgets and Relax (B20, 2026-09-27; shared/forge_widgets.js). The
    # layout itself (pages, places) is edited on the home screen with Edit.
    "widgets": {
        "default": True,
        "kind": "bool",
        "group": WIDGETS,
        "label": "Widgets on the home screen",
        "help": "Cards above the app tiles (clock, weather, music, calendar, system, disk, network, Jan, alarms, notes, visualiser, relax) on pages you can swipe between. The Edit button on the home screen moves, resizes, adds and removes them, and each card's ⚙ changes what it shows and its colour.",
    },
    "widget_look": _choice(
        "material",
        {"material": "Material (tonal cards)", "glass": "Glass, like the tiles"},
        group=WIDGETS,
        label="Widget look",
    ),
    # the owner (2026-10-19): "i dont like how ... the widgets move when i hover
    # over them", "make it a button in settings". Off keeps them still.
    "widget_hover_lift": {
        "default": False,
        "kind": "bool",
        "group": WIDGETS,
        "label": "Widgets lift under the pointer",
        "help": "A widget rises a little with a deeper shadow while the pointer is over it, on the home screen and on the desktop. Off keeps every widget still.",
    },
    "widget_scale": {
        "default": 1.0,
        "kind": "number",
        "min": 0.75,
        "max": 1.5,
        "step": 0.05,
        "unit": "times",
        "group": WIDGETS,
        "label": "Widget size",
    },
    "weather_units": _choice(
        "c",
        {"c": "Celsius, km/h", "f": "Fahrenheit, mph"},
        group=WIDGETS,
        label="Weather units",
    ),
    "alarm_sound": _choice(
        "chime",
        {"chime": "Soft chime", "bell": "Bell", "beep": "Beeps"},
        group=WIDGETS,
        label="Alarm sound",
        help="What the Alarms widget plays when an alarm or a timer goes off (it also shows a note on screen).",
    ),
    "breath_seconds": {
        "default": 4,
        "kind": "int",
        "min": 2,
        "max": 8,
        "step": 1,
        "unit": "s",
        "group": WIDGETS,
        "label": "Breathing pace",
        "help": "Relax (the moon widget) breathes in, holds, breathes out and holds for this long each.",
    },
    "visualiser_shown": {
        "default": True,
        "kind": "bool",
        "group": MUSIC,
        "label": "Show the visualiser",
        "help": "Alt+M turns it off and on without losing the style picked below (in Alt+V it opens the visuals settings instead).",
    },
    "visualiser_gain": {
        "default": 1.0,
        "kind": "number",
        "min": 0.5,
        "max": 2.5,
        "step": 0.1,
        "unit": "times",
        "group": MUSIC,
        "label": "Visualiser sensitivity",
        "help": "How strongly it reacts to the sound: higher makes quiet music move it more. Terrain already reacts 20% more than the rest.",
    },
    "visualiser_opacity": {
        "default": 1.0,
        "kind": "number",
        "min": 0.2,
        "max": 1.0,
        "step": 0.05,
        "unit": "percent",
        "group": MUSIC,
        "label": "Visualiser opacity",
        "help": "Lower lets more of the wallpaper show through it.",
    },
    "visualiser_colours": _choice(
        "accent",
        {
            "accent": "The wallpaper's colours",
            "rainbow": "Rainbow, slowly turning",
            "neon": "Neon pink and cyan",
            "fire": "Fire",
            "ice": "Ice",
            "white": "White",
        },
        group=MUSIC,
        label="Visualiser colours",
    ),
    "visualiser_in_apps": {
        "default": False,
        "kind": "bool",
        "group": MUSIC,
        "label": "Visualiser behind open apps",
        "help": "Keep the visualiser drawing behind an open app, where the wallpaper shows around it and through it, like the particles can. Off hides it while an app is open, which saves power. Behind an app it draws about 30 frames a second. The frame rate cap under Speed and detail still applies.",
    },
    "visualiser": _choice(
        "off",
        {"off": "Off", **VISUALISER_LABELS},
        group=MUSIC,
        label="Music visualiser",
        help="Draws the music on the home screen: bars along the bottom, a ring around the clock, a glowing wave, mirrored bars, aurora bands across the top, orbiting lights that burst on the beat, or a glowing 3D landscape rolling towards you.",
    ),
    "visualiser_source": _choice(
        "system",
        {
            "system": "Anything playing on the laptop",
            "music": "Only Forge's background music",
        },
        group=MUSIC,
        label="Visualiser listens to",
        help="Anything playing: QBZ, a browser tab, a Forge app or the background music (read with cava, only while the visualiser is on screen). Only Forge's background music: needs Background music on.",
    ),
    "visualiser_size": {
        "default": 1.0,
        "kind": "number",
        "min": 0.5,
        "max": 2.0,
        "step": 0.1,
        "unit": "times",
        "group": MUSIC,
        "label": "Visualiser size",
    },
    "music": {
        "default": False,
        "kind": "bool",
        "group": MUSIC,
        "label": "Background music",
        "help": "Plays the music folder below on the home screen and in ordinary apps, and fades out inside games and players. The note button in the top bar pauses it.",
    },
    "music_folder": {
        "default": "~/Music",
        "kind": "text",
        "group": MUSIC,
        "label": "Music folder",
        "help": "Its music and videos play, and those in folders one level down (Media saves downloads to ~/Music/Forge). The note button's menu adds a YouTube link's audio here.",
    },
    "music_volume": {
        "default": 35,
        "kind": "int",
        "min": 0,
        "max": 200,
        "step": 5,
        "unit": "whole_percent",
        "group": MUSIC,
        "label": "Music volume",
        "help": "Past 100% the music is boosted, for quiet tracks. The music button's Now playing has the same slider.",
    },
    "music_level": {
        "default": True,
        "kind": "bool",
        "group": MUSIC,
        "label": "Even out loud and quiet tracks",
        "help": "Quiet songs are lifted and loud ones held back, so one volume suits the whole folder.",
    },
    "music_duck": {
        "default": True,
        "kind": "bool",
        "group": MUSIC,
        "label": "Step aside for other sound",
        "help": "The background music fades out while a video or song plays in another Forge app, and comes back after.",
    },
    "music_fade": {
        "default": 150,
        "kind": "int",
        "min": 0,
        "max": 2000,
        "step": 50,
        "unit": "ms",
        "group": MUSIC,
        "label": "Music fade",
        "help": "How long the background music takes to fade out when you pause it or it steps aside, and to fade back in. 0 stops it at once.",
    },
    # --- zen mode: what its screen shows (Alt+Z or the moon on the bar)
    # Background mode (Alt+B): zen without the clock or timer, only the
    # wallpaper, its particles and the visualiser (the owner, 2026-09-27).
    "ambient_particles": {
        "default": 1.5,
        "kind": "number",
        "min": 0.5,
        "max": 3.0,
        "step": 0.25,
        "unit": "times",
        "group": AMBIENT,
        "label": "Particle boost",
        "help": "How many more particles than on the home screen.",
    },
    "ambient_visualiser": _choice(
        "keep",
        {"keep": "Same as the home screen", "off": "Off", **VISUALISER_LABELS},
        group=AMBIENT,
        label="Visualiser",
        popup_label="Visualiser in background mode",
    ),
    "ambient_drift": {
        "default": True,
        "kind": "bool",
        "group": AMBIENT,
        "label": "Slow wallpaper drift",
        "help": "The picture pans and zooms very slowly, like a film still.",
    },
    "ambient_drift_seconds": {
        "default": 90,
        "kind": "int",
        "min": 20,
        "max": 300,
        "step": 10,
        "unit": "s",
        "group": AMBIENT,
        "label": "Drift length",
        "help": "How long one slow sweep of the wallpaper takes. Shorter is faster.",
    },
    "ambient_hint": {
        "default": True,
        "kind": "bool",
        "group": AMBIENT,
        "label": "Say how to leave",
        "help": "A line at the bottom for a few seconds: Esc or Alt+B to come back.",
    },
    # B40: the entrance, and the Alt+V pulse (Pulse in hub/index.html)
    "ambient_entrance": {
        "default": True,
        "kind": "bool",
        "group": AMBIENT,
        "label": "Entrance animation",
        "help": "A bloom of light over the picture as background mode starts.",
    },
    "pulse_strength": {
        "default": 1.0,
        "kind": "number",
        "min": 0.25,
        "max": 2.0,
        "step": 0.25,
        "unit": "times",
        "group": AMBIENT,
        "label": "Pulse strength (Alt+V)",
        "help": "How hard the wallpaper, the edge glow and the light swell on the beat in the Alt+V pulse.",
    },
    "pulse_glow": {
        "default": True,
        "kind": "bool",
        "group": AMBIENT,
        "label": "Edge glow (Alt+V)",
        "help": "The screen's edges glow in the accent colours on the beat.",
    },
    "pulse_sway": {
        "default": True,
        "kind": "bool",
        "group": AMBIENT,
        "label": "Sway (Alt+V)",
        "help": "The picture sways a little, more on the beat.",
    },
    # The Alt+V effects, one switch each (the owner, 2026-09-27: "way better")
    "pulse_punch": {
        "default": True,
        "kind": "bool",
        "group": AMBIENT,
        "label": "Beat punch (Alt+V)",
        "help": "The picture kicks in sharply on each bass hit and eases back.",
    },
    "pulse_flash": {
        "default": True,
        "kind": "bool",
        "group": AMBIENT,
        "label": "Colour flash (Alt+V)",
        "help": "A flash of the accent colours over the picture on a strong beat.",
    },
    "pulse_rings": {
        "default": True,
        "kind": "bool",
        "group": AMBIENT,
        "label": "Shockwave rings (Alt+V)",
        "help": "A ring of light spreads out from the middle on each beat.",
    },
    "pulse_beams": {
        "default": True,
        "kind": "bool",
        "group": AMBIENT,
        "label": "Stage lights (Alt+V)",
        "help": "Beams of light sweep up from the bottom of the screen, faster and brighter as the music gets louder.",
    },
    "pulse_burst": {
        "default": True,
        "kind": "bool",
        "group": AMBIENT,
        "label": "Particle bursts (Alt+V)",
        "help": "The particles jump forward on each beat, and big beats throw sparks.",
    },
    "pulse_chroma": {
        "default": True,
        "kind": "bool",
        "group": AMBIENT,
        "label": "Colour split (Alt+V)",
        "help": "On a big beat the picture splits into red and blue edges for a moment, like a music video.",
    },
    "pulse_shake": {
        "default": False,
        "kind": "bool",
        "group": AMBIENT,
        "label": "Screen shake (Alt+V)",
        "help": "The picture shakes a little on the hardest beats.",
    },
    "pulse_sensitivity": {
        "default": 1.0,
        "kind": "number",
        "min": 0.5,
        "max": 2.0,
        "step": 0.1,
        "unit": "times",
        "group": AMBIENT,
        "label": "Beat sensitivity (Alt+V)",
        "help": "Higher catches softer beats; lower waits for the big ones.",
    },
    "fx_hud": {
        "default": True,
        "kind": "bool",
        "group": AMBIENT,
        "label": "Show the Alt+V controls",
        "help": "A small line of what the keys do when the pulse starts, and what changed when you press one: arrows change the visualiser and the pulse strength, Shift and the arrows the particles, 1 to 8 flip the beat effects, Alt+M opens the visuals settings.",
    },
    "pulse_full_fps": {
        "default": True,
        "kind": "bool",
        "group": AMBIENT,
        "also": [SPEED],
        "label": "Full frame rate (Alt+V)",
        "help": "While the pulse runs it ignores the frame rate cap, so beats land on time. Off keeps the cap, which saves power.",
    },
    "zen_clock": {
        "default": True,
        "kind": "bool",
        "group": ZEN,
        "label": "Clock and date",
    },
    "zen_intention": {
        "default": True,
        "kind": "bool",
        "group": ZEN,
        "label": "One-line intention",
    },
    "zen_timer": {
        "default": True,
        "kind": "bool",
        "group": ZEN,
        "label": "Focus timer",
    },
    "zen_music": {
        "default": True,
        "kind": "bool",
        "group": ZEN,
        "label": "Music button",
        "help": "The music button shows only when background music is on.",
    },
    "zen_effects": {
        "default": True,
        "kind": "bool",
        "group": ZEN,
        "label": "Wallpaper effects and visualiser",
        "help": "Off leaves only the still wallpaper behind the zen screen.",
    },
    # --- starting and closing
    "start_at_login": {
        "default": True,
        "kind": "bool",
        "group": STARTUP,
        "label": "Start Forge when I log in",
        "help": "Forge starts hidden and waits, so opening it later is instant.",
    },
    "close_action": _choice(
        "background",
        {
            "background": "keeps Forge ready in the background",
            "quit": "quits Forge and every app",
        },
        group=STARTUP,
        label="Closing the window",
        help="In the background your apps and music keep going. Quit from the power button on the bar, or Ctrl+Shift+Q.",
    ),
    # --- speed
    "pause_when_hidden": {
        "default": True,
        "kind": "bool",
        "group": SPEED,
        "label": "Rest while Forge is hidden",
        "help": "Minimised or on another workspace, Forge stops its animations and visualiser a few seconds later; music keeps playing. On another monitor it keeps going.",
    },
    "max_fps": {
        "default": 60,
        "kind": "int",
        "min": 1,
        "max": 60,
        "group": SPEED,
        "label": "Frame rate cap",
        "help": "Particles, the visualiser, games and the Browser's web pages draw at most this many frames a second. Lower saves power; 60 means no cap. Also in the Power app.",
    },
    "battery_fps": {
        "default": 30,
        "kind": "int",
        "min": 1,
        "max": 60,
        "group": SPEED,
        "label": "Frame rate on battery",
        "help": "The frame rate cap while the laptop runs on battery; plugged in, the cap above applies. Particles keep moving, in fewer frames. 60 means the same as plugged in. Also in the Power app.",
    },
    "battery_particles": {
        "default": 0.5,
        "kind": "number",
        "min": 0,
        "max": 1,
        "step": 0.05,
        "unit": "percent",
        "group": SPEED,
        "label": "Particles on battery",
        "help": "The share of the particles kept while unplugged, on the home screen and the desktop. 100% keeps them all; 0% turns them off until the charger is back.",
    },
    "battery_particle_fps": {
        "default": 20,
        "kind": "int",
        "min": 20,
        "max": 60,
        "step": 1,
        "unit": "fps",
        "group": SPEED,
        "label": "Particle frame rate on battery",
        "help": "How often the particles move while unplugged, on the home screen and the desktop. Never under 20, so they still look like they are flying.",
    },
    "battery_visualiser": {
        "default": False,
        "kind": "bool",
        "group": SPEED,
        "label": "Visualiser on battery",
        "help": "Off turns the music visualiser off while unplugged, on the home screen and the desktop, and back on with the charger. Alt+V still shows it.",
    },
    "battery_saver": {
        "default": 20,
        "kind": "int",
        "min": 0,
        "max": 50,
        "step": 5,
        "unit": "%",
        "group": SPEED,
        "label": "Low battery saver",
        "help": "Unplugged and at or under this charge, Forge and the desktop ease all the way off: no visualiser, half the particles, 25 frames a second. 0 turns it off.",
    },
    "gpu_ease": {
        "default": True,
        "kind": "bool",
        "group": SPEED,
        "label": "Ease off when the GPU is busy",
        "help": "While a game, a local AI model, a render or anything else keeps the graphics chip busy, Forge and the desktop step down so both stay smooth: first the visualiser goes off, then half the particles, then everything drops to 25 frames a second (particles never under 20). It all comes back about 10 seconds after the load ends. Alt+V ignores it.",
    },
    "gpu_ease_note": {
        "default": True,
        "kind": "bool",
        "group": SPEED,
        "label": "Say when it eases off",
        "help": 'A short line at the top of the home screen, such as "Easing off while Blender uses the GPU: visualiser off".',
    },
    "away_minutes": {
        "default": 5,
        "kind": "int",
        "min": 0,
        "max": 30,
        "step": 1,
        "unit": "min",
        "group": SPEED,
        "label": "Rest when nobody is at the computer",
        "help": "After this long with no keyboard or mouse, Forge and the desktop draw at 15 frames a second with no visualiser and half the particles, and after four times as long the moving effects stop. Touching anything brings it all back: at once on the home screen, within a few seconds inside an app or on the desktop. Nothing changes while anything can be heard playing. 0 turns it off.",
    },
    "video_fps": {
        "default": 60,
        "kind": "int",
        "min": 30,
        "max": 60,
        "step": 30,
        "unit": "fps",
        "group": SPEED,
        "label": "Browser video frame rate",
        "help": "The most frames a second a video in the Browser app may play at, YouTube included. 30 picks the 30 fps version of a 60 fps video, about half the decoding work. Takes effect from the next video.",
    },
    "battery_video_fps": {
        "default": 30,
        "kind": "int",
        "min": 30,
        "max": 60,
        "step": 30,
        "unit": "fps",
        "group": SPEED,
        "label": "Browser video frame rate on battery",
    },
    "video_height": _choice(
        "2160",
        VIDEO_HEIGHTS,
        group=SPEED,
        label="Browser video quality",
        help="The sharpest video a page in the Browser app may pick, YouTube included. Lower uses less power and data; the player can still go lower on its own. Takes effect from the next video.",
    ),
    "battery_video_height": _choice(
        "1080",
        VIDEO_HEIGHTS,
        group=SPEED,
        label="Browser video quality on battery",
    ),
    "smooth_scroll": {
        "default": True,
        "kind": "bool",
        "group": SPEED,
        "label": "Smooth scrolling",
        "help": "Pages glide when scrolled, in every Forge app and the Browser. Off jumps straight there, which draws far fewer frames.",
    },
    "battery_smooth_scroll": {
        "default": True,
        "kind": "bool",
        "group": SPEED,
        "label": "Smooth scrolling on battery",
    },
    # The performance tier (shared/forge_perf.js, shared/perf/tiers.json,
    # Relay task 379): Auto picks by itself from the machine and its frame
    # rate; the hub shows which one is on and why under this setting.
    "performance": _choice(
        "auto",
        {
            "auto": "Auto",
            "full": "Full",
            "balanced": "Balanced",
            "light": "Light",
        },
        group=SPEED,
        label="Performance",
        help="How much of the theme's looks and animations Forge draws. Auto starts from what this computer can do (processor, memory, graphics, the desktop's power saver and reduced motion) and steps down by itself when frames drop for a few seconds, then back up when they recover. Balanced draws the live wallpaper at half rate, half the particles and no frosted blur; Light shows a plain version of the same theme: a still wallpaper, the companion sitting still, no particles, blur or shadows, and 30 frames a second.",
        now="perf",
    ),
    "pause_unfocused": {
        "default": True,
        "kind": "bool",
        "group": SPEED,
        "label": "Pause animations when Forge is not in front",
        "help": "The live wallpaper, the companion, particles and looping animations wait while another window has the focus, and go on when Forge has it again. Music, a video or background mode keep them going.",
    },
    "lite_effects": _choice(
        "full",
        {"full": "Full", "battery": "On battery", "always": "Always"},
        group=SPEED,
        label="Lighter effects",
        help="Looping animations play once and stop, and the frosted blur behind panels goes flat. Particles, the wallpaper and the visualiser stay. Full keeps every effect; On battery lightens only while unplugged.",
    ),
    # Classic layout: Forge as it was
    # before the Phase 1 places. The choices and what each holds are FORGE_LAYOUTS.
    "forge_layout": _choice(
        "new",
        {k: v["label"] for k, v in FORGE_LAYOUTS.items()},
        group=APPS,
        label="Forge layout",
        help="New folds related apps into places with tabs, opens apps in Simple and reads at 15 px. Show all apps is Forge from before that: every app its own tile, every home section open, developer apps shown, each app's own text size and the mode you left it in. The Show all apps button under the home screen's search box switches it too. Your own choices below are kept for when you switch back.",
    ),
    # Every app opens in Simple, with Advanced one click away in the app
    # (the owner, 2026-10-27). Apps hear it through shared/forge_chrome.js.
    "app_mode": _choice(
        "simple",
        {
            "simple": "Simple",
            "advanced": "Advanced",
            "remember": "The one I used last in that app",
        },
        group=APPS,
        label="Apps open in",
        help="Simple shows the everyday controls; Advanced shows every control. Each app keeps its Simple and Advanced switch, so the other mode is one click away.",
    ),
    # 15 px body text in every app (the owner, 2026-10-27): shared/forge_chrome.js
    # lifts each font size by 2 px with a 13 px floor; Text size scales on top.
    "app_text": _choice(
        "bigger",
        {"bigger": "Bigger (15 px body text)", "original": "As each app sets it"},
        group=APPS,
        label="Reading size in apps",
        help="Bigger lifts the small print in every app to at least 13 px and body text to 15 px, even where busy pages get longer. Text size in Glass and layout still scales it.",
    ),
    # Relay task 383 (the owner, 2026-10-27): developer-only apps (manifest
    # "dev": true: Arena, Eighty Six, the codec apps, Board, Crew Room) stay
    # off the home screen, the dock and search until this is on.
    "show_dev_apps": {
        "default": False,
        "kind": "bool",
        "group": APPS,
        "label": "Show developer apps",
        "help": "Apps whose manifest marks them as tools for building Forge, such as Arena and the codec apps. Off, they leave the home screen, the dock and search; their files and data stay where they are.",
    },
    # --- apps: tiles taken off the home screen (app or group:<id> keys).
    # Hidden ones stay in search and All apps; archived ones leave both and
    # their backends never start. Drawn by the Settings app's Apps card.
    "hidden_apps": {
        "label": "Hidden apps",
        "default": [],
        "kind": "names",
        "custom": True,
        "group": APPS,
    },
    "archived_apps": {
        "label": "Archived apps",
        "default": [],
        "kind": "names",
        "custom": True,
        "group": APPS,
    },
    # Folders made by dragging one app onto another on the home screen:
    # {id: {"label": ..., "members": [app, ...]}}. The hub edits it.
    "app_folders": {
        "label": "App folders",
        "default": {},
        "kind": "folders",
        "custom": True,
    },
    # The Business look's company profiles ([{id, name, logo}], the logo a
    # file name in LOGO_DIR) and which one shows; Settings > Business.
    "business_companies": {
        "label": "Business companies",
        "default": [],
        "kind": "companies",
        "custom": True,
    },
    "business_company": {
        "label": "Company shown",
        "default": "",
        "kind": "id",
        "custom": True,
    },
    # The look chosen before a locked look (Business) was picked, written by
    # save(); "Back to my old look" in Settings picks it again
    # (look_to_go_back).
    "look_before_lock": {
        "label": "Look to go back to",
        "default": "",
        "kind": "id",
        "custom": True,
    },
    "claude_resume": {
        "default": True,
        "kind": "bool",
        "group": APPS,
        "label": "Claude: carry on after a restart",
        "help": "A conversation cut off mid-task by Forge quitting or the laptop restarting carries on by itself the next time Forge starts, one every 20 seconds. Off, it waits for your next message. Stop still stops it for good.",
    },
    "claude_archive_hours": {
        "default": 2,
        "kind": "int",
        "min": 0,
        "max": 168,
        "group": APPS,
        "label": "Claude: archive quiet conversations after (hours)",
        "help": "In the Claude app, a conversation in no folder moves to Archived once it has been quiet this many hours. 0 never archives. Sending it a message, filing it in a folder or its restore button brings it back.",
    },
    # --- full screen
    "start_fullscreen": {
        "default": True,
        "kind": "bool",
        "group": FULL,
        "label": "Start full screen",
        "help": "Takes effect the next time Forge starts. F11 still switches it.",
    },
    "auto_fullscreen": _choice(
        "smart",
        {
            "smart": "Smart: games and players",
            "always": "Every app",
            "off": "Never",
        },
        group=FULL,
        label="Apps fill the screen",
        help="Smart fills the screen for the apps made for it, such as games and video players; the others keep the bar and dock.",
    ),
    "reveal_bar": {
        "default": True,
        "kind": "bool",
        "group": FULL,
        "label": "Top edge shows the bar",
        "help": "Touch the top of the screen to see the apps, their numbers and the clock.",
    },
    "reveal_delay": {
        "default": 120,
        "kind": "int",
        "min": 0,
        "max": 800,
        "step": 20,
        "unit": "ms",
        "group": FULL,
        "label": "Top edge delay",
    },
}

# Font stacks for the `font` setting. "" leaves each app's own font alone.
FONTS = {
    "system": "",
    "rubik": '"Rubik", "Inter", system-ui, sans-serif',
    "inter": '"Inter", system-ui, sans-serif',
    "serif": '"Noto Serif", Georgia, serif',
    "mono": '"JetBrains Mono", ui-monospace, monospace',
}

# The palette in shared/forge.css. "Plain dark grey" is exactly this.
NEUTRAL_SURFACES = {
    "bg": "#0f1115",
    "panel": "#171a21",
    "panel_2": "#1e222b",
    "border": "#2a2f3a",
    "text": "#e7e9ee",
    "muted": "#8b93a3",
}


# --- settings ---------------------------------------------------------------


def _clean(key: str, value):
    spec = SETTINGS[key]
    kind = spec["kind"]
    try:
        if kind == "bool":
            return bool(value)
        if kind in ("number", "int"):
            number = float(value)
            number = max(spec["min"], min(spec["max"], number))
            return int(round(number)) if kind == "int" else round(number, 3)
        if kind == "choice":
            # a registry's choices are looked up again: a new live wallpaper
            # or companion file counts without a restart
            choices = _REGISTRIES[spec["registry"]]() if "registry" in spec else ()
            if value in spec["choices"] or value in choices:
                return value
            return spec["default"]
        if kind == "presets":
            return _clean_presets(value)
        if kind == "names":
            return _clean_names(value)
        if kind == "folders":
            return _clean_folders(value)
        if kind == "companies":
            return _clean_companies(value)
        if kind == "id":
            text = str(value or "")
            return text if len(text) <= 40 and _plain_id(text) else ""
        if kind == "snapshot":
            # theme_undo: other settings' values, each cleaned as its own
            return {
                k: _clean(k, v)
                for k, v in (value if isinstance(value, dict) else {}).items()
                if k in SETTINGS and SETTINGS[k]["kind"] != "snapshot"
            }
        if kind == "keys":
            return {
                action: str(text).strip()[:40]
                for action, text in (value if isinstance(value, dict) else {}).items()
                if action in HUB_KEYS and str(text or "").strip()
            }
        if kind == "colour":
            text = str(value or "").strip()
            if text == "":
                return ""
            if len(text) == 7 and text[0] == "#":
                int(text[1:], 16)
                return text.lower()
            return spec["default"]
        return str(value or "")
    except (TypeError, ValueError):
        return spec["default"]


def _clean_names(value) -> list[str]:
    """App names: short, plain characters, no repeats, at most 300."""
    names: list[str] = []
    for item in value if isinstance(value, list) else []:
        text = item if isinstance(item, str) else ""
        if text and len(text) <= 64 and text not in names:
            if all(c.isalnum() or c in "_.:-" for c in text):
                names.append(text)
    return names[:300]


def _clean_folders(value) -> dict:
    """App folders: each needs a short id and two or more apps, and an app
    sits in one folder only (the first that names it)."""
    out: dict = {}
    taken: set = set()
    for fid, item in (value if isinstance(value, dict) else {}).items():
        if not isinstance(fid, str) or not fid or len(fid) > 24:
            continue
        if not all(c.isalnum() or c in "_-" for c in fid) or not isinstance(item, dict):
            continue
        members = [m for m in _clean_names(item.get("members")) if m not in taken]
        if len(members) < 2:
            continue
        taken.update(members)
        label = str(item.get("label") or "").strip()[:40] or "Folder"
        out[fid] = {"label": label, "members": members}
        if len(out) >= 50:
            break
    return out


# Choices found by scanning a folder, looked up again on every save.
_REGISTRIES = {
    "live": forge_themes.list_live,
    "companions": forge_themes.list_companions,
    "motion": list_motion,
}


def _plain_id(text: str) -> bool:
    return all(c.isalnum() or c in "_-" for c in text)


def _clean_companies(value) -> list[dict]:
    """Company profiles: a short id, a name and a logo file name (or none);
    a logo name with a path in it is dropped, at most 50 profiles."""
    out: list[dict] = []
    seen: set = set()
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "")
        if not cid or len(cid) > 24 or not _plain_id(cid) or cid in seen:
            continue
        name = " ".join(str(item.get("name") or "").split())[:60] or "Company"
        logo = str(item.get("logo") or "")
        if (
            "/" in logo
            or "\\" in logo
            or logo.startswith(".")
            or Path(logo).suffix.lower() not in LOGO_TYPES
        ):
            logo = ""
        seen.add(cid)
        out.append({"id": cid, "name": name, "logo": logo})
        if len(out) >= 50:
            break
    return out


def _clean_presets(value) -> list[dict]:
    """Named sets of the three sizes; nameless or malformed ones are dropped."""
    out = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:30]
        if not name:
            continue
        preset: dict = {"name": name}
        for key in SIZE_KEYS:
            preset[key] = _clean(key, item.get(key, SETTINGS[key]["default"]))
        out.append(preset)
    return out[:12]


def size_presets(settings: dict) -> list[dict]:
    """The built-in size presets, then the user's saved ones."""
    mine = [dict(p, mine=True) for p in _clean_presets(settings.get("size_presets"))]
    return SIZE_PRESETS + mine


def hub_key_list(overrides: dict, skip: frozenset = frozenset()) -> list:
    """Forge's own keys as [[keys, what they do], ...] for the F1 help sheet,
    with Settings' overrides in place and Alt+1..9 as one row; `skip` leaves
    out actions a release has no key for (forge_portable)."""
    out = []
    for action, keys in HUB_KEYS.items():
        if action in skip or action.startswith("app-") and action != "app-1":
            continue
        chosen = (overrides or {}).get(action) or keys
        label = HUB_KEY_LABELS.get(action, action)
        if action == "app-1":
            chosen, label = "Alt+1 to Alt+9", "Open app 1 to 9 on the bar"
        out.append([chosen, label])
    return out


def load(path: Path | None = None) -> dict:
    """The user's settings, with defaults for anything missing or broken."""
    path = path or CONFIG
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        stored = {}
    out = {}
    for key, spec in SETTINGS.items():
        out[key] = _clean(key, stored[key]) if key in stored else spec["default"]
    return out


def hand_wallpaper(changes: dict, before: dict) -> dict:
    """What else changes when a wallpaper is picked by hand (Settings, the
    Wallpapers app, following the desktop): the picture is what Forge shows.

    Any live scene (a theme's or one picked by itself) is drawn over the
    still picture, so it goes off, or the picked picture never shows on the
    home screen; and the theme's
    accent gives way to the picture's colours (an accent picked by hand
    stays). A save that sets the theme or the live scene too (a theme pick)
    is left alone. The owner, 2026-10-28: the Wallpapers app and the themes
    fought over the background and the accent."""
    if "wallpaper" not in changes or "theme" in changes or "live_wallpaper" in changes:
        return {}
    if changes["wallpaper"] == before.get("wallpaper"):
        return {}
    out: dict = {}
    if before.get("live_wallpaper"):
        out["live_wallpaper"] = ""
    picked = forge_themes.active_theme(before)
    accent = before.get("accent")
    if (
        "accent" not in changes
        and picked
        and accent
        and accent == (picked.get("colours") or {}).get("accent")
    ):
        out["accent"] = ""
    return out


def save(changes: dict, path: Path | None = None) -> dict:
    """Merge `changes` into the stored settings and return them all, cleaned.
    Unknown keys in `changes` are ignored.

    Only the changed keys are rewritten: everything else stays in the file
    exactly as stored. Each app backend imported this module when it started,
    so an older copy must not reset or drop settings it does not know (that
    is how changing the wallpaper sometimes turned the particles off)."""
    path = path or CONFIG
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    cleaned = {k: _clean(k, v) for k, v in (changes or {}).items() if k in SETTINGS}
    # A locked look (Business) refuses every real change, leaving it included,
    # until the password opens the window; a save that changes nothing passes.
    before = load(path)
    cleaned.update(hand_wallpaper(cleaned, before))
    if any(before[k] != v for k, v in cleaned.items()):
        forge_lock.check(look_rules(before["look"])["locked"])
    # Picking a locked look from an open one remembers the open one, so
    # Settings can offer to go back to it in one step.
    if "look" in cleaned and "look_before_lock" not in cleaned:
        if (
            look_rules(str(cleaned["look"]))["locked"]
            and not look_rules(before["look"])["locked"]
        ):
            cleaned["look_before_lock"] = before["look"]
    stored.update(cleaned)
    path.parent.mkdir(parents=True, exist_ok=True)
    # one temp name per thread: a backend's thread pool may save at once
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    tmp.replace(path)
    return load(path)


# forge.py runs on the system python (it needs PyGObject), never an app's venv,
# which is what sys.executable is when the Settings app calls this.
AUTOSTART_ENTRY = """[Desktop Entry]
Type=Application
Name=Forge
Comment=Starts Forge hidden at login, so opening it is instant
Exec=/usr/bin/python3 {forge} --background
Path={folder}
Icon={icon}
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=3
"""


def set_autostart(on: bool, path: Path | None = None) -> None:
    """Start Forge when I log in: an XDG autostart entry (GNOME, and Hyprland
    through its session's autostart) running forge.py --background, or none."""
    path = Path(path or AUTOSTART)
    if not on:
        path.unlink(missing_ok=True)
        return
    text = AUTOSTART_ENTRY.format(
        forge=FORGE_PY,
        folder=FORGE_PY.parent,
        icon=HOME / ".local/share/icons/forge.png",
    )
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# The visuals popup (Alt+Shift+M anywhere, Alt+M inside the Alt+V pulse):
# these settings, in this order. The hub builds its controls from the rows
# theme() hands it, so adding one here is the whole change.
VISUALS_POPUP = [
    "visualiser_shown",
    "visualiser",
    "ambient_visualiser",
    "visualiser_gain",
    "visualiser_size",
    "visualiser_opacity",
    "visualiser_colours",
    "visualiser_source",
    "particles_shown",
    "particles",
    "particle_amount",
    "particle_size",
    "particle_speed",
    "pulse_strength",
    "pulse_sensitivity",
    "pulse_glow",
    "pulse_sway",
    "pulse_punch",
    "pulse_flash",
    "pulse_rings",
    "pulse_beams",
    "pulse_burst",
    "pulse_chroma",
    "pulse_shake",
    "wall_parallax",
    "wall_tint",
    "glass_style",
    "glass_strength",
    "wall_3d",
    "wall_3d_mode",
    "wall_3d_depth",
    "wall_3d_drift",
    "wall_3d_beat",
    "fx_hud",
]


def popup_rows(keys: list[str]) -> list[dict]:
    """The settings' descriptions for a popup outside the Settings app."""
    fields = (
        "kind",
        "default",
        "label",
        "min",
        "max",
        "step",
        "unit",
        "choices",
        "labels",
    )
    # a row may carry a clearer name for the popup, where its page's heading
    # is not there to say which visualiser it is
    return [
        {
            "key": k,
            **{f: SETTINGS[k][f] for f in fields if f in SETTINGS[k]},
            "label": SETTINGS[k].get("popup_label", SETTINGS[k]["label"]),
        }
        for k in keys
    ]


def describe() -> dict:
    """The settings table the Settings app shows, less the ones this system
    cannot use: the portable launcher lists those in FORGE_CUT_SETTINGS, and
    in FORGE_SETTING_WORDS (JSON, key to text) the help to show instead where
    the usual help names something the release does not have."""
    cut = set(filter(None, os.environ.get("FORGE_CUT_SETTINGS", "").split(",")))
    try:
        words = json.loads(os.environ.get("FORGE_SETTING_WORDS") or "{}")
    except ValueError:
        words = {}
    if not isinstance(words, dict):
        words = {}
    out = {}
    for key, spec in SETTINGS.items():
        if key in cut:
            continue
        out[key] = dict(spec)
        if isinstance(words.get(key), str):
            out[key]["help"] = words[key]
    return out


def power_values(settings: dict, on_battery: bool) -> dict:
    """What applies now for each setting in POWER_PAIRS: the plugged-in value,
    lightened by its battery twin while on battery."""
    out = {}
    for key, (twin, rule) in POWER_PAIRS.items():
        value = settings[key]
        if on_battery:
            other = settings[twin]
            if rule == "scale":
                value = round(value * other, 3)
            elif isinstance(value, str):
                value = min(value, other, key=int)
            else:
                value = min(value, other)
        out[key] = value
    return out


# --- wallpapers ---------------------------------------------------------------


def list_wallpapers(directory: Path | None = None) -> list[dict]:
    """Every picture in the folder and its sub-folders, named by its path
    relative to the folder. Hidden folders are skipped: the collection is a
    git clone, and nothing under .git is a wallpaper."""
    directory = directory or WALLPAPER_DIR
    if not directory.is_dir():
        return []
    rows = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            path = Path(root) / name
            if name.startswith(".") or path.suffix.lower() not in IMAGE_TYPES:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            rows.append({"name": path.relative_to(directory).as_posix(), "bytes": size})
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def wallpaper_path(name: str, directory: Path | None = None) -> Path | None:
    """A wallpaper by file name, only if it really is one in the folder.

    The name is matched against the folder listing rather than joined onto the
    folder path, so `../../.ssh/id_rsa` is simply not a wallpaper.
    """
    if isinstance(name, str) and name.startswith(forge_themes.WALL_PREFIX):
        return forge_themes.wall_path(name)  # a picture a theme brings
    directory = directory or WALLPAPER_DIR
    for row in list_wallpapers(directory):
        if row["name"] == name:
            return directory / name
    return None


def _gsettings(key: str) -> str:
    schema = (
        "org.gnome.desktop.interface"
        if key == "color-scheme"
        else "org.gnome.desktop.background"
    )
    try:
        out = subprocess.run(
            ["gsettings", "get", schema, key], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def desktop_wallpaper(state: Path | None = None, gsettings=_gsettings) -> Path | None:
    """The desktop's wallpaper: GNOME's own setting (its dark-mode picture when
    the desktop is dark) on GNOME, else the file caelestia keeps on Hyprland;
    on Windows (a Forge release) the picture Windows' own setting names."""
    if sys.platform == "win32":
        return _windows_wallpaper()
    if "gnome" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower():
        dark = "dark" in gsettings("color-scheme")
        uri = gsettings("picture-uri-dark" if dark else "picture-uri").strip("'\"")
        if uri.startswith("file://"):
            path = Path(unquote(urlsplit(uri).path))
            if path.is_file():
                return path
    state = state or DESKTOP_WALLPAPER
    try:
        path = Path(state.read_text(encoding="utf-8").strip()).expanduser()
    except Exception:
        return None
    return path if path.is_file() else None


def _windows_wallpaper() -> Path | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
            value = winreg.QueryValueEx(key, "WallPaper")[0]
    except OSError:
        return None
    path = Path(str(value)) if value else None
    return path if path and path.is_file() else None


def desktop_follow_supported(state: Path | None = None) -> bool:
    """Whether desktop_wallpaper can read this desktop at all: GNOME, the
    caelestia file on Hyprland, or Windows. Elsewhere (macOS, other Linux
    desktops) Settings does not offer "Follow my desktop wallpaper"."""
    return (
        sys.platform == "win32"
        or "gnome" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        or (state or DESKTOP_WALLPAPER).is_file()
    )


def chosen_wallpaper(settings: dict, directory: Path | None = None) -> Path | None:
    """The picture to use: the chosen one, else the desktop's, else the first."""
    if settings.get("wallpaper"):
        found = wallpaper_path(settings["wallpaper"], directory)
        if found:
            return found
    desktop = desktop_wallpaper()
    if desktop:
        return desktop
    rows = list_wallpapers(directory)
    return (directory or WALLPAPER_DIR) / rows[0]["name"] if rows else None


# --- rendering ----------------------------------------------------------------

# Thumbnails are generated on demand as the Settings grid scrolls. Two at a
# time keeps a first visit from pinning every CPU core.
_magick_slots = threading.BoundedSemaphore(2)


def _magick() -> str | None:
    return shutil.which("magick")


def _key(source: Path) -> str:
    stat = source.stat()
    raw = f"{source.resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _run(args: list[str]) -> bool:
    try:
        subprocess.run(args, check=True, capture_output=True, timeout=60)
        return True
    except Exception:
        return False


def thumbnail(
    source: Path, cache: Path | None = None, background: bool = False
) -> Path | None:
    """A 480x270 preview for the Settings grid, or None without ImageMagick.

    `background` is the warm-up: run at the lowest CPU priority and outside
    the two slots a person scrolling the grid gets.
    """
    cache = cache or CACHE
    out = cache / "thumbs" / f"{_key(source)}.jpg"
    if out.is_file():
        return out
    tool = _magick()
    if not tool:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    # Unique per call: the warm-up and a click can make the same one at once.
    tmp = out.with_name(f".{out.stem}.{os.getpid()}.{threading.get_ident()}.jpg")
    command = [
        tool,
        # Decode a JPEG at reduced size from the start: a big speed-up on 4K
        # sources, and ignored for other formats.
        "-define",
        "jpeg:size=960x540",
        str(source),
        "-thumbnail",
        "480x270^",
        "-gravity",
        "center",
        "-extent",
        "480x270",
        "-strip",
        "-quality",
        "80",
        str(tmp),
    ]
    if background:
        if shutil.which("nice"):
            command = ["nice", "-n", "15", *command]
        ok = _run(command)
    else:
        with _magick_slots:
            ok = _run(command)
    if not ok:
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(out)
    return out


def warm_thumbnails(
    first: list[str] | None = None,
    directory: Path | None = None,
    cache: Path | None = None,
) -> int:
    """Make every wallpaper's thumbnail ahead of time, one at a time, niced.

    Made on demand, a first visit to Settings sat mostly blank: a 4K PNG takes
    around half a second to decode, and the grid asks for twenty at once. The
    Settings backend runs this in a thread when it starts, current wallpaper
    first. Each is made once and cached, so later launches cost nothing.
    Returns how many were made.
    """
    directory = directory or WALLPAPER_DIR
    names = [row["name"] for row in list_wallpapers(directory)]
    wanted = [n for n in (first or []) if n in names]
    wanted += [n for n in names if n not in wanted]
    made = 0
    for name in wanted:
        source = directory / name
        if ((cache or CACHE) / "thumbs" / f"{_key(source)}.jpg").is_file():
            continue
        if thumbnail(source, cache, background=True):
            made += 1
    return made


def parse_histogram(text: str) -> list[tuple[int, str]]:
    """(pixel count, #rrggbb) rows from `magick ... histogram:info:-`."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3 or not parts[0].endswith(":"):
            continue
        colour = next((p for p in parts if p.startswith("#") and len(p) >= 7), "")
        try:
            rows.append((int(parts[0][:-1]), colour[:7].lower()))
        except ValueError:
            continue
    rows.sort(reverse=True)
    return [r for r in rows if r[1]]


def _hls(colour: str) -> tuple[float, float, float]:
    r, g, b = (int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)


def _hex(h: float, lightness: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h, lightness, s)
    return "#" + "".join(f"{round(c * 255):02x}" for c in (r, g, b))


def pick_accent(palette: list[str]) -> str:
    """The wallpaper colour that makes the best accent, made legible on dark.

    A photograph's most common colour is usually its darkest, which is useless
    as an accent. The pick favours saturation, weighted a little by how common
    the colour is, then lifts it to a readable lightness on a dark panel.
    """
    best, score = "", -1.0
    for rank, colour in enumerate(palette):
        h, lightness, s = _hls(colour)
        if lightness < 0.08 or lightness > 0.95:
            continue
        weight = s * (1.0 - rank * 0.06)
        if weight > score:
            best, score = colour, weight
    if not best or _hls(best)[2] < 0.08:
        # A grey wallpaper has no hue to lift; lifting one would invent red.
        return FALLBACK_ACCENT
    return lift(best)


def lift(colour: str) -> str:
    """A palette colour at a lightness and saturation that read on dark glass."""
    h, _lightness, s = _hls(colour)
    return _hex(h, 0.68, max(s, 0.45))


def swatches(palette: list[str]) -> list[str]:
    """The wallpaper's colours as accent choices: lifted, greys and repeats out."""
    out: list[str] = []
    for colour in palette:
        if _hls(colour)[2] < 0.08:
            continue
        lifted = lift(colour)
        if lifted not in out:
            out.append(lifted)
    return out


def _variants(accent: str) -> tuple[str, str]:
    """(a darker partner for fills, the text colour that sits on the accent)."""
    h, lightness, s = _hls(accent)
    darker = _hex(h, max(0.0, lightness - 0.1), s)
    # whichever of dark and white reads better on it (a luminance cut put
    # white on Neon's pink at 3.1:1)
    return darker, forge_themes.on_colour(accent, darker)


def surfaces(accent: str, tint: float, mode: str, contrast: str) -> dict:
    """The panel, border and text colours every app is drawn with.

    In wallpaper mode they take the accent's hue (the accent is already the
    wallpaper's colour) at fixed dark lightnesses, so text contrast holds
    whatever the wallpaper: tests check 7:1 for text and 4.5:1 for quiet text
    on every panel.
    """
    high = contrast == "high"
    if mode != "wallpaper":
        if not high:
            return dict(NEUTRAL_SURFACES)
        return dict(NEUTRAL_SURFACES, text="#ffffff", muted="#b8c0cc", border="#3e4552")
    h = _hls(accent)[0]
    s = 0.08 + 0.42 * max(0.0, min(1.0, tint))
    return {
        "bg": _hex(h, 0.065, s),
        "panel": _hex(h, 0.105, s),
        "panel_2": _hex(h, 0.135, s),
        "border": _hex(h, 0.30 if high else 0.21, s * 0.8),
        "text": _hex(h, 0.97 if high else 0.93, s * 0.3),
        "muted": _hex(h, 0.80 if high else 0.70, s * 0.35),
    }


def render(source: Path, cache: Path | None = None) -> dict:
    """The wallpaper copy, its blurred copy and its palette - cached by file.

    Without ImageMagick the original file is used as-is and the accent falls
    back to the default; Forge still starts, it just starts heavier.
    """
    cache = cache or CACHE
    key = _key(source)
    folder = cache / "wallpaper"
    image, blur, meta = (
        folder / f"{key}.jpg",
        folder / f"{key}-blur.jpg",
        folder / f"{key}.json",
    )
    if image.is_file() and blur.is_file() and meta.is_file():
        try:
            return {
                "image": image,
                "blur": blur,
                **json.loads(meta.read_text(encoding="utf-8")),
            }
        except Exception:
            pass
    tool = _magick()
    if not tool:
        return {"image": source, "blur": source, "palette": []}
    folder.mkdir(parents=True, exist_ok=True)
    ok = _run(
        [
            tool,
            str(source),
            "-resize",
            "2560x1440^",
            "-gravity",
            "center",
            "-extent",
            "2560x1440",
            "-strip",
            "-quality",
            "85",
            str(image),
        ]
    ) and _run(
        [
            tool,
            str(image),
            "-resize",
            "12.5%",
            "-blur",
            "0x6",
            "-resize",
            "800%",
            "-quality",
            "80",
            str(blur),
        ]
    )
    if not ok:
        return {"image": source, "blur": source, "palette": []}
    try:
        text = subprocess.run(
            [
                tool,
                str(image),
                "-resize",
                "96x96",
                "-colors",
                "8",
                "-format",
                "%c",
                "histogram:info:-",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        palette = [colour for _count, colour in parse_histogram(text)]
    except Exception:
        palette = []
    meta.write_text(json.dumps({"palette": palette}), encoding="utf-8")
    return {"image": image, "blur": blur, "palette": palette}


# --- the theme ------------------------------------------------------------------


# .mp4 and .webm too: a saved YouTube "lofi playlist" video is music here,
# and an audio element plays the sound track of a video file
MUSIC_TYPES = {
    ".mp3",
    ".ogg",
    ".opus",
    ".flac",
    ".m4a",
    ".aac",
    ".wav",
    ".mp4",
    ".webm",
}


def music_tracks(folder: str, limit: int = 300) -> list[dict]:
    """The playable files in the music folder, as file:// links the hub can
    hand to an audio element (the hub itself is loaded over file://, so
    these play with no server). Sorted by name; sub-folders one level."""
    root = Path(os.path.expanduser(folder or ""))
    if not folder or not root.is_dir():
        return []
    out = []
    for p in sorted(root.glob("*")) + sorted(root.glob("*/*")):
        if p.is_file() and p.suffix.lower() in MUSIC_TYPES:
            out.append({"name": p.stem, "url": file_link(p)})
            if len(out) >= limit:
                break
    return out


def music_note(folder: str) -> str:
    """Why the music folder gives no tracks, in words for the note button,
    or "" when it has some."""
    root = Path(os.path.expanduser(folder or ""))
    if not folder:
        return "No music folder is set (Settings > Home screen)"
    if not root.is_dir():
        return f"The music folder {folder} does not exist yet"
    if not music_tracks(folder, limit=1):
        return f"No music in {folder} yet (mp3, ogg, flac, m4a, mp4 ...)"
    return ""


# Words in a wallpaper's file name that say which particles suit it, checked
# before its colours. The kind with the most words in the name wins (ties go
# to the one listed first); adding a word is one entry.
AMBIENCE_WORDS: dict[str, tuple[str, ...]] = {
    "petals": (
        "sakura",
        "cherry",
        "blossom",
        "petal",
        "torii",
        "spring",
        "hanami",
        "japan",
    ),
    "snow": ("snow", "winter", "frost", "ice", "christmas", "yuki"),
    "rain": ("rain", "storm", "neon", "cyberpunk", "city", "street", "tokyo"),
    "fireflies": ("firefl", "forest", "night", "summer", "hotaru"),
    "lanterns": ("lantern", "festival", "matsuri", "shrine", "chouchin", "lamp"),
    "glitter": ("glitter", "sparkle", "magical", "idol", "crystal", "diamond"),
    "rays": ("sunbeam", "sunlight", "god-ray", "morning", "cathedral", "ray"),
    "dust": ("desert", "sand", "dune", "library", "cafe", "room", "ruin"),
    "leaves": ("autumn", "fall", "maple", "momiji", "leaves", "leaf", "harvest"),
    "bubbles": ("ocean", "sea", "underwater", "aqua", "reef", "bubble", "fish"),
    "stars": ("space", "galaxy", "star", "cosmos", "nebula", "planet", "astro"),
    "emberstorm": ("fire", "lava", "volcano", "forge", "flame", "inferno"),
    "wisps": ("spirit", "ghibli", "mononoke", "kodama", "wisp", "yokai", "ghost"),
    "galaxy": ("milkyway", "milky-way", "milky_way", "spiral", "andromeda"),
}
AMBIENCE_FILE = HOME / ".config/forge/ambience.json"  # {"file.jpg": "snow"}


def wallpaper_particle_picks() -> dict[str, str]:
    """Each wallpaper's own particle pick, set in the Wallpapers app: a kind
    or "off". A wallpaper with no pick matches its particles automatically."""
    try:
        data = json.loads(AMBIENCE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    kinds = PARTICLE_LABELS.keys() - {"auto"}
    return {
        str(k): v for k, v in (data or {}).items() if isinstance(v, str) and v in kinds
    }


def set_wallpaper_particles(name: str, kind: str) -> dict[str, str]:
    """Save one wallpaper's pick; "" or "auto" clears it back to matching."""
    check_lock()
    picks = wallpaper_particle_picks()
    if kind in ("", "auto"):
        picks.pop(name, None)
    elif kind in PARTICLE_LABELS:
        picks[name] = kind
    else:
        raise ValueError(f"no particle kind called {kind!r}")
    AMBIENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = AMBIENCE_FILE.with_name(f".ambience.json.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(picks, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(AMBIENCE_FILE)
    return picks


def wall_light(palette: list[str]) -> float:
    """How light the picture is overall, 0..1 (the particles use it to stay
    visible on bright pictures)."""
    colours = [_hls(c) for c in palette[:6]]
    return round(sum(l for _h, l, _s in colours) / len(colours), 3) if colours else 0.0


def ambience(
    name: str, palette: list[str], overrides: dict | None = None
) -> tuple[str, str]:
    """The particle kind that suits a wallpaper, and why: the user's own pick
    for that file, a word in its name, or its colours."""
    if overrides is None:
        try:
            overrides = json.loads(AMBIENCE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            overrides = {}
    pick = (overrides or {}).get(name)
    # an "off" pick is the wallpaper's own (wallpaper_particles); what suits
    # the picture is still worked out, for when the pick is cleared
    if (
        isinstance(pick, str)
        and pick in SETTINGS["particles"]["choices"]
        and pick not in ("off", "auto")
    ):
        return pick, "your pick for this wallpaper"
    lower = name.lower()
    hits = {k: sum(w in lower for w in words) for k, words in AMBIENCE_WORDS.items()}
    best = max(hits, key=lambda k: hits[k])  # first listed wins a tie
    if hits[best]:
        return best, "its name"
    return ambience_from_colours(palette), "its colours"


def ambience_from_colours(palette: list[str]) -> str:
    """Read the most common colours the way a person would name the picture."""
    colours = [_hls(c) for c in palette[:6]]
    if not colours:
        return "soft"
    pinks = sum(
        1 for h, l, s in colours if (h > 0.86 or h < 0.02) and s > 0.25 and l > 0.5
    )
    light = sum(l for _h, l, _s in colours) / len(colours)
    sat = sum(s for _h, _l, s in colours) / len(colours)
    hue = colours[0][0]
    if pinks >= 2:
        return "petals"
    if light < 0.1 and sat < 0.4:
        return "stars"  # near black: a night sky
    if 0.45 < hue < 0.55 and sat > 0.4 and 0.25 < light < 0.6:
        return "bubbles"  # teal and cyan: water
    if 0.02 < hue < 0.1 and sat > 0.55 and 0.25 < light < 0.6:
        return "leaves"  # deep orange and rust: autumn
    if light > 0.72 and sat < 0.25:
        return "snow"
    if light < 0.32:
        if 0.5 < hue < 0.72:
            return "rain"
        return "fireflies"
    if 0.22 < hue < 0.45:
        return "fireflies"
    if 0.03 < hue < 0.17:
        return "rays" if light > 0.5 else "dust"
    return "soft"


def wallpaper_layers(settings: dict, image: Path | None, cache: Path | None) -> dict:
    """The 2.5D layers of the wallpaper's copy when they are made
    (shared/forge_layers.py); with 2.5D on and none made yet, their making
    starts in the background and the hub gets them on the next theme."""
    out = {
        "wallpaper_fg": "",
        "wallpaper_bg": "",
        "wallpaper_subject": "",
        "wallpaper_depth": "",
        "wallpaper_plate": "",
    }
    if not settings.get("wall_3d") or not image:
        return out
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:  # loaded by file path (forge.py) or as a module
        sys.path.insert(0, here)
    import forge_layers

    folder = Path(image).parent
    key = Path(image).stem
    info = forge_layers.ready(key, folder)
    if info is None or info.get("method") != forge_layers.METHOD:
        # layers by an older recipe are made again; meanwhile two layers
        forge_layers.start(Path(image), key, folder)
    if info is None:
        return out
    p = forge_layers.layer_paths(key, folder)
    out["wallpaper_subject"] = info.get("subject", "none")
    if out["wallpaper_subject"] != "none":
        out["wallpaper_fg"] = file_link(p["fg"])
        out["wallpaper_bg"] = file_link(p["bg"])
    # real depth works on a landscape with no subject as well; it needs the
    # two-layer depth and the plate of the current recipe (task 327)
    if (
        info.get("method") == forge_layers.METHOD
        and p["depth"].is_file()
        and p["plate"].is_file()
    ):
        out["wallpaper_depth"] = file_link(p["depth"])
        out["wallpaper_plate"] = file_link(p["plate"])
    return out


def theme(settings: dict | None = None, cache: Path | None = None) -> dict:
    """Everything the hub and the apps need to draw the chosen look."""
    settings = settings or load()
    # The look's own rules (hub/looks/<look>.json): settings it holds while
    # chosen, and whether it is locked and shows a company logo.
    rules = look_rules(settings["look"])
    company = active_company(settings) if rules["company_logo"] else {}
    settings = {**settings, **rules["forces"]}
    # the Forge layout's forces (FORGE_LAYOUTS) on top: Classic holds three
    layout_rules = FORGE_LAYOUTS.get(
        settings.get("forge_layout", "new"), FORGE_LAYOUTS["new"]
    )
    settings = {**settings, **layout_rules["forces"]}
    left = forge_themes.get_theme(settings.get("theme", ""))
    if left and not forge_themes.active_theme(settings):
        # another look was picked by hand: the theme's accent goes with it
        if settings["accent"] and settings["accent"] == left["colours"].get("accent"):
            settings["accent"] = ""
    if rules["accent"] and not settings["accent"]:
        settings["accent"] = rules["accent"]
    # the theme's own panel colours, while Panel colours says to use them
    picked = forge_themes.active_theme(settings)
    themed = picked if settings["theme_source"] == "theme" else None
    source = chosen_wallpaper(settings)
    rendered = (
        render(source, cache)
        if source
        else {"image": None, "blur": None, "palette": []}
    )
    palette = rendered.get("palette") or []
    accent = settings["accent"] or (
        pick_accent(palette) if palette else FALLBACK_ACCENT
    )
    finished = forge_themes.finish_surfaces(
        forge_themes.surfaces(themed)
        or surfaces(
            accent,
            settings["tint"],
            settings["theme_source"],
            settings["contrast"],
        )
    )
    # the accent reads as text on those panels too
    accent = forge_themes.readable_accent(accent, finished)
    accent_2, on_accent = _variants(accent)
    layers = wallpaper_layers(settings, rendered.get("image"), cache)
    return {
        **layers,
        "wallpaper": file_link(rendered["image"]) if rendered.get("image") else "",
        "wallpaper_blur": file_link(rendered["blur"]) if rendered.get("blur") else "",
        "wallpaper_name": source.name if source else "",
        "follows_desktop": not settings["wallpaper"],
        "palette": palette,
        "swatches": swatches(palette),
        "accent": accent,
        "accent_2": accent_2,
        "on_accent": on_accent,
        "unify_accent": settings["unify_accent"],
        # Every ordinary setting as it is, so a new one reaches the hub and
        # the apps without touching this function.
        **{k: settings[k] for k, spec in SETTINGS.items() if not spec.get("custom")},
        "font_stack": font_stack(settings),
        "size_presets": size_presets(settings),
        # False in the Classic layout: groups' "members" lists and tabs are
        # left out (FORGE_LAYOUTS)
        "layout_places": layout_rules["places"],
        # what the layout holds, for Settings to show held rather than saved
        "layout_holds": dict(layout_rules["forces"]),
        "hub_keys": settings["hub_keys"],
        "hub_key_list": hub_key_list(settings["hub_keys"]),
        "hidden_apps": settings["hidden_apps"],
        "archived_apps": settings["archived_apps"],
        "app_folders": settings["app_folders"],
        # the hub refuses its own changes while locked; Settings sends a new
        # look_open_until when the password opens or shuts the window
        "look_locked": rules["locked"] and forge_lock.has_password(),
        "look_open_until": forge_lock.open_until() if rules["locked"] else 0,
        "company_name": company.get("name", ""),
        "company_logo": company.get("logo", ""),
        "power_pairs": {k: list(v) for k, v in POWER_PAIRS.items()},
        "visuals_popup": popup_rows(VISUALS_POPUP),
        "music_tracks": (
            music_tracks(settings["music_folder"]) if settings["music"] else []
        ),
        "music_note": music_note(settings["music_folder"]) if settings["music"] else "",
        **dict(
            zip(
                ("ambience", "ambience_reason"),
                ambience(source.name if source else "", palette),
            )
        ),
        "wallpaper_particles": (
            wallpaper_particle_picks().get(source.name, "") if source else ""
        ),
        "wall_light": wall_light(palette),
        # the panel and text colours every page is drawn with, and the CSS
        # tokens they become (forge_themes.SURFACE_TOKENS, Relay task 388)
        "surfaces": finished,
        "surface_tokens": [list(row) for row in forge_themes.SURFACE_TOKENS],
        # the theme and layout (shared/forge_themes.py): its id, light or
        # dark, its stylesheet, the home layout's rules and the picker list
        **forge_themes.extras(settings, _wall_link),
        # every setting Settings shows, for the home screen's search
        "search_settings": search_index(),
    }


def _wall_link(name: str) -> str:
    """A picker card's picture as a link: a theme's shipped picture, one
    from the wallpaper folder, or for "" the desktop's; "" for one not there
    (the card shows the theme's colours)."""
    path = wallpaper_path(name) if name else desktop_wallpaper()
    return file_link(path) if path else ""


def font_stack(settings: dict) -> str:
    """The font every page is drawn in ("" leaves each app's own)."""
    if settings["font"] == "theme":
        chosen = forge_themes.active_theme(settings)
        if not chosen:
            return ""
        return chosen["font_stack"] or FONTS.get(chosen["font"], "")
    return FONTS.get(settings["font"], "")


def write_theme_js(hub_dir: Path, data: dict) -> Path:
    # The portable launcher (forge_portable.py) serves the theme itself and
    # names a folder of its own here, so nothing is written into a release
    # folder, which may be read-only.
    hub_dir = Path(os.environ.get("FORGE_HUB_OUT") or hub_dir)
    hub_dir.mkdir(parents=True, exist_ok=True)
    out = hub_dir / "theme.js"
    tmp = out.with_name(f".theme.js.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text("window.FORGE_THEME = " + json.dumps(data) + ";\n", encoding="utf-8")
    tmp.replace(out)
    return out


def apply(hub_dir: Path) -> dict:
    """Work out the theme from the saved settings and hand it to the hub."""
    data = theme()
    write_theme_js(hub_dir, data)
    return data


# ----------------------------------------------------------------------------
# a small command line, for helpers outside Forge's apps (the GNOME desktop
# particles extension's own settings page, S21): read a group's settings with
# their current values, or change one and refresh hub/theme.js


def section_id(group: str) -> str:
    """The Settings page id a group's rows sit under, as Settings' own
    buildGroups makes it: "Speed and detail" -> "speed-and-detail"."""
    return re.sub(r"[^a-z0-9]+", "-", group.lower())


def search_index() -> list[dict]:
    """Every setting the Settings app draws a row for, for the home screen's
    one search (shared/forge_search.js): key, label, a short help, and the
    page it sits on, so a hit opens Settings at #<section>/<key>. The rows
    Settings skips (custom ones drawn by hand, app options, the ones the
    portable launcher cuts) are skipped here."""
    rows = []
    for key, spec in describe().items():
        group = spec.get("group")
        if not group or spec.get("app"):
            continue
        if spec.get("custom") and spec.get("kind") not in ("presets", "keys"):
            continue
        help_text = str(spec.get("help", ""))
        rows.append(
            {
                "key": key,
                "label": str(spec.get("label", key)),
                "help": help_text[:160],
                "section": section_id(group),
                "section_label": group,
            }
        )
    return rows


def settings_rows(groups: list[str], settings: dict | None = None) -> list[dict]:
    """The settings in `groups`, in table order, each with its value now.
    Only the kinds a plain settings page can show: switch, number, choice."""
    settings = settings or load()
    rows = []
    for key, spec in SETTINGS.items():
        if spec.get("group") not in groups or spec.get("custom"):
            continue
        if spec["kind"] not in ("bool", "number", "int", "choice"):
            continue
        row = {k: v for k, v in spec.items() if k != "also"}
        rows.append({"key": key, **row, "value": settings.get(key, spec["default"])})
    return rows


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Read or change Forge settings.")
    parser.add_argument("--rows", action="append", default=[], metavar="GROUP")
    parser.add_argument("--set", metavar="KEY=JSON")
    args = parser.parse_args(argv)
    if args.set:
        key, _, raw = args.set.partition("=")
        if key not in SETTINGS:
            parser.error(f"no setting called {key!r}")
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        try:
            saved = save({key: value})
        except forge_lock.Locked as error:
            print(error, file=sys.stderr)
            return 1
        apply(Path(__file__).resolve().parent.parent / "hub")
        print(json.dumps({key: saved[key]}))
    if args.rows:
        print(json.dumps(settings_rows(args.rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
