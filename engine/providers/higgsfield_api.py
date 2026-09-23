"""Higgsfield REST API client for Seedance image-to-video. Standard library only.

The contract is SPEC.md "Higgsfield API route" (checked against docs.higgsfield.ai and the official
higgsfield-client SDK, 2026-09-23). Three rules shape everything here:

- Credentials go only to the configured base URL's host. Presigned upload URLs and result URLs are
  fetched by the caller, without them. A `status_url` from a response is followed only if it points
  at the same host.
- A generation submit is never retried: the API has no idempotency key, so a network error, timeout,
  or any 5xx other than 503 on the POST is an unknown outcome (`HiggsfieldError.ambiguous`), not a
  failure to repeat. Every 4xx, and 503 ("model disabled or not ready" per the docs), is a refusal:
  nothing was accepted.
- Status polls retry with backoff, and never run past a caller's deadline.

The network call is injectable (`send`) so tests never touch the internet.
"""
from __future__ import annotations

import http.client
import json
import math
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

BASE_URL = "https://api.higgsfield.ai"
ENDPOINT = "bytedance/seedance-2.5/image-to-video"
USD_PER_1K_TOKENS = 0.0214  # Seedance 2.5 at 480p/720p, before customer discounts (estimate endpoint, 2026-09-23)
# Pricing frame per resolution tier. Output framing follows the start image, so the real frame is
# never larger than the 9:16 box; pricing at the box never under-reserves.
PRICE_FRAME = {"480p": (480, 854), "720p": (720, 1280)}
DURATION_S = (4, 30)
TERMINAL = frozenset({"completed", "failed", "nsfw", "canceled"})
KNOWN = TERMINAL | {"queued", "in_progress"}
CONSOLE_URL = "https://console.higgsfield.ai"  # API keys, request history and spend
RETRY_GET = frozenset({408, 429, 500, 502, 503, 504})
# The API route is unavailable to this account right now (docs: concepts/errors): fall back to the MCP.
UNAVAILABLE = frozenset({401, 403, 404, 423, 503})
DEFAULT_TIMEOUT_S = 20.0
# Network failures, including a response cut short mid-body (http.client errors are not OSError).
NETWORK = (OSError, http.client.HTTPException)
PROBE_IMAGE = "https://example.com/foundry-probe.png"  # the estimate endpoint checks the shape, not the file
USER_AGENT = "foundry-higgsfield/1.1"


def rejected(status: int) -> bool:
    """A submit answered with this status was refused: nothing was accepted, nothing is billed."""
    return 400 <= status < 500 or status == 503

# (method, url, body, headers, timeout) -> (status, headers, body)
Send = Callable[[str, str, bytes | None, Mapping[str, str], float], tuple[int, Mapping[str, str], bytes]]


class HiggsfieldError(Exception):
    """An API call that did not succeed.

    status: HTTP status, or None for a network error / timeout.
    ambiguous: True when a submit may have been accepted anyway (never resubmit).
    pending: True when polling hit the deadline with the request still running.
    """

    def __init__(self, message: str, status: int | None = None, correlation_id: str | None = None,
                 ambiguous: bool = False, pending: bool = False):
        super().__init__(message)
        self.status = status
        self.correlation_id = correlation_id
        self.ambiguous = ambiguous
        self.pending = pending


def credentials(env: Mapping[str, str] | None = None) -> str | None:
    """HF_KEY, or HF_API_KEY + HF_API_SECRET, as the SDK reads them. None when absent."""
    env = os.environ if env is None else env
    key = (env.get("HF_KEY") or "").strip()
    if key:
        return key
    k, s = (env.get("HF_API_KEY") or "").strip(), (env.get("HF_API_SECRET") or "").strip()
    return f"{k}:{s}" if k and s else None


def price_usd(seconds: float, resolution: str = "720p", rate: float = USD_PER_1K_TOKENS) -> float:
    """Seedance 2.5 token pricing, rounded UP to the cent: ceil(s * w * h * 24 / 1024) tokens."""
    if resolution not in PRICE_FRAME:
        raise ValueError(f"no price for resolution {resolution!r}; known: {', '.join(PRICE_FRAME)}")
    w, h = PRICE_FRAME[resolution]
    tokens = math.ceil(seconds * w * h * 24 / 1024)
    return math.ceil(tokens * rate / 1000 * 100 - 1e-9) / 100


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect on an authenticated call could carry the key to another host. Refuse it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"refusing redirect to {newurl}", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect())


def urllib_send(method: str, url: str, body: bytes | None, headers: Mapping[str, str],
                timeout: float) -> tuple[int, Mapping[str, str], bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() if e.fp else b""


def _detail(body: bytes) -> str:
    try:
        data = json.loads(body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return body[:200].decode(errors="replace")
    if isinstance(data, dict):
        d = data.get("detail") or data.get("message") or data.get("error") or data
        return d if isinstance(d, str) else json.dumps(d)[:300]
    return str(data)[:300]


class HiggsfieldAPI:
    def __init__(self, key: str, base_url: str = BASE_URL, endpoint: str = ENDPOINT, send: Send | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 timeout: float = DEFAULT_TIMEOUT_S):
        if not key or ":" not in key:
            raise HiggsfieldError("the Higgsfield key must look like <key_id>:<secret>")
        u = urllib.parse.urlparse(base_url)
        if u.scheme != "https" or not u.hostname:
            raise HiggsfieldError(f"base_url must be https: {base_url!r}")
        self._key = key
        self.base_url = base_url.rstrip("/")
        self.host = u.hostname
        self.endpoint = endpoint.strip("/")
        self._send = send or urllib_send
        self._sleep = sleep
        self._clock = clock
        self.timeout = timeout

    def __repr__(self) -> str:  # never print the key
        return f"HiggsfieldAPI(base_url={self.base_url!r}, endpoint={self.endpoint!r})"

    # ------------------------------------------------------------ transport
    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith("https://") or path_or_url.startswith("http://"):
            u = urllib.parse.urlparse(path_or_url)
            if u.scheme != "https" or u.hostname != self.host:
                raise HiggsfieldError(f"refusing to send credentials to {u.scheme}://{u.hostname}; "
                                      f"only {self.host} is trusted")
            return path_or_url
        return f"{self.base_url}/{path_or_url.lstrip('/')}"

    def _once(self, method: str, path_or_url: str, payload: Any = None,
              timeout: float | None = None) -> tuple[int, str | None, bytes]:
        url = self._url(path_or_url)
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Authorization": f"Key {self._key}", "Accept": "application/json", "User-Agent": USER_AGENT}
        if body is not None:
            headers["Content-Type"] = "application/json"
        status, rh, data = self._send(method, url, body, headers, timeout or self.timeout)
        cid = next((v for k, v in (rh or {}).items() if k.lower() == "x-correlation-id"), None)
        return status, cid, data

    @staticmethod
    def _json(data: bytes, status: int, cid: str | None) -> dict[str, Any]:
        try:
            out = json.loads(data.decode() or "{}")
        except (ValueError, UnicodeDecodeError):
            raise HiggsfieldError(f"unreadable response (HTTP {status})", status, cid)
        if not isinstance(out, dict):
            raise HiggsfieldError(f"unexpected response shape (HTTP {status})", status, cid)
        return out

    def _call(self, method: str, path_or_url: str, payload: Any = None) -> dict[str, Any]:
        """One attempt; any non-2xx or network failure raises (not ambiguous)."""
        try:
            status, cid, data = self._once(method, path_or_url, payload)
        except NETWORK as e:
            raise HiggsfieldError(f"network error: {getattr(e, 'reason', e)}") from e
        if not 200 <= status < 300:
            raise HiggsfieldError(f"HTTP {status}: {_detail(data)}", status, cid)
        return self._json(data, status, cid)

    # ------------------------------------------------------------ calls
    def estimate(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Free. 200 means the key works and the model is open to this account."""
        return self._call("POST", f"estimate/{self.endpoint}", dict(arguments))

    def upload_url(self, content_type: str = "image/png") -> dict[str, Any]:
        out = self._call("POST", "files/generate-upload-url", {"content_type": content_type})
        for k in ("public_url", "upload_url"):
            if not isinstance(out.get(k), str) or not out[k].startswith("https://"):
                raise HiggsfieldError(f"upload URL response has no https {k}")
        headers = out.get("upload_headers") or {"Content-Type": content_type}
        if not isinstance(headers, dict):
            raise HiggsfieldError("upload_headers is not an object")
        out["upload_headers"] = {str(k): str(v) for k, v in headers.items()}
        return out

    def submit(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Exactly one POST. A network error, a timeout, or a 5xx other than 503 is ambiguous; see `rejected`."""
        try:
            status, cid, data = self._once("POST", self.endpoint, dict(arguments))
        except NETWORK as e:
            raise HiggsfieldError(f"submit outcome unknown (network: {getattr(e, 'reason', e)})",
                                  ambiguous=True) from e
        if rejected(status):
            raise HiggsfieldError(f"HTTP {status}: {_detail(data)}", status, cid)
        if not 200 <= status < 300:
            raise HiggsfieldError(f"submit outcome unknown (HTTP {status}: {_detail(data)})", status, cid,
                                  ambiguous=True)
        try:  # a 2xx means it was accepted: an unreadable body is an unknown outcome, never a refusal
            out = self._json(data, status, cid)
        except HiggsfieldError as e:
            raise HiggsfieldError(f"submit outcome unknown ({e})", status, cid, ambiguous=True)
        if not out.get("request_id") or not out.get("status_url"):
            raise HiggsfieldError("submit accepted without a request_id/status_url", status, cid, ambiguous=True)
        try:
            self._url(out["status_url"])  # validate the host before we ever poll it
        except HiggsfieldError as e:  # accepted (and billed) upstream, but we will not follow it: unknown outcome
            raise HiggsfieldError(f"submit accepted as {out['request_id']} but {e}", status, cid, ambiguous=True)
        out["correlation_id"] = cid
        return out

    def status(self, status_url: str, deadline: float) -> dict[str, Any]:
        """GET with backoff on network errors, 408/429 and 5xx. Never starts an attempt, or lets one run, past
        `deadline` (monotonic seconds): each attempt's timeout is capped by the time left."""
        delay = 1.0
        while True:
            left = deadline - self._clock()
            if left <= 0:
                raise HiggsfieldError("no time left to read the request status", pending=True)
            try:
                status, cid, data = self._once("GET", status_url, timeout=min(self.timeout, max(1.0, left)))
                if 200 <= status < 300:
                    out = self._json(data, status, cid)
                    if out.get("status") not in KNOWN:
                        raise HiggsfieldError(f"unknown request status {out.get('status')!r}", status, cid)
                    return out
                if status not in RETRY_GET:
                    raise HiggsfieldError(f"HTTP {status}: {_detail(data)}", status, cid)
                reason = f"HTTP {status}"
            except NETWORK as e:
                reason = f"network: {getattr(e, 'reason', e)}"
            if self._clock() + delay > deadline:
                raise HiggsfieldError(f"status check kept failing ({reason})", pending=True)
            self._sleep(delay + random.uniform(0, 0.25))
            delay = min(delay * 2, 10.0)

    def wait(self, status_url: str, timeout_s: float) -> dict[str, Any]:
        """Poll until a terminal status: 2 s, growing x1.5 to 10 s, with jitter (docs: concepts/polling)."""
        deadline = self._clock() + timeout_s
        delay = 2.0
        while True:
            out = self.status(status_url, deadline)
            if out["status"] in TERMINAL:
                return out
            if self._clock() + delay > deadline:
                raise HiggsfieldError(f"request is still {out['status']} after {timeout_s:g}s", pending=True)
            self._sleep(delay + random.uniform(0, 0.5))
            delay = min(delay * 1.5, 10.0)
