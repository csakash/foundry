"""The acceptance path end to end, offline: fake image provider, synthetic clips, real ffmpeg and QC.

This is the /qa substitute for a repo with no web app. It walks SPEC.md's acceptance
criteria that do not need paid providers: 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from engine.providers.fake_images import FakeImages
from foundry import cast, cli, workspace
from foundry.piece import Piece
from foundry.util import Blocked, FoundryError, read_json, write_json

from .conftest import video


def sh(ws_root: Path, *args: str) -> tuple[int, dict]:
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(["-C", str(ws_root), *args, "--json"])
    out = buf.getvalue().strip()
    return code, (json.loads(out) if out else {})


def clip_from(image: Path, out: Path, seconds: float = 5.0) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(image), "-t", str(seconds), "-r", "24",
                    "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,format=yuv420p",
                    "-c:v", "libx264", str(out)], check=True)
    return out


@pytest.fixture
def ws(tmp_path: Path):
    root = tmp_path / "factory"
    code, _ = sh_init(root)
    cfg = read_json(root / "foundry.json")
    cfg["providers"]["image"] = {"kind": "fake"}
    write_json(root / "foundry.json", cfg)
    (root / "assets/product").mkdir(parents=True)
    video(root / "assets/product/walkthrough.mp4", seconds=22, size="1080x1920", color="0x223344", audio="tone")
    return root


def sh_init(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    return sh(root, "init")


def cast_nova(root: Path) -> None:
    assert sh(root, "cast", "nova", "--brief", "an original adult creator with cool near-black skin")[0] == 0
    assert sh(root, "cast", "nova", "--pick", "c1")[0] == 0
    code, pack = sh(root, "cast", "nova", "--approve")
    assert code == 0, pack


def approved_piece(root: Path, slug: str) -> Piece:
    sh(root, "new", "@test", slug)
    sh(root, "set", f"@test/{slug}", "hook.line=I made my monthly salary in just a few minutes using this app",
       "assets.0.path=assets/product/walkthrough.mp4", "--touch")
    assert sh(root, "sheet", f"@test/{slug}")[0] == 0
    assert sh(root, "approve", f"@test/{slug}", "--candidate", "c2")[0] == 0
    return Piece.open(workspace.load(root), f"@test/{slug}")


def pass_frames(root: Path, ref: str) -> None:
    sh(root, "region", ref, "frames/approved.png", "--face", "0.36,0.28,0.64,0.52")
    sh(root, "verdict", ref, "--stage", "frames", "--pass")
    code, rep = sh(root, "qc", ref, "--stage", "frames")
    assert code == 0 and rep["pass"], rep


def test_acceptance_path(ws: Path, tmp_path: Path):
    root = ws
    # criterion 2: cast with two human touches and measured targets
    cast_nova(root)
    pack = read_json(root / "personas/nova/pack.json")
    assert pack["cast_touches"] == 2
    assert pack["qc_targets"]["skin"]["lum"] > 0 and pack["qc_targets"]["method"].startswith("engine.qc.skin")

    # criterion 4: one round, at most five questions
    code, res = sh(root, "new", "@test", "nova-hook")
    assert code == 0 and not res["complete"]
    assert 1 <= len(res["questions"]) <= 5
    assert {q["id"] for q in res["questions"]} == {"hook", "assets"}
    ref = "@test/nova-hook"
    code, res = sh(root, "set", ref, "hook.line=I made my monthly salary in just a few minutes using this app",
                   "assets.0.path=assets/product/walkthrough.mp4", "hook.mechanism=drama", "--touch")
    assert res["complete"], res
    code, res = sh(root, "sheet", ref)
    assert code == 0
    sheet_dir = root / "work/@test/nova-hook/sheet"
    for f in ("sheet.png", "index.html", "layout.png", "product.jpg", "caption-preview.png", "candidates/c1.png", "candidates/c3.png"):
        assert (sheet_dir / f).exists(), f

    # criterion 6: build refuses before approval, approve freezes the invoice
    code, res = sh(root, "build", ref, "--mode", "bypass", "--dry-run")
    assert code == 2 and res["status"] == "REFUSED"
    code, res = sh(root, "approve", ref, "--candidate", "c2")
    assert code == 0 and res["ceilings"]["video_credits"] == 97.5
    code, res = sh(root, "build", ref, "--mode", "bypass", "--dry-run")
    assert code == 0 and "foundry qc @test/nova-hook --stage cut" in res["prompt"] and "NEVER ship red" in res["prompt"]

    # criteria 7 and 8: unattended stages go green on real QC
    pass_frames(root, ref)
    code, res = sh(root, "prompt", ref, "--kind", "motion")
    assert "0.0-0.7 s: Nova" in res["prompt"] and res["params"]["model"] == "seedance_2_5"
    code, r = sh(root, "reserve", ref, "--unit", "video_credits", "--amount", "32.5", "--note", "shot01")
    assert code == 0
    clip = clip_from(root / "work/@test/nova-hook/frames/approved.png", tmp_path / "gen.mp4")
    sh(root, "settle", ref, r["entry"], "--ok", "--ref", "job-1")
    assert sh(root, "ingest-clip", ref, str(clip), "--job", "job-1")[0] == 0
    sh(root, "verdict", ref, "--stage", "clip", "--pass")
    code, rep = sh(root, "qc", ref, "--stage", "clip")
    assert code == 0 and rep["pass"], rep
    assert rep["checks"]["frame0"]["measures"]["diff"] <= 30
    assert rep["checks"]["drift"]["measures"]["max_lum"] <= 12
    code, res = sh(root, "cut", ref)
    assert code == 0, res
    code, rep = sh(root, "qc", ref, "--stage", "cut")
    assert code == 0 and rep["pass"], rep
    assert rep["checks"]["caption_band"]["pass"] and rep["checks"]["loudness"]["pass"]
    assert 20 <= rep["checks"]["duration"]["measures"]["duration"] <= 30
    assert (rep["checks"]["duration"]["measures"]["width"], rep["checks"]["duration"]["measures"]["height"]) == (1080, 1920)
    assert rep["next"].startswith("green")

    # criterion 9: spend within the frozen ceilings, every call recorded
    inv = read_json(root / "work/@test/nova-hook/invoice.json")
    assert all(e["state"] in ("settled", "failed") for e in inv["entries"])
    p = Piece.open(workspace.load(root), ref)
    assert p.spent("video_credits") <= inv["ceilings"]["video_credits"]
    assert p.spent("image_call") <= inv["ceilings"]["image_call"]

    # criteria 11 and 12: ship does not post, saves a recipe, exactly two touches
    code, res = sh(root, "ship", ref)
    assert code == 0, res
    assert res["posted"] is False and (root / "pipelines/nova-hook.json").exists()
    assert read_json(root / "work/@test/nova-hook/publish.json")["posted_at"] is None
    assert read_json(root / "work/@test/nova-hook/status.json")["touches"] == 2

    # criterion 5: the second piece from the recipe asks at most two questions
    code, res = sh(root, "new", "@test", "nova-hook-2", "--recipe", "nova-hook")
    assert code == 0 and len(res["questions"]) <= 2 and [q["id"] for q in res["questions"]] == ["hook"]

    # criterion 13: ls and reap
    code, rows = sh(root, "ls")
    row = next(r for r in rows if r["piece"] == ref)
    assert row["state"] == "shipped" and row["video_credits"] == 32.5 and row["touches"] == 2
    code, reaped = sh(root, "reap")
    assert reaped == []  # not posted yet
    sh(root, "posted", ref, "--url", "https://example.com/reel/1")
    code, reaped = sh(root, "reap")
    assert [r["piece"] for r in reaped] == [ref]
    left = {c.name for c in (root / "work/@test/nova-hook").iterdir()}
    assert {"SPEC.md", "qc", "invoice.json"} <= left and "clips" not in left and "cut" not in left


def test_clip_blocks_after_fix_cycles(ws: Path, tmp_path: Path):
    """Criterion 10: exactly fix_cycles regenerations, then BLOCKED, work kept, nothing published."""
    root = ws
    cast_nova(root)
    p = approved_piece(root, "doomed")
    ref = p.ref
    assert sh(root, "build", ref, "--mode", "bypass", "--dry-run", "--fix-cycles", "2")[0] == 0
    pass_frames(root, ref)
    bright = tmp_path / "bright.png"
    Image.new("RGB", (720, 1280), (235, 235, 235)).save(bright)
    for attempt in range(3):
        clip = clip_from(bright, tmp_path / f"bad{attempt}.mp4")
        assert sh(root, "ingest-clip", ref, str(clip))[0] == 0
        sh(root, "verdict", ref, "--stage", "clip", "--pass")
        code, rep = sh(root, "qc", ref, "--stage", "clip")
        assert code == 1
        if attempt < 2:
            assert rep["pass"] is False and "regenerate" in rep["next"]
    assert rep["status"] == "BLOCKED" and rep["gate"].startswith("clip.")
    st = read_json(root / "work/@test/doomed/status.json")
    assert st["state"] == "blocked" and st["cycles"]["clip"] == 2
    assert (root / "work/@test/doomed/clips/shot01.mp4").exists()
    assert not (root / "work/@test/doomed/publish.json").exists()
    assert sh(root, "ingest-clip", ref, str(clip))[0] == 2  # blocked pieces refuse further work
    assert sh(root, "ship", ref)[0] == 2


def test_budget_ceiling_blocks(ws: Path):
    root = ws
    cast_nova(root)
    p = approved_piece(root, "pricey")
    code, res = sh(root, "reserve", p.ref, "--unit", "video_credits", "--amount", "97.5")
    assert code == 0
    code, res = sh(root, "reserve", p.ref, "--unit", "video_credits", "--amount", "0.5")
    assert code == 1 and res["gate"] == "budget.video_credits"


def test_cast_fails_closed_on_sheet_drift(ws: Path):
    """Criterion 3: a sheet lighter than the master blocks and writes no pack."""
    root = ws
    wsp = workspace.load(root)
    cast.bootstrap(wsp, "pale", "an original adult creator", n=2, provider=FakeImages())
    with pytest.raises(Blocked) as e:
        cast.pick(wsp, "pale", "c1", provider=FakeImages(skin=(150, 120, 110)))
    assert e.value.gate == "sheet_drift"
    assert not (root / "personas/pale/pack.json").exists()
    assert read_json(root / "personas/pale/cast.json")["state"] == "blocked"
    with pytest.raises(FoundryError):
        cast.approve(wsp, "pale")


def test_spec_refuses_without_a_creator(ws: Path):
    code, res = sh(ws, "new", "@test", "orphan")
    assert code == 2 and "cast" in res["error"]


def test_sheet_safety_refusal_blocks(ws: Path):
    root = ws
    cast_nova(root)
    sh(root, "new", "@test", "refused")
    sh(root, "set", "@test/refused", "hook.line=ok line", "assets.0.path=assets/product/walkthrough.mp4")
    wsp = workspace.load(root)
    p = Piece.open(wsp, "@test/refused")
    spec = p.spec
    spec["shots"][0]["wardrobe"] = "FAKE_REFUSE shirt"
    p.save_spec(spec)
    code, res = sh(root, "sheet", "@test/refused")
    assert code == 1 and res["gate"] == "sheet.safety_refused"
    entries = read_json(root / "work/@test/refused/invoice.json")["entries"]
    assert entries[-1]["state"] == "failed"
