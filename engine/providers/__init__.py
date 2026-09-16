"""Provider adapters. `get_image_provider(config)` picks one from foundry.json providers.image.kind."""
from __future__ import annotations

from typing import Any


def get_image_provider(cfg: dict[str, Any]):
    kind = cfg.get("kind")
    if kind == "openai-images":
        from .openai_images import OpenAIImages
        return OpenAIImages(model=cfg.get("model", "gpt-image-2.5-sunburst"), quality=cfg.get("quality", "high"),
                            rpm_images=int(cfg.get("rpm_images", 5)))
    if kind == "fake":
        from .fake_images import FakeImages
        return FakeImages(skin=tuple(cfg.get("skin", (62, 52, 50))))
    raise ValueError(f"unknown image provider kind {kind!r}")
