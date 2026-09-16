"""Provider adapters. `get_image_provider(config)` picks one from foundry.json providers.image.kind."""
from __future__ import annotations

from typing import Any


def get_image_provider(cfg: dict[str, Any]):
    kind = cfg.get("kind")
    if kind == "openai-images":
        from .openai_images import OpenAIImages
        keys = {"model": "model", "quality": "quality", "rpm_images": "rpm_images"}
        return OpenAIImages(**{arg: cfg[k] for k, arg in keys.items() if k in cfg})
    if kind == "fake":
        from .fake_images import FakeImages
        return FakeImages(skin=tuple(cfg.get("skin", (62, 52, 50))))
    raise ValueError(f"unknown image provider kind {kind!r}")
