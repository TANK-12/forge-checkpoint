"""Pulling a subject's pictures down so the library works offline.

Every pass already collects picture *references* - they arrive in the same
Wikidata payload as the facts, so they cost nothing extra. This module is the
separate step that turns a reference into a file on the drive, because that is
the part with a real cost: a 640px portrait is around 200KB, and a thousand
subjects is a couple of hundred megabytes.

It is therefore its own queue phase rather than part of a quick pass. Run it
when you want the pictures; the rest of the library works without it.

Nothing here is destructive. A file already on disk is never fetched again, and
a failure leaves the reference intact so the next run can try once more.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import httpx

import dossier
import store

from research.fetcher import USER_AGENT as UA

IMAGE_DIR = "images"
TIMEOUT = 30.0

# What a picture is allowed to be. Anything else is a redirect gone wrong or an
# error page, and writing it under a .jpg would be worse than skipping it.
ALLOWED = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}

# Commons has portraits well over 20MB even at a requested width. Anything that
# large is a mistake for this purpose and is left as a link instead.
MAX_BYTES = 8_000_000


def _safe_name(kind: str, commons_file: str, suffix: str) -> str:
    """A short, stable, filesystem-safe name for one picture.

    Commons filenames contain spaces, brackets, commas and non-ASCII, and the
    library lives on an exfat drive that is unhappy with several of those. The
    hash keeps two different files with similar names apart.
    """
    digest = hashlib.sha1(commons_file.encode("utf-8")).hexdigest()[:10]
    stem = re.sub(r"[^a-zA-Z0-9]+", "-", kind).strip("-").lower() or "image"
    return f"{stem}-{digest}{suffix}"


def fetch_for(slug: str, root: Path | None = None, log=None) -> dict:
    """Download whatever this subject has references for but no file yet."""
    say = log or (lambda _m: None)
    stored = dossier.load(slug, root)
    images = stored.get("images") or []
    if not images:
        return {"slug": slug, "held": 0, "fetched": 0, "failed": 0, "skipped": 0}

    directory = store.subject_dir(slug, root) / IMAGE_DIR
    fetched = failed = skipped = 0

    with httpx.Client(
        headers={"User-Agent": UA}, follow_redirects=True, timeout=TIMEOUT
    ) as client:
        for image in images:
            existing = image.get("stored", "")
            if existing and (store.subject_dir(slug, root) / existing).is_file():
                skipped += 1
                continue
            url = image.get("url", "")
            if not url:
                failed += 1
                continue
            try:
                response = client.get(url)
                response.raise_for_status()
                content_type = (
                    response.headers.get("content-type", "").split(";")[0].strip()
                )
                suffix = ALLOWED.get(content_type)
                if not suffix:
                    say(f"    {image.get('kind')}: not a picture ({content_type})")
                    failed += 1
                    continue
                if len(response.content) > MAX_BYTES:
                    say(
                        f"    {image.get('kind')}: {len(response.content)//1_000_000}MB "
                        "is too big to keep - left as a link"
                    )
                    failed += 1
                    continue
                directory.mkdir(parents=True, exist_ok=True)
                name = _safe_name(
                    image.get("kind", "image"), image.get("commons_file", url), suffix
                )
                # Written beside the target then renamed, like every other write
                # here: a yanked USB mid-write leaves no half a file.
                target = directory / name
                temporary = target.with_suffix(target.suffix + ".tmp")
                temporary.write_bytes(response.content)
                temporary.replace(target)
                image["stored"] = f"{IMAGE_DIR}/{name}"
                image["bytes"] = len(response.content)
                fetched += 1
                say(f"    {image.get('kind')}: {len(response.content)//1024}KB")
            except Exception as e:
                failed += 1
                say(f"    {image.get('kind')} failed: {type(e).__name__}")

    if fetched:
        store.write_json(
            store.subject_dir(slug, root) / dossier.FILES["images"], images
        )
    return {
        "slug": slug,
        "held": len(images),
        "fetched": fetched,
        "failed": failed,
        "skipped": skipped,
    }
