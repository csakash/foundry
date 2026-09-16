"""Coverage for the error paths and edges the acceptance tests do not walk.

Network, `claude -p` and paid image calls are all faked; ffmpeg runs for real on synthetic clips.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from engine.providers import get_image_provider
from engine.providers.fake_images import FakeImages
from engine.providers.openai_images import ImageRefused
from foundry import build, cast, cli, cut as cut_mod, loop, ops, services, sheet, ship as ship_mod, spec as spec_mod
from foundry import workspace
from foundry.piece import APPROVED, Piece
from foundry.util import Blocked, FoundryError, read_json, write_json

from .conftest import video


@pytest.fixture
def ws(tmp_path: Path) -> workspace.Workspace:
    w, _ = workspace.init(tmp_path / "ws")
    cfg = read_json(w.root / "foundry.json")
    cfg["providers"]["image"] = {"kind": "fake"}
    write_json(w.root / "foundry.json", cfg)
    return workspace.load(w.root)


def locked(ws: workspace.Workspace, name: str = "nova") -> None:
    cast.bootstrap(ws, name, "original adult creator", n=2, provider=FakeImages())
    cast.pick(ws, name, "c1", provider=FakeImages())
    cast.approve(ws, name)


def specced(ws: workspace.Workspace, slug: str) -> Piece:
    if not (ws.dir("personas") / "nova/pack.json").exists():
        locked(ws)
    if not (ws.root / "clip.mp4").exists():
        video(ws.root / "clip.mp4", seconds=21)
    p = spec_mod.new(ws, "@t", slug)
    assert spec_mod.set_values(ws, p, ["hook.line=ok", "assets.0.path=clip.mp4"])["complete"]
    return p


def building(ws: workspace.Workspace, slug: str) -> Piece:
    """An approved, building piece with a real lock and the master as its approved frame."""
    p = specced(ws, slug)
    p.set_state("approved")
    p.write_lock(2)
    p.set_state("building")
    p.rel("frames").mkdir(exist_ok=True)
    shutil.copyfile(ws.dir("personas") / "nova/master.png", p.rel(APPROVED))
    return p


def passed(p: Piece, *stages: str) -> None:
    for s in stages:
        write_json(p.rel("qc", f"{s}.json"), {"stage": s, "pass": True, "failed": [], "guidance": ""})


def run_cli(root: Path, *args: str, as_json: bool = True) -> tuple[int, dict]:
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(["-C", str(root), *args] + (["--json"] if as_json else []))
    out = buf.getvalue().strip()
    return code, (json.loads(out) if out and as_json else {})


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class _Opener:
    def __init__(self, data: bytes = b""):
        self.data, self.requests = data, []

    def open(self, req, timeout=None):
        self.requests.append(req)
        return _Resp(self.data)


def _public_dns(monkeypatch, table: dict[str, str] | None = None):
    table = table or {}

    def gai(host, port):
        if host not in table:
            raise socket.gaierror("unknown host")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], port))]
    monkeypatch.setattr(socket, "getaddrinfo", gai)


# ---------------------------------------------------------------- provider transfer
def test_transfer_urls_must_be_https_public_and_allowlisted(monkeypatch):
    _public_dns(monkeypatch, {"cdn.example.com": "93.184.216.34", "lan.example.com": "10.0.0.5",
                              "loop.example.com": "::1"})
    for url in ("http://cdn.example.com/a.mp4", "https:///a.mp4", "ftp://cdn.example.com/a"):
        with pytest.raises(FoundryError, match="only https"):
            loop._check_url(url)
    with pytest.raises(FoundryError, match="transfer_hosts"):
        loop._check_url("https://badexample.com/a", ["example.com"])
    with pytest.raises(FoundryError, match="cannot resolve"):
        loop._check_url("https://nope.example.com/a", ["example.com"])
    for host in ("lan.example.com", "loop.example.com"):
        with pytest.raises(FoundryError, match="non-public"):
            loop._check_url(f"https://{host}/a")
    assert loop._check_url("https://cdn.example.com/a", ["example.com"]) == "https://cdn.example.com/a"
    handler = loop._HttpsOnlyRedirect()
    handler.hosts = ["example.com"]
    with pytest.raises(FoundryError, match="only https"):  # a redirect cannot downgrade or leave the allowlist
        handler.redirect_request(None, None, 302, "Found", {}, "http://cdn.example.com/a")


def test_download_clip_sanitises_the_job_and_caps_the_size(ws, monkeypatch):
    _public_dns(monkeypatch, {"cdn.example.com": "93.184.216.34"})
    p = Piece.create(ws, "@t", "dl")
    with pytest.raises(FoundryError, match="needs building"):
        loop.download_clip(ws, p, "https://cdn.example.com/a.mp4", job="j")
    p.set_state("building")
    with pytest.raises(FoundryError, match="invalid shot id"):
        loop.download_clip(ws, p, "https://cdn.example.com/a.mp4", job="j", shot="../x")
    opener = _Opener(b"x" * 64)
    monkeypatch.setattr(loop, "_opener", lambda _ws: (opener, []))
    dst = loop.download_clip(ws, p, "https://cdn.example.com/a.mp4", job="job/../1 x")
    assert re.fullmatch(r"shot01-job1x-[0-9a-f]{8}\.mp4", dst.name) and dst.read_bytes() == b"x" * 64
    monkeypatch.setattr(loop, "MAX_DOWNLOAD", 10)
    with pytest.raises(FoundryError, match="exceeds"):
        loop.download_clip(ws, p, "https://cdn.example.com/a.mp4", job="big")
    assert not list(p.rel("incoming").glob("*.part")) and not p.rel("incoming", "shot01-big.mp4").exists()


def test_upload_sends_only_the_approved_frame(ws, monkeypatch):
    _public_dns(monkeypatch, {"up.example.com": "93.184.216.34"})
    p = Piece.create(ws, "@t", "up")
    p.set_state("building")
    p.rel("frames").mkdir()
    p.rel(APPROVED).write_bytes(b"\x89PNG-approved")
    opener = _Opener()
    monkeypatch.setattr(loop, "_opener", lambda _ws: (opener, []))
    with pytest.raises(FoundryError, match="frames QC is not green"):
        loop.upload_approved(ws, p, "https://up.example.com/put")
    passed(p, "frames")
    res = loop.upload_approved(ws, p, "https://up.example.com/put")
    req = opener.requests[0]
    assert res == {"piece": "@t/up", "uploaded": APPROVED, "bytes": 13, "http": 200}
    assert req.get_method() == "PUT" and req.data == b"\x89PNG-approved" and req.get_header("Content-type") == "image/png"
    with pytest.raises(FoundryError, match="only https"):
        loop.upload_approved(ws, p, "http://up.example.com/put")


def test_cli_fetch_always_removes_the_download(ws, monkeypatch):
    Piece.create(ws, "@t", "fetch")
    got = {}

    def fake_download(_ws, piece, url, job, shot):
        f = piece.rel("incoming", f"{shot}-{job}.mp4")
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(b"mp4")
        got["file"] = f
        return f
    monkeypatch.setattr(loop, "download_clip", fake_download)
    monkeypatch.setattr(loop, "ingest_clip", lambda *a, **k: (_ for _ in ()).throw(FoundryError("bad clip")))
    code, res = run_cli(ws.root, "fetch", "@t/fetch", "--url", "https://x.example/a", "--job", "j1")
    assert code == 2 and res["error"] == "bad clip" and not got["file"].exists()
    monkeypatch.setattr(loop, "ingest_clip", lambda _ws, piece, mp4, job, shot: {"shot": shot, "job": job})
    code, res = run_cli(ws.root, "fetch", "@t/fetch", "--url", "https://x.example/a", "--job", "j2")
    assert code == 0 and res == {"shot": "shot01", "job": "j2"} and not got["file"].exists()


# ---------------------------------------------------------------- ingest + QC refusals
def test_ingest_clip_refuses_bad_inputs_before_spending(ws, tmp_path):
    p = Piece.create(ws, "@t", "ingest")
    p.set_state("building")
    write_json(p.rel("spec.json"), {"shots": [{"id": "shot01", "duration_s": 5}]})
    passed(p, "frames")
    with pytest.raises(FoundryError, match="invalid shot id"):
        loop.ingest_clip(ws, p, tmp_path / "a.mp4", job="j", shot="../x")
    with pytest.raises(FoundryError, match="unknown shot"):
        loop.ingest_clip(ws, p, tmp_path / "a.mp4", job="j", shot="shot02")
    with pytest.raises(FoundryError, match="no file"):
        loop.ingest_clip(ws, p, tmp_path / "missing.mp4", job="j")
    p.rel("clips").mkdir()
    (p.rel("clips", "x.mp4")).write_bytes(b"x")
    with pytest.raises(FoundryError, match="outside clips/"):
        loop.ingest_clip(ws, p, p.rel("clips", "x.mp4"), job="j")
    (tmp_path / "text.mp4").write_text("not a video")
    with pytest.raises(FoundryError, match="not a readable video"):
        loop.ingest_clip(ws, p, tmp_path / "text.mp4", job="j")
    audio = tmp_path / "tone.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "aac", str(audio)], check=True)
    with pytest.raises(FoundryError, match="no video stream"):
        loop.ingest_clip(ws, p, audio, job="j")
    short = video(tmp_path / "short.mp4", seconds=0.2)
    with pytest.raises(FoundryError, match="no settled, unused video_credits reservation"):
        loop.ingest_clip(ws, p, short, job="j")  # an unpaid clip is refused before any file is touched
    assert not p.rel("clips", ".staging-shot01").exists()
    eid = p.reserve("video_credits", 32.5, "paid")
    p.settle(eid, ok=True, ref="j")
    with pytest.raises(FoundryError, match="too short"):
        loop.ingest_clip(ws, p, short, job="j")
    assert not p.rel("clips", ".staging-shot01").exists() and not p.rel("clips", "shot01.mp4").exists()
    assert [e.get("consumed") for e in p.invoice["entries"]] == [None] and p.status["cycles"]["clip"] == 0


def test_run_qc_refuses_out_of_order_stages(ws):
    fresh = Piece.create(ws, "@t", "fresh")
    with pytest.raises(FoundryError, match="needs approved"):
        loop.run_qc(ws, fresh, "frames")
    fresh.set_state("approved")
    with pytest.raises(FoundryError, match="approve the sheet first"):
        loop.run_qc(ws, fresh, "frames")
    p = building(ws, "order")
    with pytest.raises(FoundryError, match="stage must be"):
        loop.run_qc(ws, p, "final")
    with pytest.raises(FoundryError, match="no image"):
        loop.record_region(p, "frames/nope.png", (0.1, 0.1, 0.5, 0.5))
    lock = read_json(p.rel("approved.lock.json"))
    lock.pop("inputs")  # a lock written before inputs were hashed still loads
    write_json(p.rel("approved.lock.json"), lock)
    with pytest.raises(FoundryError, match="frames QC is not green"):
        loop.run_qc(ws, p, "clip")
    passed(p, "frames")
    with pytest.raises(FoundryError, match="no clip shot01.mp4"):
        loop.run_qc(ws, p, "clip")
    passed(p, "clip")
    with pytest.raises(FoundryError, match="no finished cut"):
        loop.run_qc(ws, p, "cut")


def test_lock_blocks_when_an_approved_input_is_deleted(ws):
    p = building(ws, "gone")
    (ws.root / "clip.mp4").unlink()
    with pytest.raises(Blocked) as e:
        p.lock
    assert e.value.gate == "inputs.changed_after_approval" and "missing" in e.value.evidence
    assert p.state == "blocked"


# ---------------------------------------------------------------- regeneration
def _red_frames(p: Piece) -> None:
    write_json(p.rel("qc", "frames.json"), {"stage": "frames", "pass": False, "failed": ["skin"],
                                            "guidance": "keep warm light off the skin"})


def test_regen_frame_refusal_blocks_and_crash_still_settles(ws):
    p = building(ws, "refuse")
    _red_frames(p)

    class Refuser:
        last_attempts = 3

        def edit(self, *a, **k):
            raise ImageRefused("moderation")
    with pytest.raises(Blocked) as e:
        loop.regen_frame(ws, p, provider=Refuser())
    assert e.value.gate == "frames.safety_refused" and p.state == "blocked"
    entry = p.invoice["entries"][-1]
    assert entry["state"] == "failed" and entry["amount"] == 3.0  # every attempt may be billed

    p.set_state("building")

    class Crasher:
        def edit(self, *a, **k):
            raise RuntimeError("socket closed")
    with pytest.raises(RuntimeError, match="socket closed"):
        loop.regen_frame(ws, p, provider=Crasher())
    entry = p.invoice["entries"][-1]
    assert entry["state"] == "failed" and entry["amount"] == 1.0
    assert p.status["cycles"]["frames"] == 0 and p.state == "building"


def test_regen_frame_moves_the_old_clip_to_history(ws):
    p = building(ws, "rehist")
    loop.record_region(p, APPROVED, (0.36, 0.28, 0.64, 0.52))
    _red_frames(p)
    p.rel("clips", "shot01", "frames").mkdir(parents=True)
    p.rel("clips", "shot01.mp4").write_bytes(b"old clip")
    old_frame = p.rel(APPROVED).read_bytes()
    res = loop.regen_frame(ws, p, provider=FakeImages())
    assert res["cycle"] == 1 and p.status["cycles"]["frames"] == 1
    assert p.rel("clips", "history", "shot01-frame0.mp4").read_bytes() == b"old clip"
    assert not p.rel("clips", "shot01").exists() and not p.rel("clips", "shot01.mp4").exists()
    assert p.rel("frames", "history", "approved-0.png").read_bytes() == old_frame
    assert "CORRECTIONS FROM QC: keep warm light off the skin" in p.rel("frames", "history", "prompt-1.txt").read_text()
    assert APPROVED not in loop.regions(p) and not p.rel("qc", "frames.json").exists()
    assert p.invoice["entries"][-1]["state"] == "settled"


def test_cut_rebuild_needs_a_checked_red_cut(ws):
    p = building(ws, "recut")
    passed(p, "frames", "clip")
    p.rel("cut").mkdir()
    p.rel("cut", "final.mp4").write_bytes(b"x")
    p.rel("cut", "cut.json").write_text("{}")  # a finished cut: final.mp4 plus its manifest
    with pytest.raises(FoundryError, match="has not been checked"):
        cut_mod.build(ws, p)
    passed(p, "cut")
    with pytest.raises(FoundryError, match="nothing to regenerate"):
        cut_mod.build(ws, p)
    assert p.status["cycles"]["cut"] == 0


# ---------------------------------------------------------------- ship, posted, reap
def test_ship_posted_and_reap_edges(ws, monkeypatch):
    p = building(ws, "shipit")
    passed(p, "frames", "clip")
    p.set_state("green")
    write_json(ws.dir("pipelines") / "shipit.json", {"made_from": "@t/other"})
    with pytest.raises(FoundryError, match="was made from @t/other"):
        ship_mod.ship(ws, p)
    with pytest.raises(FoundryError, match="needs shipped"):
        ship_mod.posted(ws, p, "https://example.com/r/1")
    monkeypatch.setattr(ship_mod, "run_qc", lambda *a, **k: {"pass": False, "guidance": "Loudness -30 LUFS."})
    with pytest.raises(FoundryError, match="went red on the ship re-check: Loudness"):
        ship_mod.ship(ws, p, "fresh-name")
    assert p.state == "building" and not p.rel("publish.json").exists()
    assert not (ws.dir("pipelines") / "fresh-name.json").exists()

    p.set_state("shipped")
    write_json(p.rel("publish.json"), {"posted_at": "2026-09-16T00:00:00Z"})
    rows = ops.reap(ws, dry_run=True)
    assert [r["piece"] for r in rows] == ["@t/shipit"] and "frames" in rows[0]["removed"]
    assert p.rel("frames").exists() and p.rel(APPROVED).exists()  # a dry run deletes nothing


# ---------------------------------------------------------------- build driver
def test_headless_build_runs_the_agent_and_reports_state(ws, monkeypatch):
    cfg = read_json(ws.root / "foundry.json")
    cfg["providers"]["video"]["mcp_server"] = "higgsfield"
    write_json(ws.root / "foundry.json", cfg)
    w = workspace.load(ws.root)
    unlocked = Piece.create(w, "@t", "nolock")
    unlocked.set_state("approved")
    with pytest.raises(FoundryError, match="no approval lock"):
        build.build(w, unlocked, "bypass")
    p = Piece.create(w, "@t", "headless")
    p.set_state("approved")
    write_json(p.rel("approved.lock.json"), {"fix_cycles": 2})
    with pytest.raises(FoundryError, match="mode must be"):
        build.build(w, p, "turbo")
    monkeypatch.setattr(build.shutil, "which", lambda _: None)
    with pytest.raises(FoundryError, match="not on PATH"):
        build.build(w, p, "bypass")

    monkeypatch.setattr(build.shutil, "which", lambda _: "/usr/local/bin/claude")
    seen: dict = {}

    class Proc:
        pid = 4242
        timeouts = 0

        def __init__(self, args, cwd, env, start_new_session):
            seen.update(args=args, cwd=cwd, env=env, session=start_new_session,
                        pid_during=p.rel(".build.pid").exists())

        def wait(self, timeout=None):
            if seen.get("hang") and timeout is not None:
                raise subprocess.TimeoutExpired("claude", timeout)
            if not seen.get("hang"):
                p.set_state("green")
            return -9 if seen.get("hang") else 0
    monkeypatch.setattr(build.subprocess, "Popen", Proc)
    out = build.build(w, p, "bypass")
    assert out["exit_code"] == 0 and out["state"] == "green" and out["blocked_gate"] is None
    assert seen["env"]["FOUNDRY_AGENT"] == p.ref and seen["session"] and seen["pid_during"] and seen["cwd"] == w.root
    assert seen["args"][:2] == ["claude", "-p"] and not p.rel(".build.pid").exists()

    p.set_state("approved")
    seen["hang"] = True
    killed = []
    monkeypatch.setattr(build.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    out = build.build(w, p, "bypass")
    assert out["exit_code"] == "timeout" and killed == [(4242, 9)] and out["state"] == "approved"
    assert not p.rel(".build.pid").exists()


def test_pidfile_reclaims_garbage_and_respects_foreign_builds(tmp_path, monkeypatch):
    import os
    pid = tmp_path / ".build.pid"
    pid.write_text("not-a-pid")
    os.close(build._claim_pidfile(pid, "@t/x"))  # unreadable leftovers are reclaimed
    pid.write_text("12345")

    def denied(_pid, _sig):
        raise PermissionError("another user's process")
    monkeypatch.setattr(build.os, "kill", denied)
    with pytest.raises(FoundryError, match="already running"):
        build._claim_pidfile(pid, "@t/x")


# ---------------------------------------------------------------- CLI output and parsing
def test_cli_text_output_and_error_channels(ws, tmp_path, monkeypatch, capsys):
    root = str(ws.root)
    assert cli.main(["-C", root, "ls"]) == 0
    assert capsys.readouterr().out.strip() == "(none)"
    Piece.create(ws, "@t", "txt")
    assert cli.main(["-C", root, "status", "@t/txt"]) == 0
    out = capsys.readouterr().out
    assert "state: created" in out and 'cycles: {"frames": 0' in out
    assert cli.main(["-C", root, "status", "@t/nope"]) == 2
    err = capsys.readouterr()
    assert err.out == "" and err.err.startswith("refused: no piece")
    monkeypatch.setattr(loop, "run_qc", lambda *a, **k: (_ for _ in ()).throw(Blocked("clip.frame0", "still red")))
    assert cli.main(["-C", root, "qc", "@t/txt", "--stage", "clip"]) == 1
    assert capsys.readouterr().out.strip() == "BLOCKED clip.frame0: still red"
    monkeypatch.setattr(loop, "run_qc", lambda *a, **k: 1 / 0)
    assert cli.main(["-C", root, "qc", "@t/txt", "--stage", "clip"]) == 3
    assert capsys.readouterr().err.startswith("error: ZeroDivisionError")

    (tmp_path / "empty").mkdir()
    assert cli.main(["-C", str(tmp_path / "empty"), "doctor", "--offline"]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert any(line.split()[:2] == ["fail", "workspace"] for line in lines)
    assert any(line.startswith(" " * 8 + "  1. You need a Higgsfield account") for line in lines)  # detail continuation

    cli._print({"checks": {"skin": {"pass": False, "guidance": "too warm"}, "hands": {"pass": True}},
                "prompt": "PROMPT TEXT"}, as_json=False)
    cli._print([{"piece": "@t/a", "state": "green"}], as_json=False)
    out = capsys.readouterr().out
    assert "  FAIL  skin  too warm" in out and "  PASS  hands" in out and "PROMPT TEXT" in out
    assert "piece=@t/a  state=green" in out

    for bad in ("0.1,0.2,0.3", "a,b,c,d"):
        with pytest.raises(SystemExit):
            cli.parser().parse_args(["region", "@t/txt", APPROVED, "--face", bad])
    assert "x0,y0,x1,y1" in capsys.readouterr().err


def test_cli_prompt_carries_qc_guidance(ws):
    p = specced(ws, "guided")
    write_json(p.rel("qc", "frames.json"), {"pass": False, "guidance": "the skin reads cooler than the pack"})
    code, res = run_cli(ws.root, "prompt", p.ref, "--kind", "frame", "--guidance-from", "frames")
    assert code == 0 and "CORRECTIONS FROM QC: the skin reads cooler than the pack" in res["prompt"]
    code, res = run_cli(ws.root, "prompt", p.ref, "--kind", "frame", "--guidance-from", "clip")
    assert code == 0 and "CORRECTIONS FROM QC" not in res["prompt"]  # no clip report yet: no stale guidance
    code, res = run_cli(ws.root, "prompt", p.ref, "--kind", "motion", "--guidance-from", "frames")
    assert "CORRECTIONS FROM QC: the skin reads cooler" in res["prompt"] and res["start_image"].endswith(APPROVED)


# ---------------------------------------------------------------- doctor + services
def test_mcp_listing_unavailable_and_unreachable(monkeypatch):
    monkeypatch.setattr(services.shutil, "which", lambda _: None)
    assert services.list_mcp() is None
    monkeypatch.setattr(services.shutil, "which", lambda _: "/bin/claude")

    def hang(*a, **k):
        raise subprocess.TimeoutExpired("claude", 90)
    monkeypatch.setattr(services.subprocess, "run", hang)
    assert services.list_mcp() is None

    class Out:
        stdout = "higgsfield: https://mcp.higgsfield.ai/mcp (HTTP) - ✗ Failed to connect\nnoise line\n"
    monkeypatch.setattr(services.subprocess, "run", lambda *a, **k: Out())
    rows = services.list_mcp()
    assert [(r["name"], r["status"]) for r in rows] == [("higgsfield", "failed")]
    status, lines = services.mcp_status(services.MCP_SERVERS[0], rows)
    assert status == "todo" and "not reachable" in lines[0] and any("claude mcp add" in x for x in lines)
    status, lines = services.mcp_status(services.MCP_SERVERS[0], None)
    assert status == "todo" and "Could not ask Claude Code" in lines[0]


def test_doctor_checks_the_image_model_when_online(ws, monkeypatch):
    cfg = read_json(ws.root / "foundry.json")
    cfg["providers"]["image"] = {"kind": "openai-images", "model": "gpt-image-nope"}
    write_json(ws.root / "foundry.json", cfg)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class Model:
        def check_model(self):
            return False, "HTTP 404: model_not_found"
    monkeypatch.setattr(ops, "get_image_provider", lambda *a, **k: Model())
    monkeypatch.setattr(ops.services, "list_mcp", lambda **kw: [{"name": "higgsfield", "url": "https://mcp.higgsfield.ai/mcp",
                                                             "status": "connected", "raw": "Connected"}])
    res = ops.doctor(workspace.load(ws.root), offline=False)
    rows = {r["check"]: r for r in res["checks"]}
    assert rows["OPENAI_API_KEY"]["status"] == "ok"
    assert rows["image model gpt-image-nope"] == {"check": "image model gpt-image-nope", "status": "fail",
                                                  "detail": "HTTP 404: model_not_found"}
    assert rows["Higgsfield MCP"]["status"] == "ok" and res["status"] == "fail"
    with pytest.raises(ValueError, match="unknown image provider"):
        get_image_provider({"kind": "midjourney"})


# ---------------------------------------------------------------- resolver, sheet, cast refusals
def test_resolver_reports_bad_assets_audio_and_inputs(ws):
    locked(ws)
    video(ws.root / "mute.mp4", seconds=21)
    p = spec_mod.new(ws, "@t", "bad")
    with pytest.raises(FoundryError, match="expected slot=value"):
        spec_mod.set_values(ws, p, ["hook.line"])
    r = spec_mod.set_values(ws, p, ["hook.line=ok", "assets.0.path=assets/missing.mp4"])
    assert any("does not exist" in x for x in r["problems"])
    r = spec_mod.set_values(ws, p, ["assets.0.path=mute.mp4", "audio.kind=clip"])
    assert any("has no audio track" in x for x in r["problems"]) and not r["complete"]
    r = spec_mod.set_values(ws, p, ["audio.kind=trending", "audio.path=../../outside.mp3"])
    assert any("outside" in x for x in r["problems"])
    r = spec_mod.set_values(ws, p, ["audio.kind=silent", "audio.path=null", "shots.0.scene=no-such-scene"])
    assert any("no scene" in x for x in r["problems"])
    with pytest.raises(FoundryError, match="has no pack.json"):
        spec_mod.set_values(ws, p, ["shots.0.scene=reaction-facepalm-reveal", "creator=ghost"])
    with pytest.raises(FoundryError, match="no recipe"):
        spec_mod.new(ws, "@t", "from-nothing", recipe="never-saved")


def test_sheet_candidate_count_layout_fallback_and_missing_candidate(ws):
    p = specced(ws, "sheety")
    with pytest.raises(FoundryError, match="2 to 4"):
        sheet.render(ws, p, n=5, provider=FakeImages())

    class NoSketch(FakeImages):
        def edit(self, prompt, refs, n=1, size="1024x1536"):
            if len(refs) == 1:  # only the layout sketch is sent with the master alone
                raise ImageRefused("sketch refused")
            return super().edit(prompt, refs, n, size)
    res = sheet.render(ws, p, n=2, provider=NoSketch())
    assert res["layout_refused"] and res["candidates"] == ["c1", "c2"] and p.state == "sheet_pending"
    from PIL import Image
    assert Image.open(p.rel("sheet", "layout.png")).size == (1536, 1024)
    with pytest.raises(FoundryError, match="no candidate c3"):
        sheet.approve(ws, p, "c3")
    (ws.root / "clip.mp4").unlink()
    with pytest.raises(FoundryError, match="inputs, which are missing: asset/0"):
        sheet.approve(ws, p, "c1")
    assert p.state == "sheet_pending" and not p.rel("approved.lock.json").exists()


def test_cast_refuses_unmeasurable_faces_and_out_of_order_remeasure(ws):
    with pytest.raises(FoundryError, match="nothing to re-measure"):
        cast.remeasure(ws, "ghost")
    cast.bootstrap(ws, "mira", "original adult creator", n=2, provider=FakeImages())
    corner = (0.0, 0.0, 0.05, 0.05)  # grey backdrop only
    with pytest.raises(FoundryError, match="no measurable skin"):
        cast.pick(ws, "mira", "c1", face=corner, provider=FakeImages())
    d = ws.dir("personas") / "mira"
    st = read_json(d / "cast.json")
    write_json(d / "cast.json", {**st, "state": "blocked"})
    (d / "master.png").unlink()
    with pytest.raises(FoundryError, match="no master.png and sheet.png"):
        cast.remeasure(ws, "mira")
    shutil.copyfile(d / "candidates/c1.png", d / "master.png")
    shutil.copyfile(d / "candidates/c2.png", d / "sheet.png")
    with pytest.raises(FoundryError, match="no measurable skin"):
        cast.remeasure(ws, "mira", face=corner)
    assert not (d / "pack.json").exists()
    assert "neutral white light" in cast.skin_rule({"r_minus_b": 30, "sat_pct": 40})
    assert "cool, neutral" in cast.skin_rule({"r_minus_b": 5, "sat_pct": 10})
