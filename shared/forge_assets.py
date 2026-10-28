"""On-demand free assets for Forge: search and download from Poly Haven (CC0).

Downloads land in ~/Forge/shared/assets/polyhaven/<id>/<res>/ with a
manifest.json (source, licence, authors, kind, files). An asset is never
downloaded twice. Nothing is fetched in bulk: the disk is small.

Kinds: "hdris" (360-degree sky photos that light a scene), "textures"
(photo-scanned PBR material maps) and "models" (scanned glTF models).
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

API = "https://api.polyhaven.com"
UA = "ForgeAssets/1.0 (local desktop app)"
ROOT = Path(
    os.environ.get("FORGE_ASSETS_DIR", Path(__file__).resolve().parent / "assets")
)
KINDS = ("hdris", "textures", "models")
TEXTURE_MAPS = ("Diffuse", "nor_gl", "Rough", "AO", "Displacement", "Metal", "arm")

Fetch = Callable[[str], bytes]


def _http(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _json(fetch: Fetch, path: str) -> dict:
    return json.loads(fetch(API + path))


def search(
    kind: str, query: str = "", limit: int = 12, fetch: Fetch = _http
) -> list[dict]:
    """Best matches for query (all words must hit name, tags or categories),
    most downloaded first."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    data = _json(fetch, "/assets?" + urllib.parse.urlencode({"t": kind}))
    words = query.lower().split()
    hits = []
    for aid, a in data.items():
        text = " ".join(
            [aid, a.get("name", "")] + a.get("tags", []) + a.get("categories", [])
        ).lower()
        if all(w in text for w in words):
            hits.append(
                {
                    "id": aid,
                    "name": a.get("name", aid),
                    "tags": a.get("tags", [])[:6],
                    "downloads": a.get("download_count", 0),
                    "cached": bool(cached(aid)),
                }
            )
    hits.sort(key=lambda h: -h["downloads"])
    return hits[:limit]


def _here() -> None:
    """Plain words instead of missing files when the library is kept on an
    external drive (the Store's Storage tab) that is not plugged in."""
    try:
        import forge_external  # pyright: ignore[reportMissingImports]
    except ImportError:
        return
    forge_external.require(ROOT)


def cached(aid: str, res: str | None = None) -> dict | None:
    _here()
    base = ROOT / "polyhaven" / aid
    dirs = [base / res] if res else sorted(base.glob("*")) if base.exists() else []
    for d in dirs:
        m = d / "manifest.json"
        if m.exists():
            return json.loads(m.read_text())
    return None


def _pick(files: dict, res: str) -> tuple[str, dict[str, dict]]:
    """Decide kind and the {relative path: file entry} to download."""

    def at(entry: dict) -> dict:
        if res in entry:
            return entry[res]
        avail = sorted(entry, key=lambda r: int(r.rstrip("k") or 0))
        raise ValueError(f"resolution {res} not offered; try {', '.join(avail)}")

    if "hdri" in files:
        f = at(files["hdri"])["hdr"]
        return "hdri", {Path(f["url"]).name: f}
    if "gltf" in files:
        g = at(files["gltf"])["gltf"]
        out = {Path(g["url"]).name: g}
        out.update(g.get("include", {}))
        return "model", out
    out = {}
    for m in TEXTURE_MAPS:
        if m in files:
            f = at(files[m])["jpg"]
            out[Path(f["url"]).name] = f
    if not out:
        raise ValueError("asset has no downloadable hdri, gltf or texture maps")
    return "texture", out


def get(aid: str, res: str = "1k", fetch: Fetch = _http) -> dict:
    """Download one asset (or return the cached copy). Returns its manifest,
    whose "main" is the file to load: the .hdr, the .gltf, or the diffuse map."""
    _here()
    hit = cached(aid, res)
    if hit:
        return hit
    files = _json(fetch, f"/files/{urllib.parse.quote(aid)}")
    info = _json(fetch, f"/info/{urllib.parse.quote(aid)}")
    kind, todo = _pick(files, res)
    dest = ROOT / "polyhaven" / aid / res
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for rel, f in todo.items():
        p = (dest / rel).resolve()
        if dest.resolve() not in p.parents:
            raise ValueError(f"unsafe path in asset: {rel}")
        data = fetch(f["url"])
        if f.get("md5") and hashlib.md5(data).hexdigest() != f["md5"]:
            raise ValueError(f"checksum mismatch for {rel}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        written.append(rel)
    main = next(
        (r for r in written if r.endswith((".hdr", ".gltf"))),
        next((r for r in written if "diff" in r.lower()), written[0]),
    )
    manifest = {
        "id": aid,
        "name": info.get("name", aid),
        "kind": kind,
        "res": res,
        "source": f"https://polyhaven.com/a/{aid}",
        "license": "CC0",
        "authors": sorted(info.get("authors", {})),
        "dir": str(dest),
        "main": str(dest / main),
        "files": written,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def local() -> list[dict]:
    """Every downloaded asset's manifest."""
    _here()
    return [
        json.loads(m.read_text())
        for m in sorted((ROOT / "polyhaven").glob("*/*/manifest.json"))
    ]
