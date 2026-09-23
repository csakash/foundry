"""SPEC.md "Higgsfield API route": the client contract, the route rule, and `foundry generate` end to end.

No network: the client's `send` is a fake, and `foundry.video.make_client`, `loop.put_presigned` and
`loop.download_clip` are replaced for the generate tests.
"""
from __future__ import annotations

import fcntl
import json
from pathlib import Path

import pytest

from engine.providers.higgsfield_api import HiggsfieldAPI, HiggsfieldError, credentials, price_usd
from foundry import build as build_mod, loop, ops, video, workspace
from foundry.loop import put_presigned as REAL_PUT
from foundry.piece import Piece
from foundry.util import FoundryError, read_json, write_json

from .test_e2e_offline import approved_piece, cast_nova, clip_from, pass_frames, sh, ws  # noqa: F401

KEY = "kid:secret"
DONE = {"status": "completed", "request_id": "r1", "video": {"url": "https://cdn.example/out.mp4"}}


# ---------------------------------------------------------------- client
class Wire:
    """A scripted `send`: each call pops the next (status, body[, headers]) and records the request.
    A bytes body is sent as is (to test unreadable responses)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def __call__(self, method, url, body, headers, timeout):
        self.calls.append({"method": method, "url": url, "body": json.loads(body) if body else None,
                           "headers": dict(headers), "timeout": timeout})
        r = self.replies.pop(0)
        if isinstance(r, BaseException):
            raise r
        status, payload, *rh = r
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return status, (rh[0] if rh else {"X-Correlation-ID": "cid-1"}), raw


def api(wire, **kw) -> HiggsfieldAPI:
    clock = kw.pop("clock", None) or iter(range(0, 10_000, 1)).__next__
    return HiggsfieldAPI(KEY, send=wire, sleep=lambda s: None, clock=lambda: float(clock()), **kw)


STATUS_URL = "https://api.higgsfield.ai/requests/r/status"


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


@pytest.mark.parametrize("d, n", [(4.5, 5), (6.5, 7), (29.6, 30), (5.0, 5), (4.4, 4)])
def test_the_plan_prices_exactly_what_generate_reserves(d, n):
    assert video.api_duration(d) == n
    assert video.planned_usd({"shots": [{"duration_s": d}]}, {"resolution": "720p"}) == price_usd(n, "720p")


@pytest.mark.parametrize("d", [3.2, 30.6])
def test_a_shot_outside_the_api_range_plans_no_api_budget(d):
    assert video.planned_usd({"shots": [{"duration_s": d}]}, {"resolution": "720p"}) == 0.0
    with pytest.raises(FoundryError, match="MCP steps"):
        video.api_duration(d)


def test_key_only_goes_to_the_api_host_and_never_prints():
    w = Wire((200, {"status": "queued"}))
    c = api(w)
    assert "secret" not in repr(c)
    c.status("https://api.higgsfield.ai/requests/r1/status", deadline=100)
    assert w.calls[0]["headers"]["Authorization"] == "Key kid:secret"
    for bad in ("https://evil.example/requests/r1/status", "http://api.higgsfield.ai/requests/r1/status"):
        with pytest.raises(HiggsfieldError, match="refusing to send credentials"):
            c.status(bad, deadline=100)
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

    for code in (400, 401, 402, 403, 404, 408, 409, 413, 422, 423, 429, 503):  # refused: nothing accepted
        w = Wire((code, {"detail": "no"}))
        with pytest.raises(HiggsfieldError) as e:
            api(w).submit({})
        assert not e.value.ambiguous and e.value.status == code and len(w.calls) == 1

    # 2xx means accepted (and billed): anything we cannot follow is an unknown outcome, never a refusal
    for body in ({"request_id": "r2", "status_url": "https://evil.example/s"}, b"not json", {"request_id": "r3"}, {}):
        with pytest.raises(HiggsfieldError) as e:
            api(Wire((200, body))).submit({})
        assert e.value.ambiguous, body


def test_status_retries_reads_and_stops_at_the_deadline():
    w = Wire((503, {}), TimeoutError("x"), (200, {"status": "in_progress"}))
    assert api(w).status(STATUS_URL, deadline=1000)["status"] == "in_progress"
    assert len(w.calls) == 3
    with pytest.raises(HiggsfieldError) as e:
        api(Wire((404, {"detail": "nope"}))).status(STATUS_URL, deadline=1000)
    assert e.value.status == 404 and not e.value.pending
    ticks = iter([0, 100])  # one attempt at t=0, then past the deadline
    with pytest.raises(HiggsfieldError) as e:
        api(Wire((500, {}), (500, {})), clock=lambda: next(ticks)).status(STATUS_URL, deadline=5)
    assert e.value.pending
    with pytest.raises(HiggsfieldError) as e:  # never starts an attempt past the deadline
        api(Wire(), clock=lambda: 10).status(STATUS_URL, deadline=5)
    assert e.value.pending


def test_a_status_attempt_never_outlives_the_deadline():
    w = Wire((200, {"status": "queued"}))
    api(w, clock=lambda: 97).status(STATUS_URL, deadline=100)
    assert w.calls[0]["timeout"] == 3


def test_wait_polls_to_terminal_and_reports_a_timeout_as_pending():
    w = Wire((200, {"status": "queued"}), (200, {"status": "in_progress"}),
             (200, {"status": "completed", "video": {"url": "https://cdn.example/o.mp4"}}))
    assert api(w).wait(STATUS_URL, 600)["video"]["url"].endswith("o.mp4")
    ticks = iter([0, 0, 50])  # deadline set at 0, one poll, then past it
    with pytest.raises(HiggsfieldError) as e:
        api(Wire((200, {"status": "queued"})), clock=lambda: next(ticks)).wait(STATUS_URL, 10)
    assert e.value.pending


def test_a_truncated_response_is_a_network_error_not_a_crash():
    import http.client
    with pytest.raises(HiggsfieldError) as e:
        api(Wire(http.client.IncompleteRead(b""))).submit({})
    assert e.value.ambiguous


# ---------------------------------------------------------------- fake API for generate
class FakeAPI:
    endpoint = "bytedance/seedance-2.5/image-to-video"
    timeout = 20.0

    def __init__(self):
        self._estimate = None
        self._submit = None
        self._upload = None
        self.polls = [dict(DONE)]
        self.pending_first = False
        self.calls = {"estimate": 0, "upload_url": 0, "submit": 0, "wait": 0}
        self.submitted: list[dict] = []
        self.waited: list[float] = []

    def estimate(self, args):
        self.calls["estimate"] += 1
        if isinstance(self._estimate, BaseException):
            raise self._estimate
        return {"type": "description"}

    def upload_url(self, content_type="image/png"):
        self.calls["upload_url"] += 1
        if isinstance(self._upload, BaseException):
            err, self._upload = self._upload, None
            raise err
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
        self.waited.append(timeout)
        if self.pending_first:
            self.pending_first = False
            raise HiggsfieldError("request is still queued", pending=True)
        return self.polls.pop(0) if len(self.polls) > 1 else dict(self.polls[0])


@pytest.fixture
def api_ws(ws, monkeypatch, tmp_path):  # noqa: F811
    """A workspace with a key, a fake API, a presigned PUT that records, and a download that makes a clip."""
    monkeypatch.setenv("HF_KEY", KEY)
    fake = FakeAPI()
    monkeypatch.setattr(video, "make_client", lambda w: fake)
    puts = []
    monkeypatch.setattr(loop, "put_presigned", lambda w, p, url, headers, timeout=0: puts.append({"url": url, **headers}))

    def download(w, piece, url, job, shot="shot01"):
        return clip_from(piece.rel("frames/approved.png"), piece.rel("incoming", f"{shot}-{job}.mp4"))
    monkeypatch.setattr(loop, "download_clip", download)
    return ws, fake, puts


def building(root: Path, slug: str = "api") -> str:
    cast_nova(root)
    p = approved_piece(root, slug)
    pass_frames(root, p.ref)
    return p.ref


def entries(root: Path, ref: str, unit: str = "video_usd") -> list[dict]:
    return [e for e in read_json(root / "work" / ref / "invoice.json")["entries"] if e["unit"] == unit]


def incoming(root: Path, ref: str, name: str) -> Path:
    return root / "work" / ref / "incoming" / name


def piece_of(root: Path, ref: str) -> Piece:
    return Piece.open(workspace.load(root), ref)


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
    r = sh(ws, "route")[1]
    assert r["route"] == "mcp" and r["cause"] == "pinned"


def test_a_malformed_key_falls_back_instead_of_crashing(ws, monkeypatch):  # noqa: F811
    monkeypatch.setenv("HF_KEY", "no-colon")  # the real client, not a fake
    code, r = sh(ws, "route")
    assert code == 0 and r["route"] == "mcp" and "key_id" in r["reason"]


def test_piece_approved_before_the_api_route_stays_on_mcp(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    inv = read_json(root / "work" / ref / "invoice.json")
    inv["ceilings"].pop("video_usd")
    write_json(root / "work" / ref / "invoice.json", inv)
    code, r = sh(root, "route", ref)
    assert r["route"] == "mcp" and "no video_usd ceiling" in r["reason"]
    code, r = sh(root, "generate", ref)
    assert code == 2 and "MCP steps" in r["error"] and fake.calls["submit"] == 0


def test_a_request_in_flight_keeps_the_route_on_the_api(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    fake.pending_first = True
    assert sh(root, "generate", ref)[0] == 2
    fake._estimate = HiggsfieldError("HTTP 503", 503)  # the live check now fails...
    r = sh(root, "route", ref)[1]
    assert r["route"] == "api" and "in flight" in r["reason"]  # ...but the paid request must be collected


# ---------------------------------------------------------------- generate
def test_generate_happy_path(api_ws):
    root, fake, puts = api_ws
    ref = building(root)
    code, r = sh(root, "generate", ref, "--shot", "shot01")
    assert code == 0, r
    assert r["route"] == "api" and r["request_id"] == "r1" and r["cost_usd"] == 2.32 and not r["resumed"]
    assert fake.calls["submit"] == 1 and fake.calls["estimate"] == 0  # the submit re-checks, no extra probe
    body = fake.submitted[0]
    assert body["image_url"] == "https://cdn.example/in.png" and body["duration"] == 5
    assert body["generate_audio"] is False and body["resolution"] == "720p" and "aspect_ratio" not in body
    assert puts == [{"url": "https://store.example/put", "Content-Type": "image/png",
                     "x-amz-tagging": "retention=temporary"}]  # no Authorization to the storage host
    (e,) = entries(root, ref)
    assert e["state"] == "settled" and e["ref"] == "r1" and e["consumed"] and e["amount"] == 2.32
    assert (root / "work" / ref / "clips/shot01.mp4").exists()
    assert not incoming(root, ref, "shot01.api-job.json").exists()
    row = next(x for x in sh(root, "ls")[1] if x["piece"] == ref)
    assert row["video_usd"] == 2.32 and row["video_credits"] == 0


def test_generate_refuses_on_the_mcp_route(ws):  # noqa: F811
    ref = building(ws)
    code, r = sh(ws, "generate", ref)
    assert code == 2 and "video route is mcp" in r["error"]
    assert entries(ws, ref) == []


def test_a_second_generate_for_the_same_shot_is_refused(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    lock = incoming(root, ref, ".shot01.generate.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        code, r = sh(root, "generate", ref)
    assert code == 2 and "already running" in r["error"]
    assert entries(root, ref) == [] and fake.calls["submit"] == 0


def test_ambiguous_submit_is_charged_parked_and_never_resubmitted(api_ws, monkeypatch):
    root, fake, _ = api_ws
    ref = building(root)
    fake._submit = HiggsfieldError("submit outcome unknown (network: timed out)", ambiguous=True)
    code, r = sh(root, "generate", ref)
    assert code == 2 and "outcome is unknown" in r["error"] and "nothing was resubmitted" in r["error"]
    (e,) = entries(root, ref)
    assert e["state"] == "settled" and e["ref"] == f"unknown-{e['id']}" and fake.calls["submit"] == 1
    assert not incoming(root, ref, "shot01.api-job.json").exists()
    # parked: neither a re-run nor another route can use that shot
    fake._submit = None
    code, r = sh(root, "generate", ref)
    assert code == 2 and "--clear-unknown" in r["error"] and fake.calls["submit"] == 1
    clip = clip_from(root / "work" / ref / "frames/approved.png", root / "stray.mp4")
    code, r = sh(root, "ingest-clip", ref, str(clip), "--job", f"unknown-{e['id']}")
    assert code == 2 and "parked" in r["error"]
    monkeypatch.setenv("FOUNDRY_AGENT", ref)
    monkeypatch.chdir(root)
    from foundry import cli
    assert cli.main(["generate", ref, "--clear-unknown", "--json"]) == 2  # a human step
    monkeypatch.delenv("FOUNDRY_AGENT")
    code, r = sh(root, "generate", ref, "--clear-unknown")
    assert code == 0 and r["cleared"]["unknown"]["entry"] == e["id"]
    assert sh(root, "generate", ref)[0] == 0 and fake.calls["submit"] == 2


def test_an_unknown_charge_can_never_pay_for_a_clip(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    fake._submit = HiggsfieldError("submit outcome unknown", ambiguous=True)
    sh(root, "generate", ref)
    (e,) = entries(root, ref)
    sh(root, "generate", ref, "--clear-unknown")  # unparked, but the charge stays unusable
    clip = clip_from(root / "work" / ref / "frames/approved.png", root / "stray.mp4")
    code, r = sh(root, "ingest-clip", ref, str(clip), "--job", f"unknown-{e['id']}")
    assert code == 2 and "unknown outcome" in r["error"]
    assert not (root / "work" / ref / "clips/shot01.mp4").exists()


def test_process_killed_inside_the_submit_is_an_unknown_outcome(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    eid = piece_of(root, ref).reserve("video_usd", 2.32, "shot01 via Higgsfield API")
    write_json(incoming(root, ref, "shot01.api-job.json"),
               {"phase": "submitting", "entry": eid, "shot": "shot01", "cost_usd": 2.32, "at": "t"})
    code, r = sh(root, "generate", ref)
    assert code == 2 and "interrupted while submitting" in r["error"] and fake.calls["submit"] == 0
    (e,) = entries(root, ref)
    assert e["state"] == "settled" and e["ref"] == f"unknown-{eid}"
    assert incoming(root, ref, "shot01.api-unknown.json").exists()


def test_process_killed_during_the_upload_voids_the_reservation(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    eid = piece_of(root, ref).reserve("video_usd", 2.32, "shot01 via Higgsfield API")
    write_json(incoming(root, ref, "shot01.api-job.json"),
               {"phase": "reserved", "entry": eid, "shot": "shot01", "cost_usd": 2.32, "at": "t"})
    code, r = sh(root, "generate", ref)
    assert code == 0, r
    first, second = entries(root, ref)
    assert first["state"] == "void" and second["state"] == "settled"
    assert piece_of(root, ref).spent("video_usd") == 2.32  # the voided reservation is not counted


def test_an_upload_failure_costs_nothing_and_does_not_park(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    fake._upload = HiggsfieldError("HTTP 500: storage", 500)
    code, r = sh(root, "generate", ref)
    assert code != 0 and fake.calls["submit"] == 0
    (e,) = entries(root, ref)
    assert e["state"] == "void"
    assert not incoming(root, ref, "shot01.api-job.json").exists()
    assert not incoming(root, ref, "shot01.api-unknown.json").exists()
    assert sh(root, "generate", ref)[0] == 0


def test_refused_submits_cost_nothing_and_never_exhaust_the_ceiling(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    fake._submit = HiggsfieldError("HTTP 422: bad prompt", 422)
    for _ in range(5):  # more than the 6.96 ceiling / 2.32 would allow if refusals were counted
        code, r = sh(root, "generate", ref)
        assert code == 2 and "refused the submit" in r["error"]
    assert all(e["state"] == "void" for e in entries(root, ref))
    assert piece_of(root, ref).spent("video_usd") == 0 and piece_of(root, ref).state == "building"
    fake._submit = HiggsfieldError("HTTP 403: Insufficient credits", 403)
    assert "MCP steps" in sh(root, "generate", ref)[1]["error"]


def test_interrupted_generate_resumes_without_resubmitting(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    fake.pending_first = True
    code, r = sh(root, "generate", ref)
    assert code == 2 and "not finished" in r["error"] and "never resubmits" in r["error"]
    job = read_json(incoming(root, ref, "shot01.api-job.json"))
    assert job["request_id"] == "r1" and job["phase"] == "submitted" and entries(root, ref)[0]["state"] == "reserved"
    code, r = sh(root, "generate", ref)
    assert code == 0 and r["resumed"] and fake.calls["submit"] == 1
    assert entries(root, ref)[0]["state"] == "settled"


def test_a_failed_download_resumes_without_settling_twice(api_ws, monkeypatch):
    root, fake, _ = api_ws
    ref = building(root)
    real = loop.download_clip
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise FoundryError("network down")
        return real(*a, **k)
    monkeypatch.setattr(loop, "download_clip", flaky)
    assert sh(root, "generate", ref)[0] == 2
    assert sh(root, "generate", ref)[0] == 0 and fake.calls["submit"] == 1
    (e,) = entries(root, ref)
    assert e["state"] == "settled" and e["ref"] == "r1" and e["consumed"]


def test_a_crash_after_ingest_finishes_cleanly_on_the_next_run(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    fake.pending_first = True
    sh(root, "generate", ref)
    job = read_json(incoming(root, ref, "shot01.api-job.json"))
    assert sh(root, "generate", ref)[0] == 0
    write_json(incoming(root, ref, "shot01.api-job.json"), job)  # as if killed before the job file was removed
    code, r = sh(root, "generate", ref)
    assert code == 0 and r["already_ingested"] and fake.calls["submit"] == 1
    assert not incoming(root, ref, "shot01.api-job.json").exists()


def test_a_clip_from_a_replaced_frame_is_charged_but_not_ingested(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    fake.pending_first = True
    sh(root, "generate", ref)
    approved = root / "work" / ref / "frames/approved.png"
    approved.write_bytes(approved.read_bytes() + b"\0")  # the first frame changed while the request ran
    code, r = sh(root, "generate", ref)
    assert code == 2 and "has since been replaced" in r["error"]
    (e,) = entries(root, ref)
    assert e["state"] == "settled" and not e.get("consumed")
    assert not (root / "work" / ref / "clips/shot01.mp4").exists()


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


def test_completed_without_a_url_is_charged_and_cleaned_up(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    fake.polls = [{"status": "completed", "request_id": "r1"}]
    code, r = sh(root, "generate", ref)
    assert code == 2 and "without a video URL" in r["error"]
    (e,) = entries(root, ref)
    assert e["state"] == "settled" and not e.get("consumed")
    assert not incoming(root, ref, "shot01.api-job.json").exists()


def test_an_unreadable_request_keeps_its_reservation_and_a_human_can_abandon_it(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    fake.pending_first = True
    sh(root, "generate", ref)
    fake.wait = lambda url, t: (_ for _ in ()).throw(HiggsfieldError("HTTP 404: not found", 404))
    code, r = sh(root, "generate", ref)
    assert code == 2 and "stays open" in r["error"] and fake.calls["submit"] == 1
    assert entries(root, ref)[0]["state"] == "reserved"
    code, r = sh(root, "generate", ref, "--clear-unknown")
    assert code == 0 and r["cleared"]["abandoned_request"]["request_id"] == "r1"
    (e,) = entries(root, ref)
    assert e["state"] == "settled" and e["ref"] == "unknown-r1"  # charged, never lowered, never usable


def test_an_other_clip_cannot_be_ingested_while_an_api_request_is_in_flight(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    fake.pending_first = True
    sh(root, "generate", ref)
    clip = clip_from(root / "work" / ref / "frames/approved.png", root / "mcp.mp4")
    code, r = sh(root, "ingest-clip", ref, str(clip), "--job", "mcp-job")
    assert code == 2 and "in flight" in r["error"]


def test_nobody_can_settle_a_generate_reservation_by_hand(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    fake.pending_first = True
    sh(root, "generate", ref)
    (e,) = entries(root, ref)
    code, r = sh(root, "settle", ref, e["id"], "--failed")
    assert code == 2 and "foundry generate settles it" in r["error"]


def test_api_spend_is_capped_by_the_frozen_video_usd_ceiling(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    ceiling = read_json(root / "work" / ref / "invoice.json")["ceilings"]["video_usd"]
    assert ceiling == 6.96  # planned 2.32 x credit_ceiling_multiplier 3
    piece = piece_of(root, ref)
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


def test_one_call_fits_the_agent_shell_and_a_wait_can_be_asked_for(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    assert sh(root, "generate", ref)[0] == 0
    assert 60 < fake.waited[-1] <= video.CALL_BUDGET_S - video.COLLECT_RESERVE_S  # ~75 s of a 100 s call
    sh(root, "verdict", ref, "--stage", "clip", "--fail", "--note", "hands")
    sh(root, "qc", ref, "--stage", "clip")
    assert sh(root, "generate", ref, "--wait-s", "300", "--guidance-from", "clip")[0] == 0
    assert 290 < fake.waited[-1] <= 300
    assert sh(root, "generate", ref, "--wait-s", "0")[0] == 2
    assert sh(root, "generate", ref, "--wait-s", "3601")[0] == 2


def test_agent_cannot_book_api_spend_by_hand(ws):  # noqa: F811
    ref = building(ws)
    with pytest.raises(SystemExit):
        sh(ws, "reserve", ref, "--unit", "video_usd", "--amount", "0.01")


def test_the_real_presigned_put_never_sends_credentials(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    ws_, piece = workspace.load(root), piece_of(root, ref)
    for headers in ({"Authorization": "Key x"}, {"authorization": "Key x"}):
        with pytest.raises(FoundryError, match="Authorization"):
            REAL_PUT(ws_, piece, "https://store.example/put", headers)
    with pytest.raises(FoundryError, match="https"):
        REAL_PUT(ws_, piece, "http://store.example/put", {"Content-Type": "image/png"})


def test_shipping_records_api_spend(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    from foundry import ship
    piece = piece_of(root, ref)
    piece.settle(piece.reserve("video_usd", 2.32, "x"), ok=True, ref="r")
    import inspect
    assert "VIDEO_UNITS" in inspect.getsource(ship.ship)  # the recipe's cost_per_run covers both video units
    assert piece.spent("video_usd") == 2.32


# ---------------------------------------------------------------- build + doctor
def test_headless_build_on_the_api_route_needs_no_mcp_server(api_ws):
    root, fake, _ = api_ws
    ref = building(root)
    code, r = sh(root, "build", ref, "--mode", "bypass", "--dry-run")
    assert code == 0, r
    assert r["video_route"]["route"] == "api"
    assert f"foundry generate {ref} --shot <shot id>" in r["prompt"]
    assert "BLOCKED video.route" in r["prompt"]  # headless, no MCP fallback in this session
    assert not any(a.startswith("mcp__") for a in r["argv"])
    code, r = sh(root, "build", ref, "--mode", "interactive")
    assert "MCP route:" in r["prompt"] and "BLOCKED video.route" not in r["prompt"]  # the session has its connectors

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


def test_the_build_agent_never_holds_the_key(api_ws, monkeypatch):
    root, fake, _ = api_ws
    ref = building(root)
    seen = {}

    class Proc:
        pid = 999_999

        def wait(self, timeout=None):
            return 0

    def popen(args, cwd=None, env=None, start_new_session=None):
        seen.update(env)
        return Proc()
    monkeypatch.setenv("HF_API_KEY", "kid")
    monkeypatch.setenv("HF_API_SECRET", "secret")
    monkeypatch.setattr(build_mod.subprocess, "Popen", popen)
    monkeypatch.setattr(build_mod.shutil, "which", lambda n: "/usr/bin/claude")
    sh(root, "build", ref, "--mode", "bypass")
    assert seen and seen["FOUNDRY_AGENT"] == ref
    assert not {"HF_KEY", "HF_API_KEY", "HF_API_SECRET"} & set(seen)


def test_doctor_treats_the_mcp_as_fallback_when_the_api_works(api_ws):
    root, fake, _ = api_ws
    rows = {c["check"]: c for c in ops.doctor(workspace.load(root), offline=True)["checks"]}
    assert rows["Higgsfield API"]["status"] == "ok" and rows["video route"]["detail"].startswith("api")
    assert rows["Higgsfield MCP"]["status"] == "note"


def test_doctor_without_a_key_explains_how_to_add_one(ws):  # noqa: F811
    rows = {c["check"]: c for c in ops.doctor(workspace.load(ws), offline=True)["checks"]}
    api = rows["Higgsfield API"]
    assert api["status"] == "note" and "HF_KEY=" in api["detail"] and "unavailable:" not in api["detail"]
    assert rows["video route"]["detail"].startswith("mcp") and rows["Higgsfield MCP"]["status"] == "todo"


def test_a_developer_key_never_reaches_these_tests():
    assert credentials() is None  # conftest strips HF_*: no test here can route to the real API
