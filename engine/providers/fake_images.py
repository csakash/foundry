"""Offline image provider for tests and the end-to-end QA run. Costs nothing, calls nothing.

Draws a deterministic portrait (grey backdrop, textured skin ellipse) whose pixels
depend on the prompt hash, so different prompts give different but measurable frames.
A prompt containing FAKE_REFUSE raises ImageRefused, to exercise the refusal path.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw

from .openai_images import ImageRefused


class FakeImages:
    kind = "fake"
    model = "fake"

    def __init__(self, skin: tuple[int, int, int] = (62, 52, 50)):
        self.skin = skin
        self.calls: list[dict] = []

    def _draw(self, prompt: str, i: int, size: str) -> bytes:
        if "FAKE_REFUSE" in prompt:
            raise ImageRefused("fake provider refused on request")
        w, h = (int(v) for v in size.split("x"))
        seed = int(hashlib.sha256(f"{prompt}|{i}".encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        im = Image.new("RGB", (w, h), (52, 53, 55))
        d = ImageDraw.Draw(im)
        hair = (45, 32, 25)  # dark hair passes the skin colour mask: every offline test must survive it
        if w > h:  # a character sheet: seven heads across the top row, each framed by long hair
            panels = 7  # foundry.cast.SHEET_PANELS; engine must not import foundry
            for k in range(panels):
                cx = (k + 0.5) * w / panels
                d.rectangle([cx - w / 20, h * 0.03, cx + w / 20, h * 0.32], fill=hair)
                d.ellipse([cx - w / 30, h * 0.06, cx + w / 30, h * 0.28], fill=self.skin)
                d.ellipse([cx - w / 90, h * 0.14, cx + w / 90, h * 0.17], fill=(30, 25, 22))  # a feature to match on
        else:
            jx = float(rng.uniform(-0.02, 0.02))
            d.rectangle([(0.24 + jx) * w, 0.18 * h, (0.76 + jx) * w, 0.80 * h], fill=hair)
            d.ellipse([(0.34 + jx) * w, 0.26 * h, (0.66 + jx) * w, 0.54 * h], fill=self.skin)
            d.ellipse([(0.47 + jx) * w, 0.36 * h, (0.53 + jx) * w, 0.40 * h], fill=(30, 25, 22))
            d.rectangle([0.30 * w, 0.52 * h, 0.70 * w, h], fill=self.skin)
        a = np.asarray(im).astype(np.int16) + rng.integers(-6, 7, (h, w, 1))
        buf = io.BytesIO()
        Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(buf, "PNG")
        return buf.getvalue()

    def generate(self, prompt: str, n: int = 1, size: str = "1024x1536") -> list[bytes]:
        self.calls.append({"op": "generate", "prompt": prompt, "n": n})
        return [self._draw(prompt, i, size) for i in range(n)]

    def edit(self, prompt: str, refs: Sequence[str | Path], n: int = 1, size: str = "1024x1536") -> list[bytes]:
        self.calls.append({"op": "edit", "prompt": prompt, "refs": [str(r) for r in refs], "n": n})
        return [self._draw(prompt, i, size) for i in range(n)]

    def check_model(self) -> tuple[bool, str]:
        return True, "fake"
