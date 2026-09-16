"""Pillow helpers shared by cast, sheet and cut: contact sheets, capture treatment, fonts."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_CANDIDATES = [
    ("TikTok Sans Bold", ["~/Library/Fonts/TikTokSans-Bold.ttf", "/Library/Fonts/TikTokSans-Bold.ttf",
                          "~/Library/Fonts/TikTok Sans Bold.ttf", "/usr/share/fonts/truetype/tiktok/TikTokSans-Bold.ttf"]),
    ("Arial Bold", ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
                    "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf"]),
    ("Helvetica", ["/System/Library/Fonts/Helvetica.ttc"]),
    ("DejaVu Sans Bold", ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]),
]


def find_font(wanted: str = "TikTok Sans Bold") -> tuple[str, str | None]:
    """(name actually used, path). Substitution is reported, never silent: it moves line breaks."""
    order = sorted(FONT_CANDIDATES, key=lambda c: c[0] != wanted)
    for name, paths in order:
        for p in paths:
            pp = Path(p).expanduser()
            if pp.exists():
                return name, str(pp)
    return "Pillow default", None


def font(path: str | None, size: int) -> ImageFont.ImageFont:
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size=size)


def save_png(data: bytes, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.open(io.BytesIO(data)).convert("RGB").save(path, "PNG")
    return path


def capture_treatment(src: Path, dst: Path, seed: int = 0) -> Path:
    """Generate clean, degrade last: sensor noise, a touch of lens softness, one JPEG pass."""
    im = Image.open(src).convert("RGB").filter(ImageFilter.GaussianBlur(0.45))
    rng = np.random.default_rng(seed)
    a = np.asarray(im).astype(np.float32)
    lum = a.mean(-1, keepdims=True)
    a = a + rng.normal(0, 1, a.shape[:2] + (1,)) * (4.0 * (1 - lum / 255) + 1.0)  # more noise in shadows
    buf = io.BytesIO()
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(buf, "JPEG", quality=88)
    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.open(buf).save(dst, "PNG")
    return dst


def contact(images: Sequence[Path], out: Path, labels: Sequence[str] | None = None, cols: int = 4,
            cell_w: int = 360, title: str | None = None) -> Path:
    ims = [Image.open(p).convert("RGB") for p in images]
    if not ims:
        raise ValueError("no images for contact sheet")
    cell_h = max(int(cell_w * im.height / im.width) for im in ims)
    rows = (len(ims) + cols - 1) // cols
    head = 56 if title else 0
    pad, lab = 12, 30
    sheet = Image.new("RGB", (cols * (cell_w + pad) + pad, head + rows * (cell_h + lab + pad) + pad), (21, 20, 15))
    d = ImageDraw.Draw(sheet)
    _, fpath = find_font("Arial Bold")
    if title:
        d.text((pad, 14), title, fill=(233, 228, 216), font=font(fpath, 26))
    for i, im in enumerate(ims):
        r, c = divmod(i, cols)
        x, y = pad + c * (cell_w + pad), head + pad + r * (cell_h + lab + pad)
        sheet.paste(im.resize((cell_w, int(cell_w * im.height / im.width))), (x, y))
        if labels:
            d.text((x, y + cell_h + 4), labels[i], fill=(233, 228, 216), font=font(fpath, 20))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out
