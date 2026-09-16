from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from engine.qc import caption_band, drift, duration, frame0, hands, loudness, safety_lint, skin, text_lint

from .conftest import IMANI, portrait, video, warm

FACE = (0.36, 0.28, 0.64, 0.52)


# ---------------------------------------------------------------- skin
def test_skin_measure_ignores_neutral_backdrop(tmp):
    p = portrait(tmp / "p.png")
    m = skin.measure(p)  # whole frame: grey backdrop has sat < 7 % and must not count
    assert m is not None and 8 <= m["r_minus_b"] <= 16 and m["coverage"] < 0.6


def test_skin_check_passes_within_tolerance(tmp):
    p = portrait(tmp / "p.png")
    base = skin.measure(p, FACE)
    targets = {k: base[k] for k in ("lum", "r_minus_b", "sat_pct")} | {"tol": {"lum": 12, "r_minus_b": 16, "sat_pct": 11}}
    r = skin.check(portrait(tmp / "q.png", seed=3), targets, FACE)
    assert r["pass"], r


def test_skin_check_fails_warm_drift_with_guidance(tmp):
    p = portrait(tmp / "p.png")
    base = skin.measure(p, FACE)
    targets = {k: base[k] for k in ("lum", "r_minus_b", "sat_pct")} | {"tol": {"lum": 12, "r_minus_b": 16, "sat_pct": 11}}
    r = skin.check(warm(p, tmp / "w.png"), targets, FACE)
    assert not r["pass"] and "r_minus_b" in r["measures"]["failed"] and "warm" in r["guidance"]


def test_skin_check_requires_a_box(tmp):
    r = skin.check(portrait(tmp / "p.png"), {"lum": 60, "tol": {"lum": 12}}, None)
    assert not r["pass"] and "face box" in r["guidance"]


# ---------------------------------------------------------------- frame0 + drift
def test_frame0_identical_and_different(tmp):
    a = portrait(tmp / "a.png", size=(720, 1280))
    assert frame0.check(a, a, 30)["measures"]["diff"] == 0.0
    b = tmp / "b.png"
    Image.new("RGB", (720, 1280), (230, 230, 230)).save(b)
    r = frame0.check(a, b, 30)
    assert not r["pass"] and r["measures"]["diff"] > 100


def test_frame0_resizes_approved_to_clip_size(tmp):
    a = portrait(tmp / "a.png", size=(1024, 1536))
    f = tmp / "f.png"
    Image.open(a).resize((720, 1280)).save(f)
    assert frame0.check(a, f, 30)["pass"]


def test_drift_stable_vs_warming(tmp):
    frames = [portrait(tmp / f"f{i}.png", seed=i) for i in range(4)]
    assert drift.check(frames, max_lum=12)["pass"]
    assert drift.check(frames, max_lum=12, face_box=(0.36, 0.36, 0.56, 0.54))["pass"]  # the head turns inside the doubled box
    frames.append(warm(frames[0], tmp / "f_warm.png"))
    r = drift.check(frames, max_lum=12, max_rb=12)
    assert not r["pass"] and r["measures"]["worst_frame"] == "f_warm.png"


def test_drift_needs_two_frames(tmp):
    assert not drift.check([portrait(tmp / "a.png")], 12)["pass"]


# ---------------------------------------------------------------- hands
def test_hands_missing_verdict_fails(tmp):
    r = hands.check(tmp / "verdicts.json", "clip")
    assert not r["pass"] and "record a hands verdict" in r["guidance"]


def test_hands_reads_verdict(tmp):
    v = tmp / "verdicts.json"
    v.write_text(json.dumps({"hands": {"clip": {"pass": False, "note": "six fingers at 3.1s"}, "frames": {"pass": True}}}))
    assert hands.check(v, "frames")["pass"]
    r = hands.check(v, "clip")
    assert not r["pass"] and "six fingers" in r["guidance"]


# ---------------------------------------------------------------- duration + loudness
def test_duration_expected_and_bounds(tmp):
    v = video(tmp / "v.mp4", seconds=5)
    assert duration.check(v, expected=5)["pass"]
    assert not duration.check(v, expected=8)["pass"]
    assert not duration.check(v, min_s=20, max_s=30)["pass"]
    assert duration.probe(v)["width"] == 720


def test_loudness_non_silent_branch(tmp):
    tone = video(tmp / "t.mp4", seconds=4, audio="tone")
    norm = tmp / "n.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tone), "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                    "-c:a", "aac", str(norm)], check=True)
    assert loudness.check(norm, "clip")["pass"], loudness.check(norm, "clip")
    quiet = tmp / "q.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tone), "-c:v", "copy", "-af", "volume=-25dB",
                    "-c:a", "aac", str(quiet)], check=True)
    assert not loudness.check(quiet, "clip")["pass"]
    assert not loudness.check(video(tmp / "s.mp4", seconds=1), "clip")["pass"]


def test_loudness_silent_and_tone(tmp):
    silent = video(tmp / "s.mp4", seconds=2)
    tone = video(tmp / "t.mp4", seconds=2, audio="tone")
    assert loudness.check(silent, "silent")["pass"]
    assert not loudness.check(tone, "silent")["pass"]
    assert loudness.integrated(tone) is not None


# ---------------------------------------------------------------- caption band
def test_caption_band_pass_and_fails():
    face = (0.35, 0.30, 0.65, 0.55)
    assert caption_band.check((0.12, 0.11, 0.88, 0.22), face)["pass"]
    assert not caption_band.check((0.12, 0.05, 0.88, 0.15), face)["pass"]          # above band
    assert not caption_band.check((0.02, 0.12, 0.98, 0.22), face)["pass"]          # too wide
    r = caption_band.check((0.12, 0.28, 0.88, 0.40), face)                          # over face
    assert not r["pass"] and r["measures"]["face_overlap"] > 0.02


# ---------------------------------------------------------------- lints
def test_safety_lint_rewrites():
    r = safety_lint.lint("a sheer pale-blue shirt, seductive look")
    assert not r["pass"] and "opaque" in r["rewritten"] and "confident" in r["rewritten"]
    assert safety_lint.lint("an opaque cotton shirt")["pass"]


def test_text_lint_slop_and_charter():
    charter = {"never_list": ["No FOMO — no 'last chance', 'don't miss'.",
                              "No 'guaranteed returns / get rich / risk-free / can't lose'.",
                              "No price calls — never 'buy X', never a price target."]}
    assert text_lint.lint("I made my monthly salary in just a few minutes using this app", charter)["pass"]
    assert not text_lint.lint("Last chance to get rich", charter)["pass"]
    r = text_lint.lint("buy TSLA now", charter)
    assert not r["pass"] and any("buy X" in f for f in r["measures"]["failed"])
    assert not text_lint.lint("this app — a game-changer", None)["pass"]
    assert text_lint.charter_phrases(charter)[:2] == ["last chance", "don't miss"]


# ---------------------------------------------------------------- calibration against the real Imani run (local only)
IM = IMANI / "work/_ugc/imani-salary-hook"


@pytest.mark.skipif(not (IM / "first-frame/approved.png").exists(), reason="set FOUNDRY_CALIBRATION_DIR to a gmm-contents checkout")
def test_calibration_imani():
    master = IMANI / "personas/imani/master.png"
    m = skin.measure(master, (0.36, 0.27, 0.64, 0.52))
    targets = {k: m[k] for k in ("lum", "r_minus_b", "sat_pct")} | {"tol": {"lum": 12, "r_minus_b": 16, "sat_pct": 11}}
    assert skin.check(IM / "first-frame/approved.png", targets, (0.36, 0.36, 0.56, 0.54))["pass"]
    assert skin.check(IM / "video/frames/f_0100.png", targets, (0.40, 0.26, 0.72, 0.47))["pass"]
    assert frame0.diff(IM / "first-frame/approved.png", IM / "video/frames/f_0001.png") == pytest.approx(20.3, abs=1.0)
    frames = [IM / f"video/frames/f_{i:04d}.png" for i in range(1, 122, 10)]
    assert drift.check(frames, max_lum=12)["pass"]


def test_prompt_templates_contain_no_safety_phrases():
    """The lint rewrites phrases wherever they appear; inside a NEGATIVE list that inverts the meaning
    (\"see-through clothing\" became \"opaque clothing\" in the first-frame negatives, 2026-09-17)."""
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    files = [repo / "engine/prompts/frame/first-frame.txt", repo / "engine/prompts/motion/seedance-beats.txt",
             *sorted((repo / "foundry/templates").glob("*.txt")), *sorted((repo / "catalog/scenes").glob("*.json"))]
    for f in files:
        assert safety_lint.lint(f.read_text())["pass"], f"{f.name} contains a safety-lint phrase"
