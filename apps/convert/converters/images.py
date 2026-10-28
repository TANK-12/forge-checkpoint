"""Images with Pillow: photos, screenshots, icons and animations."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps, ImageSequence

CONVERTER = {
    "id": "images",
    "label": "Images",
    "order": 1,
    "from": [
        "png",
        "jpg",
        "jpeg",
        "webp",
        "avif",
        "gif",
        "bmp",
        "tiff",
        "tif",
        "ico",
        "tga",
        "ppm",
    ],
    "to": ["png", "jpg", "webp", "avif", "gif", "bmp", "tiff", "ico", "pdf"],
    "options": [
        {
            "id": "quality",
            "label": "Quality",
            "type": "number",
            "min": 1,
            "max": 100,
            "default": 90,
            "for": ["jpg", "webp", "avif"],
        },
        {
            "id": "longest",
            "label": "Longest side in pixels (0 keeps the size)",
            "type": "number",
            "min": 0,
            "max": 20000,
            "default": 0,
        },
    ],
}

FORMATS = {
    "png": "PNG",
    "jpg": "JPEG",
    "webp": "WEBP",
    "avif": "AVIF",
    "gif": "GIF",
    "bmp": "BMP",
    "tiff": "TIFF",
    "ico": "ICO",
    "pdf": "PDF",
}
ANIMATED = ("gif", "webp", "avif")  # these keep every frame
NO_ALPHA = ("jpg", "bmp", "pdf")  # these get a white background


def _fit(img: Image.Image, longest: int) -> Image.Image:
    if longest and max(img.size) > longest:
        img = img.copy()
        img.thumbnail((longest, longest), Image.Resampling.LANCZOS)
    return img


KEEPS_16 = ("png", "tiff")  # these can hold 16-bit grey as it is
FRAME_BUDGET = 1_500_000_000  # bytes of frames held at once for an animation


def _eight_bit(img: Image.Image, to: str) -> Image.Image:
    """16-bit and 32-bit grey scaled down to 8 bits; a plain convert clips
    them to white."""
    if img.mode.startswith("I;16"):
        if to in KEEPS_16:
            return img
        return img.convert("I").point(lambda v: v * (1 / 256)).convert("L")
    if img.mode in ("I", "F"):
        lo, hi = img.getextrema()
        assert isinstance(lo, (int, float)) and isinstance(hi, (int, float))  # one band
        scale = 255 / (hi - lo) if hi > lo else 1.0
        off = -lo * scale
        return img.point(lambda v: v * scale + off).convert("L")
    return img


def _ready(img: Image.Image, to: str) -> Image.Image:
    img = _eight_bit(img, to)
    if img.mode.startswith("I;16"):
        return img
    if to in NO_ALPHA:
        if img.mode in ("RGBA", "LA", "P", "PA"):
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            return flat
        return img.convert("RGB") if img.mode not in ("RGB", "L") else img
    if img.mode == "CMYK" or (
        img.mode not in ("RGB", "RGBA", "L", "LA", "P") and to != "tiff"
    ):
        return img.convert("RGBA")
    return img


def convert(src: Path, dst: Path, to: str, opts: dict, ctx) -> None:
    longest = int(opts.get("longest", 0))
    save: dict = {}
    if to in ("jpg", "webp", "avif"):
        save["quality"] = int(opts["quality"])
    if to == "jpg":
        save["optimize"] = True
    with Image.open(src) as im:
        frames = getattr(im, "n_frames", 1)
        ctx.job.log(
            f"{im.format} {im.size[0]}x{im.size[1]} {im.mode}"
            + (f", {frames} frames" if frames > 1 else "")
        )
        if frames > 1 and to in ANIMATED:
            w, h = im.size
            shrink = min(1.0, longest / max(w, h)) if longest else 1.0
            held = frames * int(w * shrink) * int(h * shrink) * 4
            if held > FRAME_BUDGET:
                raise ValueError(
                    f"{frames} frames at this size need about {held / 1e9:.1f} GB"
                    " of memory; set a smaller longest side"
                )
            seq = [
                _ready(_fit(f.convert("RGBA"), longest), to)
                for f in ImageSequence.Iterator(im)
            ]
            durations = []
            for f in ImageSequence.Iterator(im):
                durations.append(f.info.get("duration", 100))
            if "loop" in im.info:  # one that plays once keeps playing once
                save["loop"] = im.info["loop"]
            seq[0].save(
                dst,
                FORMATS[to],
                save_all=True,
                append_images=seq[1:],
                duration=durations,
                **save,
            )
            return
        img = ImageOps.exif_transpose(im) or im
        img = _ready(_fit(img, longest), to)
        if to == "ico":
            img = _fit(img, 256)
            sizes = [s for s in (16, 24, 32, 48, 64, 128, 256) if s <= max(img.size)]
            save["sizes"] = [(s, s) for s in sizes] or [img.size]
        if to == "pdf":
            save["resolution"] = 150.0
        icc = im.info.get("icc_profile")
        if icc and im.mode != "CMYK" and to in ("jpg", "webp", "avif", "png", "tiff"):
            save["icc_profile"] = icc  # wide-gamut photos keep their colours
        exif = im.info.get("exif")
        if exif and to in ("jpg", "webp", "avif", "png", "tiff"):
            ex = Image.Exif()
            ex.load(exif)
            ex.pop(0x0112, None)  # the turn is applied, so the tag goes
            save["exif"] = ex.tobytes()
        img.save(dst, FORMATS[to], **save)
