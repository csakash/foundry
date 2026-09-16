"""Synthetic fixtures. Nothing here is persona art: the repo is public."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]
import os

# optional calibration source (a gmm-contents checkout), read in place and never copied
IMANI = Path(os.environ.get("FOUNDRY_CALIBRATION_DIR", "/Users/akashmunshi/gmm-contents"))


def portrait(path: Path, skin=(62, 52, 50), bg=(52, 53, 55), size=(512, 768), face=(0.34, 0.26, 0.66, 0.54),
             noise=6, seed=0) -> Path:
    """Grey studio backdrop with a textured near-black face ellipse and a neck/chest block."""
    rng = np.random.default_rng(seed)
    w, h = size
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    d.ellipse([face[0] * w, face[1] * h, face[2] * w, face[3] * h], fill=skin)
    d.rectangle([0.30 * w, face[3] * h - 4, 0.70 * w, h], fill=skin)
    a = np.asarray(im).astype(np.int16) + rng.integers(-noise, noise + 1, (h, w, 1))
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(path)
    return path


def warm(src: Path, dst: Path, k=(1.35, 1.05, 0.70)) -> Path:
    a = np.asarray(Image.open(src).convert("RGB")).astype(np.float32) * np.array(k)
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(dst)
    return dst


def video(path: Path, seconds=5.0, size="720x1280", color="0x3e3432", audio: str | None = None, fps=24) -> Path:
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s={size}:d={seconds}:r={fps}"]
    if audio == "tone":
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}"]
    cmd += ["-pix_fmt", "yuv420p", "-c:v", "libx264"]
    if audio == "tone":
        cmd += ["-c:a", "aac", "-shortest"]
    subprocess.run(cmd + [str(path)], check=True)
    return path


@pytest.fixture
def tmp(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture(autouse=True)
def _not_the_agent(monkeypatch):
    monkeypatch.delenv("FOUNDRY_AGENT", raising=False)
