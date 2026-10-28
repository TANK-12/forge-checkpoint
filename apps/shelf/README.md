# Shelf

Read-later for Forge, on port 8486 (`web_app.py`, FastAPI, its own `.venv`
with [trafilatura](https://github.com/adbar/trafilatura), Apache-2.0). Paste
an article's address and Shelf keeps the article itself, its text and
pictures, so it reads the same with no internet and after the page is gone.

- **Saving**: Shelf's backend fetches the page, trafilatura cuts it down to
  the article (title, author, site, date, body), and `shelf_core.clean`
  rebuilds that HTML from an allow-list of tags (`tags` in `shelf.json`). No
  scripts, styles, frames or event handlers survive, links keep only
  `http`, `https` and `mailto`, and pictures are downloaded beside the
  article and served by Shelf. The page also carries a strict
  Content-Security-Policy. Saving the same address twice, or an address
  that redirects to one already kept, opens the one already on the shelf.
- **Public addresses only**: every address a host name resolves to, and
  every redirect, must be on the public internet. Loopback, the home
  network and link-local addresses are refused, so the save box cannot be
  used to poke at the router or other Forge apps.
- **Reading**: unread, all and archived lists; mark read, archive, A− / A+
  text size (remembered); the original address is one click away.
- **Search**: SQLite FTS5 over title, author and text, with the matching
  words marked.
- **Move to bin** sends the article's folder to the desktop trash
  (`gio trash`), so it can be restored from there.
- **Send on**: `send_to` in `shelf.json` lists other apps an article can go
  to. The one entry, "Research in Dossier", asks for a name (the author is
  filled in) and starts a Dossier research job on it
  (`POST http://127.0.0.1:8437/api/research`). Adding another target is one
  entry there.
- **Bookmarklet**: the "Save from Firefox in one click" link at the bottom
  of the list. Dragged to the bookmarks bar, it opens Shelf with the
  current page's address filled in; nothing is saved until Save is pressed.

## Layout

```
web_app.py        routes: /api/save, /api/articles[/<id>], /api/image/<id>/<name>, /api/send, /api/config
shelf_core.py     fetching (public-address guard), extraction, cleaning, pictures, the SQLite shelf, sending on
shelf.json        the registry: data folder, limits, allowed tags, send_to targets
static/           the page
tests/            test_shelf.py (pytest, a fake web), check_ui.py (headless Chrome)
```

Data: `~/.local/share/forge/shelf/` (`SHELF_DATA` overrides it): `shelf.db`
plus `articles/<id>/article.html` and `articles/<id>/images/`.

## Checks

```
.venv/bin/python -m pytest -q tests/test_shelf.py
.venv/bin/python tests/check_ui.py /tmp/shelf-shots
```

`check_ui.py` runs Shelf with a temp data folder against a pretend news
site and a pretend Dossier on 127.0.0.1 (`SHELF_ALLOW_LOCAL=1`, `SHELF_CONFIG`),
so it fetches nothing real and never asks the real Dossier.
