---
name: foundry-storytelling
description: Narrative structure craft for briefs and scripts — arcs, hooks, but/therefore logic, misconception-first, pacing and retention rules. Load at the brief and script stages of any foundry piece, or whenever authoring/reviewing what a video says and in what order.
---

# Storytelling — structure before words

The brief decides ONE idea and ONE promise. The script arranges that idea so a
viewer who owes us nothing stays. Everything here is about arrangement.

## The short-form arc (scale to duration)

```
HOOK        first 1–2s   visual + text pattern interrupt; voice starts immediately
TENSION     to ~20%      "what most people think / what's at stake" — open the gap
CORE        ~50%         1 concept per 8–12s of runtime, connected by but/therefore
PROOF       ~20%         mechanism shown, not asserted (custody doc, order ticket, chart)
REFRAME     last 5–10%   callback to the hook; restate the insight in one line; loop point
```

Duration → concept budget: 15s = 1 concept · 30s = 1–2 · 60s = 2–3. More concepts
than that is a carousel or a series, not one reel.

## Connective logic: but / therefore

Never join beats with "and then." Every beat earns the next with **but** (a
complication) or **therefore** (a consequence). If a beat can be removed without
breaking a but/therefore chain, it is filler — cut it. Lint heuristic: "and then",
"also", "another thing" appearing as beat connectors = revise.

## Misconception-first (research-backed)

Muller (2008): presenting the common misconception FIRST and refuting it beats
presenting correct information alone, on both learning and engagement. This is the
engine of our `myth_buster` format and a strong default for any educational beat:
open with what the audience believes, then break it.

## Hook craft

- Hook archetypes live in `engine/prompts/hook.md` (vibe_check, negative_frame,
  etc.) — pick from there; add new archetypes there, not ad hoc.
- Frame 1 rules: visual interest in frame 1, on-screen text within 0.5s, voice
  immediately, movement present. No logos, no "hey guys", no silent build.
- AI-persona constraint (FTC): hooks must be information-framed, never
  first-person experience claims ("5 assets people find out about too late", not
  "I found out too late").

## Pacing + retention targets

| Rule | Value |
|---|---|
| New visual element | every 1–3s (short-form) |
| Max static hold | 3s |
| One new concept per | 30–45s of runtime |
| Deliberate silence after the key insight | 1–3s |
| Retention checkpoints | ≥70% @3s · ≥60% @15s · ≥50% @30s (measure on YT Shorts — only platform giving curves) |

Total-watch-time beats completion vanity: 45s at 70% completion (31.5s) out-earns
15s at 40% (6s). Duration is chosen by the idea's real size, not by a completion
target.

## Mayer's principles we enforce mechanically

- **Temporal contiguity** — narration and its visual land simultaneously. QC
  asserts card/plate timings against whisper word timestamps.
- **Coherence** — seductive-but-irrelevant detail reduces transfer; if a fact
  doesn't serve the one idea, it goes to the caption or dies.
- **Modality** — spoken words + pictures beat written words + pictures. On-screen
  text is for the muted viewer and for emphasis, not a second essay.

## Every brief carries a title and a story

Two plain-English fields, authored at the brief and required by the lint:

- **`title`** — the piece's name, 2–4 words, in a human's words. "The Wrong
  Number". Not the slug, not the topic, not a headline with a colon in it.
- **`story`** — one paragraph recounting the video the way you would describe it
  to a friend: who is on screen, what happens in order, what the point is. If you
  cannot write that paragraph, you do not yet have a piece — you have a topic.

These are not documentation. They are the top of the review page a human judges
Gate 1 from, and writing them is the fastest test of whether the idea is real.

## Anti-subjective rule (applies to briefs too)

Describe the visual cause, never the felt effect. "Epic reveal" constrains no
pixels; "slow push-in, subject silhouetted, music drops to silence for 1.5s" does.
The kill-question for any brief: **could this piece belong to any topic after
swapping the title? Then the idea is not yet specific enough to spend on.**
