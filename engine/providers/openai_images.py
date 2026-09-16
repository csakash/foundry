"""OpenAI images API: text-to-image and image edit, stdlib only.

- One image per request, looped, exactly like the proven casting script
  (gmm-contents pipeline/gen_casting_openai.py): a refusal costs one candidate, not all.
- Rate limit: the org caps input images per minute; every call waits for enough
  slots in a sliding 60 s window before it is sent. A 429 waits out a full window.
- Transport errors and timeouts are retried; the timeout matches the proven script (600 s).
- Moderation: gpt-image refusals are stochastic (the Imani cast cleared about one
  bootstrap in three), so a 400 whose body names moderation/safety is retried up to
  `retries` times. Every other error raises immediately.
- Returns PNG bytes, one per image.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Sequence

GEN = "https://api.openai.com/v1/images/generations"
EDIT = "https://api.openai.com/v1/images/edits"
MODELS = "https://api.openai.com/v1/models/"


class ImageRefused(RuntimeError):
    """The provider refused every attempt on safety grounds."""


class OpenAIImages:
    kind = "openai-images"

    def __init__(self, model: str = "gpt-image-2.5-sunburst", quality: str = "high", rpm_images: int = 5,
                 retries: int = 5, timeout: int = 600, sleep=time.sleep):
        self.model, self.quality, self.rpm, self.retries, self.timeout = model, quality, rpm_images, retries, timeout
        self._slots: list[float] = []
        self._sleep = sleep

    # ------------------------------------------------------------ plumbing
    @property
    def key(self) -> str:
        k = os.environ.get("OPENAI_API_KEY")
        if not k:
            raise RuntimeError("OPENAI_API_KEY is not set (put it in the workspace .env)")
        return k

    def _wait_slots(self, n: int) -> None:
        n = max(1, min(n, self.rpm))
        while True:
            t = time.monotonic()
            self._slots = [s for s in self._slots if t - s < 60]
            if len(self._slots) + n <= self.rpm:
                self._slots += [t] * n
                return
            self._sleep(60 - (t - self._slots[0]) + 0.5)

    def _post(self, url: str, body: bytes, content_type: str) -> dict:
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": content_type})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    def _call(self, url: str, body: bytes, content_type: str, images_in: int) -> list[bytes]:
        last = ""
        for attempt in range(1, self.retries + 1):
            self._wait_slots(images_in)
            try:
                data = self._post(url, body, content_type)
                return [base64.b64decode(d["b64_json"]) for d in data["data"]]
            except urllib.error.HTTPError as e:
                text = e.read().decode(errors="replace")
                last = text[:400]
                if e.code == 400 and any(w in text.lower() for w in ("moderation", "safety", "content_policy")):
                    continue
                if e.code == 429 and attempt < self.retries:
                    self._sleep(62)
                    continue
                if e.code in (500, 502, 503) and attempt < self.retries:
                    self._sleep(min(60, 5 * attempt))
                    continue
                raise RuntimeError(f"OpenAI images HTTP {e.code}: {last}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = f"transport: {e}"
                if attempt < self.retries:
                    self._sleep(min(60, 5 * attempt))
                    continue
                raise RuntimeError(f"OpenAI images unreachable after {attempt} attempts: {last}") from None
        raise ImageRefused(f"refused {self.retries}x on safety grounds: {last}")

    # ------------------------------------------------------------ API
    def generate(self, prompt: str, n: int = 1, size: str = "1024x1536") -> list[bytes]:
        body = json.dumps({"model": self.model, "prompt": prompt, "n": 1, "size": size,
                           "quality": self.quality}).encode()
        return [img for _ in range(n) for img in self._call(GEN, body, "application/json", images_in=1)]

    def edit(self, prompt: str, refs: Sequence[str | Path], n: int = 1, size: str = "1024x1536") -> list[bytes]:
        return [img for _ in range(n) for img in self._edit_one(prompt, refs, size)]

    def _edit_one(self, prompt: str, refs: Sequence[str | Path], size: str) -> list[bytes]:
        boundary = uuid.uuid4().hex
        parts: list[bytes] = []

        def field(name: str, value: str) -> None:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())

        for k, v in (("model", self.model), ("prompt", prompt), ("n", "1"), ("size", size),
                     ("quality", self.quality)):
            field(k, v)
        for ref in refs:
            p = Path(ref)
            mime = mimetypes.guess_type(p.name)[0] or "image/png"
            parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; '
                          f'filename="{p.name}"\r\nContent-Type: {mime}\r\n\r\n').encode() + p.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return self._call(EDIT, b"".join(parts), f"multipart/form-data; boundary={boundary}", images_in=len(refs))

    def check_model(self) -> tuple[bool, str]:
        """Free call: does the configured model exist for this key?"""
        req = urllib.request.Request(MODELS + self.model, headers={"Authorization": f"Bearer {self.key}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return True, json.loads(r.read()).get("id", self.model)
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}"
        except urllib.error.URLError as e:
            return False, f"network: {e.reason}"
