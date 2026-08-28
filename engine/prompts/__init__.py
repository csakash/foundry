"""Prompt library: load, validate, render.

A prompt family is one markdown file. YAML frontmatter is the machine contract;
the body carries the craft guidance and the ``` block under "## Template" is what
actually gets rendered.

    python -m engine.prompts list
    python -m engine.prompts show shot
    python -m engine.prompts build hook --set archetype=negative_frame --set claim="..."
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

DIR = Path(__file__).resolve().parent
BRAND = DIR.parent.parent / "brand" / "brand.tokens.json"


class PromptError(ValueError):
    """A prompt failed validation. Always raised before anything is spent."""


def _banned_phrases() -> list[str]:
    if not BRAND.exists():
        return []
    data = json.loads(BRAND.read_text())
    return data.get("compliance", {}).get("banned_phrases", []) or []


def families() -> list[str]:
    return sorted(p.stem for p in DIR.glob("*.md") if p.stem != "README")


def load(family: str) -> dict[str, Any]:
    path = DIR / f"{family}.md"
    if not path.exists():
        raise PromptError(f"no prompt family {family!r}; have: {', '.join(families())}")
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise PromptError(f"{family}.md is missing YAML frontmatter")
    meta = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)

    tpl = re.search(r"^## Template\s*\n+```[a-z]*\n(.*?)```", body, re.S | re.M)
    if not tpl:
        raise PromptError(f"{family}.md has no '## Template' fenced block")
    meta["template"] = tpl.group(1).strip()
    meta["body"] = body
    meta["path"] = str(path)
    return meta


def _apply_defaults(spec: dict, slots: dict) -> dict:
    out = dict(slots)
    for name, rule in (spec.get("slots") or {}).items():
        if name not in out and isinstance(rule, dict) and "default" in rule:
            out[name] = rule["default"]
    return out


def _validate_slots(spec: dict, slots: dict) -> None:
    problems = []
    for name, rule in (spec.get("slots") or {}).items():
        rule = rule if isinstance(rule, dict) else {}
        value = slots.get(name)
        if rule.get("required") and not value:
            hint = f" — {rule['help']}" if rule.get("help") else ""
            problems.append(f"missing required slot {name!r}{hint}")
            continue
        if value and rule.get("enum") and value not in rule["enum"]:
            problems.append(
                f"slot {name!r} = {value!r} not in {rule['enum']}")
    unknown = set(slots) - set(spec.get("slots") or {})
    if unknown:
        problems.append(f"unknown slot(s): {', '.join(sorted(unknown))}")
    if problems:
        raise PromptError("; ".join(problems))


def _validate_output(spec: dict, rendered: str, slots: dict) -> list[str]:
    problems = []
    limits = spec.get("limits") or {}

    if "words" in limits:
        n = len(rendered.split())
        lo, hi = limits["words"].get("min", 0), limits["words"].get("max", 10**6)
        if not lo <= n <= hi:
            problems.append(
                f"{n} words is outside the researched band {lo}-{hi} for this family")

    if "spoken_words" in limits:
        # Only the slots the family declares as spoken count. Stage direction
        # like "[frame 1: ...]" is instruction to the renderer, not dialogue.
        sources = spec.get("spoken_from") or []
        spoken = " ".join(str(slots.get(k, "")) for k in sources) if sources else \
            re.sub(r"\[[^\]]*\]", " ", rendered)
        n = len(spoken.split())
        lo, hi = limits["spoken_words"].get("min", 0), limits["spoken_words"].get("max", 10**6)
        if not lo <= n <= hi:
            problems.append(f"{n} spoken words outside the {lo}-{hi} band "
                            f"(~{n / 2.5:.1f}s at 150 wpm)")

    low = rendered.lower()
    for phrase in _banned_phrases():
        if phrase.lower() in low:
            problems.append(f"contains banned phrase {phrase!r} (brand.tokens.json)")
    for phrase in spec.get("forbid_in_output") or []:
        if str(phrase).lower() in low:
            problems.append(f"contains {phrase!r}, forbidden for family {spec['family']!r}")

    # forbid_in_slots checks what the caller asked for, not what the template
    # renders. A music template may legitimately say "no vocals" while the
    # caller must never request them.
    slot_text = " ".join(str(v) for v in slots.values()).lower()
    for phrase in spec.get("forbid_in_slots") or []:
        if str(phrase).lower() in slot_text:
            problems.append(
                f"slot value contains {phrase!r}, not allowed for family {spec['family']!r}")
    return problems


def build(family: str, slots: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
    """Render a prompt. Raises PromptError rather than emit something unsafe."""
    spec = load(family)
    slots = _apply_defaults(spec, slots)
    _validate_slots(spec, slots)

    rendered = spec["template"]
    for name, value in slots.items():
        rendered = rendered.replace("{" + name + "}", str(value))

    leftover = re.findall(r"\{([a-z_]+)\}", rendered)
    declared = set(spec.get("slots") or {})
    unfilled = [n for n in leftover if n not in declared]
    if unfilled:
        raise PromptError(
            f"template for {family!r} references undeclared slot(s) "
            f"{sorted(set(unfilled))} — fix {family}.md, this is a template bug")
    # An unset optional slot vanishes. Its line goes too, but only when the
    # placeholder was the whole line — otherwise a stray optional would take a
    # required slot down with it.
    if leftover:
        out_lines = []
        for line in rendered.split("\n"):
            if not re.search(r"\{[a-z_]+\}", line):
                out_lines.append(line)
                continue
            stripped = re.sub(r"\{[a-z_]+\}", "", line)
            # A bare label with nothing after it ("Audio: .") is not content.
            if re.fullmatch(r"\s*[\w ]+:\s*[.,;]?\s*", stripped):
                continue
            if re.sub(r"[\s.,:;—-]", "", stripped):
                out_lines.append(re.sub(r"\s{2,}", " ", stripped).strip())
        rendered = "\n".join(out_lines)

    problems = _validate_output(spec, rendered, slots)
    if problems and strict:
        raise PromptError(" | ".join(problems))

    return {
        "family": family,
        "version": spec.get("version"),
        "prompt": rendered.strip(),
        "slots": slots,
        "words": len(rendered.split()),
        "warnings": problems,
        "dropped_optional_slots": leftover,
    }
