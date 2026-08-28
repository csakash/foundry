---
name: foundry
description: Router for the Creator Foundry skill suite — the gstack of content creation. Use when the user says /foundry, asks which foundry command fits, or starts any content-production task in this repo (birthing an influencer/account, briefing, scripting, storyboarding, producing, QC, saving a piece as a reusable pipeline, or batch/parallel runs). Routes to the stage flow and loads the right craft skills per stage.
---

# Creator Foundry — the video-creation stack

Terminal-native production system for this repo. No app: Claude Code is the engine,
these skills are the product, and every stage writes a typed artifact to disk
(`work/<account>/<slug>/NN-*.json`). Canonical process: `JOURNEY.md`. Product
blueprint: the "Creator Foundry" artifact (URL in memory).

## The vision — full-stack content creators

The user is **the taste, not the crew**. Assume they have never made a video,
never written a screenplay, never directed anything — and never require them
to. They create an **influencer** once (`/foundry birth`: identity, look,
voice, hero image, charter), then just drop ideas; the foundry is the writer,
director, cinematographer, editor, and QC. Every question asked back to the
user must be answerable by a non-creator (see foundry-interview's
plain-language rules), every decision comes with a recommended default, and
"you choose" is always a valid answer. The system's competence must never leak
out as homework for the user.

## Posts, not just videos

The unit of output is a **post**: video OR image. Image posts are the journey
terminated at the storyboard — a single image post is one approved board frame,
finished; a **carousel** is N approved frames plus the Stage-2 caption. They
are not separate pipelines: same interview, same gates, same review page, and
every video project produces publishable image/carousel derivatives for free.
`post_type` (video `ugc`/`faceless`/`ambient`/`clip`/…, image single/multi,
carousel) is locked in the brief.

## The stage flow

| Stage | Command (intent) | Artifact | Craft skills to load |
|---|---|---|---|
| **Interview** (interactive front door) | `/foundry interview` | lands a brief OR an account via phased interrogation | **foundry-interview** |
| Birth an account | `/foundry birth` | `accounts/@handle/{account,charter,portfolio}.json` | foundry-interview (account mode), foundry-storytelling |
| Intake + brief | `/foundry brief` | `00-intake.json`, `01-brief.json` | foundry-storytelling |
| Script | `/foundry script` | `02-script.json` (two-column) | foundry-screenwriting, foundry-voice |
| Storyboard | `/foundry board` | `03-board/` (keyframes + board.json) | foundry-storyboard |
| Produce | `/foundry produce` | `04-assets/`, `05-cut/final.mp4` | foundry-voice, foundry-sound |
| QC | `/foundry qc` | `06-qc.json` | foundry-storyboard (conformance), foundry-sound |
| Publish + learn | `/foundry learn` | publish log, `priors.json` update | — |
| **Review** (runs after EVERY stage) | `/foundry review` | `review.html` — the page a human judges gates from | **foundry-review** |
| Save as pipeline | `/foundry save <name>` | `pipelines/<name>.json` — the piece frozen as a reusable recipe | — |
| Run a pipeline | `/foundry run <name> [overrides]` | a new `work/` piece with only changed stages regenerated | craft skills of the re-run stages |

Stages that lack a dedicated builder run as guided flows using the bundled
engine modules (`engine/`, `pipeline/`; Remotion projects live in `motion/`). Never collapse stages: gates
exist so the human decides idea → words → look BEFORE money is spent on motion.

**Routing rule for vague input:** a raw idea, a dropped reel URL, a screenshot,
or "let's make something about X" routes to `/foundry interview`, not straight to
a brief — the interview interrogates until Gate 1 can actually be judged.
`/foundry birth` with no prepared answers also runs as an interview (account
mode). Only skip the interview when a complete brief already exists.

## Hard rules the router enforces

1. **Read the craft skill before doing the stage.** Writing a script without
   foundry-screenwriting loaded, or mixing audio without foundry-sound, is the
   same violation as skipping a lint.
2. **Charter is lint.** Every brief/script/board is validated against
   `accounts/@handle/charter.json` (if the account layer exists for this piece)
   plus `brand.tokens.json` banned phrases and the evidence ledger.
3. **Cost pyramid.** Words are free, stills ₹2–20, motion ₹70–430. Iterate at the
   cheapest level that can answer the current question. Lock stills before motion.
4. **Gates before spend.** Gate 1 brief ("right idea?"), Gate 2 script ("right
   words?"), Gate 3 board ("right look?"), Gate 4 QC ("matches plan + legal?").
   Surface gates to the user in chat; a rejection note becomes regeneration
   guidance, not a new creative debate.
5. **Delivery promise lock.** The brief states its lane (A deterministic /
   B captured / C generative) and motion character. If production cannot honor it,
   STOP AND ASK — never silently downgrade a motion-led piece to stills.
6. **Concurrency guard.** `grep -n 'id="' motion/src/Root.tsx` before any render;
   merge registrations, never overwrite (concurrent sessions drop compositions).
7. **Never hand a human raw JSON.** Every stage write is followed by
   `python3 engine/review.py work/@handle/slug`, and every gate is surfaced with
   the path to that `review.html` (plus its Artifact URL when the user wants a
   link). Pasting artifact excerpts into chat is the same failure in a thinner
   disguise — it shows only what you chose to show. Load **foundry-review**
   before touching the generator. The page is derived: fix the artifact and
   re-run, never hand-edit the HTML, never write a one-off page for one piece.
   **It must read plainly.** No raw keys, statuses, ids or slot names on the
   page; technical detail stays reachable behind a disclosure, never in the
   default view. That requires the artifacts to carry plain language:
   `01-brief.json` needs `title` and `story`, and every beat in
   `02-script.json` needs a one-sentence `plain` line. A beat that cannot be
   said plainly in one sentence is not clear enough to build.
8. **User-supplied copy is intake, never evidence.** Pre-written post text,
   figures pasted into chat, numbers from a screenshot — all of it enters at
   Stage 0 and every figure gets sourced and registered via
   `engine/evidence.py` (`put_figure()` for stated numbers) before it reaches a
   frame. A fabricated figure passes every other lint in the stack.

9. **Reference decomposition is Apify-first, and never deaf.** Any reel, clip or video
   that informs a brief, charter, board or taste anchor goes through
   `pipeline/analyze_reel.py` (Apify -> ffmpeg -> whisper -> Gemini) BEFORE it is
   discussed - never from memory of watching it, and never from a screenshot when a
   URL exists. `APIFY_TOKEN`, `GOOGLE_API_KEY`, ffmpeg/ffprobe and
   `./.venv/bin/yt-dlp` are hard dependencies of this stack, not optional extras.
   Apify regularly hands back a **video-only DASH stream**: whisper then returns 0
   segments and the Gemini pass analyses the reel deaf, emitting a plausible-looking
   but shallow template. The analyzer probes every download for an audio stream,
   re-fetches via yt-dlp when one is missing, records `provenance.audio_source`, and
   skips any reel whose audio cannot be recovered rather than writing a deaf
   template. **A template with an empty `transcript` or `asr_language: "none"` is
   invalid evidence** - re-run it before citing it for anything.
   Frame-exact timing - plate arrivals, gesture sync, overlay cadence, cycle
   boundaries - is MEASURED from `templates/raw/<code>.mp4` with ffprobe/ffmpeg
   (per-zone luminance deltas, audio RMS envelopes, labelled contact sheets), never
   estimated by eye from the beat summaries. The Gemini beats are a description;
   the file is the evidence.


## The ingredient manifest

Every post is assembled from a known ingredient list. `00-intake.json` carries
it explicitly, and the review page renders it as a plain checklist so the user
always sees what is set, what was defaulted, and what is still owed:

1. **idea** · 2. **post type** (video ugc/faceless/ambient/clip · image
single/multi · carousel) · 3. **sound** (music family / trending audio /
silent) · 4. **brand assets** (tokens, watermark — if applicable) ·
5. **inspiration** (reel/video refs, decomposed per rule 9) ·
6. **captures** (screenshots / screen recordings for product proof) ·
7. **voice** (voiced or not; which voice) · 8. **character** (ethnicity, age,
look, shape and form, voice match) · 9. **hero character image** (the
canonical identity anchor) · 10. **duration** · 11. **video model** (which
generative model, if Lane C) · 12. **edit route** (Remotion programmatic /
captured / generative assembly) · 13. **render spec** (aspect, resolution,
platform).

Each entry is `{status: provided | defaulted | n/a | missing, value, source}`.
The interview asks ONLY about ingredients that are missing AND matter for this
piece; everything else is defaulted from the charter, the recipe, or the
catalog — and shown, never hidden. Character-bound ingredients (7–9) come from
the influencer's charter and are never re-asked per piece.

## Saved pipelines — one good post becomes a series

After a piece passes QC, offer `/foundry save <name>` → `pipelines/<name>.json`
(contract: `pipelines/README.md`). The recipe freezes every approved decision;
`/foundry run <name> topic="…"` regenerates only the stages the changed
parameters touch (per the recipe's `stage_map`), with exactly one human gate
before spend: the review page with new values filled in. Recipes are derived
from artifacts, never hand-edited; charter + compliance lint still run on every
run. **Always offer to save** when a piece clears QC — a produced post that
isn't saved as a recipe is a series the user has to re-interview for.

## Parallel production

The unit of parallelism is **one piece = one `work/` directory = one agent**.
Rules:

- **Fan out with subagents.** A batch (`/foundry run <name> --matrix`, or a
  campaign of variants) launches one Claude subagent per piece, each given the
  recipe + its parameter set, each writing only inside its own
  `work/<account>/<slug>/`. Never two agents in one piece directory.
- **Gates batch too.** The human approves the matrix ONCE before fan-out (one
  review page listing every planned variant + the total invoice); per-piece QC
  still runs after production. Interviews are never parallel — they have a
  human in the loop.
- **Shared files are merge-only.** Root.tsx composition registrations (rule 6),
  the evidence ledger, and priors are append/merge — an agent that overwrites a
  shared file has corrupted its siblings. Caches may be shared read-write only
  if keyed by content hash.
- **Report back structured.** Each agent returns piece path + QC verdict +
  actual cost; the parent renders one batch review page, never a wall of logs.

## The catalog — preference & inspiration layer (`catalog/`)

The catalog is data, not code: hooks, personas, geos, intents, and raw reference
briefs that parameterize briefs and scripts. `catalog/README.md` is the
contract; this repo ships starter entries, the host project supplies its own.

- **Read it at intake.** `/foundry interview` and `/foundry brief` list
  `catalog/{hooks,personas,geos,intents}/*.json` and read `catalog/briefs/*.md`
  as inspiration context before proposing an angle. A brief that picks a hook,
  persona, or geo records the catalog `id`s it used in `01-brief.json`
  (`"catalog": {"hook": …, "persona": …, "geo": …, "intent": …}`) so
  performance can be joined back to catalog picks at `/foundry learn`.
- **Intent ≠ format.** Intent (why the piece exists) is a catalog pick; format
  (how it is made) is the pipeline choice. A piece =
  intent × format × hook × persona × geo. One video = ONE discovery — never
  stack benefits.
- **Users extend it by dropping files** — a markdown doc into `catalog/briefs/`
  or a JSON entry copied from a sibling file. Never hard-code a hook line,
  archetype, or geo rule in a skill or engine module when it belongs in the
  catalog; when new preferences arrive in chat, offer to land them as catalog
  entries.
- **Director's lint** applies at Gate 2 for UGC-style pieces: would a person say
  this to a friend; is it detectable as an ad with sound off; is it explaining
  more than one thing. Every `compliance` note on a picked catalog entry
  becomes a Gate 4 check.

## Updating — `/foundry upgrade`

Foundry installs are copied files, so updating = re-copying the
**foundry-owned** paths from a fresh clone of the repo and touching nothing
else. Two classes of files, never confused:

- **Foundry-owned (always safe to overwrite):** `.claude/skills/foundry*`,
  `engine/`, `pipeline/analyze_reel.py`, `pipelines/README.md` +
  `pipelines/example-recipe.json`, `SETUP.md`, `.env.example`,
  `requirements.txt`, `catalog/**/example-*` + the catalog READMEs.
- **User-owned (never overwrite):** `.env`, `brand/brand.tokens.json` once
  edited, every catalog entry the user added, `accounts/`, `work/`,
  `templates/`, `evidence/`, saved `pipelines/*.json` recipes.

On `/foundry upgrade`: clone the repo to a temp dir, copy the foundry-owned
paths over, run `pip install -r requirements.txt` into the venv, then run
`/foundry doctor` and report what changed (diff the skill/engine versions in
one line each). If a user-owned file collides with a foundry-owned update
(rare), show the diff and ask — never clobber silently.

## Dependencies — `/foundry doctor`

`SETUP.md` is the canonical dependency manifest: API keys via `.env` /
`.env.example` (Apify token or MCP, ElevenLabs, fal or Higgsfield MCP, Gemini
for analysis + Nano Banana images, optional OpenAI images), local tools
(ffmpeg, yt-dlp, Python venv, Node), and the skill/MCP layer (official Remotion
skill → Lane A, official Playwright skill → Lane B). `/foundry doctor` = verify
each row of SETUP.md **plus the engine contract set** (`engine/review.py`,
`engine/evidence.py`, `engine/formats.py`, `engine/prompts/`,
`pipeline/analyze_reel.py`, `brand/brand.tokens.json` — all bundled; if any is
missing the install is incomplete: re-copy from the foundry repo) and report
what's missing and **which lane it degrades**
(e.g. no fal/Higgsfield → Lane C pieces stop at the storyboard). Run it on any
fresh clone before producing.

## Provenance

Craft principles distilled from public research (Mayer, Muller 2008, platform
specs) and inspired by the OpenMontage project's approach (AGPL-3.0 — principles
re-authored here, no text or code vendored), fused with this repo's own measured
production lessons (see memory + `research/`).
