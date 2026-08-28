---
name: foundry
description: Router for the Creator Foundry skill suite — the gstack of video creation. Use when the user says /foundry, asks which foundry command fits, or starts any content-production task in this repo (birthing an account, briefing, scripting, storyboarding, producing, QC). Routes to the stage flow and loads the right craft skills per stage.
---

# Creator Foundry — the video-creation stack

Terminal-native production system for this repo. No app: Claude Code is the engine,
these skills are the product, and every stage writes a typed artifact to disk
(`work/<account>/<slug>/NN-*.json`). Canonical process: `JOURNEY.md`. Product
blueprint: the "Creator Foundry" artifact (URL in memory).

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

Stages that lack a dedicated builder today run as guided flows using the engine
modules directly (`engine/`, `pipeline/`, `motion/`). Never collapse stages: gates
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

## Dependencies — `/foundry doctor`

`SETUP.md` is the canonical dependency manifest: API keys via `.env` /
`.env.example` (Apify token or MCP, ElevenLabs, fal or Higgsfield MCP, Gemini
for analysis + Nano Banana images, optional OpenAI images), local tools
(ffmpeg, yt-dlp, Python venv, Node), and the skill/MCP layer (official Remotion
skill → Lane A, official Playwright skill → Lane B). `/foundry doctor` = verify
each row of SETUP.md and report what's missing and **which lane it degrades**
(e.g. no fal/Higgsfield → Lane C pieces stop at the storyboard). Run it on any
fresh clone before producing.

## Provenance

Craft principles distilled from public research (Mayer, Muller 2008, platform
specs) and inspired by the OpenMontage project's approach (AGPL-3.0 — principles
re-authored here, no text or code vendored), fused with this repo's own measured
production lessons (see memory + `research/`).
