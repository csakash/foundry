from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from engine import formats
from engine.qc import skin
from engine.providers.fake_images import FakeImages
from foundry import build, caption, cast, spec as spec_mod, util, workspace
from foundry.piece import Piece
from foundry.util import Blocked, FoundryError, read_json, write_json

from PIL import Image

from .conftest import video


@pytest.fixture
def ws(tmp_path: Path) -> workspace.Workspace:
    w, _ = workspace.init(tmp_path / "ws")
    cfg = read_json(w.root / "foundry.json")
    cfg["providers"]["image"] = {"kind": "fake"}
    write_json(w.root / "foundry.json", cfg)
    return workspace.load(w.root)


def locked(ws: workspace.Workspace, name: str) -> None:
    cast.bootstrap(ws, name, "original adult creator", n=2, provider=FakeImages())
    cast.pick(ws, name, "c1", provider=FakeImages())
    cast.approve(ws, name)


# ---------------------------------------------------------------- workspace + util
def test_version_pinning():
    assert workspace.version_ok("0.1.x", "0.1.7")
    assert workspace.version_ok("0.1.0", "0.1.0")
    assert not workspace.version_ok("0.2.x", "0.1.0")
    assert not workspace.version_ok("0.1.x", "0.10.0")


def test_load_refuses_version_mismatch(ws):
    cfg = read_json(ws.root / "foundry.json")
    cfg["requires"] = "9.9.x"
    write_json(ws.root / "foundry.json", cfg)
    with pytest.raises(FoundryError, match="requires foundry 9.9.x"):
        workspace.load(ws.root)
    with pytest.raises(FoundryError, match="foundry init"):
        workspace.load(ws.root.parent)


def test_dotenv_does_not_override(tmp_path, monkeypatch):
    monkeypatch.setenv("FOUNDRY_T1", "from-env")
    monkeypatch.delenv("FOUNDRY_T2", raising=False)
    (tmp_path / ".env").write_text("# c\nFOUNDRY_T1=file\nexport FOUNDRY_T2='quoted value'\nbad line\n")
    assert util.load_dotenv(tmp_path / ".env") == ["FOUNDRY_T2"]
    assert os.environ["FOUNDRY_T1"] == "from-env" and os.environ["FOUNDRY_T2"] == "quoted value"
    monkeypatch.delenv("FOUNDRY_T2")


def test_dotenv_values_with_spaces_and_comments(tmp_path, monkeypatch):
    for k in ("FT_A", "FT_B", "FT_C"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / ".env").write_text("FT_A=\"quoted\"   \nFT_B=plain value  # a comment\nFT_C='has # inside'\n")
    util.load_dotenv(tmp_path / ".env")
    assert (os.environ["FT_A"], os.environ["FT_B"], os.environ["FT_C"]) == ("quoted", "plain value", "has # inside")
    for k in ("FT_A", "FT_B", "FT_C"):
        monkeypatch.delenv(k, raising=False)


def test_rate_window_is_shared_across_processes(tmp_path):
    from engine.providers.openai_images import OpenAIImages
    waits = []
    a = OpenAIImages(rpm_images=2, state_file=tmp_path / "rate.json", sleep=waits.append)
    b = OpenAIImages(rpm_images=2, state_file=tmp_path / "rate.json", sleep=waits.append)
    assert a._take(2) == 0.0
    assert b._take(1) > 50  # b sees a's slots


def test_drift_catches_a_face_only_change(tmp_path):
    from engine.qc import drift
    from .conftest import portrait
    frames = [portrait(tmp_path / f"f{i}.png", seed=i) for i in range(3)]
    frames.append(portrait(tmp_path / "changed.png", skin=(95, 70, 55), seed=9))  # skin warmer and lighter, backdrop same
    whole = drift.check(frames, max_lum=12, max_rb=12)
    boxed = drift.check(frames, max_lum=12, max_rb=12, face_box=(0.36, 0.28, 0.64, 0.52))
    assert not boxed["pass"] and boxed["measures"]["face"]["max_rb"] >= whole["measures"]["frame"]["max_rb"]


def test_dotted_paths_and_values():
    d: dict = {}
    util.set_path(d, "assets.0.path", "a.mp4")
    util.set_path(d, "hook.line", "x")
    assert d == {"assets": [{"path": "a.mp4"}], "hook": {"line": "x"}}
    assert util.get_path(d, "assets.0.path") == "a.mp4" and util.get_path(d, "assets.3.path") is None
    assert util.parse_value("[0, 20]") == [0, 20] and util.parse_value("hello world") == "hello world"


# ---------------------------------------------------------------- invoice
def test_invoice_reserve_settle_and_ceiling(ws):
    p = Piece.create(ws, "@t", "inv")
    e1 = p.reserve("video_credits", 32.5, "before approval: no ceiling")
    p.settle(e1, ok=False)
    assert p.spent("video_credits") == 32.5  # a failed call may still be billed
    with pytest.raises(FoundryError, match="already failed"):
        p.settle(e1, ok=True)
    inv = p.invoice
    inv.update(frozen=True, ceilings={"video_credits": 40}, baseline={"video_credits": 32.5})
    write_json(p.rel("invoice.json"), inv)
    e2 = p.reserve("video_credits", 32.5, "first after approval")
    with pytest.raises(FoundryError, match="never lowered"):
        p.settle(e2, ok=True, actual=1)
    with pytest.raises(Blocked, match="budget.video_credits"):
        p.reserve("video_credits", 32.5, "second")
    assert p.state == "blocked"
    with pytest.raises(FoundryError):
        p.reserve("video_credits", 0, "zero")


def test_piece_refuses_bad_account_and_duplicates(ws):
    with pytest.raises(FoundryError):
        Piece.create(ws, "noat", "x")
    Piece.create(ws, "@t", "dup")
    with pytest.raises(FoundryError):
        Piece.create(ws, "@t", "dup")


# ---------------------------------------------------------------- resolver
def test_resolver_requires_a_cast_creator(ws):
    with pytest.raises(FoundryError, match="cast"):
        spec_mod.new(ws, "@t", "nocreator") and spec_mod.resolve(ws, Piece.open(ws, "@t/nocreator"))


def test_resolver_single_creator_asks_two(ws):
    locked(ws, "nova")
    p = spec_mod.new(ws, "@t", "one")
    r = spec_mod.resolve(ws, p)
    assert [q["id"] for q in r["questions"]] == ["hook", "assets"]
    s = p.spec
    assert s["creator"] == "nova" and s["resolved_from"]["creator"] == "only_option"
    assert s["qc_targets"]["skin"]["tol"]["lum"] == 12 and s["resolved_from"]["qc_targets.skin"] == "pack"


def test_resolver_two_creators_asks_which(ws):
    locked(ws, "nova")
    locked(ws, "orion")
    r = spec_mod.resolve(ws, spec_mod.new(ws, "@t", "two"))
    q = next(q for q in r["questions"] if q["id"] == "creator")
    assert q["options"] == ["nova", "orion"] and len(r["questions"]) == 3


def test_resolver_problems_and_warnings(ws):
    locked(ws, "nova")
    (ws.dir("accounts") / "@t").mkdir(parents=True)
    write_json(ws.dir("accounts") / "@t" / "charter.json", {"never_list": ["No 'get rich' promises."]})
    (ws.root / "notes.txt").write_text("x")
    p = spec_mod.new(ws, "@t", "warn")
    r = spec_mod.set_values(ws, p, ["hook.line=How I get rich — fast", "assets.0.path=notes.txt"], touch=True)
    assert not r["complete"] and any("not a video" in x for x in r["problems"])
    assert any("get rich" in x for x in r["problems"]) and any("dash" in x for x in r["problems"])
    long_line = "word " * 60
    r = spec_mod.set_values(ws, p, [f"hook.line={long_line.strip()}"])
    assert any(x.startswith("caption:") or "characters" in x for x in r["problems"])
    assert p.status["touches"] == 1 and p.state == "created"


def test_resolver_complete_sets_budget_and_state(ws):
    locked(ws, "nova")
    video(ws.root / "clip.mp4", seconds=21)
    p = spec_mod.new(ws, "@t", "done")
    r = spec_mod.set_values(ws, p, ["hook.line=ok", "assets.0.path=clip.mp4"])
    assert r["complete"] and p.state == "specced"
    b = p.spec["budget"]
    assert b["planned"] == {"image_call": 4.0, "video_credits": 32.5}
    assert b["ceiling"] == {"image_call": 12.0, "video_credits": 97.5}
    assert p.spec["structure"][-1]["t"] == [5, 25]
    md = (p.path / "SPEC.md").read_text()
    assert md.count("**unresolved**") == 0 and "State: **specced**" in md


def test_set_reopens_and_freezes(ws):
    locked(ws, "nova")
    video(ws.root / "clip.mp4", seconds=21)
    p = spec_mod.new(ws, "@t", "freeze")
    spec_mod.set_values(ws, p, ["hook.line=ok", "assets.0.path=clip.mp4"])
    p.set_state("approved")
    with pytest.raises(FoundryError, match="frozen"):
        spec_mod.set_values(ws, p, ["hook.line=changed"])


def test_prompts_render_from_pack_and_scene(ws):
    locked(ws, "nova")
    video(ws.root / "clip.mp4", seconds=21)
    p = spec_mod.new(ws, "@t", "prompts")
    spec_mod.set_values(ws, p, ["hook.line=ok line", "assets.0.path=clip.mp4"])
    s = p.spec
    ff = spec_mod.first_frame_prompt(ws, s, guidance="skin drifted warm")
    assert "EXACT SAME PERSON, Nova" in ff and "CORRECTIONS FROM QC: skin drifted warm" in ff
    assert "{" not in ff
    mo = spec_mod.motion_prompt(ws, s)
    assert mo.count(" s: Nova ") == 5 and "{" not in mo
    assert '"ok line"' in spec_mod.layout_prompt(s)


# ---------------------------------------------------------------- cast
def test_cast_touch_counting_and_order(ws):
    with pytest.raises(FoundryError):
        cast.pick(ws, "nova", "c1", provider=FakeImages())
    cast.bootstrap(ws, "nova", "original adult creator", n=2, provider=FakeImages())
    with pytest.raises(FoundryError):
        cast.approve(ws, "nova")
    with pytest.raises(FoundryError):
        cast.pick(ws, "nova", "c9", provider=FakeImages())
    cast.pick(ws, "nova", "c2", provider=FakeImages())
    pack = cast.approve(ws, "nova", story="s", wardrobe="grey tee")
    assert pack["cast_touches"] == 2 and pack["wardrobe_default"] == "grey tee"
    with pytest.raises(FoundryError, match="already locked"):
        cast.bootstrap(ws, "nova", "again", provider=FakeImages())


def test_cast_bootstrap_applies_safety_rewrites(ws):
    fake = FakeImages()
    cast.bootstrap(ws, "lint", "wears a sheer blouse", n=2, provider=fake)
    assert "sheer" not in fake.calls[0]["prompt"] and "opaque blouse" in fake.calls[0]["prompt"]


# ---------------------------------------------------------------- caption
def test_caption_numbers_and_band(tmp_path):
    meta = caption.render({"text": "I made my monthly salary in just a few minutes using this app", "font": "TikTok Sans Bold",
                           "size_pct_w": 6.6, "band_start_pct_h": 11, "stroke_pct": 12.5}, tmp_path / "c.png")
    assert meta["font_px"] == 71 and len(meta["lines"]) >= 2
    x0, y0, x1, y1 = meta["box"]
    assert 0.10 <= x0 and x1 <= 0.90 and 0.105 <= y0 <= 0.13
    assert meta["font_substituted"] == (meta["font_used"] != "TikTok Sans Bold")
    assert json.loads((tmp_path / "c.json").read_text())["box"] == meta["box"]


# ---------------------------------------------------------------- build modes
def test_build_modes(ws):
    locked(ws, "nova")
    video(ws.root / "clip.mp4", seconds=21)
    p = spec_mod.new(ws, "@t", "modes")
    spec_mod.set_values(ws, p, ["hook.line=ok", "assets.0.path=clip.mp4"])
    with pytest.raises(FoundryError, match="approved sheet"):
        build.build(ws, p, "bypass", dry_run=True)
    p.set_state("approved")
    p.write_lock(2)
    with pytest.raises(FoundryError, match="autonomous"):
        build.build(ws, p, "autonomous", dry_run=True)
    with pytest.raises(FoundryError, match="mcp_server"):
        build.build(ws, p, "bypass", dry_run=True)
    cfg = read_json(ws.root / "foundry.json")
    cfg["providers"]["video"]["mcp_server"] = "higgs field; Write"
    write_json(ws.root / "foundry.json", cfg)
    with pytest.raises(FoundryError, match="must match"):
        build.build(workspace.load(ws.root), p, "bypass", dry_run=True)
    cfg["providers"]["video"]["mcp_server"] = "higgsfield"
    write_json(ws.root / "foundry.json", cfg)
    out = build.build(workspace.load(ws.root), p, "bypass", cycles=3, dry_run=True)
    a = out["argv"]
    assert a[a.index("--permission-mode") + 1] == "dontAsk"
    allowed = a[a.index("--allowedTools") + 1:a.index("--disallowedTools")]
    assert allowed[:2] == ["Bash(foundry:*)", "Read(./work/**)"]
    assert set(allowed[2:]) == {f"mcp__higgsfield__{t}" for t in build.VIDEO_TOOLS} and "mcp__higgsfield" not in allowed
    denied = set(a[a.index("--disallowedTools") + 1:])
    assert {"Edit", "Write", "Read(./.env)", "Bash(foundry ship:*)", "Bash(foundry approve:*)"} <= denied
    assert "3 regeneration(s)" in out["prompt"] and p.lock["fix_cycles"] == 2  # dry run persists nothing
    assert build.build(ws, p, "interactive")["next"].startswith("run /foundry-build")


def test_agent_env_refuses_build(ws, monkeypatch):
    monkeypatch.setenv("FOUNDRY_AGENT", "1")
    p = Piece.create(ws, "@t", "nested")
    with pytest.raises(FoundryError, match="human step"):
        build.build(ws, p, "bypass", dry_run=True)


# ---------------------------------------------------------------- guards
@pytest.mark.parametrize("fn,args", [
    ("check_name", ("@a/../b", util.ACCOUNT_RE, "account")),
    ("check_name", ("Bad Slug", util.SLUG_RE, "slug")),
    ("check_name", ("c0", util.CANDIDATE_RE, "candidate")),
    ("check_name", ("shot/01", util.SHOT_RE, "shot")),
])
def test_name_guards(fn, args):
    with pytest.raises(FoundryError, match="invalid"):
        getattr(util, fn)(*args)


def test_inside_guard(tmp_path):
    (tmp_path / "a").mkdir()
    assert util.inside(tmp_path, "a", "x") == (tmp_path / "a").resolve()
    for bad in ("../x", "/etc/hosts", "a/../../x"):
        with pytest.raises(FoundryError, match="outside"):
            util.inside(tmp_path, bad, "x")


def test_region_and_verdict_validation(ws):
    from foundry import loop
    p = Piece.create(ws, "@t", "obs")
    (p.path / "frames").mkdir()
    Image.new("RGB", (10, 10)).save(p.path / "frames/approved.png")
    for bad in ((0.6, 0.2, 0.4, 0.5), (0, 0, 1.2, 1)):
        with pytest.raises(FoundryError, match="face box"):
            loop.record_region(p, "frames/approved.png", bad)
    with pytest.raises(FoundryError, match="outside"):
        loop.record_region(p, "../../../foundry.json", (0.1, 0.1, 0.5, 0.5))
    assert loop.record_region(p, "./frames/approved.png", (0.1, 0.1, 0.5, 0.5))["face"] == [0.1, 0.1, 0.5, 0.5]
    assert "frames/approved.png" in loop.regions(p)
    with pytest.raises(FoundryError):
        loop.record_verdict(p, "skin", "frames", True)
    with pytest.raises(FoundryError):
        loop.record_verdict(p, "hands", "cut", True)


def test_concat_escapes_quotes(tmp_path):
    from foundry import media
    d = tmp_path / "o'neil"
    d.mkdir()
    parts = [video(d / "a.mp4", seconds=1, audio="tone"), video(d / "b.mp4", seconds=1, audio="tone")]
    out = media.concat(parts, d / "joined.mp4")
    from engine.qc.duration import probe
    assert probe(out)["duration"] == pytest.approx(2.0, abs=0.2)
    with pytest.raises(ValueError):
        media._concat_escape(Path("bad\nname"))


# ---------------------------------------------------------------- providers + doctor
def test_openai_retries_moderation_then_refuses(monkeypatch):
    import io as _io
    import urllib.error
    from engine.providers.openai_images import ImageRefused, OpenAIImages
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    calls = []
    prov = OpenAIImages(retries=3, rpm_images=100, sleep=lambda s: None)

    def refuse(*a):
        calls.append(1)
        raise urllib.error.HTTPError("u", 400, "x", {}, _io.BytesIO(b'{"error":"moderation_blocked"}'))
    monkeypatch.setattr(prov, "_post", refuse)
    with pytest.raises(ImageRefused):
        prov.generate("x")
    assert len(calls) == 3

    def bad_request(*a):
        raise urllib.error.HTTPError("u", 400, "x", {}, _io.BytesIO(b'{"error":"invalid size"}'))
    monkeypatch.setattr(prov, "_post", bad_request)
    with pytest.raises(RuntimeError, match="HTTP 400"):
        prov.generate("x")


def test_openai_n_is_one_per_request_and_429_waits(monkeypatch):
    import base64 as _b64
    import io as _io
    import json as _json
    import urllib.error
    from engine.providers.openai_images import OpenAIImages
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    slept, bodies = [], []
    prov = OpenAIImages(retries=3, rpm_images=100, sleep=slept.append)
    state = {"n": 0}

    def post(url, body, ctype):
        state["n"] += 1
        bodies.append(body)
        if state["n"] == 1:
            raise urllib.error.HTTPError("u", 429, "x", {}, _io.BytesIO(b"rate"))
        if state["n"] == 2:
            raise urllib.error.URLError("reset")
        return {"data": [{"b64_json": _b64.b64encode(b"png").decode()}]}
    monkeypatch.setattr(prov, "_post", post)
    assert prov.generate("x", n=2) == [b"png", b"png"]
    assert all(_json.loads(b)["n"] == 1 for b in bodies)
    assert slept[0] == 62


def test_doctor_offline(ws, monkeypatch):
    from foundry import ops
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fake = ops.doctor(ws, offline=True)
    assert any(r["check"] == "image provider" and r["status"] == "warn" for r in fake["checks"])
    higgs = next(r for r in fake["checks"] if r["check"] == "Higgsfield MCP")
    assert higgs["status"] == "todo" and "https://mcp.higgsfield.ai/mcp" in higgs["detail"]
    assert fake["status"] == "action needed"
    cfg = read_json(ws.root / "foundry.json")
    cfg["providers"]["image"] = {"kind": "openai-images"}
    write_json(ws.root / "foundry.json", cfg)
    real = ops.doctor(workspace.load(ws.root), offline=True)
    assert real["status"] == "fail"
    key = next(r for r in real["checks"] if r["check"] == "OPENAI_API_KEY")
    assert key["status"] == "fail" and "https://platform.openai.com/api-keys" in key["detail"]
    assert ops.doctor(None, offline=True)["status"] == "fail"


def test_doctor_reads_the_mcp_connection(monkeypatch):
    from foundry import services
    listing = """Checking MCP server health...

claude.ai Apify: https://mcp.apify.com - ✓ Connected
claude.ai Higgsfield: https://mcp.higgsfield.ai/mcp - ✓ Connected
openseo: https://app.openseo.so/mcp (HTTP) - ! Needs authentication
"""

    class Done:
        stdout = listing
    monkeypatch.setattr(services.shutil, "which", lambda _: "/bin/claude")
    monkeypatch.setattr(services.subprocess, "run", lambda *a, **k: Done())
    rows = services.list_mcp()
    assert [r["status"] for r in rows] == ["connected", "connected", "needs_auth"]
    higgs = services.MCP_SERVERS[0]
    assert services.mcp_status(higgs, rows) == ("ok", ["connected as 'claude.ai Higgsfield' (https://mcp.higgsfield.ai/mcp)"])
    auth = [{"name": "higgsfield", "url": "https://mcp.higgsfield.ai/mcp", "status": "needs_auth", "raw": "! Needs authentication"}]
    status, lines = services.mcp_status(higgs, auth)
    assert status == "todo" and "/mcp" in lines[0]
    status, lines = services.mcp_status(higgs, rows[:1])
    assert status == "todo" and any("claude mcp add --transport http higgsfield" in x for x in lines)
    assert any(services.CLAUDE_CONNECTORS_URL in x for x in lines)


# ---------------------------------------------------------------- formats router
def test_hook_reel_registered_and_ready():
    f = formats.BY_KEY["hook_reel"]
    row = next(r for r in formats.readiness() if r["key"] == "hook_reel")
    assert f.composition == "none" and row["composition_registered"] and row["ready"], row


# ---------------------------------------------------------------- sheet gate v2 (face finding)
def _face_image(size, faces, skin=(170, 125, 100), hair=(45, 32, 25), bg=(128, 128, 128)):
    """Grey backdrop; for each (cx, cy, fw) a hair block, a skin oval and two eyes and a mouth to match on."""
    im = Image.new("RGB", size, bg)
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    W, H = size
    for cx, cy, fw in faces:
        fw_px, fh_px = fw * W, fw * W * 1.3
        x0, y0 = cx * W - fw_px / 2, cy * H - fh_px / 2
        d.rectangle([x0 - fw_px * 0.3, y0 - fh_px * 0.2, x0 + fw_px * 1.3, y0 + fh_px * 1.5], fill=hair)
        d.ellipse([x0, y0, x0 + fw_px, y0 + fh_px], fill=skin)
        for ex in (0.3, 0.7):
            d.ellipse([x0 + fw_px * (ex - 0.08), y0 + fh_px * 0.38, x0 + fw_px * (ex + 0.08), y0 + fh_px * 0.46], fill=(40, 30, 28))
        d.rectangle([x0 + fw_px * 0.35, y0 + fh_px * 0.72, x0 + fw_px * 0.65, y0 + fh_px * 0.76], fill=(120, 60, 60))
    return im


def _write_cast(ws, name, master_faces, sheet_faces, sheet_skin=(170, 125, 100), face=(0.28, 0.18, 0.72, 0.62)):
    d = ws.dir("personas") / name
    (d / "candidates").mkdir(parents=True, exist_ok=True)
    _face_image((1024, 1536), master_faces).save(d / "master.png")
    SW, SH = 1536, 1024
    top = cast.SHEET_TOP_ROW
    faces = []
    for i, (dx, dy, fw) in enumerate(sheet_faces):
        if dx is None:
            continue
        cx = (i + 0.5 + dx) / cast.SHEET_PANELS
        cy = top[1] + (top[3] - top[1]) * dy
        faces.append((cx, cy, fw / cast.SHEET_PANELS))
    _face_image((SW, SH), faces, skin=sheet_skin).save(d / "sheet.png")
    write_json(d / "cast.json", {"name": name, "state": "blocked", "blocked_gate": "sheet_drift", "touches": 1,
                                 "calls": [], "master_from": "c1", "face_box": list(face)})
    return d


MASTER = [(0.5, 0.40, 0.44)]


def test_facefind_locates_a_moved_and_resized_face():
    from engine.qc import facefind
    master = _face_image((1024, 1536), MASTER)
    panel = _face_image((220, 320), [(0.62, 0.62, 0.45)])  # lower right, smaller share of the image
    r = facefind.locate(panel, master, (0.28, 0.18, 0.72, 0.62))
    assert r["confident"] and abs((r["box"][0] + r["box"][2]) / 2 - 0.62) < 0.1 and abs((r["box"][1] + r["box"][3]) / 2 - 0.62) < 0.1
    assert not facefind.locate(Image.new("RGB", (220, 320), (128, 128, 128)), master, (0.28, 0.18, 0.72, 0.62))["confident"]


def test_sheet_with_long_dark_hair_and_low_faces_passes(ws):
    """Michelle (hair fills the panels) and Imani (faces sit low) both used to be at the mercy of layout."""
    placements = [(0, 0.45, 0.55), (0.05, 0.5, 0.5), (None, 0, 0), (0, 0.62, 0.45), (None, 0, 0), (0, 0.55, 0.5), (-0.05, 0.6, 0.5)]
    _write_cast(ws, "hairy", MASTER, placements)
    st = cast.remeasure(ws, "hairy")
    m = read_json(ws.dir("personas") / "hairy/measure.json")
    assert st["state"] == "sheet_measured", m["failed"]
    assert len(m["sheet"]["matched_panels"]) >= 4 and abs(m["sheet"]["row"]["lum"] - m["master"]["lum"]) <= 12
    old_whole_row = skin.measure_array(skin.crop(skin.load_rgb(ws.dir("personas") / "hairy/sheet.png"), cast.SHEET_TOP_ROW))
    assert m["master"]["lum"] - old_whole_row["lum"] > 12  # the v1 measurement would have blocked this sheet
    pack = cast.approve(ws, "hairy")
    assert pack["qc_targets"]["method"] == cast.METHOD and pack["skin_box"] and pack["sheet_check"]["gate"] == "measured"


def test_sheet_with_really_different_skin_still_blocks(ws):
    placements = [(0, 0.5, 0.5)] * 7
    _write_cast(ws, "drifted", MASTER, placements, sheet_skin=(235, 205, 190))
    with pytest.raises(Blocked) as e:
        cast.remeasure(ws, "drifted")
    assert e.value.gate == "sheet_drift"
    with pytest.raises(FoundryError, match="cannot be approved by eye"):
        cast.approve(ws, "drifted", visual_check="looks fine to me")
    assert not (ws.dir("personas") / "drifted/pack.json").exists()


def test_unmeasurable_sheet_needs_a_human_look(ws):
    _write_cast(ws, "blank", MASTER, [(None, 0, 0)] * 7)
    with pytest.raises(Blocked) as e:
        cast.remeasure(ws, "blank")
    assert e.value.gate == "sheet_unmeasurable" and "--visual-check" in e.value.evidence
    with pytest.raises(FoundryError, match="visual-check"):
        cast.approve(ws, "blank")
    pack = cast.approve(ws, "blank", visual_check="same face, same skin in all seven heads")
    assert pack["sheet_check"]["gate"] == "sheet_unmeasurable" and "same face" in pack["sheet_check"]["note"]


def test_remeasure_a_locked_pack_requires_approval_again(ws):
    _write_cast(ws, "relock", MASTER, [(0, 0.5, 0.5)] * 7)
    cast.remeasure(ws, "relock")
    cast.approve(ws, "relock")
    assert (ws.dir("personas") / "relock/pack.json").exists()
    assert cast.remeasure(ws, "relock", face=(0.3, 0.2, 0.7, 0.6))["state"] == "sheet_measured"
    assert not (ws.dir("personas") / "relock/pack.json").exists()


def test_specs_refuse_packs_measured_the_old_way(ws):
    locked(ws, "nova")
    pack = read_json(ws.dir("personas") / "nova/pack.json")
    pack["qc_targets"]["method"] = "engine.qc.skin face-box v1"
    write_json(ws.dir("personas") / "nova/pack.json", pack)
    r = spec_mod.resolve(ws, spec_mod.new(ws, "@t", "oldpack"))
    assert any("--remeasure" in x for x in r["problems"])


REAL_CASTS = [("michelle", Path(os.environ.get("FOUNDRY_MICHELLE_DIR", "/Users/akashmunshi/foundry-test/personas/michelle")),
               (0.33, 0.19, 0.67, 0.57)),
              ("imani", Path(os.environ.get("FOUNDRY_CALIBRATION_DIR", "/Users/akashmunshi/gmm-contents")) / "personas/imani",
               (0.36, 0.27, 0.64, 0.52))]


@pytest.mark.parametrize("name,d,face", REAL_CASTS)
def test_real_sheets_pass_the_v2_gate(name, d, face):
    if not (d / "sheet.png").exists():
        pytest.skip(f"{name} images not on this machine")
    master = skin.measure_face(d / "master.png", face)
    sheet = cast.measure_sheet(d / "sheet.png", d / "master.png", face)
    assert len(sheet["matched_panels"]) >= cast.MIN_MATCHED_PANELS
    assert abs(sheet["row"]["lum"] - master["lum"]) <= 12, (sheet["row"], master)
    assert abs(sheet["row"]["r_minus_b"] - master["r_minus_b"]) <= 16
