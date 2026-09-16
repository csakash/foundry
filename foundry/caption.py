"""Burned-in caption: reel-style white bold text with a black outline, in a top band.

Numbers follow the caption spec: font size is a percentage of frame width, the block
is centred in the middle 80 % of the width, the stroke is 12.5 % of the font size
painted behind the fill (so about half is visible), line height 1.2.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .imaging import find_font, font
from .util import write_json


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def render(spec_captions: dict[str, Any], out_png: Path, size: tuple[int, int] = (1080, 1920)) -> dict[str, Any]:
    w, h = size
    name, path = find_font(spec_captions.get("font", "TikTok Sans Bold"))
    px = round(w * float(spec_captions.get("size_pct_w", 6.6)) / 100)
    fnt = font(path, px)
    stroke = max(1, round(px * float(spec_captions.get("stroke_pct", 12.5)) / 100 / 2))
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    max_w = int(w * 0.80) - 2 * stroke
    lines = wrap(d, spec_captions["text"], fnt, max_w)
    line_h = round(px * 1.2)
    top = round(h * float(spec_captions.get("band_start_pct_h", 11)) / 100)
    x_min, x_max = w, 0
    for i, line in enumerate(lines):
        lw = d.textlength(line, font=fnt)
        x = (w - lw) / 2
        y = top + i * line_h
        d.text((x, y), line, font=fnt, fill=(255, 255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        x_min, x_max = min(x_min, x - stroke), max(x_max, x + lw + stroke)
    bbox = im.getbbox() or (0, top, w, top)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_png)
    meta = {"text": spec_captions["text"], "font_wanted": spec_captions.get("font"), "font_used": name,
            "font_substituted": name != spec_captions.get("font"), "font_px": px, "stroke_px": stroke,
            "lines": lines, "box": [round(bbox[0] / w, 4), round(bbox[1] / h, 4), round(bbox[2] / w, 4), round(bbox[3] / h, 4)],
            "size": list(size)}
    write_json(out_png.with_suffix(".json"), meta)
    return meta


def overlay(frame: Path, caption_png: Path, out: Path) -> Path:
    base = Image.open(frame).convert("RGBA")
    cap = Image.open(caption_png).convert("RGBA").resize(base.size)
    Image.alpha_composite(base, cap).convert("RGB").save(out)
    return out
