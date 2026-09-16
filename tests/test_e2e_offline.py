"""The acceptance path end to end, offline: fake image provider, synthetic clips, real ffmpeg and QC.

This is the /qa substitute for a repo with no web app. It walks SPEC.md's acceptance
criteria that do not need paid providers (2-13), plus the review's state-machine repros.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from engine.providers.fake_images import FakeImages
from foundry import cast, cli, workspace
from foundry.piece import Piece
from foundry.util import Blocked, FoundryError, read_json, write_json

from .conftest import video

HOOK = "hook.line=I made my monthly salary in just a few minutes using this app"
ASSET = "assets.0.path=assets/product/walkthrough.mp4"


def sh(ws_root: Path, *args: str) -> tuple[int, dict]:
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
    root.mkdir()
    sh(root, "init")
    cfg = read_json(root / "foundry.json")
    cfg["providers"]["image"] = {"kind": "fake"}
    write_json(root / "foundry.json", cfg)
    (root / "assets/product").mkdir(parents=True)
    video(root / "assets/product/walkthrough.mp4", seconds=22, size="1080x1920", color="0x223344", audio="tone")
    return root


def cast_nova(root: Path) -> None:
    assert sh(root, "cast", "nova", "--brief", "an original adult creator with cool near-black skin")[0] == 0
    assert sh(root, "cast", "nova", "--pick", "c1")[0] == 0
    code, pack = sh(root, "cast", "nova", "--approve")
    assert code == 0, pack


def approved_piece(root: Path, slug: str, *extra: str) -> Piece:
    sh(root, "new", "@test", slug)
    code, res = sh(root, "set", f"@test/{slug}", HOOK, ASSET, *extra, "--touch")
    assert res["complete"], res
    assert sh(root, "sheet", f"@test/{slug}")[0] == 0
    assert sh(root, "approve", f"@test/{slug}", "--candidate", "c2")[0] == 0
    return Piece.open(workspace.load(root), f"@test/{slug}")


def pass_frames(root: Path, ref: str) -> None:
    sh(root, "region", ref, "frames/approved.png", "--face", "0.36,0.28,0.64,0.52")
    sh(root, "verdict", ref, "--stage", "frames", "--pass")
    code, rep = sh(root, "qc", ref, "--stage", "frames")
    assert code == 0 and rep["pass"], rep


def paid_clip(root: Path, ref: str, image: Path, out: Path, job: str) -> tuple[int, dict]:
    """What the agent does: reserve, generate, settle with the job id, ingest."""
    code, r = sh(root, "reserve", ref, "--unit", "video_credits", "--amount", "32.5", "--note", job)
    if code != 0:
        return code, r
    clip = clip_from(image, out)
    sh(root, "settle", ref, r["entry"], "--ok", "--ref", job)
    return sh(root, "ingest-clip", ref, str(clip), "--job", job)


def green_clip(root: Path, ref: str, tmp_path: Path, job: str = "job-1") -> None:
    code, res = paid_clip(root, ref, root / "work" / ref / "frames/approved.png", tmp_path / f"{job}.mp4", job)
    assert code == 0, res
    sh(root, "verdict", ref, "--stage", "clip", "--pass")
    code, rep = sh(root, "qc", ref, "--stage", "clip")
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
    assert {q["id"] for q in res["questions"]} == {"hook", "assets"}
    ref = "@test/nova-hook"
    code, res = sh(root, "set", ref, HOOK, ASSET, "hook.mechanism=drama", "--touch")
    assert res["complete"], res
    assert sh(root, "sheet", ref)[0] == 0
    sheet_dir = root / "work/@test/nova-hook/sheet"
    for f in ("sheet.png", "index.html", "layout.png", "product.jpg", "caption-preview.png", "candidates/c1.png", "candidates/c3.png"):
        assert (sheet_dir / f).exists(), f
    assert (sheet_dir / "index.html").stat().st_size < 3_000_000

    # criterion 6: build refuses before approval, approve freezes the invoice and the limits
    code, res = sh(root, "build", ref, "--mode", "bypass", "--dry-run")
    assert code == 2 and res["status"] == "REFUSED"
    code, res = sh(root, "approve", ref, "--candidate", "c2")
    assert code == 0 and res["ceilings"]["video_credits"] == 97.5 and res["fix_cycles"] == 2
    assert (root / "work/@test/nova-hook/approved.lock.json").exists()
    code, res = sh(root, "resolve", ref)
    assert code == 2 and "frozen" in res["error"]
    cfg = read_json(root / "foundry.json")
    cfg["providers"]["video"]["mcp_server"] = "higgsfield"
    write_json(root / "foundry.json", cfg)
    code, res = sh(root, "build", ref, "--mode", "bypass", "--dry-run")
    assert code == 0 and "foundry qc @test/nova-hook --stage cut" in res["prompt"] and "NEVER ship red" in res["prompt"]
    assert "Bash(curl:*)" not in res["argv"] and "Edit" in res["argv"] and "Bash(foundry ship:*)" in res["argv"]

    # criteria 7 and 8: unattended stages go green on real QC
    pass_frames(root, ref)
    code, res = sh(root, "prompt", ref, "--kind", "motion")
    assert "0.0-0.7 s: Nova" in res["prompt"] and res["params"]["model"] == "seedance_2_5"
    green_clip(root, ref, tmp_path)
    rep = read_json(root / "work/@test/nova-hook/qc/clip.json")
    assert rep["checks"]["frame0"]["measures"]["diff"] <= 30 and rep["checks"]["drift"]["measures"]["max_lum"] <= 12
    code, res = sh(root, "cut", ref)
    assert code == 0, res
    code, rep = sh(root, "qc", ref, "--stage", "cut")
    assert code == 0 and rep["pass"], rep
    assert rep["checks"]["caption_band"]["pass"] and rep["checks"]["loudness"]["pass"]
    assert 20 <= rep["checks"]["duration"]["measures"]["duration"] <= 30
    assert (rep["checks"]["duration"]["measures"]["width"], rep["checks"]["duration"]["measures"]["height"]) == (1080, 1920)
    assert rep["next"].startswith("green")

    # criterion 9: spend within the frozen ceilings, every call recorded and closed
    inv = read_json(root / "work/@test/nova-hook/invoice.json")
    assert all(e["state"] in ("settled", "failed") for e in inv["entries"])
    p = Piece.open(workspace.load(root), ref)
    assert p.spent("video_credits") <= inv["ceilings"]["video_credits"]

    # criteria 11 and 12: ship does not post, saves a recipe, exactly two touches
    code, res = sh(root, "ship", ref)
    assert code == 0, res
    assert res["posted"] is False and (root / "pipelines/nova-hook.json").exists()
    assert read_json(root / "work/@test/nova-hook/publish.json")["posted_at"] is None
    assert read_json(root / "work/@test/nova-hook/status.json")["touches"] == 2

    # criterion 5: the second piece from the recipe asks at most two questions
    code, res = sh(root, "new", "@test", "nova-hook-2", "--recipe", "nova-hook")
    assert code == 0 and [q["id"] for q in res["questions"]] == ["hook"]

    # criterion 13: ls and reap
    code, rows = sh(root, "ls")
    row = next(r for r in rows if r["piece"] == ref)
    assert row["state"] == "shipped" and row["video_credits"] == 32.5 and row["touches"] == 2
    assert sh(root, "reap")[1] == []
    sh(root, "posted", ref, "--url", "https://example.com/reel/1")
    code, reaped = sh(root, "reap")
    assert [r["piece"] for r in reaped] == [ref]
    left = {c.name for c in (root / "work/@test/nova-hook").iterdir()}
    assert {"SPEC.md", "qc", "invoice.json", "approved.lock.json"} <= left and "clips" not in left and "cut" not in left


def test_clip_blocks_on_exact_gate_after_fix_cycles(ws: Path, tmp_path: Path):
    """Criterion 10: frame0_max_diff=1, clips that pass everything else, exactly 2 regenerations, then BLOCKED clip.frame0."""
    root = ws
    cast_nova(root)
    p = approved_piece(root, "doomed", "qc_targets.frame0_max_diff=1")
    ref = p.ref
    pass_frames(root, ref)
    approved = root / "work/@test/doomed/frames/approved.png"
    for attempt in range(3):
        code, res = paid_clip(root, ref, approved, tmp_path / f"c{attempt}.mp4", f"job-{attempt}")
        assert code == 0, res
        sh(root, "verdict", ref, "--stage", "clip", "--pass")
        code, rep = sh(root, "qc", ref, "--stage", "clip")
        assert code == 1
        if attempt < 2:
            assert rep["failed"] == ["frame0"] and "regenerate" in rep["next"]
    assert rep["status"] == "BLOCKED" and rep["gate"] == "clip.frame0"
    st = read_json(root / "work/@test/doomed/status.json")
    assert st["state"] == "blocked" and st["blocked_gate"] == "clip.frame0" and st["cycles"]["clip"] == 2
    assert (root / "work/@test/doomed/clips/shot01.mp4").exists()
    assert not (root / "work/@test/doomed/publish.json").exists()
    assert sh(root, "ingest-clip", ref, str(tmp_path / "c0.mp4"), "--job", "job-0")[0] == 2
    assert sh(root, "ship", ref)[0] == 2


def test_reingest_invalidates_green_clip_and_cut(ws: Path, tmp_path: Path):
    """Review repro: a replaced clip must not inherit the old clip's pass."""
    root = ws
    cast_nova(root)
    p = approved_piece(root, "stale")
    pass_frames(root, p.ref)
    green_clip(root, p.ref, tmp_path)
    red = tmp_path / "red.png"
    Image.new("RGB", (720, 1280), (200, 20, 20)).save(red)
    # a regeneration is refused while the clip is green
    code, res = paid_clip(root, p.ref, red, tmp_path / "red.mp4", "job-2")
    assert code == 2 and "green" in res["error"]
    assert (root / "work/@test/stale/qc/clip.json").exists()
    assert sh(root, "cut", p.ref)[0] == 0
    code, rep = sh(root, "qc", p.ref, "--stage", "cut")
    assert code == 0 and rep["pass"]


def test_regen_frame_budget_and_invalidation(ws: Path, tmp_path: Path):
    root = ws
    cast_nova(root)
    p = approved_piece(root, "frames")
    ref = p.ref
    assert sh(root, "regen-frame", ref)[0] == 2  # no QC yet
    for i in range(2):
        assert sh(root, "region", ref, "frames/approved.png", "--face", "0.36,0.28,0.64,0.52")[0] == 0
        code, res = sh(root, "region", ref, "frames/approved.png", "--face", "0.30,0.20,0.70,0.60")
        assert code == 2 and "already recorded" in res["error"]  # one look per image
        assert sh(root, "verdict", ref, "--stage", "frames", "--fail", "--note", "six fingers")[0] == 0
        assert sh(root, "verdict", ref, "--stage", "frames", "--pass")[0] == 2
        code, rep = sh(root, "qc", ref, "--stage", "frames")
        assert code == 1 and rep["failed"] == ["hands"]
        code, res = sh(root, "regen-frame", ref)
        assert code == 0 and res["cycle"] == i + 1
        assert not (root / "work/@test/frames/qc/frames.json").exists()
        assert "frames/approved.png" not in read_json(root / "work/@test/frames/qc/regions.json")
        assert sh(root, "regen-frame", ref)[0] == 2  # needs a fresh QC run first
    sh(root, "region", ref, "frames/approved.png", "--face", "0.36,0.28,0.64,0.52")
    sh(root, "verdict", ref, "--stage", "frames", "--fail", "--note", "still six")
    code, rep = sh(root, "qc", ref, "--stage", "frames")
    assert code == 1 and rep["gate"] == "frames.hands"
    inv = read_json(root / "work/@test/frames/invoice.json")
    assert sum(1 for e in inv["entries"] if e["note"] == "frames regeneration" and e["state"] == "settled") == 2


def test_regen_frame_moves_the_old_clip_aside(ws: Path, tmp_path: Path):
    root = ws
    cast_nova(root)
    p = approved_piece(root, "reframe")
    ref = p.ref
    pass_frames(root, ref)
    code, res = paid_clip(root, ref, root / "work/@test/reframe/frames/approved.png", tmp_path / "a.mp4", "j1")
    assert code == 0
    sh(root, "verdict", ref, "--stage", "clip", "--fail", "--note", "melting hand")
    assert sh(root, "qc", ref, "--stage", "clip")[0] == 1
    # frames were fine; the clip failed. A new clip for the same frame is a clip regeneration:
    code, res = paid_clip(root, ref, root / "work/@test/reframe/frames/approved.png", tmp_path / "b.mp4", "j2")
    assert code == 0 and res["cycle"] == 1


def test_frames_skin_requires_a_recorded_face_box(ws: Path):
    root = ws
    cast_nova(root)
    p = approved_piece(root, "nobox")
    sh(root, "verdict", p.ref, "--stage", "frames", "--pass")
    code, rep = sh(root, "qc", p.ref, "--stage", "frames")
    assert code == 1 and rep["failed"] == ["skin"] and "face box" in rep["guidance"]


def test_limits_cannot_be_moved_after_approval(ws: Path, tmp_path: Path):
    root = ws
    cast_nova(root)
    p = approved_piece(root, "locked")
    ref = p.ref
    cfg = read_json(root / "foundry.json")
    cfg["providers"]["video"]["mcp_server"] = "higgsfield"
    write_json(root / "foundry.json", cfg)
    assert sh(root, "build", ref, "--dry-run", "--fix-cycles", "5")[0] == 0
    assert read_json(root / "work/@test/locked/approved.lock.json")["fix_cycles"] == 2  # dry run changes nothing
    code, res = sh(root, "build", ref, "--dry-run", "--fix-cycles", "50")
    assert code == 2 and "between 0 and 10" in res["error"]
    pass_frames(root, ref)  # state is now building
    code, res = sh(root, "build", ref, "--dry-run", "--fix-cycles", "5")
    assert code == 2 and "fixed" in res["error"]
    assert sh(root, "set", ref, "qc_targets.frame0_max_diff=999")[0] == 2
    spec = read_json(root / "work/@test/locked/spec.json")
    spec["qc_targets"]["frame0_max_diff"] = 999
    write_json(root / "work/@test/locked/spec.json", spec)
    code, rep = sh(root, "qc", ref, "--stage", "frames")
    assert code == 1 and rep["gate"] == "spec.changed_after_approval"


def test_invoice_is_one_way_and_ingest_needs_payment(ws: Path, tmp_path: Path):
    root = ws
    cast_nova(root)
    p = approved_piece(root, "money")
    ref = p.ref
    pass_frames(root, ref)
    clip = clip_from(root / "work/@test/money/frames/approved.png", tmp_path / "c.mp4")
    code, res = sh(root, "ingest-clip", ref, str(clip), "--job", "free-ride")
    assert code == 2 and "reservation" in res["error"]
    code, r = sh(root, "reserve", ref, "--unit", "video_credits", "--amount", "32.5")
    assert sh(root, "settle", ref, r["entry"], "--ok", "--actual", "0", "--ref", "j")[0] == 2
    assert sh(root, "settle", ref, r["entry"], "--failed")[0] == 0
    assert sh(root, "settle", ref, r["entry"], "--ok", "--ref", "j")[0] == 2
    assert Piece.open(workspace.load(root), ref).spent("video_credits") == 32.5  # a failed job still counts
    code, r2 = sh(root, "reserve", ref, "--unit", "video_credits", "--amount", "32.5")
    sh(root, "settle", ref, r2["entry"], "--ok", "--ref", "j2")
    assert sh(root, "ingest-clip", ref, str(clip), "--job", "j2")[0] == 0
    sh(root, "verdict", ref, "--stage", "clip", "--fail", "--note", "x")
    assert sh(root, "qc", ref, "--stage", "clip")[0] == 1
    assert sh(root, "ingest-clip", ref, str(clip), "--job", "j2")[0] == 2  # a payment buys one clip
    code, res = sh(root, "reserve", ref, "--unit", "video_credits", "--amount", "40")
    assert code == 1 and res["gate"] == "budget.video_credits"  # 65 + 40 > 97.5


def test_agent_cannot_take_human_steps(ws: Path, monkeypatch):
    root = ws
    cast_nova(root)
    sh(root, "new", "@test", "agent")
    sh(root, "set", "@test/agent", HOOK, ASSET)
    monkeypatch.setenv("FOUNDRY_AGENT", "1")
    code, res = sh(root, "ls")
    assert code == 2 and "-C is not allowed" in res["error"]  # the agent cannot point foundry at another workspace
    monkeypatch.chdir(root)

    def agent_sh(*args):  # the agent runs inside its workspace, without -C
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main([*args, "--json"])
        return code, json.loads(buf.getvalue().strip() or "{}")
    for args in (("sheet", "@test/agent"), ("set", "@test/agent", "hook.line=x"), ("approve", "@test/agent", "--candidate", "c1"),
                 ("build", "@test/agent", "--dry-run"), ("ship", "@test/agent"), ("reap",), ("cast", "evil", "--brief", "x"),
                 ("new", "@test", "other")):
        code, res = agent_sh(*args)
        assert code == 2 and "human step" in res["error"], args
    assert agent_sh("ls")[0] == 0


def test_names_cannot_escape_the_workspace(ws: Path):
    root = ws
    for args in (("new", "@x/../../..", "evil"), ("new", "@test", "../evil"), ("cast", "../../evil", "--brief", "x")):
        code, res = sh(root, *args)
        assert code == 2 and "invalid" in res["error"], args
    cast_nova(root)
    sh(root, "new", "@test", "escape")
    code, res = sh(root, "set", "@test/escape", "hook.line=x", "assets.0.path=../../etc/hosts")
    assert not res["complete"] and "outside" in res["problems"][0]
    assert not (root.parent / "evil").exists()


def test_cut_normalises_clip_audio_and_checks_asset_length(ws: Path, tmp_path: Path):
    root = ws
    cast_nova(root)
    video(root / "assets/product/short.mp4", seconds=16, size="1920x1080", audio="tone")  # landscape, shorter than 20 s
    sh(root, "new", "@test", "short")
    code, res = sh(root, "set", "@test/short", HOOK, "assets.0.path=assets/product/short.mp4", "audio.kind=clip")
    assert not res["complete"] and any("trims to 20" in x for x in res["problems"])
    code, res = sh(root, "set", "@test/short", "assets.0.trim_s=[0, 15]")
    assert res["complete"], res
    sh(root, "sheet", "@test/short")
    sh(root, "approve", "@test/short", "--candidate", "c1")
    pass_frames(root, "@test/short")
    green_clip(root, "@test/short", tmp_path)
    assert sh(root, "cut", "@test/short")[0] == 0
    code, rep = sh(root, "qc", "@test/short", "--stage", "cut")
    assert code == 0 and rep["pass"], rep
    assert abs(rep["checks"]["loudness"]["measures"]["integrated_lufs"] + 14) <= 2


def test_budget_ceiling_blocks(ws: Path):
    root = ws
    cast_nova(root)
    p = approved_piece(root, "pricey")
    assert sh(root, "reserve", p.ref, "--unit", "video_credits", "--amount", "0.5")[0] == 2  # below one clip's price
    for _ in range(3):
        assert sh(root, "reserve", p.ref, "--unit", "video_credits", "--amount", "32.5")[0] == 0
    code, res = sh(root, "reserve", p.ref, "--unit", "video_credits", "--amount", "32.5")
    assert code == 1 and res["gate"] == "budget.video_credits"


def test_parallel_reserves_cannot_overspend(ws: Path):
    """Adversarial repro: 12 concurrent reserves against a 97.5 ceiling used to book 162.5 with duplicate ids."""
    import sys
    from concurrent.futures import ThreadPoolExecutor
    root = ws
    cast_nova(root)
    p = approved_piece(root, "race")
    cmd = [sys.executable, "-m", "foundry", "-C", str(root), "reserve", p.ref, "--unit", "video_credits",
           "--amount", "32.5", "--json"]
    with ThreadPoolExecutor(12) as pool:
        codes = list(pool.map(lambda _: subprocess.run(cmd, capture_output=True, text=True).returncode, range(12)))
    inv = read_json(root / "work/@test/race/invoice.json")
    booked = [e for e in inv["entries"] if e["unit"] == "video_credits"]
    assert codes.count(0) == 3 and len(booked) == 3
    assert len({e["id"] for e in booked}) == 3
    assert sum(e["amount"] for e in booked) <= inv["ceilings"]["video_credits"]


def test_swapped_inputs_block_after_approval(ws: Path):
    root = ws
    cast_nova(root)
    p = approved_piece(root, "swap")
    pass_frames(root, p.ref)
    video(root / "assets/product/walkthrough.mp4", seconds=22, size="1080x1920", color="0xff0000", audio="tone")
    code, rep = sh(root, "qc", p.ref, "--stage", "frames")
    assert code == 1 and rep["gate"] == "inputs.changed_after_approval" and "asset/0" in rep["evidence"]


def test_approve_refuses_a_spec_edited_after_render(ws: Path):
    root = ws
    cast_nova(root)
    sh(root, "new", "@test", "edited")
    sh(root, "set", "@test/edited", HOOK, ASSET)
    assert sh(root, "sheet", "@test/edited")[0] == 0
    assert sh(root, "resolve", "@test/edited")[0] == 2
    spec = read_json(root / "work/@test/edited/spec.json")
    spec["qc_targets"]["frame0_max_diff"] = 999
    write_json(root / "work/@test/edited/spec.json", spec)
    code, res = sh(root, "approve", "@test/edited", "--candidate", "c1")
    assert code == 2 and "render the sheet again" in res["error"]


def test_exit_codes_for_crashes_and_unfinished_builds(ws: Path, monkeypatch):
    from foundry import build as build_mod
    root = ws
    cast_nova(root)
    p = approved_piece(root, "exits")
    monkeypatch.setattr(build_mod, "build", lambda *a, **k: {"piece": p.ref, "exit_code": 0, "state": "building"})
    assert sh(root, "build", p.ref, "--mode", "bypass")[0] == 1  # the agent stopped before green
    monkeypatch.setattr(build_mod, "build", lambda *a, **k: {"piece": p.ref, "exit_code": 0, "state": "green"})
    assert sh(root, "build", p.ref, "--mode", "bypass")[0] == 0
    from foundry import loop
    monkeypatch.setattr(loop, "run_qc", lambda *a, **k: 1 / 0)
    code, res = sh(root, "qc", p.ref, "--stage", "frames")
    assert code == 3 and res["status"] == "ERROR" and "ZeroDivisionError" in res["error"]


def test_cast_fails_closed_on_sheet_drift(ws: Path):
    """Criterion 3: a sheet lighter than the master blocks and writes no pack."""
    wsp = workspace.load(ws)
    cast.bootstrap(wsp, "pale", "an original adult creator", n=2, provider=FakeImages())
    with pytest.raises(Blocked) as e:
        cast.pick(wsp, "pale", "c1", provider=FakeImages(skin=(150, 120, 110)))
    assert e.value.gate == "sheet_drift"
    assert not (ws / "personas/pale/pack.json").exists()
    assert read_json(ws / "personas/pale/cast.json")["state"] == "blocked"
    with pytest.raises(FoundryError):
        cast.approve(wsp, "pale")


def test_spec_refuses_without_a_creator(ws: Path):
    code, res = sh(ws, "new", "@test", "orphan")
    assert code == 2 and "cast" in res["error"]


def test_sheet_refusals_lose_candidates_not_the_piece(ws: Path):
    root = ws
    cast_nova(root)
    sh(root, "new", "@test", "refused")
    sh(root, "set", "@test/refused", HOOK, ASSET)
    wsp = workspace.load(root)
    p = Piece.open(wsp, "@test/refused")

    class Picky(FakeImages):
        def edit(self, prompt, refs, n=1, size="1024x1536"):
            self.i = getattr(self, "i", 0) + 1
            if self.i == 2:
                return super().edit("FAKE_REFUSE", refs, n, size)
            return super().edit(prompt, refs, n, size)

    from foundry import sheet
    res = sheet.render(wsp, p, n=3, provider=Picky())
    assert res["candidates"] == ["c1", "c3"] and res["refused"] == 1 and p.state == "sheet_pending"

    class Prude(FakeImages):
        def edit(self, prompt, refs, n=1, size="1024x1536"):
            return super().edit("FAKE_REFUSE", refs, n, size)

    with pytest.raises(FoundryError, match="refused 3 of 3"):
        sheet.render(wsp, p, n=3, provider=Prude())
    assert p.state == "sheet_pending"
    failed = [e for e in read_json(root / "work/@test/refused/invoice.json")["entries"] if e["state"] == "failed"]
    assert len(failed) == 4


def test_shared_file_changes_do_not_block_a_paid_piece(ws: Path):
    """Verification repro: creating the account charter after approval blocked the piece forever."""
    root = ws
    cast_nova(root)
    p = approved_piece(root, "charter")
    (root / "accounts/@test").mkdir(parents=True, exist_ok=True)
    write_json(root / "accounts/@test/charter.json", {"never_list": ["No 'monthly salary' claims."]})
    pass_frames(root, p.ref)  # not BLOCKED inputs.changed_after_approval
    assert read_json(root / "work/@test/charter/approved.lock.json")["charter"] is None  # lint uses the approved charter


def test_dry_run_never_blocks(ws: Path):
    root = ws
    cast_nova(root)
    p = approved_piece(root, "dry")
    cfg = read_json(root / "foundry.json")
    cfg["providers"]["video"]["mcp_server"] = "higgsfield"
    write_json(root / "foundry.json", cfg)
    video(root / "assets/product/walkthrough.mp4", seconds=22, size="1080x1920", color="0x00ff00", audio="tone")
    code, res = sh(root, "build", p.ref, "--mode", "bypass", "--dry-run")
    assert code == 0 and read_json(root / "work/@test/dry/status.json")["state"] == "approved"
    assert not any(t in res["argv"] for t in ("Read(~/**)", "Read"))
    assert "Read(./work/**)" in res["argv"]


def test_resolve_catches_missing_music_and_real_cut_length(ws: Path):
    root = ws
    cast_nova(root)
    sh(root, "new", "@test", "music")
    code, res = sh(root, "set", "@test/music", HOOK, ASSET, "audio.kind=trending", "audio.path=assets/nope.mp3")
    assert not res["complete"] and any("nope.mp3" in x for x in res["problems"])
    code, res = sh(root, "set", "@test/music", "audio.kind=silent", "shots.0.duration_s=10", "assets.0.trim_s=[0, 22]")
    assert not res["complete"] and any("32s" in x for x in res["problems"])  # 10 s shot + 22 s asset, back to back
    code, res = sh(root, "set", "@test/music", "shots.0.id=history")
    assert any("reserved" in x for x in res["problems"])


def test_build_pidfile_is_exclusive(tmp_path: Path):
    import os
    from foundry.build import _claim_pidfile
    pid = tmp_path / ".build.pid"
    fd = _claim_pidfile(pid, "@t/x")
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    with pytest.raises(FoundryError, match="already running"):
        _claim_pidfile(pid, "@t/x")
    dead = subprocess.Popen(["true"])
    dead.wait()  # a pid that certainly belonged to a finished process (999999 can be live on Linux)
    pid.write_text(str(dead.pid))
    os.close(_claim_pidfile(pid, "@t/x"))
