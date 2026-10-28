# Typeset

Writes documents in Typst (a modern markup for typesetting, like LaTeX but
quick and readable) with a live preview beside the text, and exports a
PDF. Start from a template: a blank page, a report, a CV or a letter.

Port 8491, section Create. Settings live in `typeset.json`
(`TYPESET_CONFIG` points at another one).

## Where things are

- Each document is a folder in `~/Documents/Typeset` (`TYPESET_DOCS_DIR`
  moves it) holding `main.typ`, any pictures or data files added to it,
  and `<name>.pdf` once exported. They are ordinary files: edit them in
  any editor, or run `typst` on them yourself.
- The data folder (`TYPESET_DATA_DIR`, default
  `~/.local/share/forge/typeset`) holds the Typst program, the preview
  pages and Typst's package cache.
- Typst 0.15.1 (the official musl build, about 17 MB) is fetched once by
  `shared/forge_fetch.py` into `<data>/bin`, pinned by sha256 in
  `typeset.json`. `TYPESET_TYPST` points at another typst instead.

## Using it

- Type on the left; the preview follows about half a second after you
  stop (Ctrl+S compiles at once). Tab inserts two spaces.
- A mistake keeps the last good preview and lists the problem under the
  text with its line; click it to jump there.
- Add a file puts a picture (png, jpg, gif, svg, webp) or a data file
  (bib, csv, json, yaml, toml, typ, txt) beside the document, up to 50 MB.
  Click its name under the text to insert it.
- Export PDF writes `<name>.pdf` into the document's folder; a failed
  export keeps the old PDF.
- Rename renames the folder and the PDF; Move to trash uses `gio trash`.
- Templates are a registry: `templates/templates.json` plus one `.typ` file
  each. Adding one is one file and one entry.

## Safety

- Typst runs with `--root` set to the document's folder, so a document can
  read nothing outside it. Typst still follows a symlink out of the
  folder (checked with 0.15.1), so a document folder holding any link is
  refused until the link is replaced by a copy (rename and trash still
  work). Each compile has a 30 s limit (it stops everything Typst started)
  and a 4 GB memory cap set by `prlimit`, and at most two run at once.
- Saving is apart from compiling: an edit is saved about 300 ms after the
  last key and never waits behind a compile.
- Preview pages are served as SVG with a Content-Security-Policy that lets
  them run nothing.
- The backend accepts only its own pages (`shared/forge_guard.py`).
- `#import "@preview/..."` packages are fetched from the internet by Typst
  itself into `<data>/packages` the first time a document uses one.

## Checks

    .venv/bin/python -m pytest -q tests
    ~/Forge/apps/clipboard/.venv/bin/python tests/check_ui.py /tmp/shots

The unit tests need the real Typst; they look for it in
`~/.cache/forge-checks/typeset-data/bin` and skip if it is not there
(`check_ui.py` fetches it there the first time).
