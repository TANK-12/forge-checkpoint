"""Documents with pandoc (fetched on first use, pinned in convert.json)."""

from __future__ import annotations

from pathlib import Path

CONVERTER = {
    "id": "documents",
    "label": "Documents",
    "order": 3,
    "from": [
        "md",
        "markdown",
        "txt",
        "docx",
        "odt",
        "html",
        "htm",
        "epub",
        "rst",
        "tex",
        "org",
        "rtf",
        "ipynb",
    ],
    "to": ["docx", "odt", "html", "epub", "md", "txt", "rst"],
    "needs": "pandoc",
    "note": "PDF needs a typesetter; that is Typeset's job. A document may not"
    " read other files, so pictures it links to stay links.",
}

READS = {
    "md": "markdown",
    "markdown": "markdown",
    "txt": "markdown",
    "docx": "docx",
    "odt": "odt",
    "html": "html",
    "htm": "html",
    "epub": "epub",
    "rst": "rst",
    "tex": "latex",
    "org": "org",
    "rtf": "rtf",
    "ipynb": "ipynb",
}
WRITES = {
    "docx": "docx",
    "odt": "odt",
    "html": "html",
    "epub": "epub",
    "md": "markdown",
    "txt": "plain",
    "rst": "rst",
}


def convert(src: Path, dst: Path, to: str, opts: dict, ctx) -> None:
    pandoc = ctx.tool("pandoc")
    ext = src.suffix.lower().lstrip(".")
    argv = [pandoc, "--from", READS[ext], "--to", WRITES[to], "--output", dst]
    if to in ("html", "epub", "docx", "odt"):
        argv.append("--standalone")
    if to == "html":
        argv += ["--embed-resources", "--metadata", f"pagetitle={src.stem}"]
    # Always: without it an include line (rst, tex, org) copies any file
    # this account can read into the output, and html fetches web images.
    argv.append("--sandbox")
    ctx.run([*argv, src])
