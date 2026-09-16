"""Regression tests for the /ship pre-landing review (specialists + red team), 2026-09-17."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from engine.providers.fake_images import FakeImages
from foundry import build, cast, loop, services, workspace
from foundry.piece import Piece
from foundry.util import Blocked, FoundryError, read_json, write_json

from .conftest import video
from .test_coverage_ship2 import building, locked, passed, run_cli, ws  # noqa: F401  (fixture re-export)
from .test_units import MASTER, _write_cast


# ---------------------------------------------------------------- cast sheet gate (red team)
def test_visual_check_cannot_launder_a_measured_drift(ws):
    _write_cast(ws, "launder", MASTER, [(0, 0.5, 0.5)] * 7, sheet_skin=(235, 205, 190))
    with pytest.raises(Blocked) as e:
        cast.remeasure(ws, "launder")
    assert e.value.gate == "sheet_drift"
    # a face box on the hair below the face still "measures" (dark hair passes the colour mask) but its flat
    # crop matches no panel, so the gate reports unmeasurable ...
    with pytest.raises(Blocked) as e:
        cast.remeasure(ws, "launder", face=(0.3, 0.62, 0.7, 0.76))
    assert e.value.gate == "sheet_unmeasurable"
    # ... but the drift already seen for these exact images still refuses the by-eye approval
    with pytest.raises(FoundryError, match="already measured as drift"):
        cast.approve(ws, "launder", visual_check="looks fine")
    assert not (ws.dir("personas") / "launder/pack.json").exists()


def test_face_boxes_are_validated(ws):
    _write_cast(ws, "boxes", MASTER, [(0, 0.5, 0.5)] * 7)
    for bad in ((0, 0, 1, 1.2), (0.6, 0.2, 0.4, 0.5), (0.1, 0.1, 0.12, 0.5)):
        with pytest.raises(FoundryError, match="face box"):
            cast.remeasure(ws, "boxes", face=bad)
    with pytest.raises(SystemExit):  # argparse rejects it before any command runs
        run_cli(ws.root, "region", "@t/none", "frames/approved.png", "--face", "0,0,1,1.2")


def test_failed_sheet_call_leaves_nothing_to_approve(ws):
    cast.bootstrap(ws, "stale", "original adult creator", n=2, provider=FakeImages())
    cast.pick(ws, "stale", "c1", provider=FakeImages())
    assert cast.state(ws, "stale")["state"] == "sheet_measured"

    class Down(FakeImages):
        def edit(self, *a, **k):
            raise ConnectionError("provider down")
    with pytest.raises(ConnectionError):
        cast.pick(ws, "stale", "c2", provider=Down())
    d = ws.dir("personas") / "stale"
    assert cast.state(ws, "stale")["state"] == "picking"
    assert not (d / "measure.json").exists() and not (d / "sheet.png").exists()
    with pytest.raises(FoundryError):
        cast.approve(ws, "stale")
    # a retry of the pick works from the picking state
    assert cast.pick(ws, "stale", "c2", provider=FakeImages())["state"] == "sheet_measured"


def test_approve_refuses_images_changed_since_measurement(ws):
    cast.bootstrap(ws, "swap", "original adult creator", n=2, provider=FakeImages())
    cast.pick(ws, "swap", "c1", provider=FakeImages())
    d = ws.dir("personas") / "swap"
    Image.open(d / "candidates/c2.png").save(d / "master.png")
    with pytest.raises(FoundryError, match="changed since they were measured"):
        cast.approve(ws, "swap")


def test_remeasure_refuses_a_creator_with_active_pieces(ws):
    p = building(ws, "inuse")
    with pytest.raises(FoundryError, match="@t/inuse"):
        cast.remeasure(ws, "nova")
    assert (ws.dir("personas") / "nova/pack.json").exists()
    assert p.lock["fix_cycles"] == 2  # the piece is still healthy


def test_reapproving_the_same_numbers_does_not_block_pieces(ws):
    p = building(ws, "relock")
    pack_path = ws.dir("personas") / "nova/pack.json"
    pack = read_json(pack_path)
    pack.update(locked_at="2099-01-01T00:00:00Z", cast_touches=9)  # bytes change, build-relevant fields do not
    write_json(pack_path, pack)
    assert p.lock["fix_cycles"] == 2
    pack["qc_targets"]["skin"]["lum"] += 20  # a real change still blocks
    write_json(pack_path, pack)
    with pytest.raises(Blocked, match="persona/pack"):
        p.lock


def test_sheet_saturation_drift_blocks(ws, monkeypatch):
    _write_cast(ws, "vivid", MASTER, [(0, 0.5, 0.5)] * 7)
    real = cast.measure_sheet

    def oversaturated(*a, **k):  # same brightness and warmth as the master, saturation pushed up
        m = real(*a, **k)
        m["row"] = {**m["row"], "sat_pct": m["row"]["sat_pct"] + 20}
        return m
    monkeypatch.setattr(cast, "measure_sheet", oversaturated)
    with pytest.raises(Blocked) as e:
        cast.remeasure(ws, "vivid")
    assert e.value.gate == "sheet_drift"
    assert any("saturation" in f for f in read_json(ws.dir("personas") / "vivid/measure.json")["failed"])


# ---------------------------------------------------------------- agent boundaries (security)
def test_agent_can_only_ingest_downloaded_clips(ws, monkeypatch, tmp_path):
    p = building(ws, "outside")
    passed(p, "frames")
    clip = video(tmp_path / "elsewhere.mp4", seconds=2)
    monkeypatch.setenv("FOUNDRY_AGENT", "1")
    with pytest.raises(FoundryError, match="outside"):
        loop.ingest_clip(ws, p, clip, job="j")


def test_transfer_refuses_shared_address_space(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("100.64.1.2", 443))])
    with pytest.raises(FoundryError, match="non-public"):
        loop._check_url("https://cgnat.example.com/x")


def test_ffprobe_refuses_playlist_protocols(tmp_path):
    from engine.qc import duration
    playlist = tmp_path / "evil.mp4"
    playlist.write_text("#EXTM3U\n#EXTINF:1,\nhttp://127.0.0.1:9/x.ts\n")
    with pytest.raises(subprocess.CalledProcessError):
        duration.probe(playlist)


# ---------------------------------------------------------------- build (testing)
def test_build_fix_cycles_override_persists_when_real(ws, monkeypatch):
    p = building(ws, "budget")
    p.set_state("approved")
    cfg = read_json(ws.root / "foundry.json")
    cfg["providers"]["video"]["mcp_server"] = "higgsfield"
    write_json(ws.root / "foundry.json", cfg)
    monkeypatch.setattr(build.shutil, "which", lambda _: "/bin/claude")

    class Proc:
        pid = os.getpid()

        def wait(self, timeout=None):
            return 0
    monkeypatch.setattr(build.subprocess, "Popen", lambda *a, **k: Proc())
    out = build.build(workspace.load(ws.root), p, "bypass", cycles=1)
    assert out["exit_code"] == 0 and p.lock["fix_cycles"] == 1
    with pytest.raises(FoundryError, match="between 0 and 10"):
        build.build(ws, p, "bypass", cycles=-1, dry_run=True)


def test_build_prompt_names_every_shot(ws):
    p = building(ws, "shots")
    p.set_state("approved")
    text = build.prompt(ws, p, 2)
    assert "repeat for each shot: shot01" in text and "--shot <shot id>" in text


# ---------------------------------------------------------------- cut QC length (testing)
def test_cut_qc_fails_only_on_length(ws, tmp_path):
    p = building(ws, "long")
    passed(p, "frames", "clip")
    p.rel("cut").mkdir()
    video(p.rel("cut", "final.mp4"), seconds=35, size="1080x1920")
    write_json(p.rel("cut", "cut.json"), {"parts": []})
    write_json(p.rel("cut", "caption.json"), {"box": [0.12, 0.11, 0.88, 0.2]})
    write_json(p.rel("qc", "regions.json"), {"frames/approved.png": {"face": [0.36, 0.3, 0.64, 0.55]}})
    rep = loop.run_qc(ws, p, "cut")
    assert rep["failed"] == ["duration"] and rep["checks"]["duration"]["measures"]["max"] == 30


# ---------------------------------------------------------------- doctor MCP (red team)
def test_mcp_check_runs_in_the_workspace_and_prefers_a_connected_match(ws, monkeypatch):
    seen = {}

    class Done:
        stdout = ("stale: https://mcp.higgsfield.ai/mcp - ✗ Failed to connect\n"
                  "decoy: https://evil.example/?u=mcp.higgsfield.ai - ✓ Connected\n"
                  "claude.ai Higgsfield: https://mcp.higgsfield.ai/mcp - ✓ Connected\n")
    monkeypatch.setattr(services.shutil, "which", lambda _: "/bin/claude")
    monkeypatch.setattr(services.subprocess, "run", lambda *a, **k: seen.update(k) or Done())
    rows = services.list_mcp(cwd=str(ws.root))
    assert seen["cwd"] == str(ws.root)
    status, lines = services.mcp_status(services.MCP_SERVERS[0], rows)
    assert status == "ok" and "claude.ai Higgsfield" in lines[0]
    decoy_only = [r for r in rows if r["name"] == "decoy"]
    assert services.mcp_status(services.MCP_SERVERS[0], decoy_only)[0] == "todo"


def test_doctor_notes_open_transfers_without_failing(ws):
    from foundry import ops
    res = ops.doctor(ws, offline=True)
    note = next(r for r in res["checks"] if r["check"] == "transfer hosts")
    assert note["status"] == "note" and "transfer_hosts" in note["detail"]


# ---------------------------------------------------------------- ship review cycle 2 (adversarial)
def test_money_values_must_be_finite(ws):
    p = building(ws, "nan")
    for bad in (float("nan"), float("inf")):
        with pytest.raises(FoundryError, match="finite"):
            p.reserve("video_credits", bad, "x")
    eid = p.reserve("video_credits", 32.5, "ok")
    with pytest.raises(FoundryError, match="finite"):
        p.settle(eid, ok=True, actual=float("nan"))
    with pytest.raises(SystemExit):  # argparse refuses before the command runs
        run_cli(ws.root, "reserve", p.ref, "--unit", "video_credits", "--amount", "nan")


def test_settling_over_the_ceiling_is_recorded_then_blocks(ws):
    p = building(ws, "over")
    inv = p.invoice
    inv.update(frozen=True, ceilings={"video_credits": 40}, baseline={"video_credits": 0})
    write_json(p.rel("invoice.json"), inv)
    eid = p.reserve("video_credits", 32.5, "short shot")
    with pytest.raises(Blocked, match="budget.video_credits"):
        p.settle(eid, ok=True, actual=65, ref="j")
    assert p.invoice["entries"][-1]["amount"] == 65 and p.state == "blocked"


def test_pick_and_approve_refuse_a_creator_in_use(ws):
    p = building(ws, "live")
    with pytest.raises(FoundryError, match="@t/live"):
        cast.pick(ws, "nova", "c2", provider=FakeImages())
    with pytest.raises(FoundryError, match="@t/live"):
        cast.approve(ws, "nova")
    assert p.lock["fix_cycles"] == 2


def test_a_red_remeasure_keeps_the_existing_pack(ws, monkeypatch):
    locked(ws, "keep")
    real = cast.measure_sheet

    def drifted(*a, **k):
        m = real(*a, **k)
        m["row"] = {**m["row"], "lum": m["row"]["lum"] + 40}
        return m
    monkeypatch.setattr(cast, "measure_sheet", drifted)
    with pytest.raises(Blocked):
        cast.remeasure(ws, "keep")
    assert (ws.dir("personas") / "keep/pack.json").exists()


def test_approve_refuses_a_failed_measurement(ws):
    locked(ws, "failed")
    d = ws.dir("personas") / "failed"
    m = read_json(d / "measure.json")
    m["failed"] = ["forged"]
    write_json(d / "measure.json", m)
    st = cast.state(ws, "failed")
    st["state"] = "sheet_measured"
    write_json(d / "cast.json", st)
    with pytest.raises(FoundryError, match="measured green"):
        cast.approve(ws, "failed")


def test_a_final_without_its_manifest_is_rebuilt_not_wedged(ws):
    from foundry import cut as cut_mod
    p = building(ws, "wedge")
    passed(p, "frames", "clip")
    p.rel("cut").mkdir()
    p.rel("cut", "final.mp4").write_bytes(b"half an encode")
    with pytest.raises(RuntimeError, match="shot01.mp4"):  # it tries to build (no clip here), it does not refuse
        cut_mod.build(ws, p)
    assert p.status["cycles"]["cut"] == 0


def test_the_agent_is_tied_to_its_own_piece(ws, monkeypatch):
    mine = building(ws, "mine")
    other = building(ws, "other")
    monkeypatch.setenv("FOUNDRY_AGENT", mine.ref)
    monkeypatch.chdir(ws.root)
    from foundry import cli
    import contextlib
    import io
    import json

    def agent(*args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main([*args, "--json"])
        return code, json.loads(buf.getvalue().strip() or "{}")
    code, res = agent("reserve", other.ref, "--unit", "video_credits", "--amount", "32.5")
    assert code == 2 and "may not touch" in res["error"]
    assert agent("status", mine.ref)[0] == 0


def test_prompt_is_per_shot(ws):
    p = building(ws, "pershot")
    code, res = run_cli(ws.root, "prompt", p.ref, "--kind", "motion", "--shot", "shot09")
    assert code == 2 and "unknown shot" in res["error"]
    code, res = run_cli(ws.root, "prompt", p.ref, "--kind", "motion", "--shot", "shot01")
    assert code == 0 and res["params"]["duration"] == 5


def test_unchanged_inputs_are_not_rehashed(ws, monkeypatch):
    p = building(ws, "stats")
    fresh = Piece.open(ws, p.ref)
    calls = []
    real = Piece._cached_hash
    monkeypatch.setattr(Piece, "_cached_hash", lambda self, path: calls.append(str(path)) or real(self, path))
    assert fresh.lock["fix_cycles"] == 2
    assert calls == []  # nothing on disk changed, so no input file (the product clip included) was hashed again
    (ws.root / "clip.mp4").write_bytes(b"changed")
    with pytest.raises(Blocked, match="asset/0"):
        Piece.open(ws, p.ref).lock


def test_sheet_approval_refuses_a_recast_creator(ws):
    from foundry import sheet, spec as spec_mod
    locked(ws)
    video(ws.root / "clip.mp4", seconds=21)
    p = spec_mod.new(ws, "@t", "recast")
    spec_mod.set_values(ws, p, ["hook.line=ok", "assets.0.path=clip.mp4"])
    sheet.render(ws, p, n=2, provider=FakeImages())
    master = ws.dir("personas") / "nova/master.png"
    Image.open(ws.dir("personas") / "nova/candidates/c2.png").save(master)
    with pytest.raises(FoundryError, match="changed after these candidates"):
        sheet.approve(ws, p, "c1")
