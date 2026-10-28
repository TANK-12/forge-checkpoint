"""Vault: one browser for the 3D models, skies, textures, images and sounds
already on disk, plus Poly Haven's free assets, with "send to Blender /
Godot / PixelForge".

Three registries next to this file drive it:

- sources.json      folders always looked in; the page can add more, kept in
                    <data>/folders.json
- kinds.json        what each file ending is, and which name parts mark a
                    material map (a folder of maps is one texture item)
- send_targets.json where an item can go; each id has a function in SENDERS

Nothing in a source folder is ever changed. Sending copies or reads; a copy
never lands on an existing name.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
FORGE = ROOT.parent.parent
SHARED = Path(os.environ.get("FORGE_SHARED_DIR") or FORGE / "shared")
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

import forge_art  # noqa: E402  # pyright: ignore[reportMissingImports]
import forge_assets  # noqa: E402  # pyright: ignore[reportMissingImports]

KINDS_DOC = json.loads((ROOT / "kinds.json").read_text())
KINDS = {k["id"]: k for k in KINDS_DOC["kinds"]}
TARGETS = {
    t["id"]: t for t in json.loads((ROOT / "send_targets.json").read_text())["targets"]
}
EXT_KIND: dict[str, str] = {}
for _k in KINDS_DOC["kinds"]:
    for _e in _k["exts"]:
        EXT_KIND.setdefault(_e, _k["id"])
IMAGE_EXTS = set(KINDS["image"]["exts"])
COLOR_WORDS = KINDS_DOC["map_words"]["color"]
MAP_WORDS = COLOR_WORDS + KINDS_DOC["map_words"]["other"]

SKIP_DIRS = {"node_modules", "__pycache__", ".venv", "venv", "site-packages"}
MAX_DEPTH = 6
MAX_ITEMS_PER_SOURCE = 20000
MAX_FILES_WALKED = 200000  # per source, so a huge folder cannot hold the scan
MAX_GLTF_READ = 20 * 1024 * 1024  # a bigger .gltf is listed without its parts
MAX_THUMB_SOURCE = 80 * 1024 * 1024  # bigger images get no thumbnail
DISK_FLOOR = 2 * 1024**3  # Poly Haven downloads stop below 2 GB free
PH_ID = re.compile(r"^[a-z0-9_]{1,80}$")
PH_SIZES = ("1k", "2k", "4k")
RES_TAIL = re.compile(r"_\d+k$")  # rock_nor_gl_2k
# folders that hold whole systems or every home; a folder inside them is fine
TOO_BIG = {"/", "/home", "/usr", "/etc", "/var", "/opt", "/srv", "/mnt", "/media"}
SYSTEM_TREES = ("/proc", "/sys", "/dev", "/run", "/boot")
ART_LOCK = threading.Lock()  # a free pack name and its save happen together


class VaultError(Exception):
    pass


class NotFound(VaultError):
    pass


def data_dir() -> Path:
    d = Path(
        os.environ.get("VAULT_DATA_DIR") or Path.home() / ".local/share/forge/vault"
    )
    d.mkdir(parents=True, exist_ok=True)
    return d


def _expand(path: str) -> Path:
    """{forge} is the Forge folder, {assets} where forge_assets keeps its
    downloads (FORGE_ASSETS_DIR: Forge's data place in a release), ~ home."""
    path = path.replace("{assets}", str(forge_assets.ROOT))
    return Path(os.path.expanduser(path.replace("{forge}", str(FORGE))))


# --- sources -----------------------------------------------------------------


def _registry_sources() -> list[dict]:
    path = os.environ.get("VAULT_SOURCES") or ROOT / "sources.json"
    return json.loads(Path(path).read_text())["sources"]


def _folders_file() -> Path:
    return data_dir() / "folders.json"


def _user_folders() -> list[str]:
    try:
        folders = json.loads(_folders_file().read_text())
    except (OSError, ValueError):
        return []
    return [f for f in folders if isinstance(f, str)]


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def sources() -> list[dict]:
    out = []
    for s in _registry_sources():
        out.append(
            {
                "id": s["id"],
                "label": s["label"],
                "path": str(_expand(s["path"])),
                "user": False,
            }
        )
    for f in _user_folders():
        out.append(
            {
                "id": "u-" + hashlib.sha1(f.encode()).hexdigest()[:10],
                "label": Path(f).name or f,
                "path": f,
                "user": True,
            }
        )
    for s in out:
        s["exists"] = Path(s["path"]).is_dir()
    return out


def add_folder(path: str) -> list[dict]:
    p = Path(os.path.expanduser(str(path or "").strip()))
    if not str(path or "").strip() or not p.is_absolute():
        raise VaultError("Give the full path of a folder, such as ~/Pictures/Art")
    p = Path(os.path.realpath(p))
    if not p.is_dir():
        raise VaultError(f"{p} is not a folder")
    home = Path(os.path.realpath(Path.home()))
    if str(p) in TOO_BIG or p == home or p in home.parents:
        raise VaultError("That folder is too big to look through; pick one inside it")
    if any(str(p) == t or _under(str(p), t) for t in SYSTEM_TREES):
        raise VaultError("That is a system folder, not one with files to look through")
    folders = _user_folders()
    known = {s["path"] for s in sources()}
    if str(p) not in known:
        folders.append(str(p))
        _write_json(_folders_file(), folders)
    INDEX.clear()
    return sources()


def forget_folder(source_id: str) -> list[dict]:
    """Stops looking in a folder the user added; the folder itself is untouched."""
    match = [s for s in sources() if s["id"] == source_id]
    if not match:
        raise NotFound("No such folder")
    if not match[0]["user"]:
        raise VaultError("That folder comes from sources.json and stays")
    _write_json(_folders_file(), [f for f in _user_folders() if f != match[0]["path"]])
    INDEX.clear()
    return sources()


# --- scanning ----------------------------------------------------------------


def _item_id(path: str) -> str:
    return hashlib.sha1(path.encode()).hexdigest()[:16]


def _utf8(name: str) -> bool:
    """False for a file name that is not valid UTF-8 (it could not be shown
    or asked for by the page, so it is left out)."""
    try:
        name.encode()
    except UnicodeEncodeError:
        return False
    return True


def _map_parts(name: str) -> tuple[str, str] | None:
    """(map word, material) for a material map file name, or None.

    rock_nor_gl_2k.jpg gives ("nor_gl", "rock") and Brick01_1K-JPG_Color.jpg
    gives ("color", "brick01_1k_jpg"): every map of one material shares the
    material part, so loose photos with a map word in them do not pair up."""
    flat = re.sub(r"[^a-z0-9]+", "_", Path(name).stem.lower()).strip("_")
    flat = RES_TAIL.sub("", flat) or flat
    padded = f"_{flat}_"
    for w in sorted(MAP_WORDS, key=len, reverse=True):
        tag = f"_{w}_"
        if tag in padded:
            rest = padded.replace(tag, "_", 1).strip("_")
            return w, rest
    return None


def _map_word(name: str) -> str | None:
    """The map a file name marks (colour, normal...), or None."""
    found = _map_parts(name)
    return found[0] if found else None


def _stat(p: Path) -> tuple[int, float]:
    try:
        st = p.stat()
        return st.st_size, st.st_mtime
    except OSError:
        return 0, 0.0


def _text(value, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _item(source: dict, kind: str, main: Path, files: list[str], **extra) -> dict:
    size, mtime = _stat(main)
    if len(files) > 1:
        size = sum(_stat(main.parent / f)[0] for f in files)
    item = {
        "id": _item_id(str(main)),
        "name": extra.pop("name", None) or main.stem,
        "kind": kind,
        "path": str(main),
        "dir": str(main.parent),
        "files": files,
        "ext": main.suffix.lower(),
        "size": size,
        "mtime": mtime,
        "source": source["id"],
        "folder": os.path.relpath(main.parent, source["path"]),
    }
    item.update(extra)
    return item


def _from_manifest(source: dict, folder: Path) -> dict | None:
    """A forge_assets download (Poly Haven) is one item, whatever it holds."""
    try:
        m = json.loads((folder / "manifest.json").read_text())
        # the paths were written where it was downloaded; read them from here
        main = folder / os.path.relpath(
            m["main"], m.get("dir") or Path(m["main"]).parent
        )
        kind = {"hdri": "hdri", "texture": "texture", "model": "model"}[m["kind"]]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not main.is_file():
        return None
    files = m.get("files")
    files = [f for f in files if isinstance(f, str)] if isinstance(files, list) else []
    if main.name not in files:
        files.insert(0, main.name)
    authors = m.get("authors")
    if isinstance(authors, str):
        authors = [authors]
    authors = (
        [a for a in authors if isinstance(a, str)] if isinstance(authors, list) else []
    )
    return _item(
        source,
        kind,
        main,
        files,
        name=_text(m.get("name")) or main.stem,
        license=_text(m.get("license")),
        link=_text(m.get("source")),
        authors=authors,
    )


def _texture_sets(source: dict, folder: Path, files: list[str]) -> list[dict]:
    """One texture item per material in the folder: a colour map plus at
    least one other map with the same material part in its name."""
    groups: dict[str, dict[str, str]] = {}
    for f in files:
        found = _map_parts(f)
        if found:
            groups.setdefault(found[1], {})[f] = found[0]
    sets = []
    for material, maps in sorted(groups.items()):
        colour = sorted(f for f, w in maps.items() if w in COLOR_WORDS)
        if len(maps) < 2 or not colour:
            continue
        # a picture the page can show leads, ahead of an .exr colour map
        colour.sort(key=lambda f: Path(f).suffix.lower() not in IMAGE_EXTS)
        sets.append((material, colour[0], sorted(maps)))
    note = folder / "SOURCE.txt"
    extra = {}
    if sets and note.is_file():
        extra["note"] = note.read_text(errors="replace")[:400]
    name = folder.name
    if re.fullmatch(r"\d+k", name.lower()) and folder.parent != folder:
        name = f"{folder.parent.name} ({name})"
    out = []
    for material, main, maps in sets:
        label = name if len(sets) == 1 else material or name
        out.append(_item(source, "texture", folder / main, maps, name=label, **extra))
    return out


def _gltf_parts(main: Path) -> list[str]:
    """The .gltf and every buffer or image it points at, relative to it."""
    parts = [main.name]
    try:
        if main.stat().st_size > MAX_GLTF_READ:
            return parts
        doc = json.loads(main.read_text())
    except (OSError, ValueError):
        return parts
    if not isinstance(doc, dict):
        return parts
    for group in ("buffers", "images"):
        entries = doc.get(group)
        for entry in entries if isinstance(entries, list) else []:
            uri = entry.get("uri") if isinstance(entry, dict) else None
            if (
                isinstance(uri, str)
                and not uri.startswith("data:")
                and "://" not in uri
            ):
                parts.append(urllib.parse.unquote(uri))
    return parts


def scan_source(source: dict) -> list[dict]:
    root = Path(source["path"])
    items: list[dict] = []
    if not root.is_dir():
        return items
    real_root = [os.path.realpath(root)]
    walked = 0

    def keep(it: dict | None) -> bool:
        # a link out of the folder is not shown at all
        return bool(it) and _inside(it["path"], real_root)

    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        depth = len(here.relative_to(root).parts)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".")
            and d not in SKIP_DIRS
            and depth < MAX_DEPTH
            and _utf8(d)
        )
        walked += len(filenames)
        if walked > MAX_FILES_WALKED or len(items) >= MAX_ITEMS_PER_SOURCE:
            break
        if not _utf8(dirpath):
            continue
        if "manifest.json" in filenames:
            one = _from_manifest(source, here)
            if one:
                if keep(one):
                    items.append(one)
                dirnames[:] = []
                continue
        files = sorted(f for f in filenames if not f.startswith(".") and _utf8(f))
        maps = [
            f
            for f in files
            if Path(f).suffix.lower() in IMAGE_EXTS
            or EXT_KIND.get(Path(f).suffix.lower()) == "hdri"
        ]
        used: set[str] = set()
        for tex in _texture_sets(source, here, maps):
            used.update(tex["files"])
            if keep(tex):
                items.append(tex)
        for f in files:
            kind = EXT_KIND.get(Path(f).suffix.lower())
            if not kind or f in used:
                continue
            if kind == "hdri" and _map_word(f) not in (None, *COLOR_WORDS):
                continue  # a normal or height map in .exr, not a sky
            main = here / f
            parts = _gltf_parts(main) if main.suffix.lower() == ".gltf" else [f]
            one = _item(source, kind, main, parts)
            if keep(one):
                items.append(one)
    return items[:MAX_ITEMS_PER_SOURCE]


class Index:
    """Every item from every source, scanned on first use and on Refresh."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.scanned = 0.0
        self.lock = threading.Lock()

    def clear(self) -> None:
        with self.lock:
            self.scanned = 0.0

    def all(self) -> dict[str, dict]:
        with self.lock:
            if not self.scanned:
                found: dict[str, dict] = {}
                for s in sources():
                    try:
                        for it in scan_source(s):
                            found.setdefault(it["id"], it)
                    except Exception as e:  # one odd folder never hides the rest
                        print(f"vault: skipped {s['path']}: {e!r}", file=sys.stderr)
                self.items, self.scanned = found, time.time()
            return self.items


INDEX = Index()


def list_items(q: str = "", kind: str = "", source: str = "", limit: int = 400) -> dict:
    items = list(INDEX.all().values())
    words = q.lower().split()
    counts: dict[str, int] = {}
    hits = []
    for it in items:
        if source and it["source"] != source:
            continue
        text = f"{it['name']} {it['folder']} {Path(it['path']).name}".lower()
        if words and not all(w in text for w in words):
            continue
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1
        if kind and it["kind"] != kind:
            continue
        hits.append(it)
    hits.sort(key=lambda it: (-it["mtime"], it["name"].lower()))
    return {"items": hits[:limit], "total": len(hits), "counts": counts}


def _roots() -> list[str]:
    return [os.path.realpath(s["path"]) for s in sources() if s["exists"]]


def _under(path: str, base: str, paths=os.path) -> bool:
    """`path` is inside the folder `base` (not `base` itself), by this
    system's separators and case rules (Windows: backslashes, any case)."""
    path, base = paths.normcase(path), paths.normcase(base)
    if path == base:
        return False
    try:
        return paths.commonpath([path, base]) == base
    except ValueError:  # another drive on Windows
        return False


def _inside(path: str, roots: list[str]) -> bool:
    real = os.path.realpath(path)
    return any(
        os.path.normcase(real) == os.path.normcase(r) or _under(real, r) for r in roots
    )


def get_item(item_id: str) -> dict:
    it = INDEX.all().get(item_id)
    if not it:
        raise NotFound("No such item; press Refresh")
    if not _inside(it["path"], _roots()):
        raise NotFound("That file points outside Vault's folders")
    return it


def item_file(item_id: str, rel: str) -> Path:
    """A file belonging to an item (its main file, a map, a glTF buffer),
    never anything outside the item's folder or Vault's folders."""
    it = get_item(item_id)
    rel = os.path.normpath(rel or ".")
    if rel not in {os.path.normpath(f) for f in it["files"]}:
        raise NotFound(
            "No such file"
        )  # only the item's own files, never its neighbours
    base = os.path.realpath(it["dir"])
    path = os.path.realpath(os.path.join(base, rel))
    if not (_under(path, base) and _inside(path, _roots())):
        raise NotFound("No such file")
    if not os.path.isfile(path):
        raise NotFound("No such file")
    return Path(path)


def thumb(item_id: str) -> Path:
    """A small webp of an image or texture item, made once."""
    it = get_item(item_id)
    if it["kind"] not in ("image", "texture"):
        raise NotFound("No picture for this kind")
    src = Path(it["path"])
    size, mtime = _stat(src)
    if not size or size > MAX_THUMB_SOURCE:
        raise NotFound("Too big for a thumbnail")
    out = data_dir() / "thumbs" / f"{item_id}-{int(mtime)}.webp"
    if out.is_file():
        return out
    from PIL import Image

    out.parent.mkdir(exist_ok=True)
    try:
        with Image.open(src) as im:
            im.thumbnail((256, 256))
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            tmp = out.with_suffix(".tmp")
            im.save(tmp, "WEBP", quality=80)
            os.replace(tmp, out)
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        raise NotFound(f"Cannot read that picture: {e}") from e
    return out


# --- Poly Haven ----------------------------------------------------------------


def ph_search(kind: str, q: str) -> list[dict]:
    """Poly Haven hits, each with the sizes already downloaded."""
    try:
        hits = forge_assets.search(kind, q, 24)
        for hit in hits:
            hit["sizes"] = [
                r
                for r in PH_SIZES
                if (
                    forge_assets.ROOT / "polyhaven" / hit["id"] / r / "manifest.json"
                ).is_file()
            ]
        return hits
    except ValueError as e:
        raise VaultError(str(e)) from e
    except OSError as e:
        raise VaultError(f"Poly Haven did not answer ({e})") from e


def ph_thumb(asset_id: str) -> Path:
    if not PH_ID.match(asset_id):
        raise NotFound("No such asset")
    out = data_dir() / "ph-thumbs" / f"{asset_id}.webp"
    if out.is_file():
        return out
    out.parent.mkdir(exist_ok=True)
    url = f"https://cdn.polyhaven.com/asset_img/thumbs/{asset_id}.png?width=256&height=256"
    try:
        raw = forge_assets._http(url)
    except OSError as e:
        raise NotFound(f"No thumbnail ({e})") from e
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.thumbnail((256, 256))
            tmp = out.with_suffix(".tmp")
            im.convert("RGBA").save(tmp, "WEBP", quality=80)
            os.replace(tmp, out)
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        raise NotFound(f"No thumbnail ({e})") from e
    return out


def free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists():
        probe = probe.parent
    return shutil.disk_usage(probe).free


def ph_get(asset_id: str, res: str = "1k") -> dict:
    if not PH_ID.match(str(asset_id)):
        raise VaultError("No such asset")
    if res not in PH_SIZES:
        raise VaultError("Size must be 1k, 2k or 4k")
    if free_bytes(forge_assets.ROOT) < DISK_FLOOR:
        raise VaultError("Less than 2 GB of disk is free, so nothing was downloaded")
    try:
        manifest = forge_assets.get(asset_id, res)
    except (OSError, ValueError, KeyError) as e:
        raise VaultError(f"The download did not finish ({e})") from e
    INDEX.clear()
    return {"id": _item_id(manifest["main"]), "name": manifest.get("name", asset_id)}


# --- sending -------------------------------------------------------------------


def _blender_port() -> int:
    return int(os.environ.get("FORGE_BLENDER_PORT", "9876"))


def _blender_token() -> str:
    path = Path(
        os.environ.get("FORGE_BLENDER_TOKEN")
        or Path.home() / ".local/share/forge/bridges/blender.token"
    )
    try:
        return path.read_text().strip()
    except OSError:
        raise VaultError(
            "Blender is not open with the Forge bridge; open it from Acchan first"
        ) from None


def _blender_code(it: dict) -> str:
    path = repr(it["path"])
    if it["kind"] == "model":
        return f"result = forge.import_asset({path})"
    if it["kind"] == "hdri":
        return f"result = forge.use_hdri({path})"
    return (
        "obj = bpy.context.active_object\n"
        "if obj is None:\n"
        "    raise RuntimeError('Select an object in Blender first')\n"
        f"result = forge.texture(obj.name, {path})"
    )


def send_blender(it: dict, _body: dict) -> dict:
    token = _blender_token()
    request = {"token": token, "code": _blender_code(it), "timeout": 120}
    try:
        with socket.create_connection(("127.0.0.1", _blender_port()), timeout=5) as s:
            s.settimeout(130)
            s.sendall((json.dumps(request) + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
    except OSError:
        raise VaultError(
            "Blender is not open with the Forge bridge; open it from Acchan first"
        ) from None
    try:
        reply = json.loads(buf)
    except ValueError:
        raise VaultError("Blender gave an answer Vault could not read") from None
    if not reply.get("ok"):
        err = str(reply.get("error") or "Blender refused it").strip().splitlines()
        raise VaultError("Blender: " + (err[-1] if err else "refused it"))
    return {"message": f"Sent {it['name']} to Blender", "result": reply.get("result")}


def godot_projects() -> list[dict]:
    out = []
    for root in TARGETS["godot"].get("roots", []):
        base = _expand(os.environ.get("VAULT_GODOT_ROOT") or root)
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if (d / "project.godot").is_file():
                out.append({"name": d.name, "path": str(d)})
    return out


def _free_name(parent: Path, stem: str) -> Path:
    n, dest = 1, parent / stem
    while dest.exists():
        n += 1
        dest = parent / f"{stem}-{n}"
    return dest


def send_godot(it: dict, body: dict) -> dict:
    projects = {p["path"]: p for p in godot_projects()}
    project = str(body.get("project") or "")
    if project not in projects:
        raise VaultError("Pick one of the Godot projects")
    parent = Path(project) / "assets" / "vault"
    parent.mkdir(parents=True, exist_ok=True)
    dest = _free_name(parent, forge_art.slug(it["name"]))
    base = os.path.realpath(it["dir"])
    copied = 0
    dest.mkdir()
    for rel in it["files"]:
        src = os.path.realpath(os.path.join(base, rel))
        if not _under(src, base) or not os.path.isfile(src):
            continue
        target = dest / os.path.relpath(src, base)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied += 1
    where = os.path.relpath(dest, project)
    return {
        "message": f"Copied {copied} file{'s' if copied != 1 else ''} into"
        f" {projects[project]['name']}/{where}",
        "path": str(dest),
    }


def _free_art_id(stem: str) -> str:
    n, art_id = 1, stem
    while os.path.exists(forge_art.pack_path(art_id)) or os.path.exists(
        forge_art.palette_path(art_id)
    ):
        n += 1
        art_id = f"{stem}-{n}"
    return art_id


def send_pixelforge(it: dict, body: dict) -> dict:
    """The picture, made small and given at most `colors` colours, as a new
    pack and palette called vault-<name>; nothing is ever written over."""
    from PIL import Image

    try:
        size = max(8, min(256, int(body.get("size") or 64)))
        colors = max(2, min(48, int(body.get("colors") or 24)))
    except (TypeError, ValueError):
        raise VaultError("Size and colours must be numbers") from None
    try:
        with Image.open(it["path"]) as im:
            im = im.convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        raise VaultError(f"Cannot read that picture: {e}") from e
    if im.width > size or im.height > size:
        im.thumbnail((size, size), Image.Resampling.LANCZOS)
    solid = im.getchannel("A").point([0] * 128 + [255] * 128)
    flat = Image.new("RGB", im.size, (0, 0, 0))
    flat.paste(im, mask=solid)
    q = flat.quantize(
        colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )
    pal = q.getpalette() or []
    keys = forge_art.PALETTE_KEYS
    used: dict[int, str] = {}
    rows = []
    for y in range(q.height):
        row = []
        for x in range(q.width):
            if not solid.getpixel((x, y)):
                row.append(forge_art.TRANSPARENT)
                continue
            idx = q.getpixel((x, y))
            assert isinstance(idx, int)
            if idx not in used:
                used[idx] = keys[len(used)]
            row.append(used[idx])
        rows.append("".join(row))
    if not used:
        raise VaultError("That picture is all see-through")
    with ART_LOCK:
        art_id = _free_art_id("vault-" + forge_art.slug(it["name"])[:40])
        _save_art(it, q, pal, used, rows, art_id)
    return {
        "message": f"Made pack {art_id} ({q.width}x{q.height}, {len(used)} colours)"
        " for PixelForge",
        "pack": art_id,
    }


def _save_art(
    it: dict, q, pal: list, used: dict[int, str], rows: list[str], art_id: str
) -> None:
    palette = {
        "id": art_id,
        "label": f"Vault: {it['name']}",
        "colors": {
            k: "#%02x%02x%02x" % tuple(pal[i * 3 : i * 3 + 3]) for i, k in used.items()
        },
    }
    sprite_name = forge_art.slug(it["name"]).replace("-", "_")[:40] or "sprite"
    pack = {
        "id": art_id,
        "label": f"Vault: {it['name']}",
        "tile": max(q.width, q.height),
        "default_palette": art_id,
        "sprites": {
            sprite_name: {
                "w": q.width,
                "h": q.height,
                "tags": ["vault"],
                "frames": [{"ms": 0, "rows": rows}],
            }
        },
    }
    forge_art.ensure_root()
    forge_art.save_palette(palette)
    forge_art.save_pack(pack)


SENDERS: dict[str, Callable[[dict, dict], dict]] = {
    "blender": send_blender,
    "godot": send_godot,
    "pixelforge": send_pixelforge,
}


def send(item_id: str, target: str, body: dict) -> dict:
    if target not in TARGETS or target not in SENDERS:
        raise VaultError("No such place to send to")
    it = get_item(item_id)
    if it["kind"] not in TARGETS[target]["kinds"]:
        raise VaultError(f"{TARGETS[target]['label']} does not take {it['kind']} items")
    return SENDERS[target](it, body)
