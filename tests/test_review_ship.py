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
