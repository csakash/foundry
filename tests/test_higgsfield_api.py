"""SPEC.md "Higgsfield API route": the client contract, the route rule, and `foundry generate` end to end.

No network: the client's `send` is a fake, and `foundry.video.make_client`, `loop.put_presigned` and
`loop.download_clip` are replaced for the generate tests.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from engine.providers.higgsfield_api import HiggsfieldAPI, HiggsfieldError, credentials, price_usd
from foundry import loop, ops, video, workspace
from foundry.piece import Piece
from foundry.util import read_json, write_json

from .test_e2e_offline import approved_piece, cast_nova, clip_from, pass_frames, sh, ws  # noqa: F401

KEY = "kid:secret"


# ---------------------------------------------------------------- client
class Wire:
    """A scripted `send`: each call pops the next (status, body[, headers]) and records the request."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def __call__(self, method, url, body, headers, timeout):
        self.calls.append({"method": method, "url": url, "body": json.loads(body) if body else None,
                           "headers": dict(headers)})
        r = self.replies.pop(0)
        if isinstance(r, BaseException):
            raise r
        status, payload, *rh = r
        return status, (rh[0] if rh else {"X-Correlation-ID": "cid-1"}), json.dumps(payload).encode()


def api(wire, **kw) -> HiggsfieldAPI:
    clock = kw.pop("clock", None) or iter(range(0, 10_000, 1)).__next__
    return HiggsfieldAPI(KEY, send=wire, sleep=lambda s: None, clock=lambda: float(clock()), **kw)


def test_credentials_follow_the_sdk():
    assert credentials({"HF_KEY": " a:b "}) == "a:b"
    assert credentials({"HF_API_KEY": "a", "HF_API_SECRET": "b"}) == "a:b"
    assert credentials({"HF_API_KEY": "a"}) is None and credentials({}) is None


def test_price_is_token_metered_and_rounds_up():
    assert price_usd(5, "720p") == 2.32  # ceil(5*720*1280*24/1024) = 108,000 tokens * $0.0214/1k = 2.3112
    assert price_usd(10, "720p") == 4.63
    assert price_usd(5, "480p") == 1.03
    with pytest.raises(ValueError):
        price_usd(5, "1080p")


def test_key_only_goes_to_the_api_host_and_never_prints():
    w = Wire((200, {"status": "queued"}))
    c = api(w)
    assert "secret" not in repr(c)
    c.status("https://api.higgsfield.ai/requests/r1/status")
    assert w.calls[0]["headers"]["Authorization"] == "Key kid:secret"
    for bad in ("https://evil.example/requests/r1/status", "http://api.higgsfield.ai/requests/r1/status"):
        with pytest.raises(HiggsfieldError, match="refusing to send credentials"):
            c.status(bad)
    assert len(w.calls) == 1


def test_submit_is_sent_exactly_once_and_ambiguity_is_flagged():
    ok = {"request_id": "r1", "status_url": "https://api.higgsfield.ai/requests/r1/status"}
    w = Wire((200, ok))
    assert api(w).submit({"image_url": "x"})["request_id"] == "r1" and len(w.calls) == 1

    for reply in (TimeoutError("slow"), (500, {"detail": "boom"}), (502, {}), (504, {})):
        w = Wire(reply)
        with pytest.raises(HiggsfieldError) as e:
            api(w).submit({})
        assert e.value.ambiguous and len(w.calls) == 1, reply

    for code in (400, 401, 403, 404, 422, 423, 503):
        w = Wire((code, {"detail": "no"}))
        with pytest.raises(HiggsfieldError) as e:
            api(w).submit({})
        assert not e.value.ambiguous and e.value.status == code and len(w.calls) == 1

    # accepted, but the status URL points elsewhere / the body is unreadable: billed, so ambiguous
    w = Wire((200, {"request_id": "r2", "status_url": "https://evil.example/s"}))
    with pytest.raises(HiggsfieldError) as e:
        api(w).submit({})
    assert e.value.ambiguous


def test_status_retries_reads_and_stops_at_the_deadline():
    w = Wire((503, {}), TimeoutError("x"), (200, {"status": "in_progress"}))
    assert api(w).status("https://api.higgsfield.ai/requests/r/status")["status"] == "in_progress"
    assert len(w.calls) == 3
    with pytest.raises(HiggsfieldError) as e:
        api(Wire((404, {"detail": "nope"}))).status("https://api.higgsfield.ai/requests/r/status")
    assert e.value.status == 404 and not e.value.pending
    ticks = iter([0, 100])  # one retry at t=0, then past the deadline
    with pytest.raises(HiggsfieldError) as e:
        api(Wire((500, {}), (500, {})), clock=lambda: next(ticks)).status(
            "https://api.higgsfield.ai/requests/r/status", deadline=5)
    assert e.value.pending


def test_wait_polls_to_terminal_and_reports_a_timeout_as_pending():
    url = "https://api.higgsfield.ai/requests/r/status"
    w = Wire((200, {"status": "queued"}), (200, {"status": "in_progress"}),
             (200, {"status": "completed", "video": {"url": "https://cdn.example/o.mp4"}}))
    assert api(w).wait(url, 600)["video"]["url"].endswith("o.mp4")
    ticks = iter([0, 0, 50])  # deadline set at 0, one more poll, then past it
    with pytest.raises(HiggsfieldError) as e:
        api(Wire((200, {"status": "queued"}), (200, {"status": "queued"})), clock=lambda: next(ticks)).wait(url, 10)
    assert e.value.pending


# ---------------------------------------------------------------- fake API for generate
class FakeAPI:
    endpoint = "bytedance/seedance-2.5/image-to-video"

    def __init__(self, estimate=None, submit=None, polls=None, pending_first=False):
        self._estimate = estimate
        self._submit = submit
        self.polls = polls or [{"status": "completed", "request_id": "r1",
                                "video": {"url": "https://cdn.example/out.mp4"}}]
        self.pending_first = pending_first
        self.calls = {"estimate": 0, "upload_url": 0, "submit": 0, "wait": 0}
        self.submitted: list[dict] = []

    def estimate(self, args):
        self.calls["estimate"] += 1
        if isinstance(self._estimate, BaseException):
            raise self._estimate
        return {"type": "description"}

    def upload_url(self, content_type="image/png"):
        self.calls["upload_url"] += 1
        return {"public_url": "https://cdn.example/in.png", "upload_url": "https://store.example/put",
                "upload_headers": {"Content-Type": content_type, "x-amz-tagging": "retention=temporary"}}

    def submit(self, args):
        self.calls["submit"] += 1
        self.submitted.append(dict(args))
        if isinstance(self._submit, BaseException):
            raise self._submit
        return {"request_id": "r1", "status_url": "https://api.higgsfield.ai/requests/r1/status"}

    def wait(self, url, timeout):
        self.calls["wait"] += 1
        if self.pending_first:
            self.pending_first = False
            raise HiggsfieldError("request is still queued after 1800s", pending=True)
        return self.polls.pop(0)


@pytest.fixture
def api_ws(ws, monkeypatch, tmp_path):  # noqa: F811
    """A workspace with a key, a fake API, a presigned PUT that records, and a download that makes a clip."""
    monkeypatch.setenv("HF_KEY", KEY)
    fake = FakeAPI()
    monkeypatch.setattr(video, "make_client", lambda w: fake)
    puts = []
    monkeypatch.setattr(loop, "put_presigned", lambda w, p, url, headers: puts.append({"url": url, **headers}))

    def download(w, piece, url, job, shot="shot01"):
        return clip_from(piece.rel("frames/approved.png"), piece.rel("incoming", f"{shot}-{job}.mp4"))
    monkeypatch.setattr(loop, "download_clip", download)
    (ws / "incoming").mkdir(exist_ok=True)
    return ws, fake, puts


def building(root: Path, slug: str = "api") -> str:
    cast_nova(root)
    p = approved_piece(root, slug)
    pass_frames(root, p.ref)
    return p.ref


def entries(root: Path, ref: str, unit: str = "video_usd") -> list[dict]:
    return [e for e in read_json(root / "work" / ref / "invoice.json")["entries"] if e["unit"] == unit]


# ---------------------------------------------------------------- route
def test_route_rule(ws, monkeypatch):  # noqa: F811
    code, r = sh(ws, "route")
    assert code == 0 and r["route"] == "mcp" and "no HF_KEY" in r["reason"]  # criterion 1

    monkeypatch.setenv("HF_KEY", KEY)
    fake = FakeAPI()
    monkeypatch.setattr(video, "make_client", lambda w: fake)
    assert sh(ws, "route")[1]["route"] == "api" and fake.calls["estimate"] == 1

    for status in (401, 403, 404, 423, 503, None):
        fake._estimate = HiggsfieldError(f"HTTP {status}", status)
        r = sh(ws, "route")[1]
        assert r["route"] == "mcp" and "availability check failed" in r["reason"], status

    cfg = read_json(ws / "foundry.json")
    cfg["providers"]["video"]["route"] = "api"
    write_json(ws / "foundry.json", cfg)
    code, r = sh(ws, "route")
    assert code == 2 and "pinned to api" in r["error"]  # pinned api never silently falls back
    cfg["providers"]["video"]["route"] = "mcp"
    write_json(ws / "foundry.json", cfg)
    fake._estimate = None
    assert sh(ws, "route")[1] == {"route": "mcp", "reason": "providers.video.route is pinned to mcp", "pinned": "mcp"}


def test_piece_approved_before_the_api_route_stays_on_mcp(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    inv = read_json(root / "work" / ref / "invoice.json")
    inv["ceilings"].pop("video_usd")
    write_json(root / "work" / ref / "invoice.json", inv)
    code, r = sh(root, "route", ref)
    assert r["route"] == "mcp" and "no video_usd ceiling" in r["reason"]
    code, r = sh(root, "generate", ref)
    assert code == 2 and "use the MCP steps" in r["error"] and fake.calls["submit"] == 0


# ---------------------------------------------------------------- generate
def test_generate_happy_path(api_ws):
    root, fake, puts = api_ws
    ref = building(root)
    code, r = sh(root, "generate", ref, "--shot", "shot01")
    assert code == 0, r
    assert r["route"] == "api" and r["request_id"] == "r1" and r["cost_usd"] == 2.32 and not r["resumed"]
    assert fake.calls["submit"] == 1
    body = fake.submitted[0]
    assert body["image_url"] == "https://cdn.example/in.png" and body["duration"] == 5
    assert body["generate_audio"] is False and body["resolution"] == "720p" and "aspect_ratio" not in body
    assert puts == [{"url": "https://store.example/put", "Content-Type": "image/png",
                     "x-amz-tagging": "retention=temporary"}]  # no Authorization to the storage host
    (e,) = entries(root, ref)
    assert e["state"] == "settled" and e["ref"] == "r1" and e["consumed"] and e["amount"] == 2.32
    assert (root / "work" / ref / "clips/shot01.mp4").exists()
    assert not (root / "work" / ref / "incoming/shot01.api-job.json").exists()
    row = next(x for x in sh(root, "ls")[1] if x["piece"] == ref)
    assert row["video_usd"] == 2.32 and row["video_credits"] == 0


def test_generate_refuses_on_the_mcp_route(ws):  # noqa: F811
    ref = building(ws)
    code, r = sh(ws, "generate", ref)
    assert code == 2 and "video route is mcp" in r["error"]
    assert entries(ws, ref) == []


def test_ambiguous_submit_is_charged_parked_and_never_resubmitted(api_ws, monkeypatch):
    root, fake, _ = api_ws
    ref = building(root)
    fake._submit = HiggsfieldError("submit outcome unknown (network: timed out)", ambiguous=True)
    code, r = sh(root, "generate", ref)
    assert code == 2 and "outcome is unknown" in r["error"] and "nothing was resubmitted" in r["error"]
    (e,) = entries(root, ref)
    assert e["state"] == "settled" and e["ref"].startswith("unknown-") and fake.calls["submit"] == 1
    assert not (root / "work" / ref / "incoming/shot01.api-job.json").exists()
    # parked: neither a re-run nor the agent can submit that shot again
    fake._submit = None
    code, r = sh(root, "generate", ref)
    assert code == 2 and "--clear-unknown" in r["error"] and fake.calls["submit"] == 1
    monkeypatch.setenv("FOUNDRY_AGENT", ref)
    monkeypatch.chdir(root)
    assert sh(root, "generate", ref, "--clear-unknown")[0] == 2  # -C is refused under the agent anyway
    from foundry import cli
    assert cli.main(["generate", ref, "--clear-unknown", "--json"]) == 2  # human step
    monkeypatch.delenv("FOUNDRY_AGENT")
    code, r = sh(root, "generate", ref, "--clear-unknown")
    assert code == 0 and r["cleared"]["entry"] == e["id"]
    assert sh(root, "generate", ref)[0] == 0 and fake.calls["submit"] == 2


def test_process_killed_inside_the_submit_is_an_unknown_outcome(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    piece = Piece.open(workspace.load(root), ref)
    eid = piece.reserve("video_usd", 2.32, "shot01 via Higgsfield API")
    write_json(root / "work" / ref / "incoming/shot01.api-job.json",
               {"phase": "submitting", "entry": eid, "shot": "shot01", "cost_usd": 2.32, "at": "t"})
    code, r = sh(root, "generate", ref)
    assert code == 2 and "interrupted while submitting" in r["error"] and fake.calls["submit"] == 0
    (e,) = entries(root, ref)
    assert e["state"] == "settled" and e["ref"] == f"unknown-{eid}"
    assert (root / "work" / ref / "incoming/shot01.api-unknown.json").exists()


def test_wait_is_short_by_default_and_overridable(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    seen = []
    orig = fake.wait
    fake.wait = lambda url, timeout: (seen.append(timeout), orig(url, timeout))[1]
    assert sh(root, "generate", ref)[0] == 0 and seen == [90.0]
    assert sh(root, "generate", ref, "--wait-s", "0")[0] == 2


def test_refused_submit_costs_nothing_and_points_to_mcp(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    fake._submit = HiggsfieldError("HTTP 403: Insufficient credits", 403)
    code, r = sh(root, "generate", ref)
    assert code == 2 and "use the MCP steps" in r["error"]
    (e,) = entries(root, ref)
    assert e["state"] == "failed" and "ref" not in e


def test_interrupted_generate_resumes_without_resubmitting(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    fake.pending_first = True
    code, r = sh(root, "generate", ref)
    assert code == 2 and "not finished" in r["error"] and "does not resubmit" in r["error"]
    job = read_json(root / "work" / ref / "incoming/shot01.api-job.json")
    assert job["request_id"] == "r1" and entries(root, ref)[0]["state"] == "reserved"
    code, r = sh(root, "generate", ref)
    assert code == 0 and r["resumed"] and fake.calls["submit"] == 1
    assert entries(root, ref)[0]["state"] == "settled"


@pytest.mark.parametrize("status", ["failed", "nsfw"])
def test_failed_generation_settles_failed_and_ingests_nothing(api_ws, status):
    root, fake, _ = api_ws
    ref = building(root)
    fake.polls = [{"status": status, "request_id": "r1", "error": "Generation failed"}]
    code, r = sh(root, "generate", ref)
    assert code == 2 and f"ended {status}" in r["error"]
    assert ("safety" in r["error"]) == (status == "nsfw")
    (e,) = entries(root, ref)
    assert e["state"] == "failed" and e["ref"] == "r1"
    assert not (root / "work" / ref / "clips/shot01.mp4").exists()


def test_api_spend_is_capped_by_the_frozen_video_usd_ceiling(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    ceiling = read_json(root / "work" / ref / "invoice.json")["ceilings"]["video_usd"]
    assert ceiling == 6.96  # planned 2.32 x credit_ceiling_multiplier 3
    piece = Piece.open(workspace.load(root), ref)
    piece.settle(piece.reserve("video_usd", 5.0, "earlier clips"), ok=True, ref="old")
    code, r = sh(root, "generate", ref)
    assert r["status"] == "BLOCKED" and r["gate"] == "budget.video_usd"
    assert fake.calls["upload_url"] == 0 and fake.calls["submit"] == 0


def test_green_clip_is_not_regenerated(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    assert sh(root, "generate", ref)[0] == 0
    sh(root, "verdict", ref, "--stage", "clip", "--pass")
    assert sh(root, "qc", ref, "--stage", "clip")[1]["pass"]
    code, r = sh(root, "generate", ref)
    assert code == 2 and "nothing to regenerate" in r["error"] and fake.calls["submit"] == 1


def test_agent_cannot_book_api_spend_by_hand(ws):  # noqa: F811
    ref = building(ws)
    with pytest.raises(SystemExit):
        sh(ws, "reserve", ref, "--unit", "video_usd", "--amount", "0.01")


# ---------------------------------------------------------------- build + doctor
def test_headless_build_on_the_api_route_needs_no_mcp_server(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    code, r = sh(root, "build", ref, "--mode", "bypass", "--dry-run")
    assert code == 0, r
    assert r["video_route"]["route"] == "api"
    assert f"foundry generate {ref} --shot <shot id>" in r["prompt"]
    assert "BLOCKED video.route" in r["prompt"]  # no MCP fallback in this session
    assert not any(a.startswith("mcp__") for a in r["argv"])

    cfg = read_json(root / "foundry.json")
    cfg["providers"]["video"]["mcp_server"] = "higgsfield"
    write_json(root / "foundry.json", cfg)
    r = sh(root, "build", ref, "--mode", "bypass", "--dry-run")[1]
    assert "mcp__higgsfield__generate_video" in r["argv"] and "MCP route:" in r["prompt"]

    fake._estimate = HiggsfieldError("HTTP 401: Invalid credentials", 401)
    cfg["providers"]["video"]["mcp_server"] = None
    write_json(root / "foundry.json", cfg)
    code, r = sh(root, "build", ref, "--mode", "bypass", "--dry-run")
    assert code == 2 and "mcp_server is not set" in r["error"] and "Invalid credentials" in r["error"]


def test_doctor_treats_the_mcp_as_fallback_when_the_api_works(api_ws):
    root, fake, _ = api_ws
    rows = {c["check"]: c for c in ops.doctor(workspace.load(root), offline=True)["checks"]}
    assert rows["Higgsfield API"]["status"] == "ok" and rows["video route"]["detail"].startswith("api")
    assert rows["Higgsfield MCP"]["status"] == "note"


def test_doctor_without_a_key_explains_how_to_add_one(ws):  # noqa: F811
    rows = {c["check"]: c for c in ops.doctor(workspace.load(ws), offline=True)["checks"]}
    assert rows["Higgsfield API"]["status"] == "note" and "HF_KEY=" in rows["Higgsfield API"]["detail"]
    assert rows["video route"]["detail"].startswith("mcp") and rows["Higgsfield MCP"]["status"] == "todo"


def test_shot_duration_must_fit_the_api(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    ws_ = workspace.load(root)
    spec = Piece.open(ws_, ref).spec
    spec["shots"][0]["duration_s"] = 3.2
    with pytest.raises(Exception, match="whole seconds from 4 to 30"):
        video.arguments(ws_, spec, 0, "p", "https://x")
    shutil.rmtree(root / "work" / ref / "incoming", ignore_errors=True)
