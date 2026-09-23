# Foundry Loops v1 — cast / spec / build / ship for a local short-form content factory

Status: APPROVED (Phase 4, 2026-09-16) · Branch: `feat/foundry-loops` · Date: 2026-09-16
Decisions already taken (gstack decision log): two human touches per piece · global CLI + workspace file ·
bypass mode for the acceptance run · no script migration from gmm-contents, Foundry code is written fresh ·
agent-driven loop with Python QC · sheet = layout sketch + real first-frame candidates.

## Context

Creator Foundry produced one AI-persona hook reel (Imani, 2026-09-15) through 14 commands and about
18 decision points: four rounds of first-frame candidates, a hand-run Higgsfield motion job, ad-hoc
skin measurements, and an ffmpeg assembly done by hand. The second reel is blocked on doing all of
that again. gstack-loops shows the shape that removes the pain: one spec artifact, one human gate,
then an unattended loop against machine-checkable gates that never ships red. This loop rebuilds
Foundry's skill layer in that shape and adds the engine pieces the loop needs. The video engine is
Python; the video provider is the Higgsfield MCP (`seedance_2_5`); the image provider is
`gpt-image-2.5` via the OpenAI images API. Foundry stays the single home for engine code.

## Current State (verified 2026-09-16 on `main` @ 70857d9)

| Layer | Today | Gap |
|---|---|---|
| Skills (`skills/`, 10 dirs, 1,591 lines) | 14 router commands: research, interview, birth, brief, script, board, produce, qc, learn, review, save, run, doctor, upgrade | Decisions are spread over 5 gates; no unattended path; no video build at all |
| `engine/review.py:131-135` | Reads `00-research.json`, `00-intake.json`, `01-brief.json`, `02-script.json`, `03-board/board.json` by name | Must read `SPEC.md` / `spec.json` instead |
| `engine/formats.py` | 11 `Format` rows, all evidence/chart formats; capabilities probe Remotion components | No `hook_reel` format; no persona, image-edit, or video-provider capability |
| `pipeline/` (5 files) | Carousel + reel analysis only | No casting, first-frame, motion, QC, or assembly code |
| `pipelines/README.md` | Recipe schema: ingredients, parameters, stage_map | Kept as is; a recipe becomes a pre-filled SPEC |
| Persona pipeline | Lives only in gmm-contents (`gen_casting_openai.py`, ad-hoc skin numbers) | Foundry gets its own `cast` implementation (fresh, per D5) |
| Video route | Higgsfield MCP: `media_upload` → `media_confirm` → `generate_video` (get_cost, declined_preset_id) → `jobs_wait`; 32.5 cr / 5 s 720p 9:16; frame-0 mean-abs-diff ≈ 20 vs start image | Nothing in Foundry drives it |
| Install | Clone; skills symlinked by hand | No CLI, no workspace file, no version check |
| gstack-loops in this repo | `loops.json` + gloop CLAUDE.md written to `main`, uncommitted; `dev` guessed as `npm run dev` (wrong: Python engine) | Fix `dev` to `null`, commit both on this branch |

Human touches on the Imani reel, counted from `work/_ugc/imani-salary-hook/`: prompt v1 → 2 candidates
→ v2 → v3 (4 candidates, compare sheet) → approve → motion prompt → Higgsfield preset decline → clip
→ 121-frame eye check → product cut reframe → caption → draft. About 18 decisions, 4 image rounds.

## Proposed Change

Four verbs, one driver, one file per piece, one human gate before spend.

```
foundry cast <name>      identity → mandatory sheet → measured targets → pack + story   (2 touches, once)
foundry spec             ≤5 questions, one round → SPEC.md + sheet.png                  (touch 1)
                          human approves the sheet                                     (touch 2)
foundry build            frames → clip → cut, each looping on QC ≤ N cycles; never red   (unattended)
foundry ship             caption, audio, export, publish handoff, save recipe           (bypass: stops)
/foundry <plain English> reads status.json, advances one step, reports                  (driver)
```

### Implementation Details

**1. Package + CLI.** `pyproject.toml` with console script `foundry` (Python ≥ 3.11, stdlib +
Pillow + numpy). `./setup` does `pipx install -e .` and symlinks `skills/foundry*` into
`~/.claude/skills/`. `foundry --version` prints the package version; every `foundry` command and
every skill preamble compares it with `foundry.json.requires` and refuses on mismatch.

CLI surface (all commands print JSON with `--json`):

| Command | Does |
|---|---|
| `foundry init` | writes `foundry.json` in cwd; creates `personas/ accounts/ work/ pipelines/` |
| `foundry doctor` | checks: OPENAI_API_KEY, Higgsfield MCP reachable (via the skill), ffmpeg, Pillow, version match, skills symlinked |
| `foundry cast <name> [--n 3]` | bootstrap → master candidates → (touch) → sheet → measure → pack; fails closed on drift |
| `foundry new <account> <slug> [--recipe <name>]` | creates `work/<account>/<slug>/`, `status.json = created`, SPEC skeleton pre-filled from recipe/defaults |
| `foundry resolve <piece>` | fills every SPEC slot it can (pack, format defaults, recipe, last run); prints the unresolved slots (max 5) |
| `foundry sheet <piece>` | renders layout sketch + candidates + product thumb + caption into `sheet/sheet.png` and `sheet/index.html`; `status = sheet_pending` |
| `foundry approve <piece> --candidate cN` | copies the chosen candidate to `frames/approved.png`; `status = approved`; freezes `invoice.json` |
| `foundry build <piece> --mode interactive\|bypass\|autonomous [--fix-cycles N] [--dry-run]` | spawns `claude -p` in the workspace with the driving prompt (see 6); refuses unless `status = approved` |
| `foundry qc <piece> --stage frames\|clip\|cut` | runs the stage's QC modules; writes `qc/<stage>.json`; exit 0 green / 1 red |
| `foundry cut <piece>` | assembles `cut/final.mp4` from `clips/`, product asset, caption spec, audio spec |
| `foundry ship <piece>` | re-runs cut QC, writes `publish.json` (Buffer payload), saves `pipelines/<recipe>.json`, prints the publish command; bypass stops here |
| `foundry ls` | every piece: account, slug, status, cycles used, credits spent, blocked gate |
| `foundry reap` | deletes `work/` dirs whose `status = shipped` and `publish.json.posted_at` is set, keeping `SPEC.md`, `qc/`, `invoice.json` |

**2. `foundry.json` (workspace, written by `init`).**

```json
{
  "requires": "1.0.x",
  "dirs": {"personas": "personas", "accounts": "accounts", "work": "work", "pipelines": "pipelines"},
  "providers": {
    "image": {"kind": "openai-images", "model": "gpt-image-2.5", "quality": "high", "rpm_images": 5},
    "video": {"kind": "higgsfield-mcp", "model": "seedance_2_5", "resolution": "720p", "aspect": "9:16", "audio": false}
  },
  "defaults": {"mode": "bypass", "fix_cycles": 2, "credit_ceiling_multiplier": 3, "max_duration_s": 60},
  "publish": {"kind": "buffer", "channels": {"@handle": "buffer_channel_id"}}
}
```

**3. Piece directory** `work/<account>/<slug>/`:

```
SPEC.md            human-readable spec (rendered from spec.json; the file the driver reads)
spec.json          machine spec, schema below
status.json        {"state": created|specced|sheet_pending|approved|building|green|blocked|shipped,
                    "cycles": {"frames": 0, "clip": 0, "cut": 0}, "blocked_gate": null, "credits": 0}
invoice.json       frozen at approve: planned generations × unit cost; ceiling = plan × multiplier
sheet/             layout.png (sketch), candidates/c1..cN.png, index.html, sheet.png
frames/            approved.png (+ candidates history)
clips/             shot01.mp4, shot01/frames/f_0001.png … (sampled every 10th frame for QC)
cut/               final.mp4, caption.png, product-vertical.mp4
qc/                frames.json, clip.json, cut.json, safety_lint.json
publish.json       Buffer payload + posted_at (null until posted by the human in bypass)
```

**4. `spec.json` schema (hook-reel v1).**

```json
{
  "format": "hook_reel",
  "creator": "personas/<name>",
  "account": "@handle",
  "goal": "one sentence the viewer walks away with",
  "hook": {"line": "…", "mechanism": "drama|story|credential|insider|numbered|diagnostic|inversion|overheard|confession|pov|value|take|fourthwall|transformation|wall"},
  "structure": [{"t": [0, 5], "beat": "persona reaction"}, {"t": [5, 25], "beat": "product cut"}],
  "shots": [{
    "id": "shot01", "scene": "scenes/reaction-facepalm-reveal", "camera": "propped",
    "duration_s": 5, "beats": [{"t": [0.0, 0.7], "action": "…"}, …],
    "wardrobe": "opaque …", "light": "cool screen key, warm lamp background only",
    "on_screen_text": null
  }],
  "assets": [{"path": "assets/product/walkthrough.mp4", "enter_at_s": 5, "trim_s": [0, 20], "reframe": "9:16"}],
  "audio": {"kind": "silent|trending|clip"},
  "captions": {"font": "TikTok Sans Bold", "size_pct_w": 6.6, "band": "top", "band_start_pct_h": 11, "stroke_pct": 12.5, "text": "<hook.line>"},
  "qc_targets": {"skin": {"lum": 74.8, "r_minus_b": 9.4, "sat_pct": 14, "tol": {"lum": 12, "r_minus_b": 16, "sat_pct": 11}},
                 "frame0_max_diff": 30, "drift_max_lum": 12, "caption_safe": {"top_pct": 11, "bottom_pct": 71}},
  "budget": {"unit_credits": {"image_edit": 1, "video_5s": 32.5}, "planned": 4, "ceiling_credits": 130},
  "resolved_from": {"creator": "pack", "captions": "format_default", "hook": "user", …}
}
```
`qc_targets.skin` is copied from the creator pack at `resolve`; tolerances are the pack's measured
master-to-sheet spread plus margin (Imani: lum 74.8 → 91.8, so tol 12 would have flagged the sheet;
that is intended: the sheet gate fails closed).

**5. Spec resolver + the five questions.** `foundry resolve` fills slots in this order: recipe →
creator pack → format defaults → last shipped piece for the account → nothing. Only unresolved slots
become questions, asked in one `AskUserQuestion` call by `/foundry-spec`, each with a recommended
default: (1) format (2) creator (3) hook line or goal (4) reference reel / product asset (5) audio.
If all five resolve, no question is asked; the sheet is rendered and the single approval is the
only touch. Hard cap: the skill must never ask a sixth question; anything else is a resolver bug.

**6. The build driver (`foundry build`).** Mirrors `gstack-loops/lib/driver.js`: spawns
`claude -p` in the workspace with `--permission-mode acceptEdits` (bypass) or
`bypassPermissions` (autonomous), and this prompt shape:

```
You are building work/<account>/<slug>. SPEC.md is approved; do not re-scope it.
Stage FRAMES: frames/approved.png exists from the sheet gate; run `foundry qc --stage frames`.
  If red, regenerate via the image provider with the QC guidance appended, ≤ N cycles.
Stage CLIP: upload approved.png (media_upload → media_confirm); generate_video seedance_2_5
  start_image=approved.png, prompt = shots[0].beats rendered by engine/prompts/motion,
  get_cost first; if the reply is a preset_recommendation, re-send with declined_preset_id;
  refuse if cost > invoice.ceiling - credits_spent. jobs_wait; download; sample frames;
  `foundry qc --stage clip`. If red, regenerate with guidance, ≤ N cycles.
Stage CUT: `foundry cut`; `foundry qc --stage cut`. If red, fix caption/audio/trim, ≤ N cycles.
NEVER ship red. On exhaustion: write status.blocked_gate, print BLOCKED <gate>: <evidence>, stop.
On green: status=green; print DONE with credits used; do not publish.
```
`--fix-cycles` defaults to `foundry.json.defaults.fix_cycles` (2). Every provider call is logged to
`invoice.json` before it is made (credits reserved), so a crash never loses the spend record.

**7. QC modules (`engine/qc/`), all pure functions over files, each returning
`{"pass": bool, "measures": {...}, "guidance": "one sentence to append to the next prompt"}`:**

| Module | Stage | Check | Threshold source |
|---|---|---|---|
| `skin.py` | frames, clip | mean lum, R−B, saturation over a face-skin mask (Pillow, HSV threshold + largest-blob) | `qc_targets.skin ± tol` |
| `safety_lint.py` | frames (pre-call) | prompt phrase table (`sheer`, `see-through`, … → suggested rewrite) | `catalog/safety_phrases.json` |
| `frame0.py` | clip | mean abs pixel diff, frame 1 vs `approved.png` | `frame0_max_diff` (30; Imani observed 20) |
| `drift.py` | clip | skin measures on every 10th frame; max deviation from frame 1 | `drift_max_lum` |
| `hands.py` | frames, clip | VLM count of visible hands/fingers on sampled frames via the image provider's vision call; fails on ≠5 | fixed |
| `duration.py` | clip, cut | ffprobe duration vs `shots[].duration_s` (±0.3 s) and `max_duration_s` | spec |
| `caption_band.py` | cut | caption bbox inside `[band_start, 71 %]` and inside middle 80 % width; face bbox not overlapped | spec |
| `loudness.py` | cut | ffmpeg ebur128; silent spec must be −∞; otherwise −14 LUFS ± 2 | spec |
| `text_lint.py` | cut | no-ai-slop rules on `captions.text`; account charter compliance phrases (from `accounts/@handle/charter.json`) | charter |

**8. Cast (`foundry cast`).** Fresh implementation against the OpenAI images API: `bootstrap`
(text → n masters) → touch: pick master → `sheet` (image-to-image 24-panel) → `measure` (skin numbers
on master and on every panel; `panel_spread`) → fail closed if `|sheet.lum − master.lum| > tol` or
spread > 45 → touch: approve sheet → writes `personas/<name>/{master.png, sheet.png, pack.json,
prompts/}`. `pack.json` carries `qc_targets`, `skin_rule`, `camera_rule`, `known_defects`, and the
story (charter fields). The safety lint runs on every cast prompt before the call.

**9. Sheet (`foundry sheet`), per D7 "both".** One page: (a) `layout.png`, a gpt-image sketch of
the whole reel: title strip, cast portrait from `master.png`, one panel per `structure` beat with
its timestamp and label; (b) 2–4 real first-frame candidates, each an image-edit off `master.png` +
`sheet.png` with the shot prompt, capture-treated; (c) product-asset thumbnail at its entry time;
(d) the caption drawn in the band over candidate 1. `index.html` has one Approve button per
candidate and an Edit box; `foundry approve` is what the button runs. Cost before approval:
1 sketch + n candidates (n ≤ 4).

**10. Format registration.** `engine/formats.py` gains `Format("hook_reel", 0, "Persona hook reel
→ product cut", ["UGC"], (20, 30), composition="none", needs_capabilities=["persona_pack",
"image_edit", "video_i2v", "captions_burn", "qc_skin", "qc_frame0"], …)` and the capability probes
for the new modules. `engine/review.py` reads `spec.json` when present and the legacy files
otherwise (no carousel regression).

**11. Skills.** `skills/foundry/SKILL.md` becomes the driver (state table like `/gloop`). New:
`foundry-cast`, `foundry-spec`, `foundry-build`, `foundry-ship`, each ≤ 60 lines, each a thin wrapper
that runs the CLI and handles the one interactive moment it owns. The ten existing skills stay on
disk until acceptance passes, then `research`, `interview`, `brief`, `script`, `board`, `qc`,
`learn`, `save`, `run`, `birth` are removed from the router in one commit; `foundry-carousel`,
`foundry-review`, `foundry-sound`, `foundry-voice`, `foundry-storytelling`, `foundry-screenwriting`,
`foundry-storyboard` stay as craft skills loaded by stage.

**12. Modes.** `interactive`: `/foundry-build` runs in-session, you approve each stage. `bypass`
(default): headless, auto-edits, stops at green and prints the publish step. `autonomous`: headless,
also posts via `publish.json`; refuses unless `qc/cut.json.text_lint.pass` and `--i-accept-autopost`.

**13. gstack-loops housekeeping on this branch.** Commit `loops.json` with `"dev": null` and the
gloop CLAUDE.md; add a Foundry-specific Definition of Done to CLAUDE.md (below).

## Acceptance Criteria

Run in a fresh workspace (`mkdir ~/foundry-test && cd ~/foundry-test && foundry init`), fresh cast,
Imani's reel is the quality bar, not an input.

1. `foundry doctor` exits 0 on the machine with only `OPENAI_API_KEY` set and the Higgsfield MCP configured.
2. `foundry cast nova` reaches `personas/nova/pack.json` with exactly two human touches (pick master, approve sheet), and `pack.json.qc_targets.skin` holds measured numbers, not defaults.
3. A cast whose sheet lum deviates from master by more than the tolerance exits 1 with `BLOCKED sheet_drift` and writes no `pack.json`.
4. `foundry new @test nova-hook` + `/foundry-spec` asks at most 5 questions in exactly one `AskUserQuestion` call, then renders `sheet/sheet.png` containing a layout sketch, 2–4 real candidates, the product thumbnail, and the caption in band.
5. Second spec for the same creator and account, with a recipe, asks ≤ 2 questions (hook line, product asset).
6. `foundry approve` freezes `invoice.json`; `foundry build` refuses with exit 2 when `status ≠ approved`.
7. `foundry build --mode bypass` runs with no human input from approval to `status = green`, producing `cut/final.mp4` with duration 20–30 s, 1080×1920, and `qc/{frames,clip,cut}.json` all `pass: true`.
8. In that run, `qc/clip.json.frame0.diff ≤ 30`, `qc/clip.json.drift.max_lum ≤ 12`, `qc/frames.json.skin` within tolerance, and `qc/cut.json.caption_band.pass = true`.
9. Total credits spent ≤ `invoice.json.ceiling_credits`; every provider call has an `invoice.json` entry written before the call.
10. Forcing a failure (set `frame0_max_diff` to 1) makes the loop stop after exactly `fix_cycles` clip regenerations with `status = blocked`, `blocked_gate = "clip.frame0"`, the work dir intact, and no `publish.json`.
11. `foundry ship` in bypass writes `publish.json`, saves `pipelines/nova-hook.json`, prints the exact publish command, and does not post.
12. Human touches across `spec → ship` for the piece: exactly 2 (the spec answers, the sheet approval). Counted by `status.json.touches`, which every interactive skill increments.
13. `foundry ls` shows the piece's state, cycles per stage, credits, and blocked gate; `foundry reap` removes only shipped-and-posted pieces and keeps `SPEC.md`, `qc/`, `invoice.json`.
14. `engine/review.py` still renders a legacy carousel piece from gmm-contents unchanged (byte-identical `review.html` for one fixture).
15. Unit tests for all nine QC modules pass; the workspace contains no copy of any engine or pipeline file.

## Testing Plan

| Layer | What | Count |
|---|---|---|
| Unit | each `engine/qc/*` on fixture frames (Imani approved frame, a warm-drift frame, a 6-finger frame, a caption over the face) | +18 |
| Unit | `resolve` slot filling from pack / recipe / defaults; question cap; `invoice` ceiling math | +8 |
| Integration | `cast` fail-closed path with a synthetic drifted sheet; `build --dry-run` prints the driver prompt with the right N and ceiling; `review.py` legacy fixture | +4 |
| E2E | the acceptance run above, bypass mode, recorded as `work/@test/nova-hook/` with its `status.json` history | +1 |

## Rollback Plan

Everything lands on `feat/foundry-loops`; `main` keeps the 14-command router. The ten old skills stay
on disk until criterion 7 passes, so `git checkout main` restores the old surface at any point. The
workspace file is additive; a consumer without `foundry.json` gets a clear `foundry init` message.

## Effort Estimate (CC-assisted)

| Component | CC |
|---|---|
| Package, CLI skeleton, `init`, `doctor`, `ls`, `reap`, version check | 2 h |
| `cast` (bootstrap, sheet, measure, fail-closed, pack) | 3 h |
| `spec.json` schema, `resolve`, `new`, SPEC.md renderer, recipe pre-fill | 3 h |
| `sheet` (layout sketch, candidates, html, `approve`, invoice) | 3 h |
| QC modules ×9 + fixtures + tests | 5 h |
| `build` driver prompt + Higgsfield flow in `foundry-build` skill + BLOCKED protocol | 3 h |
| `cut` (ffmpeg concat, reframe, caption burn, loudness) + `ship` + recipe save | 3 h |
| Skills: driver + 4 verbs; router cleanup; formats/review changes | 2 h |
| Acceptance run in a fresh workspace, fixes | 3 h |
| **Total** | **~27 h CC** (human team: ~4 weeks) |

## Files Reference

| File | Change |
|---|---|
| `pyproject.toml`, `setup`, `foundry/__main__.py`, `foundry/cli.py` | new: package, console script, install |
| `foundry/workspace.py` | new: `foundry.json` load/validate/version check |
| `foundry/piece.py` | new: piece dir, `status.json`, `invoice.json`, touches counter |
| `foundry/cast.py` | new: bootstrap/sheet/measure/pack |
| `foundry/spec.py` | new: schema, resolver, SPEC.md renderer |
| `foundry/sheet.py` | new: layout sketch, candidates, index.html, approve |
| `foundry/build.py` | new: driver prompt, `claude -p` spawn, modes |
| `foundry/cut.py`, `foundry/ship.py` | new: assembly, publish payload, recipe save |
| `engine/providers/openai_images.py` | new: generate/edit with rate limit + moderation retry |
| `engine/qc/{skin,safety_lint,frame0,drift,hands,duration,caption_band,loudness,text_lint}.py` | new |
| `engine/formats.py:95-140` | add `hook_reel` + capability probes |
| `engine/review.py:131-135` | read `spec.json` first, legacy files second |
| `engine/prompts/motion/*` | new: seedance beat-sheet template |
| `catalog/hooks/mechanisms.json`, `catalog/safety_phrases.json`, `scenes/reaction-facepalm-reveal.json` | new |
| `skills/foundry/SKILL.md` | rewrite as driver |
| `skills/foundry-{cast,spec,build,ship}/SKILL.md` | new |
| `skills/foundry-{research,interview,…}` | removed from router after criterion 7 |
| `loops.json`, `CLAUDE.md` | commit; `dev: null`; Foundry Definition of Done |
| `tests/` | new |

## Out of Scope

- Every video type except `hook_reel` (ugc-talk, walkthrough, split-screen, motion-graphic, demo, clip-cut).
- Carousel changes; `pipeline/render_carousel.mjs` and `foundry-carousel` untouched.
- Migrating any gmm-contents script (decided: fresh code).
- Autonomous posting as the acceptance path; the mode exists but is not the test.
- ~~A Python Higgsfield HTTP adapter; the MCP is the only video route.~~ In scope from 1.1: see
  "Higgsfield API route" below.
- Codex host support for the skills.
- Retention analytics feeding back into the hook catalog.

## Related

- Design doc: `plans/foundry-loops.md` in the gmm-contents workspace
- gstack-loops: https://github.com/csakash/gstack-loops (`SPEC.md`, `lib/driver.js`, `skills/gloop*`)
- Quality bar: `gmm-contents/work/_ugc/imani-salary-hook/`, `gmm-contents/personas/imani/character.json`

---

# Higgsfield API route (loop `higgsfield-api`, 1.1)

## Context

Every clip goes through the Higgsfield MCP today: the build agent calls six MCP tools, and
`foundry` only sees the upload URL, the reservation and the result URL. Three costs follow:

1. The MCP must be connected **in the session that builds**. A claude.ai connector is invisible
   to `claude mcp list`, so `foundry doctor` reports it missing and a headless `claude -p` build
   cannot use it.
2. The agent holds the generate tool, so a generation made without a reservation leaves no
   trace (TODOS: "Tie video generations to reservations at the provider").
3. Policy is split between the CLI and the agent's discipline.

Higgsfield now has a first-party REST API (`https://api.higgsfield.ai`, key `HF_KEY`) with
Seedance 2.5 image-to-video. When it is available, `foundry` should call it itself.

## Rule

> **If the Higgsfield API is available, always use it. Otherwise use the Higgsfield MCP.**

"Available" is decided per build, live, never cached across runs:

| Condition | Route |
|---|---|
| `providers.video.route` is `"mcp"` | mcp (pinned) |
| no `HF_KEY` and no `HF_API_KEY`+`HF_API_SECRET` in the environment / workspace `.env` | mcp |
| piece was approved before the API existed (its frozen invoice has no `video_usd` ceiling) | mcp |
| `POST /estimate/<endpoint>` → 200 | **api** |
| estimate → 401, 403, 404, 423, 503, network error or timeout | mcp, with the reason |
| `providers.video.route` is `"api"` and any of the above fails | refused (no silent fallback) |

`route` defaults to `"auto"`. Existing workspaces merge the default, so they get the rule
without editing `foundry.json`.

## API contract (verified 2026-09-23 against docs.higgsfield.ai and the official SDK)

| Step | Call |
|---|---|
| auth | `Authorization: Key <key_id>:<secret>` — sent **only** to the configured `base_url` host |
| availability + price | `POST /estimate/bytedance/seedance-2.5/image-to-video` (no charge) |
| upload | `POST /files/generate-upload-url {content_type}` → `{public_url, upload_url, upload_headers}`; `PUT upload_url` with exactly `upload_headers`, **no credentials** |
| submit | `POST /bytedance/seedance-2.5/image-to-video {image_url, prompt, duration, resolution, generate_audio: false, bitrate_mode}` → `{request_id, status_url, cancel_url}` |
| poll | `GET status_url` → `status` ∈ queued, in_progress, completed, failed, nsfw, canceled |
| result | completed → `video.url` (kept ≥ 7 days) |

Notes that shape the implementation:

- The schema is `additionalProperties: false` and has **no aspect field**; framing follows the
  start image. `aspect_ratio` is never sent.
- `generate_audio` defaults to **true** upstream; Foundry always sends `false` (audio is
  replaced in the cut).
- `duration` is an integer, 4–30 s. A shot whose `duration_s` does not round to that range, or
  rounds by more than 0.5 s, is refused before any spend.
- Seedance 2.5's estimate returns a pricing *description*, not a number: tokens =
  ceil(seconds × width × height × 24 / 1024), USD 0.0214 per 1,000 tokens at 480p/720p. Foundry
  computes the price from this formula at the **720×1280 upper bound** (framing follows the start
  image, so the real frame is no larger). If an estimate ever returns a numeric `usd`, the larger
  of the two is reserved.
- Submissions have **no idempotency key**. A submit POST is never retried. A timeout or 5xx on
  submit is an unknown outcome: the reservation is settled as charged (never lowered) and nothing
  is resubmitted. Status GETs retry with backoff (2 s → 10 s, ×1.5, jitter) until a deadline.
- `failed` and `nsfw` are refunded upstream, so they settle as `failed`.
- `status_url` from a response is only followed if its host is the configured `base_url` host.

## Money

The API bills in USD, the MCP in Higgsfield credits. One ledger unit per currency:

- `video_credits` (MCP, unchanged) and **`video_usd`** (API, new).
- `hook_reel.plan()` plans **both**, and approval freezes a ceiling for **both**
  (`planned × credit_ceiling_multiplier`). Whichever route a build takes — including a
  fallback part-way through — its spend has a frozen ceiling.
- `video_usd` is reserved only by `foundry generate`. `foundry reserve --unit` keeps its current
  choices, so the agent cannot book API spend by hand.
- `ingest-clip` / `fetch` accept a settled, unconsumed reservation in either video unit.

## New commands

| Command | Who | Does |
|---|---|---|
| `foundry route <piece>` | agent + human | Prints `{route, reason}`. Live check; spends nothing. |
| `foundry generate <piece> --shot <id> [--guidance-from clip] [--wait-s N]` | agent + human | API route only. Refuses unless the route is api. Under a per-shot non-blocking lock: build the motion prompt, price it, `reserve video_usd` (may BLOCK on the ceiling), upload the approved frame, write `incoming/<shot>.api-job.json` (`phase: submitting`) **before** the POST, submit, rewrite it `phase: submitted`, poll, settle, download through the existing https checks, ingest. Re-running after an interruption **resumes polling the saved request instead of resubmitting.** |
| `foundry generate <piece> --shot <id> --clear-unknown` | **human only** | Clears a shot parked after an unknown-outcome submit, once the human has checked the Higgsfield console. |

**Each call waits at most 90 s** (`providers.video.api.poll_timeout_s`, or `--wait-s` up to 3600). The
build agent's shell kills long commands, so generate returns "not finished — run again" and the next call
resumes. A call killed *inside* the POST leaves `phase: submitting`; the next call treats that as an
unknown outcome.

**Unknown outcome** (submit timeout, 5xx, accepted-but-unfollowable, or killed mid-POST): the reservation
is settled as charged (`ref unknown-<entry>`), the shot is parked in `incoming/<shot>.api-unknown.json`,
and every later `generate` for that shot refuses until a human runs `--clear-unknown`. The build agent
prints `BLOCKED video.unknown_submit` and stops; it never generates that shot another way.

## Build, skill, doctor

- The build prompt and `/foundry-build` start STAGE CLIP with `foundry route`; api →
  `foundry generate`; mcp → the existing six-tool MCP steps, unchanged.
- Headless `argv`: `providers.video.mcp_server` is required only when the route resolves to mcp.
  With the api route the session gets no MCP tools unless `mcp_server` is set.
- `foundry doctor`: new `Higgsfield API` row (live estimate unless `--offline`). When the API is
  ok, the `Higgsfield MCP` row becomes a `note` (fallback only) instead of `todo`. A `video route`
  row states which route builds will take and why.

## Acceptance criteria

1. With `HF_KEY` unset, behaviour and every existing test are unchanged (route mcp).
2. With a working key, `foundry route` → api; doctor status is not "action needed" because of
   the MCP row alone.
3. `foundry generate` makes exactly one submit per call, reserves `video_usd` before any
   upload, refuses when the route is mcp, and never sends credentials to the upload or
   download host.
4. Submit timeout / 5xx → reservation settled charged, request not resubmitted, the shot parked until a
   human `--clear-unknown` (refused under `FOUNDRY_AGENT`).
5. Interrupted generate → re-run resumes the saved request (no second submit); killed mid-POST → treated
   as criterion 4. Default wait per call is 90 s.
6. failed / nsfw → settled failed with the request id; clip not ingested.
7. Budget: `video_usd` ceiling frozen at approval; a reservation past it BLOCKs `budget.video_usd`.
8. Headless dry-run with api route builds argv without `mcp_server`.
9. Gate: `python3 -m pytest -q` and `python3 -m compileall -q foundry engine`; no network in tests.
