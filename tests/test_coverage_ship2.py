"""Coverage pass 2: the remaining offline-testable branches (media fallbacks, QC guidance, provider errors, cut rebuilds).

Network and paid image calls are faked; ffmpeg runs for real on synthetic clips.
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import shutil
import subprocess
import urllib.error
from pathlib import Path

import pytest
from PIL import Image

from engine.providers import openai_images
from engine.providers.fake_images import FakeImages
from engine.providers.openai_images import OpenAIImages
from engine.qc import drift, loudness, skin
from foundry import caption, cast, cli, cut as cut_mod, imaging, loop, media, sheet, spec as spec_mod, workspace
from foundry.piece import APPROVED, Piece
from foundry.util import FoundryError, read_json, write_json

from .conftest import portrait, video

FACE = (0.36, 0.28, 0.64, 0.52)


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


def building(ws: workspace.Workspace, slug: str, *pairs: str) -> Piece:
    """Cast, spec (plus extra slot=value pairs), approve with a real lock, start building."""
    if not (ws.dir("personas") / "nova/pack.json").exists():
        locked(ws)
    if not (ws.root / "clip.mp4").exists():
        video(ws.root / "clip.mp4", seconds=21)
    p = spec_mod.new(ws, "@t", slug)
    res = spec_mod.set_values(ws, p, ["hook.line=ok", "assets.0.path=clip.mp4", *pairs])
    assert res["complete"], res
    p.set_state("approved")
    p.write_lock(2)
    p.set_state("building")
    p.rel("frames").mkdir(exist_ok=True)
    shutil.copyfile(ws.dir("personas") / "nova/master.png", p.rel(APPROVED))
    return p


def passed(p: Piece, *stages: str) -> None:
    for s in stages:
        write_json(p.rel("qc", f"{s}.json"), {"stage": s, "pass": True, "failed": [], "guidance": ""})


def run_cli(root: Path, *args: str) -> tuple[int, dict]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(["-C", str(root), *args, "--json"])
    out = buf.getvalue().strip()
    return code, (json.loads(out) if out else {})


def tone(path: Path, seconds: float, silent: bool = False) -> Path:
    src = "anullsrc=r=48000:cl=stereo" if silent else "sine=frequency=440:sample_rate=48000"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", str(seconds), "-i", src,
                    "-c:a", "aac", str(path)], check=True)
    return path


# ---------------------------------------------------------------- CLI dispatch + workspace + piece guards
def test_cli_dispatches_remeasure_upload_and_repeat_init(ws, monkeypatch):
    locked(ws)
    code, res = run_cli(ws.root, "cast", "nova", "--remeasure")
    assert code == 0 and res["state"] == "sheet_measured"
    assert not (ws.dir("personas") / "nova/pack.json").exists()  # re-measured numbers need approval again

    Piece.create(ws, "@t", "up")
    seen = {}
    monkeypatch.setattr(loop, "upload_approved", lambda _ws, piece, url: seen.update(ref=piece.ref, url=url) or
                        {"uploaded": APPROVED, "http": 200})
    code, res = run_cli(ws.root, "upload", "@t/up", "--url", "https://up.example.com/put")
    assert code == 0 and res["http"] == 200 and seen == {"ref": "@t/up", "url": "https://up.example.com/put"}

    before = (ws.root / "foundry.json").read_text()
    code, res = run_cli(ws.root, "init")
    assert code == 0 and res["created"] is False and (ws.root / "foundry.json").read_text() == before
    again, created = workspace.init(ws.root)
    assert created is False and again.root == ws.root


def test_piece_guards_unknown_entry_missing_spec_and_frozen_spec(ws):
    p = Piece.create(ws, "@t", "guards")
    with pytest.raises(FoundryError, match="no invoice entry e999"):
        p.settle("e999", ok=True)
    with pytest.raises(FoundryError, match="has no spec.json"):
        p.spec
    write_json(p.rel("approved.lock.json"), {"spec_sha256": "x"})
    with pytest.raises(FoundryError, match="its spec is frozen"):
        p.save_spec({"slug": "guards"})
    assert not p.rel("spec.json").exists()


# ---------------------------------------------------------------- QC branches
def test_multi_shot_clip_qc_prefixes_checks_per_shot(ws):
    locked(ws)
    first = spec_mod.hook_reel.defaults()["shots"][0]
    second = {**first, "id": "shot02"}
    p = building(ws, "multi", "captions.during=all", f"shots.1={json.dumps(second)}")
    assert [s["id"] for s in p.spec["shots"]] == ["shot01", "shot02"]
    passed(p, "frames")
    p.rel("clips").mkdir()
    for sid in ("shot01", "shot02"):
        clip = video(p.rel("clips", f"{sid}.mp4"), seconds=5)
        media.sample_frames(clip, p.rel("clips", sid, "frames"), every=10)
    rep = loop.run_qc(ws, p, "clip")
    keys = set(rep["checks"])
    assert {f"{s}.{c}" for s in ("shot01", "shot02") for c in ("frame0", "drift", "skin", "duration")} <= keys
    assert "hands" in keys and "frame0" not in keys
    assert not rep["pass"] and "regenerate clip" in rep["next"]  # a flat colour clip is not the approved frame


def test_cut_qc_fails_a_cut_rendered_at_the_wrong_size(ws):
    p = building(ws, "small")
    passed(p, "frames", "clip")
    p.rel("cut").mkdir()
    video(p.rel("cut", "final.mp4"), seconds=22, size="720x1280")
    write_json(p.rel("cut", "cut.json"), {"parts": []})
    write_json(p.rel("cut", "caption.json"), {"box": [0.12, 0.11, 0.88, 0.2]})
    rep = loop.run_qc(ws, p, "cut")
    assert rep["failed"] == ["size"] and rep["checks"]["size"]["measures"] == {"width": 720, "height": 1280}
    assert rep["guidance"] == "Render the cut at 1080x1920." and p.state == "building"


def test_skin_check_guidance_for_cool_saturated_dark_and_empty_boxes(tmp_path):
    p = portrait(tmp_path / "p.png")
    m = skin.measure_face(p, FACE)
    tol = {"lum": 2, "r_minus_b": 2, "sat_pct": 2}
    r = skin.check(p, {"lum": m["lum"] + 20, "r_minus_b": m["r_minus_b"] + 20, "sat_pct": m["sat_pct"] - 10, "tol": tol}, FACE)
    assert set(r["measures"]["failed"]) == {"lum", "r_minus_b", "sat_pct"}
    assert "cooler" in r["guidance"] and "oversaturated" in r["guidance"] and "too dark" in r["guidance"]
    r = skin.check(p, {"lum": m["lum"] - 20, "tol": tol}, FACE)
    assert "too light" in r["guidance"]
    r = skin.check(p, {"lum": 60, "tol": tol}, (0.0, 0.0, 0.1, 0.1))  # backdrop only
    assert not r["pass"] and "No skin pixels" in r["guidance"] and r["measures"]["box"] == [0.0, 0.0, 0.1, 0.1]
    with pytest.raises(ValueError, match="empty box"):
        skin.crop(skin.load_rgb(p), (0.5, 0.5, 0.5, 0.9))


def test_drift_fails_when_the_subject_leaves_the_frame(tmp_path):
    frames = [portrait(tmp_path / "f_0001.png"), portrait(tmp_path / "f_0011.png", seed=1)]
    Image.new("RGB", (512, 768), (52, 53, 55)).save(tmp_path / "f_0021.png")
    r = drift.check(frames + [tmp_path / "f_0021.png"], max_lum=12)
    assert not r["pass"] and r["measures"] == {"frame": "f_0021.png", "region": "frame"}
    assert "left the frame" in r["guidance"]


# ---------------------------------------------------------------- sheet + cut
def test_sheet_call_crash_settles_failed_and_reraises(ws):
    p = Piece.create(ws, "@t", "crash")

    class Flaky:
        last_attempts = 2

        def edit(self, *a, **k):
            raise ConnectionError("reset by peer")
    with pytest.raises(ConnectionError):
        sheet._call(p, Flaky(), "a portrait, sheer blouse", [], "1024x1536", "sheet candidate c1")
    e = p.invoice["entries"][-1]
    assert e["state"] == "failed" and e["amount"] == 2.0 and "safety rewrites: sheer" in e["note"]
    assert sheet._call(p, FakeImages(), "a portrait", [], "1024x1536", "c2")[:4] == b"\x89PNG"
    assert p.invoice["entries"][-1]["state"] == "settled"


def test_trending_cut_then_rebuild_after_red_cut_qc(ws):
    tone(ws.root / "music.m4a", 30)
    p = building(ws, "trend", "audio.kind=trending", "audio.path=music.m4a")
    passed(p, "frames", "clip")
    p.rel("clips").mkdir()
    video(p.rel("clips", "shot01.mp4"), seconds=5)
    res = cut_mod.build(ws, p)
    final = Path(res["final"])
    assert res["cycle"] == 0 and final.exists() and not p.rel("cut", "joined.mp4").exists()
    assert not list(p.rel("cut").glob("*-swapped.mp4"))
    assert abs(loudness.integrated(final) - loudness.TARGET_LUFS) <= 2
    assert read_json(p.rel("cut", "cut.json"))["audio"] == "trending"

    write_json(p.rel("qc", "cut.json"), {"stage": "cut", "pass": False, "failed": ["loudness"], "guidance": "too loud"})
    res = cut_mod.build(ws, p)
    assert res["cycle"] == 1 and p.status["cycles"]["cut"] == 1
    assert not p.rel("qc", "cut.json").exists() and read_json(p.rel("cut", "cut.json"))["cycle"] == 1
    assert Path(res["final"]).exists()


def test_cut_refuses_trending_without_a_track(ws, monkeypatch):
    p = building(ws, "notrack")
    passed(p, "frames", "clip")
    p.rel("clips").mkdir()
    video(p.rel("clips", "shot01.mp4"), seconds=5)
    real = Piece.spec.fget

    def spec_without_track(self):
        s = real(self)
        s["audio"] = {"kind": "trending"}
        return s
    monkeypatch.setattr(Piece, "spec", property(spec_without_track))
    with pytest.raises(FoundryError, match="audio.path is missing"):
        cut_mod.build(ws, p)


# ---------------------------------------------------------------- media + fonts
def test_concat_falls_back_to_reencode_when_stream_copy_fails(tmp_path, monkeypatch):
    parts = [video(tmp_path / "a.mp4", seconds=1, audio="tone"), video(tmp_path / "b.mp4", seconds=1, audio="tone")]
    real, calls = media.run, []

    def copy_fails(cmd):
        calls.append(cmd)
        if "copy" in cmd:
            raise RuntimeError("ffmpeg failed: codec parameters differ")
        return real(cmd)
    monkeypatch.setattr(media, "run", copy_fails)
    out = media.concat(parts, tmp_path / "joined.mp4")
    assert len(calls) == 2 and "libx264" in calls[1] and out.exists()
    assert not (tmp_path / "joined.txt").exists()
    from engine.qc.duration import probe
    assert probe(out)["duration"] == pytest.approx(2.0, abs=0.2)


def test_ffmpeg_failure_and_loudnorm_refusals(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        media.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp_path / "missing.mp4"), str(tmp_path / "o.mp4")])
    silent = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=2",
                    "-f", "lavfi", "-t", "2", "-i", "anullsrc=r=48000:cl=stereo", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(silent)], check=True)
    with pytest.raises(RuntimeError, match="silent"):
        media.loudnorm(silent, tmp_path / "out.mp4", -14.0)

    class NoJson:
        stderr = "Invalid data found when processing input"
    monkeypatch.setattr(media.subprocess, "run", lambda *a, **k: NoJson())
    with pytest.raises(RuntimeError, match="measurement failed"):
        media.loudnorm(silent, tmp_path / "out.mp4", -14.0)


def test_loudnorm_corrects_an_undershoot_with_plain_gain(tmp_path, monkeypatch):
    src = video(tmp_path / "t.mp4", seconds=3, audio="tone")
    import engine.qc.loudness as qc_loudness
    monkeypatch.setattr(qc_loudness, "integrated", lambda _p: -19.5)  # loudnorm fell back to dynamic mode
    real, calls = media.run, []
    monkeypatch.setattr(media, "run", lambda cmd: (calls.append(cmd), real(cmd))[1])
    out = media.loudnorm(src, tmp_path / "out.mp4", -14.0)
    gain = [c for c in calls if any("volume=5.50dB" in str(x) for x in c)]
    assert len(gain) == 1 and "alimiter" in " ".join(gain[0])
    assert out.exists() and not (tmp_path / "out-gain.mp4").exists()


def test_fonts_fall_back_to_the_pillow_default(tmp_path, monkeypatch):
    monkeypatch.setattr(imaging, "FONT_CANDIDATES", [("TikTok Sans Bold", [str(tmp_path / "nope.ttf")])])
    assert imaging.find_font("TikTok Sans Bold") == ("Pillow default", None)
    meta = caption.render({"text": "a short hook line", "font": "TikTok Sans Bold"}, tmp_path / "c.png")
    assert meta["font_used"] == "Pillow default" and meta["font_substituted"] is True and meta["lines"]
    assert imaging.font(None, 30) is not None
    with pytest.raises(ValueError, match="no images"):
        imaging.contact([], tmp_path / "contact.png")


# ---------------------------------------------------------------- OpenAI images provider (network mocked)
def _png(path: Path) -> Path:
    Image.new("RGB", (4, 4), (10, 20, 30)).save(path)
    return path


def test_openai_edit_sends_one_multipart_request_per_image(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    prov = OpenAIImages(model="gpt-image-x", quality="low", rpm_images=100, sleep=lambda s: None)
    master = _png(tmp_path / "master.png")
    sheet_ref = tmp_path / "sheet.jpg"
    Image.new("RGB", (4, 4)).save(sheet_ref, "JPEG")
    sent = []

    def post(url, body, ctype):
        sent.append((url, body, ctype))
        return {"data": [{"b64_json": base64.b64encode(b"img").decode()}]}
    monkeypatch.setattr(prov, "_post", post)
    assert prov.edit("keep the face", [master, sheet_ref], n=2, size="1536x1024") == [b"img", b"img"]
    assert len(sent) == 2 and prov.last_attempts == 2
    url, body, ctype = sent[0]
    boundary = ctype.split("boundary=")[1]
    assert url == openai_images.EDIT and ctype.startswith("multipart/form-data")
    assert body.endswith(f"--{boundary}--\r\n".encode())
    for field, value in (("model", "gpt-image-x"), ("prompt", "keep the face"), ("n", "1"), ("size", "1536x1024"),
                         ("quality", "low")):
        assert f'name="{field}"\r\n\r\n{value}\r\n'.encode() in body
    assert b'name="image[]"; filename="master.png"\r\nContent-Type: image/png' in body
    assert b'filename="sheet.jpg"\r\nContent-Type: image/jpeg' in body and master.read_bytes() in body


def test_openai_gives_up_after_5xx_and_transport_errors_and_needs_a_key(monkeypatch):
    slept = []
    prov = OpenAIImages(retries=3, rpm_images=100, sleep=slept.append)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        prov._post(openai_images.GEN, b"{}", "application/json")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def unavailable(*a):
        raise urllib.error.HTTPError("u", 503, "x", {}, io.BytesIO(b"upstream overloaded"))
    monkeypatch.setattr(prov, "_post", unavailable)
    with pytest.raises(RuntimeError, match="HTTP 503: upstream overloaded"):
        prov.generate("x")
    assert slept == [5, 10] and prov.last_attempts == 3

    slept.clear()

    def unreachable(*a):
        raise TimeoutError("read timed out")
    monkeypatch.setattr(prov, "_post", unreachable)
    with pytest.raises(RuntimeError, match="unreachable after 3 attempts: transport: read timed out"):
        prov.generate("x")
    assert slept == [5, 10]


def test_openai_check_model_reports_http_and_network_errors(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    prov = OpenAIImages(model="gpt-image-x")
    seen = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def ok(req, timeout):
        seen.append((req.full_url, req.get_header("Authorization"), timeout))
        return Resp(b'{"id": "gpt-image-x"}')
    monkeypatch.setattr(openai_images.urllib.request, "urlopen", ok)
    assert prov.check_model() == (True, "gpt-image-x")
    assert seen == [(openai_images.MODELS + "gpt-image-x", "Bearer sk-test", 20)]

    def missing(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b'{"error":"model_not_found"}'))
    monkeypatch.setattr(openai_images.urllib.request, "urlopen", missing)
    assert prov.check_model() == (False, 'HTTP 404: {"error":"model_not_found"}')

    def offline(req, timeout):
        raise urllib.error.URLError("nodename nor servname provided")
    monkeypatch.setattr(openai_images.urllib.request, "urlopen", offline)
    assert prov.check_model() == (False, "network: nodename nor servname provided")
