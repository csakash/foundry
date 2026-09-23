"""Video routes: the Higgsfield API when it is available, the Higgsfield MCP otherwise.

SPEC.md "Higgsfield API route". `resolve` decides the route; `generate` runs the whole API path inside
foundry — price, reserve, upload, submit, poll, settle, download, ingest — so the build agent never holds
a generate tool or the key, and every API spend passes through the invoice.

Every step of `generate` leaves `incoming/<shot>.api-job.json` in a phase that says what a re-run must do
if the process is killed there:

    reserved    money reserved, nothing sent       -> the reservation is voided, start again
    submitting  the POST may have landed            -> unknown outcome: charged, shot parked for a human
    submitted   request id known                    -> poll it; never resubmit

One call never runs past CALL_BUDGET_S, because the build agent's shell kills long commands (~2 min).
"""
from __future__ import annotations

import contextlib
import fcntl
import math
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterator

from engine.providers.higgsfield_api import (CONSOLE_URL, DURATION_S, PRICE_FRAME, PROBE_IMAGE, UNAVAILABLE,
                                             HiggsfieldAPI, HiggsfieldError, credentials, price_usd)

from . import loop
from . import spec as spec_mod
from .piece import UNKNOWN_REF_PREFIX, Piece
from .util import AGENT_ENV, SHOT_RE, FoundryError, check_name, human_only, now, read_json, sha256_file, write_json
from .workspace import Workspace

ROUTES = ("auto", "api", "mcp")
DEFAULT_RESOLUTION = "720p"
CALL_BUDGET_S = 100       # one `foundry generate` call, start to finish, unless a wait is asked for
COLLECT_RESERVE_S = 25    # kept back from the wait for download + ingest
SUBMIT_MARGIN_S = 5       # never start the POST without the request timeout plus this left
NO_KEY = "no HF_KEY (or HF_API_KEY + HF_API_SECRET) in the environment or the workspace .env"
MCP_HINT = " Use the MCP steps for this clip."


def _client(ws: Workspace) -> HiggsfieldAPI | None:
    key = credentials()
    return HiggsfieldAPI(key) if key else None


# Tests replace this with a fake; everything else goes through it.
make_client: Callable[[Workspace], HiggsfieldAPI | None] = _client


def api_duration(d: float) -> int:
    """The whole seconds the API is asked for (round half up), or FoundryError when the API cannot do it."""
    n = int(math.floor(float(d) + 0.5))
    lo, hi = DURATION_S
    if not lo <= n <= hi:
        raise FoundryError(f"a {float(d):g}s shot is outside the API's {lo}-{hi}s range.{MCP_HINT}")
    return n


def planned_usd(spec: dict[str, Any], video: dict[str, Any]) -> float:
    """One API clip per shot at the API price: the video_usd line of the plan (hook_reel.plan).

    0 when any shot or the resolution cannot go through the API; such a piece gets no video_usd ceiling,
    so resolve() keeps it on the MCP route."""
    res = video.get("resolution", DEFAULT_RESOLUTION)
    if res not in PRICE_FRAME:
        return 0.0
    try:
        return round(sum(price_usd(api_duration(sh["duration_s"]), res) for sh in spec.get("shots", [])), 2)
    except FoundryError:
        return 0.0


# ---------------------------------------------------------------- route
def _jobs(piece: Piece) -> list[Path]:
    return sorted(piece.rel("incoming").glob("*.api-job.json")) if piece.rel("incoming").exists() else []


def resolve(ws: Workspace, piece: Piece | None = None, live: bool = True, in_flight: bool = True) -> dict[str, Any]:
    """{route, reason, cause, pinned}. Never cached: availability is checked each time it is asked.

    in_flight: a piece with API requests in flight routes to api so they are collected. `generate` turns it
    off before a NEW submit, so another shot's request never waives the pin, key or ceiling checks."""
    video = ws.config["providers"]["video"]
    pinned = video.get("route", "auto")
    if pinned not in ROUTES:
        raise FoundryError(f"providers.video.route must be one of {', '.join(ROUTES)}, not {pinned!r}")
    if in_flight and piece is not None and _jobs(piece):  # money is in flight on the API: collect it there
        shots = ", ".join(p.name.split(".")[0] for p in _jobs(piece))
        return {"route": "api", "reason": f"API requests in flight for {shots}; collect them with foundry generate",
                "cause": None, "pinned": pinned}
    if pinned == "mcp":
        return {"route": "mcp", "reason": "providers.video.route is pinned to mcp", "cause": "pinned",
                "pinned": pinned}

    def unavailable(cause: str) -> dict[str, Any]:
        if pinned == "api":
            raise FoundryError(f"providers.video.route is pinned to api, but {cause}")
        return {"route": "mcp", "reason": f"Higgsfield API unavailable: {cause}", "cause": cause, "pinned": pinned}

    if not credentials():
        return unavailable(NO_KEY)
    if piece is not None:
        inv = piece.invoice
        if inv.get("frozen") and "video_usd" not in (inv.get("ceilings") or {}):
            return unavailable(f"{piece.ref} has no video_usd ceiling (approved before the API route existed, or "
                               f"a shot or the resolution is outside what the API offers)")
    try:
        client = make_client(ws)
        if live:
            client.estimate({"image_url": PROBE_IMAGE, "duration": 5,
                             "resolution": video.get("resolution", DEFAULT_RESOLUTION), "generate_audio": False})
    except HiggsfieldError as e:
        return unavailable(f"the availability check failed ({e})")
    reason = f"key accepted and {client.endpoint} is open to this account" if live else \
        "credentials present (not checked live)"
    return {"route": "api", "reason": reason, "cause": None, "pinned": pinned}


def arguments(ws: Workspace, spec: dict[str, Any], idx: int, prompt: str, image_url: str) -> dict[str, Any]:
    """The Seedance 2.5 image-to-video body. No aspect field: framing follows the start image. No audio:
    the cut replaces it, and the price assumes none."""
    video = ws.config["providers"]["video"]
    res = video.get("resolution", DEFAULT_RESOLUTION)
    if res not in PRICE_FRAME:
        raise FoundryError(f"providers.video.resolution {res!r} is not offered by the API "
                           f"({', '.join(PRICE_FRAME)}).{MCP_HINT}")
    return {"image_url": image_url, "prompt": prompt, "duration": api_duration(spec["shots"][idx]["duration_s"]),
            "resolution": res, "generate_audio": False, "bitrate_mode": "high"}


# ---------------------------------------------------------------- generate
@contextlib.contextmanager
def _shot_lock(piece: Piece, shot: str) -> Iterator[None]:
    """Non-blocking: a second generate for the same shot is refused, never queued behind the first."""
    path = piece.rel("incoming", f".{shot}.generate.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise FoundryError(f"a generation is already running for {piece.ref} {shot}")
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _durable(path: Path, data: dict[str, Any]) -> None:
    """The job file decides what a re-run does, so it must survive a crash right after it is written."""
    write_json(path, data)
    with open(path, "rb") as f:
        os.fsync(f.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _entry(piece: Piece, eid: str) -> dict[str, Any]:
    return next((e for e in piece.invoice["entries"] if e["id"] == eid), {})


def _settle_once(piece: Piece, eid: str, ok: bool, ref: str) -> None:
    """Resumable: a re-run after a crash between settle and ingest must not settle twice."""
    e = _entry(piece, eid)
    if e.get("state") == "reserved":
        piece.settle(eid, ok=ok, ref=ref)
    elif e.get("ref") != ref or e.get("state") != ("settled" if ok else "failed"):
        raise FoundryError(f"invoice entry {eid} is {e.get('state')} with ref {e.get('ref')!r}; expected {ref}. "
                           f"A human can clear the shot with --clear-unknown")


def _void(piece: Piece, eid: str) -> None:
    if _entry(piece, eid).get("state") == "reserved":
        piece.settle(eid, ok=False, void=True)


def _unknown(piece: Piece, shot: str, eid: str, cause: str) -> FoundryError:
    """A submit whose outcome is unknown: record the charge, park the shot for a human, never resubmit."""
    if _entry(piece, eid).get("state") == "reserved":
        piece.settle(eid, ok=True, ref=f"{UNKNOWN_REF_PREFIX}{eid}")
    _durable(piece.rel("incoming", f"{shot}.api-unknown.json"), {"entry": eid, "cause": cause, "at": now()})
    piece.rel("incoming", f"{shot}.api-job.json").unlink(missing_ok=True)
    return FoundryError(f"the submit's outcome is unknown ({cause}); it is recorded as spent on {eid} and nothing was "
                        f"resubmitted. A human must check {CONSOLE_URL} for the request, then run "
                        f"`foundry generate {piece.ref} --shot {shot} --clear-unknown` before this shot can be generated "
                        f"again")


def _clear(piece: Piece, shot: str) -> dict[str, Any]:
    """Human only. Unpark a shot, and abandon a request foundry cannot collect (charged, never lowered)."""
    human_only("generate --clear-unknown")
    unknown = read_json(piece.rel("incoming", f"{shot}.api-unknown.json"))
    job = read_json(piece.rel("incoming", f"{shot}.api-job.json"))
    if job:
        eid = job["entry"]
        if job.get("phase") == "reserved":
            _void(piece, eid)
        elif _entry(piece, eid).get("state") == "reserved":
            piece.settle(eid, ok=True, ref=f"{UNKNOWN_REF_PREFIX}{job.get('request_id') or eid}")
    piece.rel("incoming", f"{shot}.api-unknown.json").unlink(missing_ok=True)
    piece.rel("incoming", f"{shot}.api-job.json").unlink(missing_ok=True)
    # a kill between reserve and the first job-file write leaves a reservation nothing refers to: nothing was sent
    live = {(read_json(p) or {}).get("entry") for p in _jobs(piece)}
    orphans = [e["id"] for e in piece.invoice["entries"]
               if e["unit"] == "video_usd" and e["state"] == "reserved" and e["id"] not in live]
    for eid in orphans:
        _void(piece, eid)
    return {"piece": piece.ref, "shot": shot,
            "cleared": {"unknown": unknown, "abandoned_request": job, "voided_orphans": orphans}}


def generate(ws: Workspace, piece: Piece, shot: str, guidance_from: str | None = None,
             wait_s: float | None = None, clear_unknown: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    check_name(shot, SHOT_RE, "shot id")
    if clear_unknown:
        with _shot_lock(piece, shot):
            return _clear(piece, shot)
    piece.require("building")
    piece.require_pass("frames")
    spec = piece.spec
    ids = [sh["id"] for sh in spec["shots"]]
    if shot not in ids:
        raise FoundryError(f"unknown shot {shot}; this spec has {', '.join(ids)}")
    if wait_s is not None and not 0 < wait_s <= 3600:
        raise FoundryError("--wait-s must be between 0 and 3600 seconds")
    # --wait-s, else providers.video.api.poll_timeout_s, else fit the whole call in CALL_BUDGET_S (~75 s of waiting)
    wait = wait_s or (ws.config["providers"]["video"].get("api") or {}).get("poll_timeout_s")
    budget = float(wait) + COLLECT_RESERVE_S if wait else CALL_BUDGET_S
    if os.environ.get(AGENT_ENV):  # the agent's shell kills long commands: never plan past it
        budget = min(budget, CALL_BUDGET_S)
    deadline = started + budget
    job_path = piece.rel("incoming", f"{shot}.api-job.json")
    with _shot_lock(piece, shot):
        if piece.rel("incoming", f"{shot}.api-unknown.json").exists():
            u = read_json(piece.rel("incoming", f"{shot}.api-unknown.json")) or {}
            raise FoundryError(f"an earlier submit for {shot} ({u.get('entry')}, {u.get('at')}) has an unknown outcome. "
                               f"A human must check {CONSOLE_URL}, then run `foundry generate {piece.ref} --shot {shot} "
                               f"--clear-unknown`")
        job = read_json(job_path)
        if job and job.get("phase") == "reserved":  # killed before anything was sent: nothing was bought
            _void(piece, job["entry"])
            job_path.unlink(missing_ok=True)
            job = None
        if job and job.get("phase") == "submitting":  # killed inside the POST
            raise _unknown(piece, shot, job["entry"], "the previous generate was interrupted while submitting")
        if job:
            try:
                client = make_client(ws)
            except HiggsfieldError as e:
                raise FoundryError(f"request {job['request_id']} is in flight but the key is unusable ({e})")
            if client is None:
                raise FoundryError(f"request {job['request_id']} is in flight but {NO_KEY}; restore the key and run "
                                   f"foundry generate again to collect it")
            return _collect(ws, piece, client, job, job_path, deadline, resumed=True)
        route = resolve(ws, piece, live=False, in_flight=False)  # `foundry route` checked live; the submit re-checks
        if route["route"] != "api":
            raise FoundryError(f"the video route is mcp ({route['reason']}).{MCP_HINT}")
        client = make_client(ws)
        job = _submit(ws, piece, client, spec, ids.index(shot), shot, guidance_from, job_path, deadline)
        return _collect(ws, piece, client, job, job_path, deadline, resumed=False)


def _left(deadline: float) -> float:
    return deadline - time.monotonic()


def _submit(ws: Workspace, piece: Piece, client: HiggsfieldAPI, spec: dict[str, Any], idx: int, shot: str,
            guidance_from: str | None, job_path: Path, deadline: float) -> dict[str, Any]:
    with piece.exclusive():  # refuse a regeneration without a red clip QC or budget before spending anything
        if piece.rel("clips", f"{shot}.mp4").exists():
            loop.begin_regeneration(piece, "clip")
    guidance = ""
    if guidance_from:
        guidance = ((read_json(piece.rel("qc", f"{guidance_from}.json")) or {}).get("guidance")) or ""
    args = arguments(ws, spec, idx, spec_mod.motion_prompt(ws, spec, idx, guidance), PROBE_IMAGE)
    cost = price_usd(args["duration"], args["resolution"])
    frame = sha256_file(piece.rel(loop.APPROVED))
    eid = piece.reserve("video_usd", cost, f"{shot} via Higgsfield API {client.endpoint}")  # may BLOCK
    base = {"entry": eid, "shot": shot, "cost_usd": cost, "frame_sha256": frame, "endpoint": client.endpoint}
    _durable(job_path, {**base, "phase": "reserved", "at": now()})

    try:  # nothing has been submitted yet: any failure here costs nothing
        up = client.upload_url("image/png")
        loop.put_presigned(ws, piece, up["upload_url"], up["upload_headers"],
                           timeout=max(1.0, min(client.timeout, _left(deadline))))
        args["image_url"] = up["public_url"]
        if _left(deadline) < client.timeout + SUBMIT_MARGIN_S:
            raise FoundryError("not enough time left in this call to submit safely; run foundry generate again "
                               "(nothing was submitted or spent)")
    except BaseException:
        _void(piece, eid)
        job_path.unlink(missing_ok=True)
        raise

    _durable(job_path, {**base, "phase": "submitting", "at": now()})  # BEFORE the POST
    try:
        sub = client.submit(args)
    except HiggsfieldError as e:
        if e.ambiguous:  # it may have been accepted and billed: record the charge, never resubmit
            raise _unknown(piece, shot, eid, str(e))
        _void(piece, eid)  # refused: nothing was accepted
        job_path.unlink(missing_ok=True)
        raise FoundryError(f"the Higgsfield API refused the submit ({e})." + (MCP_HINT if e.status in UNAVAILABLE else ""))
    job = {**base, "phase": "submitted", "request_id": sub["request_id"], "status_url": sub["status_url"],
           "correlation_id": sub.get("correlation_id"), "prompt_guidance": guidance, "submitted_at": now()}
    _durable(job_path, job)
    return job


def _already_ingested(piece: Piece, job: dict[str, Any]) -> dict[str, Any] | None:
    """A kill after ingest but before the job file was removed: the clip is in, finish cleanly."""
    clip = read_json(piece.rel("clips", f"{job['shot']}.json")) or {}
    if _entry(piece, job["entry"]).get("consumed"):  # consume runs only after the clip is in place
        return {"piece": piece.ref, "shot": job["shot"], "cycle": clip.get("cycle"), "already_ingested": True}
    return None


def _collect(ws: Workspace, piece: Piece, client: HiggsfieldAPI, job: dict[str, Any], job_path: Path,
             deadline: float, resumed: bool) -> dict[str, Any]:
    rid, eid, shot = job["request_id"], job["entry"], job["shot"]
    done = {"route": "api", "request_id": rid, "entry": eid, "cost_usd": job["cost_usd"], "resumed": resumed}
    if (prior := _already_ingested(piece, job)) is not None:
        job_path.unlink(missing_ok=True)
        return {**prior, **done, "next": "look at the sampled frames, record the hands verdict, then foundry qc --stage clip"}
    again = f"run foundry generate {piece.ref} --shot {shot} again: it resumes request {rid} and never resubmits"
    budget = _left(deadline) - COLLECT_RESERVE_S
    if budget <= 0:
        raise FoundryError(f"request {rid} is submitted; {again}")
    try:
        res = client.wait(job["status_url"], budget)
    except HiggsfieldError as e:
        if e.pending:
            raise FoundryError(f"request {rid} is not finished ({e}); {again}")
        raise FoundryError(f"could not read request {rid} ({e}); its reservation {eid} stays open. Try again; if it "
                           f"keeps failing, a human can check {CONSOLE_URL} and abandon it with --clear-unknown")
    status = res["status"]
    if status != "completed":
        _settle_once(piece, eid, ok=False, ref=rid)  # counted, conservatively, though upstream refunds it
        job_path.unlink(missing_ok=True)
        guide = " The prompt tripped the provider's safety filter; see catalog/safety_phrases.json." if status == "nsfw" else ""
        raise FoundryError(f"Higgsfield request {rid} ended {status} ({res.get('error') or status}); settled as failed."
                           f"{guide}")
    _settle_once(piece, eid, ok=True, ref=rid)  # completed is billed, whatever happens next
    if job.get("frame_sha256") != sha256_file(piece.rel(loop.APPROVED)):
        job_path.unlink(missing_ok=True)
        raise FoundryError(f"request {rid} was generated from a first frame that has since been replaced; it is "
                           f"charged on {eid} but not ingested. Generate the shot again from the new frame")
    url = (res.get("video") or {}).get("url")
    if not url:
        job_path.unlink(missing_ok=True)
        raise FoundryError(f"request {rid} completed without a video URL; {eid} is settled as spent")
    if _left(deadline) < COLLECT_RESERVE_S / 2:
        raise FoundryError(f"request {rid} completed; {again} to download it")
    mp4 = loop.download_clip(ws, piece, url, job=rid, shot=shot, timeout=max(1.0, _left(deadline) / 2))
    try:
        with piece.exclusive():
            ingest = loop.ingest_clip(ws, piece, mp4, job=rid, shot=shot, units=("video_usd",))
    finally:
        mp4.unlink(missing_ok=True)
    job_path.unlink(missing_ok=True)
    return {**ingest, **done}
