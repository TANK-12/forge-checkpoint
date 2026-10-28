"""2.5D wallpapers (S23): the picture split into a subject and a sky, once.

the owner (2026-09-27): "separate things from the wallpaper like people to make
2.5d or 3d effects". Once per wallpaper, on the CPU at low priority, this
makes these files beside the wallpaper's cached copy
(~/.cache/forge/wallpaper/<key>.jpg, shared/forge_theme.render):

    <key>-fg.webp     the subject with see-through everywhere else
    <key>-bg.jpg      the picture with the subject filled in, so nothing is
                      seen twice when the two layers move apart
    <key>-depth.png   how near each part is, split into the near things and
                      the scene behind them (split_depth), for the 3D look
    <key>-plate.jpg   the picture with every near thing filled in: the scene
                      behind them, seen where they slide aside in 3D

The hub stacks them: the background, the particles, then the subject, and
moves the subject further than the background as the pointer moves (and on
the beat in Alt+V), so the particles fly between the character and the sky.

What counts as the subject: the anime cut-out model's mask when it finds a
character of a sensible size, else the nearest part of the depth map (a
tree, a ledge), else nothing (the wallpaper stays flat).

Nothing is downloaded or installed. The models are the ones PanelForge
already keeps (~/PanelForgeData/models: skytnt/anime-seg isnetis.onnx, the
model rembg ships as isnet-anime, and Depth Anything V2 from
onnx-community), and the work runs in whichever Forge app's .venv already
has onnxruntime, numpy and Pillow (find_python), so no copies are made.

    python3 shared/forge_layers.py make <image> <key> <folder>
    python3 shared/forge_layers.py adopt <new folder> <folder> <old copies>

adopt moves in layers made elsewhere (task 275 made every wallpaper's again
in ~/.cache/forge/wallpaper-layers-v2): the files they replace are moved to
<old copies> first, never deleted.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

FORGE = Path(__file__).resolve().parents[1]
MODELS = Path(
    os.environ.get("FORGE_LAYER_MODELS", Path.home() / "PanelForgeData" / "models")
)
# nearest first: the small depth models are quicker, the base one sharper
SEG_MODELS = ("scene-seg/isnetis.onnx",)
DEPTH_MODELS = (
    "scene-depth_small/model.onnx",
    "scene-depth/model_int8.onnx",
    "scene-depth_base/model.onnx",
)
NEEDS = ("onnxruntime", "numpy", "PIL")
# a character this share of the picture is a subject; smaller is a speck,
# larger is most likely the model mistaking the scene for a person
SUBJECT_MIN, SUBJECT_MAX = 0.015, 0.6
# with no character, the nearest this share of the depth map is the subject
NEAR_SHARE = 0.18
THREADS = 2  # onnxruntime threads: the laptop stays usable while it works
# depth (task 275): the model sees the picture at its own shape, short side
# DEPTH_SIDE; the map is saved at most DEPTH_SAVE wide (the hub draws the 3D
# at most 1920 across)
DEPTH_SIDE, DEPTH_LONG, DEPTH_SAVE = 518, 1036, 1920
# the near things (task 327, split_depth): anything narrower than NARROW or
# WIDE of the picture's width that stands out of the scene around it by more
# than STANDS (a pole, a wire, an arm; a person, a car), with its depth
# spread BAND of the width into the scene so the hub's ray never steps over
# a thin wire. The scene behind is smoothed over SMOOTH of the width and never
# climbs more than CLIMB depth per picture width, so bending it never folds.
NARROW, WIDE, BAND, SMOOTH, CLIMB = 1 / 30, 1 / 8, 1 / 240, 1 / 100, 6.0
STANDS = (0.04, 0.12)  # at the NARROW and the WIDE scale
# the layer recipe; layers made by an older one are made again
METHOD = 3


def layer_paths(key: str, folder: Path) -> dict[str, Path]:
    return {
        "fg": folder / f"{key}-fg.webp",
        "bg": folder / f"{key}-bg.jpg",
        "depth": folder / f"{key}-depth.png",
        "plate": folder / f"{key}-plate.jpg",
        "info": folder / f"{key}-layers.json",
        "lock": folder / f"{key}-layers.lock",
    }


def ready(key: str, folder: Path) -> dict | None:
    """The finished layers' info ({"subject": "character" | "near" | "none"}),
    or None while they are not made (or making them failed)."""
    p = layer_paths(key, folder)
    try:
        info = json.loads(p["info"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if info.get("subject") == "none":
        return info
    return info if p["fg"].is_file() and p["bg"].is_file() else None


def find_models(root: Path = MODELS) -> dict[str, Path] | None:
    seg = next((root / m for m in SEG_MODELS if (root / m).is_file()), None)
    depth = next((root / m for m in DEPTH_MODELS if (root / m).is_file()), None)
    return {"seg": seg, "depth": depth} if seg and depth else None


def find_python(apps: Path = FORGE / "apps") -> str | None:
    """A Forge app's own Python that already has onnxruntime, numpy and
    Pillow, so nothing is installed twice."""
    for py in sorted(apps.glob("*/.venv/bin/python")):
        libs = list((py.parent.parent / "lib").glob("python3*/site-packages"))
        if libs and all((libs[0] / name).is_dir() for name in NEEDS):
            return str(py)
    return None


def start(
    image: Path, key: str, folder: Path, popen: Callable[..., Any] = subprocess.Popen
) -> bool:
    """Make the layers in the background unless this METHOD made them (or
    failed to: then the picture stays flat, never retried in a loop) or they
    are being made. Layers by an older recipe are made again over the old
    ones, which serve until then, and only once: a remake that fails or is
    stopped leaves them as they are. Returns whether a job started."""
    p = layer_paths(key, folder)
    if not Path(image).is_file():
        return False
    try:
        info = json.loads(p["info"].read_text(encoding="utf-8"))
        if not isinstance(info, dict):
            info = {}
    except (OSError, ValueError):
        info = {}
    if METHOD in (info.get("method"), info.get("tried")):
        return False
    try:  # a lock younger than 10 minutes: a job is running
        if time.time() - p["lock"].stat().st_mtime < 600:
            return False
    except OSError:
        pass
    python, models = find_python(), find_models()
    if not python or not models:
        return False
    folder.mkdir(parents=True, exist_ok=True)
    if info:  # tried once by this recipe, whatever becomes of the job
        p["info"].write_text(json.dumps(dict(info, tried=METHOD)))
    p["lock"].write_text(str(time.time()))
    with open(folder / f"{key}-layers.log", "w") as log:
        popen(
            [
                "nice",
                "-n",
                "19",
                python,
                __file__,
                "make",
                str(image),
                key,
                str(folder),
            ],
            stdout=subprocess.DEVNULL,
            stderr=log,
            start_new_session=True,
        )
    return True


# ----------------------------------------------------------------------------
# the work itself, in the Python find_python() picked


def pick_subject(seg, depth):  # arrays 0..1, same shape
    """The subject mask and what it is: the character when the cut-out
    found one of a sensible size, else the nearest part of the scene."""
    import numpy as np

    share = float((seg > 0.5).mean())
    if SUBJECT_MIN <= share <= SUBJECT_MAX:
        return seg, "character"
    near = float(np.quantile(depth, 1 - NEAR_SHARE))
    far = float(np.quantile(depth, 0.5))
    if near - far < 0.15:  # a flat scene: nothing stands out
        return np.zeros_like(depth), "none"
    soft = np.clip((depth - near) / 0.08 + 0.5, 0, 1)
    return soft, "near"


def _run_seg(session, img):
    import numpy as np

    w, h = img.size
    side = max(w, h)
    sq = np.zeros((side, side, 3), np.float32)
    sq[:h, :w] = np.asarray(img, np.float32) / 255
    from PIL import Image

    x = np.asarray(
        Image.fromarray((sq * 255).astype(np.uint8)).resize((1024, 1024)), np.float32
    )
    x = (x / 255).transpose(2, 0, 1)[None]
    m = session.run(None, {session.get_inputs()[0].name: x})[0][0][0]
    m = Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8)).resize((side, side))
    return np.asarray(m, np.float32)[:h, :w] / 255


def _depth_size(w: int, h: int) -> tuple[int, int]:
    """The depth model's input size: the picture's own shape (a 16:9 picture
    squashed into a square lost most of its width, task 275), the short side
    DEPTH_SIDE, both sides whole patches of 14, the long side capped."""
    k = DEPTH_SIDE / min(w, h)
    if max(w, h) * k > DEPTH_LONG:
        k = DEPTH_LONG / max(w, h)
    return (max(14, round(w * k / 14) * 14), max(14, round(h * k / 14) * 14))


def _run_depth(session, img):
    """The model's depth at its own size, 0..1 (light = near), the furthest
    and nearest half a percent clipped so one bright speck does not squash
    everything else into the dark."""
    import numpy as np
    from PIL import Image

    x = np.asarray(img.resize(_depth_size(*img.size), Image.Resampling.BICUBIC))
    x = (x.astype(np.float32) / 255 - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    d = session.run(None, {session.get_inputs()[0].name: x})[0][0]
    lo, hi = (float(v) for v in np.quantile(d, [0.005, 0.995]))
    return np.clip((d - lo) / max(1e-6, hi - lo), 0, 1).astype(np.float32)


def refine_depth(img, depth):
    """The depth map at the picture's shape (at most DEPTH_SAVE wide).
    Bilinear, not bicubic: bicubic overshoots at an edge. Task 275 also grew
    near edges outward; split_depth's BAND does that job now without moving
    the edge itself (grown, a rim of sky slid along with every pole)."""
    import numpy as np
    from PIL import Image, ImageFilter

    w, h = img.size
    k = min(1.0, DEPTH_SAVE / w)
    size = (max(1, round(w * k)), max(1, round(h * k)))
    up = Image.fromarray((np.clip(depth, 0, 1) * 255 + 0.5).astype(np.uint8))
    up = up.resize(size, Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(1))
    return np.asarray(up, np.float32) / 255


def _slide(a, r: int, fn):
    """A square min (fn=np.min) or max filter of radius r, in two passes."""
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view

    if r < 1:
        return a
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        wide = np.pad(a, pad, mode="edge")
        a = fn(sliding_window_view(wide, 2 * r + 1, axis=axis), axis=-1)
    return a


def _blur(a, r: int, axes=(0, 1)):
    """A soft blur of a float map (or picture) along axes: three box blurs
    of radius r (about a Gaussian of r), edges held."""
    import numpy as np

    if r < 1:
        return a
    for _ in range(3):
        for axis in axes:
            pad = [(0, 0)] * a.ndim
            pad[axis] = (r + 1, r)
            c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
            n = a.shape[axis]
            hi = np.take(c, range(2 * r + 1, 2 * r + 1 + n), axis=axis)
            lo = np.take(c, range(n), axis=axis)
            a = ((hi - lo) / (2 * r + 1)).astype(np.float32)
    return a


def _climb_at_most(a, step: float):
    """The map changed as little as it takes to climb at most step per
    pixel: the mean of the lowest such map above it and the highest below."""
    import numpy as np

    up, down = a.copy(), a.copy()
    for m in (up, down):
        for t in (m, m.T):
            for rows in (range(1, t.shape[0]), range(t.shape[0] - 2, -1, -1)):
                for i in rows:
                    near = t[i - 1] if rows.step == 1 else t[i + 1]
                    if m is up:
                        np.maximum(t[i], near - step, out=t[i])
                    else:
                        np.minimum(t[i], near + step, out=t[i])
    return (up + down) / 2


def _stands_out(depth, r: int, stands: float):
    """How much each pixel is a near thing narrower than 2r: its height above
    the scene (the depth opened at r) against the highest such height close
    by, so the edge sits halfway up the depth's own edge, not at its foot."""
    import numpy as np

    top = depth - _slide(_slide(depth, r, np.min), r, np.max)
    peak = _slide(top, max(1, r // 8), np.max)
    return _edge(top, peak, stands)


def _edge(top, peak, stands: float):
    """A near thing's alpha: crisp halfway up its depth edge, and all or
    nothing by its height (a half-seen thing showed the plate through it)."""
    import numpy as np

    edge = np.clip((top / np.maximum(peak, 1e-3) - 0.4) / 0.2, 0, 1)
    return edge * np.clip((peak - stands) / (0.25 * stands), 0, 1)


def _fill_map(a, hole, r: int):
    """A float map with the hole filled from around it (normalised blur,
    widened until every part is reached)."""
    import numpy as np

    keep = 1 - hole
    out = a.copy()
    todo = hole > 0.02
    while todo.any() and r < max(a.shape):
        kb = _blur(keep, r)
        fill = _blur(a * keep, r) / np.maximum(kb, 1e-4)
        got = todo & (kb > 0.05)
        out[got] = fill[got]
        todo &= ~got
        r *= 2
    return a * (1 - hole) + out * hole


def split_depth(depth, subject=None):
    """The depth map (H x W, 0..1, light = near) as the two layers the hub's
    3D drawing uses (shared/forge_depth.js), and the hole: (rgb, hole).

    Task 327: bending one depth map tore and streaked every edge, because
    where a near thing slides it uncovers scene that is not in the picture.
    So the near things are a layer of their own, drawn over the scene behind
    them, which is filled in under them (the plate) and bends smoothly:
      R  the near things' depth, spread BAND into the scene around them
         (0 elsewhere): what the ray looks for
      G  the scene behind them: the depth with them filled in, smoothed,
         climbing at most CLIMB per picture width
      B  how much of each pixel is a near thing (the near layer's alpha)
    hole (0..1) is where the plate is filled in. subject is the cut-out's
    mask, a near thing too whatever its size."""
    import numpy as np
    from PIL import Image

    h, w = depth.shape
    alpha = _stands_out(depth, max(2, round(w * NARROW)), STANDS[0])
    # the wide scale on a quarter-size map, its opened scene brought back up
    k = max(1, w // 480)
    small = Image.fromarray(depth).resize(
        (max(1, w // k), max(1, h // k)), Image.Resampling.BOX
    )
    sd = np.asarray(small, np.float32)
    r = max(2, round(sd.shape[1] * WIDE))
    opened = Image.fromarray(_slide(_slide(sd, r, np.min), r, np.max))
    scene = np.asarray(opened.resize((w, h), Image.Resampling.BILINEAR), np.float32)
    top = np.clip(depth - scene, 0, None)
    peak = _slide(top, max(1, round(w * BAND)) * 2, np.max)
    alpha = np.maximum(alpha, _edge(top, peak, STANDS[1]))
    if subject is not None:
        alpha = np.maximum(alpha, np.clip(subject, 0, 1))
    band = max(1, round(w * BAND))
    core = alpha > 0.3
    # each near thing at its own nearest depth up to its rim: the depth
    # model's soft edge would leave a dip there, a wall the ray streaks on
    front = _slide(np.where(core, depth, 0), band + band // 2, np.max)
    hole = _slide((alpha > 0.02).astype(np.float32), max(1, band // 2), np.max)
    # the scene behind, worked out on the quarter-size map: it is smooth
    hs = np.asarray(
        Image.fromarray(hole).resize(small.size, Image.Resampling.BOX), np.float32
    )
    hs = np.clip(hs * 2, 0, 1)
    back = _fill_map(sd, hs, max(2, sd.shape[1] // 160))
    back = _blur(back, max(1, round(sd.shape[1] * SMOOTH)))
    back = _climb_at_most(back, CLIMB / sd.shape[1])
    back = np.asarray(
        Image.fromarray(back.astype(np.float32)).resize(
            (w, h), Image.Resampling.BILINEAR
        ),
        np.float32,
    )
    rgb = np.stack([front, back, alpha], axis=-1)
    return (np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8), hole


def _fill(img, mask, radius: int):
    """The picture with the masked part filled from around it: a blur that
    only counts the unmasked pixels (normalised convolution), widened until
    every hole is covered. Along the rows first: a near thing slides
    sideways, so the gap it leaves shows the rows beside it carried on (a 2D
    blur pulled the sky down into it as a pale smear, task 327); rows with
    no scene in them at all from the 2D blur. Softened down the columns
    after, so the carried rows do not show as streaks."""
    import numpy as np
    from PIL import Image

    a = np.asarray(img, np.float32)
    keep = (1 - mask)[..., None]
    out = a.copy()
    todo = mask > 0.02
    for axes in ((1,), (0, 1)):
        r = radius
        while todo.any() and r < max(img.size):
            kb = _blur(keep, r, axes)
            fill = _blur(a * keep, r, axes) / np.maximum(kb, 1e-4)
            got = todo & (kb[..., 0] > 0.05)
            out[got] = fill[got]
            todo &= ~got
            r *= 2
    out = _blur(out, max(1, img.size[0] // 512), (0,))
    m = mask[..., None]
    return Image.fromarray(np.clip(a * (1 - m) + out * m, 0, 255).astype(np.uint8))


def save_depth(img, depth, cut, p: dict[str, Path]) -> None:
    """The 3D drawing's two layers (split_depth) and the plate: the picture
    with the near things filled in, at the picture's own size."""
    import numpy as np
    from PIL import Image

    size = (depth.shape[1], depth.shape[0])
    if cut is not None and cut.shape != depth.shape:
        cut = Image.fromarray(cut.astype(np.float32)).resize(
            size, Image.Resampling.BILINEAR
        )
        cut = np.asarray(cut, np.float32)
    rgb, hole = split_depth(depth, cut)
    Image.fromarray(rgb, "RGB").save(p["depth"])
    hole = Image.fromarray(hole).resize(img.size, Image.Resampling.BILINEAR)
    plate = _fill(img, np.asarray(hole, np.float32), max(4, img.size[0] // 320))
    plate.save(p["plate"], quality=90)


def make(image: Path, key: str, folder: Path) -> dict:
    import numpy as np
    import onnxruntime as ort
    from PIL import Image, ImageFilter

    models = find_models()
    if not models:
        raise RuntimeError("the cut-out and depth models are not in " + str(MODELS))
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = THREADS
    opts.inter_op_num_threads = 1
    cpu = ["CPUExecutionProvider"]
    img = Image.open(image).convert("RGB")
    seg = _run_seg(ort.InferenceSession(str(models["seg"]), opts, providers=cpu), img)
    raw = _run_depth(
        ort.InferenceSession(str(models["depth"]), opts, providers=cpu), img
    )
    depth = refine_depth(img, raw)
    if depth.shape != seg.shape:  # the subject is picked at the picture's size
        depth_full = np.asarray(
            Image.fromarray(depth).resize(img.size, Image.Resampling.BILINEAR),
            np.float32,
        )
    else:
        depth_full = depth
    mask, subject = pick_subject(seg, depth_full)
    p = layer_paths(key, folder)
    save_depth(img, depth, mask if subject == "character" else None, p)
    info = {
        "subject": subject,
        "share": round(float((mask > 0.5).mean()), 4),
        "method": METHOD,
    }
    if subject != "none":
        # a soft edge, and the hole in the background a little wider than the
        # subject so no rim of it shows when the layers move apart
        w = img.size[0]
        soft = Image.fromarray((mask * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(max(1, w // 1600))
        )
        fg = img.copy()
        fg.putalpha(soft)
        fg.save(p["fg"], "WEBP", quality=90, method=4)
        hole = Image.fromarray(((mask > 0.3) * 255).astype(np.uint8)).filter(
            ImageFilter.MaxFilter(max(3, (w // 180) | 1))
        )
        hole = hole.filter(ImageFilter.GaussianBlur(max(2, w // 400)))
        _fill(img, np.asarray(hole, np.float32) / 255, max(4, w // 160)).save(
            p["bg"], quality=88
        )
    p["info"].write_text(json.dumps(info), encoding="utf-8")
    return info


def adopt(new: Path, folder: Path, old: Path) -> int:
    """Every complete layer set in new (made by this METHOD) copied into
    folder, the files it replaces moved into old first. A set folder already
    has from this METHOD is skipped, and nothing in old is overwritten (a
    later file gets a .1, .2 ... suffix). The count copied."""
    import shutil

    n = 0
    for info in sorted(new.glob("*-layers.json")):
        key = info.name[: -len("-layers.json")]
        src = layer_paths(key, new)
        meta = json.loads(info.read_text(encoding="utf-8"))
        parts = ("depth", "plate")
        if meta.get("subject") != "none":
            parts += ("fg", "bg")
        if meta.get("method") != METHOD or not all(src[x].is_file() for x in parts):
            continue
        dst = layer_paths(key, folder)
        if dst["lock"].exists():  # being made right now
            continue
        if dst["info"].is_file():
            have = json.loads(dst["info"].read_text(encoding="utf-8"))
            if have.get("method") == METHOD:
                continue
        for name in ("fg", "bg", "depth", "plate", "info"):
            if dst[name].is_file():
                old.mkdir(parents=True, exist_ok=True)
                keep, i = old / dst[name].name, 1
                while keep.exists():  # the first original keeps its name
                    keep, i = old / f"{dst[name].name}.{i}", i + 1
                shutil.move(dst[name], keep)
            if src[name].is_file():
                shutil.copy2(src[name], dst[name])
        n += 1
    return n


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[0] == "make":
        image, key, folder = Path(argv[1]), argv[2], Path(argv[3])
        p = layer_paths(key, folder)
        try:
            info = make(image, key, folder)
        except Exception as e:  # recorded, so it is not tried again and again
            failed = {"subject": "none", "error": str(e), "method": METHOD}
            try:  # a remake that failed keeps the older layers it was to replace
                old = json.loads(p["info"].read_text(encoding="utf-8"))
                if isinstance(old, dict) and old.get("subject", "none") != "none":
                    failed = dict(old, tried=METHOD, error=str(e))
            except (OSError, ValueError):
                pass
            p["info"].write_text(json.dumps(failed))
            print(f"forge_layers: {e}", file=sys.stderr)
            return 1
        finally:
            p["lock"].unlink(missing_ok=True)
        # the hub picks the layers up from a fresh hub/theme.js
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import forge_theme

        forge_theme.apply(FORGE / "hub")
        print(json.dumps(info))
        return 0
    if len(argv) == 4 and argv[0] == "adopt":
        n = adopt(Path(argv[1]), Path(argv[2]), Path(argv[3]))
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import forge_theme

        forge_theme.apply(FORGE / "hub")
        print(f"forge_layers: {n} wallpapers adopted")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
