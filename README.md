# Creator Foundry

A suite of eight [Claude Code](https://claude.com/claude-code) skills that turn short-form video production into a staged, gated, artifact-driven process — the way a build pipeline treats code.

No app, no UI. Claude Code is the engine, the skills are the product, and every stage writes a typed JSON artifact to disk that the next stage reads. A human approves at four gates, and the expensive stages never run before the cheap ones are locked.

The end state is a **full-stack content creator**: you birth an influencer once — identity, look, voice, a hero image you approve like a casting decision — and from then on you just drop ideas. The Foundry is the writer, director, cinematographer, editor, and QC; you are the taste. You never need to know production vocabulary: every question comes in plain words with a recommended default, and "you choose" is always a valid answer. Output is **posts**, not just videos — image posts and carousels are the same journey stopped at the storyboard, so every video project yields image derivatives for free.

## Why it exists

Most AI video workflows collapse "what should this say?", "what should it look like?" and "render it" into one prompt. That is how you spend money on motion for an idea nobody vetted.

The Foundry forces a **cost pyramid**: words are free, stills cost a rupee or two, motion costs a hundred or more. Every question gets answered at the cheapest level that can answer it. A storyboard is approved before a single clip is generated — approving the board *is* approving the invoice.

## The skills

| Skill | What it does |
|---|---|
| **`foundry`** | Router. Maps intent → stage → which craft skills to load. Enforces the hard rules (gates, cost pyramid, delivery-promise lock, evidence discipline). |
| **`foundry-interview`** | Interactive front door. Interrogates a vague idea (or a blank account) round by round until it lands as a locked, linted brief or account charter. Like `/spec`, but for content. |
| **`foundry-storytelling`** | Narrative structure — the short-form arc, but/therefore beat logic, misconception-first, hook craft, pacing and retention targets, Mayer's principles applied mechanically. |
| **`foundry-screenwriting`** | The two-column script contract — beat format, the 5-slot visual spec (subject / motion / scene / spatial / camera), anti-subjective language lint, word bands, delivery cues. |
| **`foundry-storyboard`** | One keyframe per beat, sourced per lane. Composed-frame review, safe zones, slideshow-risk and variation checks, board-as-invoice, QC conformance. |
| **`foundry-voice`** | Voice performance direction — making TTS sound directed rather than read. Performance plans, the sample gate, lipsync routing, locked persona voices. |
| **`foundry-sound`** | Mix craft in numbers, not taste — ducking levels, loudness targets, SFX timing, the AI-TTS processing chain, silent-master rules for trending-audio formats. |
| **`foundry-review`** | The review-page craft. Never hand a human raw JSON: every gate is surfaced as a single readable HTML page derived from the artifacts. |

## Install

Skills live in a `skills/` directory that Claude Code discovers. Clone into your project (or your user-level skills directory):

```bash
git clone https://github.com/csakash/foundry.git /tmp/foundry && cp -R /tmp/foundry/skills/foundry* .claude/skills/
```

For all projects instead of one, copy into `~/.claude/skills/` :

```bash
git clone https://github.com/csakash/foundry.git /tmp/foundry && cp -R /tmp/foundry/skills/foundry* ~/.claude/skills/
```

Then copy the catalog scaffold and setup manifest into your project root (skip if you already have your own):

```bash
cp -R /tmp/foundry/catalog /tmp/foundry/SETUP.md /tmp/foundry/.env.example .
```

Restart Claude Code (or start a new session) and the eight skills appear in the skill list. Fill `.env` (see `SETUP.md`), then run `/foundry doctor` to verify the stack.

## Use

Start anywhere with the router:

```
/foundry
```

Or go straight to the front door with a raw idea, a topic, or a dropped reel URL:

```
/foundry interview
```

The interview never produces an artifact from the first message. It runs phased: **the Why** (who, what they believe after, why now, what's the promise, how we know it worked) → **scope and locks** (format, lane, audio architecture, persona, duration, budget ceiling) → **craft interrogation** → **draft review** → **lint gate** → **land it**. Expensive-to-change decisions are asked first, on purpose.

### The stage flow

| Stage | Intent | Artifact |
|---|---|---|
| Interview | `/foundry interview` | a brief, or a new account charter |
| Birth an account | `/foundry birth` | `accounts/@handle/{account,charter,portfolio}.json` |
| Intake + brief | `/foundry brief` | `00-intake.json`, `01-brief.json` |
| Script | `/foundry script` | `02-script.json` (two-column) |
| Storyboard | `/foundry board` | `03-board/` — keyframes + `board.json` |
| Produce | `/foundry produce` | `04-assets/`, `05-cut/final.mp4` |
| QC | `/foundry qc` | `06-qc.json` |
| Publish + learn | `/foundry learn` | publish log, priors update |
| Review | `/foundry review` | `review.html` — runs after **every** stage |

Artifacts land under `work/<account>/<slug>/`.

### The four gates

1. **Gate 1 — brief.** Right idea?
2. **Gate 2 — script.** Right words?
3. **Gate 3 — board.** Right look?
4. **Gate 4 — QC.** Matches the plan, and is it legal?

Gates are where a human decides. A rejection becomes regeneration guidance, not a reopened creative debate. Stages are never collapsed — the whole point is that idea → words → look are each judged *before* money reaches motion.

## The rules the router enforces

- **Read the craft skill before doing the stage.** Writing a script without `foundry-screenwriting` loaded is the same violation as skipping a lint.
- **Charter is lint.** Every brief, script and board is validated against the account charter, banned-phrase tokens, and the evidence ledger.
- **Cost pyramid.** Iterate at the cheapest level that can answer the current question. Lock stills before motion.
- **Delivery promise lock.** A brief declares its lane (deterministic / captured / generative) and motion character. If production can't honor it, stop and ask — never silently downgrade a motion-led piece to a slideshow.
- **Never hand a human raw JSON.** Every stage write is followed by a regenerated review page. Pasting artifact excerpts into chat is the same failure in a thinner disguise — it shows only what you chose to show.
- **User-supplied copy is intake, never evidence.** Every figure gets sourced and registered before it reaches a frame. A fabricated number passes every other lint in the stack.
- **Reference decomposition is never deaf.** Any reel that informs a brief goes through the analyzer with real audio — a template with an empty transcript is invalid evidence. Frame-exact timing is measured off the file, never estimated by eye.

## Pipelines — produce once, reuse forever

When a piece passes QC, save it as a recipe: `/foundry save <name>` freezes every approved decision into [`pipelines/<name>.json`](pipelines/README.md). `/foundry run <name> topic="…"` then regenerates only the stages the changed parameters touch — no re-interview, one confirmation before spend. A recipe run over a parameter matrix fans out **one Claude subagent per piece** (each in its own `work/` directory), the human approves the whole matrix once, and per-piece QC still runs after. That's the path from one good video to a parallel-produced series.

## The catalog

`catalog/` is the preference & inspiration layer — **data, not code**. Hook
families, creator personas, target geos, and campaign intents live as one JSON
file each; raw reference docs (creative briefs, tone direction, meeting notes)
drop into `catalog/briefs/` as markdown. The interview and brief stages read the
catalog before proposing an angle, and every brief records which catalog ids it
used, so performance joins back to picks.

Extending the system = dropping a file. No skill edits, no code. The contract
(schemas, the variation matrix, the director's lint) is in
[`catalog/README.md`](catalog/README.md); this repo ships starter entries you
replace with your own.

## Setup & dependencies

[`SETUP.md`](SETUP.md) is the tiered dependency manifest — API keys
(`.env.example`), local tools (ffmpeg, yt-dlp), and the skill/MCP layer
(official Remotion skill for deterministic motion graphics, official Playwright
skill for captured web demos, Higgsfield/fal for generative video, Apify for
inspiration scraping). Nothing is all-or-nothing: `/foundry doctor` checks every
row and reports what's missing and which production lane it degrades.

## Portability

The skills are the craft layer and are readable and useful on their own — the structure rules, lint rules, mix levels, and gate discipline apply to any pipeline.

They do, however, reference a companion implementation in the repo they were authored for — `engine/` (review generator, evidence ledger, formats, prompt slots), `pipeline/` (reel decomposition via Apify → ffmpeg → whisper → Gemini), `motion/` (Remotion compositions), plus `accounts/`, `personas/`, `templates/` and `brand.tokens.json`. Those scripts are **not** included here. Treat every such path as a named contract to implement against your own stack:

| Referenced path | What it must provide |
|---|---|
| `engine/review.py` | renders artifacts → a single self-contained `review.html` |
| `engine/evidence.py` | a citable ledger; every on-screen number resolves to an id |
| `engine/formats.py`, `engine/prompts/` | format registry and the hook / shot / brief / voice slot templates |
| `pipeline/analyze_reel.py` | reference decomposition with verified audio provenance |
| `accounts/@handle/charter.json` | the per-account lint source — purpose, tone, topics in/out, never-list, visual identity |
| `brand.tokens.json` | banned phrases and compliance overlays |

Swap the tooling; keep the gates.

## Provenance

Craft principles distilled from public research (Mayer's multimedia principles, Muller 2008 on misconception-first instruction, platform specs) and inspired by the OpenMontage project's approach (AGPL-3.0 — principles re-authored here; no text or code vendored), fused with measured production lessons from the repo these were built in.

## License

MIT — see [LICENSE](LICENSE).
