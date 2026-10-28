# Vault

One browser for the assets already on this laptop: 3D models, HDRI skies,
material textures, images and sprites, and sounds, plus a Poly Haven tab
for free CC0 assets. Anything can be sent on to Blender, Godot or
PixelForge. Forge-built, port 8494, section Create.

## What it does

- **Looks in folders.** `sources.json` lists the folders always looked in
  (Forge assets in `shared/assets`, `~/Downloads`, `~/Music/Loops`); the
  page's Add box adds more, kept in `<data>/folders.json`. Forgetting a
  folder only stops Vault looking; the folder is never touched. Hidden
  folders, `node_modules`, `.venv` and `__pycache__` are skipped, at most 6
  folders deep, 20,000 items and 200,000 files a folder; whole-system
  folders (`/home`, `/usr`, `/proc`...) cannot be added. A file that links
  out of its folder, or whose name is not UTF-8, is not shown, and only an
  item's own files are ever served.
- **Knows the kinds.** `kinds.json` maps file endings to kinds. A folder
  with a `manifest.json` from `shared/forge_assets.py` (a Poly Haven
  download) is one item with its licence and authors. A colour map plus
  at least one other map (normal, roughness...) of the same material (the
  name without the map word and size: `rock_diff_2k`, `rock_nor_gl_2k.exr`)
  is one texture item, so a folder of three materials gives three. A `.gltf` carries the buffers and pictures it points at.
- **Shows them.** Pictures get a thumbnail (Pillow, cached in
  `<data>/thumbs`); `.gltf`/`.glb` models turn in a three.js preview and
  `.hdr` skies can be looked around (vendored three.js from
  `shared/vendor/three`); sounds play. Other model formats (.fbx, .obj,
  .blend, .stl, .vrm) and `.exr` skies are listed without a preview.
- **Poly Haven.** Search models, skies or textures; Download fetches one
  asset at 1k, 2k or 4k through `shared/forge_assets.py` into Forge assets,
  once, and refuses when under 2 GB of disk is free. Thumbnails come through
  Vault's own server, so the page itself never talks to the internet.
- **Send to** (`send_targets.json`; each id has a function in
  `vault_core.SENDERS`):
  - **Blender**: over the Forge Blender bridge (127.0.0.1:9876 and the token
    in `~/.local/share/forge/bridges/blender.token`). Models go through
    `forge.import_asset`, skies `forge.use_hdri`, textures `forge.texture`
    on the selected object. Blender has to be open with the bridge (Acchan's
    blender_launch).
  - **Godot**: copies the item's files into `<project>/assets/vault/<name>/`
    of a project (a folder with `project.godot`) under `~/Games`; a second
    copy becomes `<name>-2`, never over the first.
  - **PixelForge**: the picture shrunk to 16 to 256 px and cut to 8 to 48
    colours, as a new pack and palette `vault-<name>` in the Forge art
    library (`~/ForgeArtData`, `shared/forge_art.py`); see-through pixels
    stay see-through; never written over an existing pack.

## Running and checking

    .venv/bin/python -m pytest -q tests/          # 19 unit tests
    node --test tests/logic.test.mjs              # page helpers
    .venv/bin/python tests/check_ui.py [SHOTS]    # headless Chrome, real clicks

The browser check builds a scratch asset folder (`tests/fixture.py`), a
scratch Godot project, a scratch art library and a stand-in Blender bridge,
so nothing real is read or written; only its Poly Haven search goes out to
the internet, through Vault's server.

Environment overrides (used by the tests): `VAULT_DATA_DIR`,
`VAULT_SOURCES`, `VAULT_GODOT_ROOT`, `FORGE_ART_DIR`, `FORGE_BLENDER_PORT`,
`FORGE_BLENDER_TOKEN`.
