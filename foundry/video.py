"""Video routes: the Higgsfield API when it is available, the Higgsfield MCP otherwise.

SPEC.md "Higgsfield API route". `resolve` decides the route live for each build; `generate` runs the
whole API path inside foundry — price, reserve, upload, submit, poll, settle, download, ingest — so the
build agent never holds a generate tool or the key, and every API spend passes through the invoice.
"""
from __future__ import annotations

import contextlib
import fcntl
import math
from typing import Any, Callable, Iterator

from engine.providers.higgsfield_api import (BASE_URL, DURATION_S, ENDPOINT, PRICE_FRAME, PROBE_IMAGE,
                                             USD_PER_1K_TOKENS, HiggsfieldAPI, HiggsfieldError, credentials,
                                             price_usd)

from . import loop
from . import spec as spec_mod
from .piece import VIDEO_UNITS, Piece  # noqa: F401  (re-exported for callers)
from .util import SHOT_RE, FoundryError, check_name, human_only, now, read_json, write_json
from .workspace import Workspace

ROUTES = ("auto", "api", "mcp")
API_DEFAULTS: dict[str, Any] = {"base_url": BASE_URL, "endpoint": ENDPOINT, "usd_per_1k_tokens": USD_PER_1K_TOKENS,
                                "bitrate_mode": "high", "poll_timeout_s": 90, "request_timeout_s": 60}
# poll_timeout_s is per `foundry generate` call, not per clip: the build agent's shell kills long commands
# (~2 min), so each call waits briefly and a re-run resumes the same request. Humans can pass --wait-s.
CONSOLE_URL = "https://console.higgsfield.ai"
NO_KEY = "no HF_KEY (or HF_API_KEY + HF_API_SECRET) in the environment or the workspace .env"


def api_cfg(video: dict[str, Any]) -> dict[str, Any]:
    return {**API_DEFAULTS, **(video.get("api") or {})}


def _client(ws: Workspace) -> HiggsfieldAPI | None:
    key = credentials()
    if not key:
        return None
    cfg = api_cfg(ws.config["providers"]["video"])
    return HiggsfieldAPI(key, base_url=cfg["base_url"], endpoint=cfg["endpoint"],
                         timeout=float(cfg["request_timeout_s"]))


# Tests replace this with a fake; everything else goes through it.
make_client: Callable[[Workspace], HiggsfieldAPI | None] = _client


def planned_usd(spec: dict[str, Any], video: dict[str, Any]) -> float:
    """One API clip per shot at the API price: the video_usd line of the plan (hook_reel.plan)."""
    cfg = api_cfg(video)
    res = video.get("resolution", "720p")
    if res not in PRICE_FRAME:
        return 0.0
    return round(sum(price_usd(max(DURATION_S[0], round(float(sh["duration_s"]))), res,
                               float(cfg["usd_per_1k_tokens"])) for sh in spec.get("shots", [])), 2)


# ---------------------------------------------------------------- route
def resolve(ws: Workspace, piece: Piece | None = None, live: bool = True) -> dict[str, Any]:
    """{route, reason, pinned}. Never cached: availability is checked each time it is asked."""
    video = ws.config["providers"]["video"]
    pinned = video.get("route", "auto")
    if pinned not in ROUTES:
        raise FoundryError(f"providers.video.route must be one of {', '.join(ROUTES)}, not {pinned!r}")
    if pinned == "mcp":
        return {"route": "mcp", "reason": "providers.video.route is pinned to mcp", "pinned": pinned}

    def unavailable(reason: str) -> dict[str, Any]:
        if pinned == "api":
            raise FoundryError(f"providers.video.route is pinned to api, but {reason}")
        return {"route": "mcp", "reason": f"Higgsfield API unavailable: {reason}", "pinned": pinned}

    if not credentials():
        return unavailable(NO_KEY)
    if piece is not None:
        inv = piece.invoice
        if inv.get("frozen") and "video_usd" not in (inv.get("ceilings") or {}):
            return unavailable(f"{piece.ref} was approved before the API route existed, so its invoice has no "
                               f"video_usd ceiling")
    if not live:
        return {"route": "api", "reason": "credentials present (not checked live: --offline)", "pinned": pinned}
    client = make_client(ws)
    try:
        client.estimate(_probe_args(video))
    except HiggsfieldError as e:
        return unavailable(f"the availability check failed ({e})")
    return {"route": "api", "reason": f"key accepted and {client.endpoint} is open to this account", "pinned": pinned}


def _probe_args(video: dict[str, Any]) -> dict[str, Any]:
    return {"image_url": PROBE_IMAGE, "duration": 5, "resolution": video.get("resolution", "720p"),
            "generate_audio": bool(video.get("audio", False))}


def arguments(ws: Workspace, spec: dict[str, Any], idx: int, prompt: str, image_url: str) -> dict[str, Any]:
    """The Seedance 2.5 image-to-video body. No aspect field: framing follows the start image."""
    video = ws.config["providers"]["video"]
    d = float(spec["shots"][idx]["duration_s"])
    n = int(math.floor(d + 0.5))
    lo, hi = DURATION_S
    if not lo <= n <= hi or abs(n - d) > 0.5:
        raise FoundryError(f"{spec['shots'][idx]['id']} runs {d:g}s; the API takes whole seconds from {lo} to {hi}")
    res = video.get("resolution", "720p")
    if res not in PRICE_FRAME:
        raise FoundryError(f"providers.video.resolution {res!r} is not offered by the API ({', '.join(PRICE_FRAME)})")
    return {"image_url": image_url, "prompt": prompt, "duration": n, "resolution": res,
            "generate_audio": bool(video.get("audio", False)),
            "bitrate_mode": api_cfg(video)["bitrate_mode"]}


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


def _entry(piece: Piece, eid: str) -> dict[str, Any]:
    return next((e for e in piece.invoice["entries"] if e["id"] == eid), {})


def _settle_once(piece: Piece, eid: str, ok: bool, ref: str) -> None:
    """Resumable: a re-run after a crash between settle and ingest must not settle twice."""
    e = _entry(piece, eid)
    if e.get("state") == "reserved":
        piece.settle(eid, ok=ok, ref=ref)
    elif e.get("ref") != ref or e.get("state") != ("settled" if ok else "failed"):
        raise FoundryError(f"invoice entry {eid} is {e.get('state')} with ref {e.get('ref')!r}; expected {ref}")


def _unknown(piece: Piece, shot: str, eid: str, cause: str) -> FoundryError:
    """A submit whose outcome is unknown: record the charge, park the shot for a human, never resubmit."""
    if _entry(piece, eid).get("state") == "reserved":
        piece.settle(eid, ok=True, ref=f"unknown-{eid}")
    write_json(piece.rel("incoming", f"{shot}.api-unknown.json"), {"entry": eid, "cause": cause, "at": now()})
    piece.rel("incoming", f"{shot}.api-job.json").unlink(missing_ok=True)
    return FoundryError(f"the submit's outcome is unknown ({cause}); it is recorded as spent on {eid} and nothing was "
                        f"resubmitted. A human must check {CONSOLE_URL} for the request, then run "
                        f"`foundry generate {piece.ref} --shot {shot} --clear-unknown` before this shot can be generated "
                        f"again")


def generate(ws: Workspace, piece: Piece, shot: str, guidance_from: str | None = None,
             wait_s: float | None = None, clear_unknown: bool = False) -> dict[str, Any]:
    check_name(shot, SHOT_RE, "shot id")
    unknown_path = piece.rel("incoming", f"{shot}.api-unknown.json")
    if clear_unknown:
        human_only("generate --clear-unknown")
        prior = read_json(unknown_path)
        unknown_path.unlink(missing_ok=True)
        return {"piece": piece.ref, "shot": shot, "cleared": prior}
    piece.require("building")
    piece.require_pass("frames")
    spec = piece.spec
    ids = [sh["id"] for sh in spec["shots"]]
    if shot not in ids:
        raise FoundryError(f"unknown shot {shot}; this spec has {', '.join(ids)}")
    if wait_s is not None and not 0 < wait_s <= 3600:
        raise FoundryError("--wait-s must be between 0 and 3600 seconds")
    pending_path = piece.rel("incoming", f"{shot}.api-job.json")
    with _shot_lock(piece, shot):
        if unknown_path.exists():
            u = read_json(unknown_path) or {}
            raise FoundryError(f"an earlier submit for {shot} ({u.get('entry')}, {u.get('at')}) has an unknown outcome. "
                               f"A human must check {CONSOLE_URL}, then run `foundry generate {piece.ref} --shot {shot} "
                               f"--clear-unknown`")
        pending = read_json(pending_path)
        if pending and pending.get("phase") == "submitting":  # the process died inside the submit POST
            raise _unknown(piece, shot, pending["entry"], "the previous generate was interrupted while submitting")
        if pending:
            client = make_client(ws)
            if client is None:
                raise FoundryError(f"request {pending['request_id']} is pending but {NO_KEY}; restore the key "
                                   f"and run foundry generate again to collect it")
            return _collect(ws, piece, client, pending, pending_path, resumed=True, wait_s=wait_s)
        route = resolve(ws, piece)
        if route["route"] != "api":
            raise FoundryError(f"the video route is mcp ({route['reason']}); use the MCP steps for this clip")
        client = make_client(ws)
        pending = _submit(ws, piece, client, spec, ids.index(shot), shot, guidance_from, pending_path)
        return _collect(ws, piece, client, pending, pending_path, resumed=False, wait_s=wait_s)


def _submit(ws: Workspace, piece: Piece, client: HiggsfieldAPI, spec: dict[str, Any], idx: int, shot: str,
            guidance_from: str | None, pending_path) -> dict[str, Any]:
    with piece.exclusive():  # refuse a regeneration without a red clip QC or budget before spending anything
        if piece.rel("clips", f"{shot}.mp4").exists():
            loop.begin_regeneration(piece, "clip")
    guidance = ""
    if guidance_from:
        guidance = ((read_json(piece.rel("qc", f"{guidance_from}.json")) or {}).get("guidance")) or ""
    prompt = spec_mod.motion_prompt(ws, spec, idx, guidance)
    args = arguments(ws, spec, idx, prompt, PROBE_IMAGE)
    cost = price_usd(args["duration"], args["resolution"],
                     float(api_cfg(ws.config["providers"]["video"])["usd_per_1k_tokens"]))
    eid = piece.reserve("video_usd", cost, f"{shot} via Higgsfield API {client.endpoint}")  # may BLOCK

    try:  # nothing has been submitted yet: any failure here costs nothing
        up = client.upload_url("image/png")
        loop.put_presigned(ws, piece, up["upload_url"], up["upload_headers"])
        args["image_url"] = up["public_url"]
    except Exception:
        piece.settle(eid, ok=False)
        raise

    # Written BEFORE the POST: if this process dies inside it, the next run knows a submit may have landed.
    write_json(pending_path, {"phase": "submitting", "entry": eid, "shot": shot, "cost_usd": cost, "at": now()})
    try:
        sub = client.submit(args)
    except HiggsfieldError as e:
        if e.ambiguous:  # it may have been accepted and billed: record the charge, never resubmit
            raise _unknown(piece, shot, eid, str(e))
        pending_path.unlink(missing_ok=True)
        piece.settle(eid, ok=False)
        hint = " The API route is unavailable for this clip; use the MCP steps." if e.status in (401, 403, 404, 423, 503) else ""
        raise FoundryError(f"the Higgsfield API refused the submit ({e}).{hint}")
    pending = {"phase": "submitted", "request_id": sub["request_id"], "status_url": sub["status_url"], "entry": eid,
               "shot": shot, "cost_usd": cost, "endpoint": client.endpoint,
               "correlation_id": sub.get("correlation_id"), "prompt_guidance": guidance, "submitted_at": now()}
    write_json(pending_path, pending)
    return pending


def _collect(ws: Workspace, piece: Piece, client: HiggsfieldAPI, pending: dict[str, Any], pending_path,
             resumed: bool, wait_s: float | None = None) -> dict[str, Any]:
    rid, eid, shot = pending["request_id"], pending["entry"], pending["shot"]
    timeout = float(wait_s or api_cfg(ws.config["providers"]["video"])["poll_timeout_s"])
    try:
        res = client.wait(pending["status_url"], timeout)
    except HiggsfieldError as e:
        if e.pending:
            raise FoundryError(f"request {rid} is not finished ({e}); run foundry generate {piece.ref} --shot {shot} "
                               f"again to keep waiting — it resumes this request and does not resubmit")
        raise FoundryError(f"could not read request {rid} ({e}); its reservation {eid} stays open. Run foundry "
                           f"generate again to retry reading it")
    status = res["status"]
    if status != "completed":
        _settle_once(piece, eid, ok=False, ref=rid)
        pending_path.unlink(missing_ok=True)
        why = res.get("error") or status
        guide = (" The prompt tripped the provider's safety filter; see catalog/safety_phrases.json."
                 if status == "nsfw" else "")
        raise FoundryError(f"Higgsfield request {rid} ended {status} ({why}); not charged upstream, settled as failed."
                           f"{guide}")
    url = (res.get("video") or {}).get("url")
    _settle_once(piece, eid, ok=True, ref=rid)  # completed is billed, whatever happens next
    if not url:
        pending_path.unlink(missing_ok=True)
        raise FoundryError(f"request {rid} completed without a video URL; {eid} is settled as spent")
    mp4 = loop.download_clip(ws, piece, url, job=rid, shot=shot)
    try:
        with piece.exclusive():
            ingest = loop.ingest_clip(ws, piece, mp4, job=rid, shot=shot)
    finally:
        mp4.unlink(missing_ok=True)
    pending_path.unlink(missing_ok=True)
    return {**ingest, "route": "api", "request_id": rid, "entry": eid, "cost_usd": pending["cost_usd"],
            "resumed": resumed}

