# Convert

Re-saves files in another format: images, sound and documents. Drop files
on the page (or type a path to one already on this computer), pick what
each should become, press Convert. Each file is converted as its own job,
with progress and a Stop button, and saved to `~/Downloads/Converted`
under a name that never overwrites an existing file (`song.mp3`, then
`song (2).mp3`).

Two files convert at a time; the rest wait their turn.

Port 8490, section System. Settings live in `convert.json` (`CONVERT_CONFIG`
points at another one); `CONVERT_OUT_DIR` moves the output folder and
`CONVERT_DATA_DIR` the data folder (default `~/.local/share/forge/convert`).

## What it converts

| Kind | Reads | Writes | Uses |
| --- | --- | --- | --- |
| Images | png, jpg, webp, avif, gif, bmp, tiff, ico, tga, ppm and more | png, jpg, webp, avif, gif, bmp, tiff, ico, pdf | Pillow (in the venv) |
| Audio | mp3, flac, wav, ogg, opus, m4a and more, plus the sound of a video | mp3, flac, wav, ogg, opus, m4a | ffmpeg (the system one) |
| Documents | md, docx, odt, html, epub, rst, txt, tex, org and more | docx, odt, html, epub, md, txt, rst | pandoc 3.12.1, fetched once |
| Video | mkv, mp4, webm and more | (handed to MediaForge's Video Enhancer) | MediaForge |

- Images: quality for jpg, webp and avif; a longest side in pixels to
  shrink to. Transparent images get a white background in jpg, bmp and
  pdf; animated gif, webp and avif keep their frames; photos are turned
  upright from their EXIF orientation.
- Audio: high, medium or small quality. Tags (title, artist and so on) are
  carried over.
- Documents: PDF is not offered here; that needs a typesetter (Typeset's
  job). HTML out is one self-contained file. pandoc runs sandboxed: a
  document cannot read any other file, so linked pictures stay links.
- Video: the button opens MediaForge's Video Enhancer with the file in its
  Files box (only when Convert is open inside Forge, and only for a file
  added by path; a dropped file has no path to hand over). The Audio
  choices are still there for "only its sound".

## How it works

| File | What it does |
| --- | --- |
| `converters/*.py` | Registry: one file per kind. `CONVERTER` says what it reads, writes and which options it has; `convert(src, dst, to, opts, ctx)` does it. A new kind is one new file here. |
| `convert_core.py` | Loads and checks the registry, works out choices for a file name, checks options, the free-disk check, safe output names, and runs a converter into a hidden temp file that is renamed only when whole. |
| `convert.json` | The output folder, the free-space margin (`keep_free_gb`, 2 GB) and the pandoc pin (URL, sha256, size). |
| `web_app.py` | FastAPI: `/api/state`, `/api/choices`, `/api/convert/file` (the dropped file streams to a spool folder, removed after the job), `/api/convert/path`, `/api/recent`, `/api/out/<name>`, plus the shared job routes. |
| `static/` | The page. |

pandoc is fetched through `shared/forge_fetch.py` the first time a
document is converted (35 MB download, 165 MB program, in
`<data>/bin`), and refused if its sha256 differs from the pin.
`CONVERT_PANDOC` points at another pandoc instead; ffmpeg and ffprobe
are the ones on the PATH.

## Checks

    .venv/bin/python -m pytest -q tests                     # 31 tests
    ~/Forge/apps/clipboard/.venv/bin/python tests/check_ui.py /tmp/shots   # headless Chrome
