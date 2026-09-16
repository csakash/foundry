"""Criterion 14: a legacy piece renders byte-identically after the spec.json change."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import engine.review as new_review

REPO = Path(__file__).resolve().parents[1]
BASE = "70857d9"  # main before Foundry Loops
FIXTURE = REPO / "tests/fixtures/legacy_carousel"


def _old_module(tmp: Path):
    try:
        src = subprocess.run(["git", "-C", str(REPO), "show", f"{BASE}:engine/review.py"],
                             capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("base commit not available")
    f = tmp / "old_review.py"
    f.write_text(src)
    spec = importlib.util.spec_from_file_location("old_review", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = new_review.ROOT
    return mod


def test_legacy_piece_is_byte_identical(tmp_path: Path):
    piece = tmp_path / "legacy-carousel"
    shutil.copytree(FIXTURE, piece)
    old = _old_module(tmp_path)
    assert old.render(old.collect(piece)) == new_review.render(new_review.collect(piece))


def test_spec_piece_renders(tmp_path: Path):
    piece = tmp_path / "loop-piece"
    piece.mkdir()
    (piece / "spec.json").write_text(json.dumps({"account": "@test", "slug": "loop-piece", "format": "hook_reel",
                                                 "creator": "nova", "hook": {"line": "Fixture hook"}}))
    data = new_review.collect(piece)
    assert data["spec"]["format"] == "hook_reel" and data["stages"]["spec"] is True
    assert data["account_handle"] == "@test"
    assert "Fixture hook" in new_review.render(data)
