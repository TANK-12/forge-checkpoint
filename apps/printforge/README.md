# PrintForge

Look over 3D-print files (STL) before slicing them. PrintForge lists every STL under
the chosen folders, shows it on a print bed in a 3D view, and checks what a slicer
cares about. It never changes the files.

## Use
- Pick a print on the left (grouped by project and folder; a folder named like `1-35`
  shows as scale 1:35). Search box on top.
- Drag to turn, right-drag or Shift-drag to pan, scroll to zoom, double-click (or `f`)
  to fit. Buttons: 3/4, Front, Side, Back, Top, Turntable (`r`), Wireframe (`w`), bed
  class and Bed on/off. Front is +Y in the file, which is how the Juggernaut faces.
- The right panel shows size, scale, triangles, volume (ml of resin if solid), surface,
  **Watertight** (every edge shared by exactly two triangles facing the right way;
  "almost" means parts touch along a line, which slicers usually cope with), **Pieces**
  (separate shells), an inside-out warning, and which bed classes it fits standing or
  laid over. The bed outline turns red when the print is too big for it.
- **Overhangs**: the check lists how much of the print faces down steeper than the
  support angle (45 degrees unless changed; faces resting on the bed do not count).
  The Overhangs button (`o`) colours those faces red (inside-out prints too); Below
  looks from underneath, where they face.
- **New exports**: export the open print again (from Blender, say) and come back to
  PrintForge: it notices the new size and time and loads the new version by itself.
  A click on the open print does the same, downloads nothing when the file is
  unchanged, and retries a check that failed.
- **Build report**: when a JSON file in a `reports` folder beside or above the print
  names it (as the print pipeline's `print/reports/<milestone>_build.json` does),
  its milestone and plain values show under the bed list, with a note when the STL
  is newer than the report.
- Advanced mode adds light brightness, the support angle, a custom bed (slider plus
  number), the folder list, and Save picture.

## Run and test
- In Forge: it is discovered from `forge_app.json` (port 8462, Create section).
- Standalone: `cd ~/Forge/apps/printforge && FORGE_SHARED_DIR=~/Forge/shared .venv/bin/python -m uvicorn web_app:app --port 8462`
- Tests: `.venv/bin/python -m pytest -q tests`
- Headless UI check (starts Chrome; not part of pytest):
  `.venv/bin/python tests/check_ui.py [out_dir]`, with `PRINTFORGE_CHECK_PORT=N` to
  run its scratch server on a fixed port.

## Files
- `stl.py`: binary/ASCII STL reading, `analyse` (numpy, including `overhang_areas`),
  `fits`.
- `library.py`: settings, folder scan, path rule (only `.stl` inside a configured
  folder is ever served), analysis cache (versioned by `CACHE_VERSION`, safe when two
  checks finish at once), `report_for` (build reports).
- `web_app.py`: FastAPI routes (`/api/settings`, `/api/library`, `/api/info`, `/api/stat`
  (size and time of one print), `/api/stl`, `/api/open-folder`).
- `static/`: `index.html`, `app.js` (page), `viewer.js` (three.js view and STL parser).
  three.js r186 comes from `~/Forge/shared/vendor/three/` (a copy of Cosmos's, MIT).
- Data: `~/.config/forge-printforge/settings.json`, `~/.cache/forge-printforge/info.json`.
