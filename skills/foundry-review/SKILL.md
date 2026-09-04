---
name: foundry-review
description: The review-page craft — turning a piece's JSON artifacts into the single HTML page a human actually judges a gate from. Load whenever a gate is about to be surfaced to the user, when a stage artifact has just been written, or when asked to show/visualise a piece.
---

# Review — never hand a human raw JSON

JSON is the storage format. It is not the review format. Every gate in
`JOURNEY.md` asks a person a question — "right idea?", "right words?", "right
look?" — and nobody can answer those from a wall of braces. Pasting artifact
excerpts into chat is the same failure in a thinner disguise: it shows the parts
you chose to show, which is exactly the bias a gate exists to defeat.

**The rule: any time a gate is surfaced, regenerate the review page first and
give the user its path (and, when they want a link, its Artifact URL).**

```bash
python3 engine/review.py work/@handle/slug          # -> work/@handle/slug/review.html
python3 engine/review.py work/@handle/slug --open   # and open it
```

## Plain language is the whole point

A review page that reads like a spec sheet has failed, however complete it is.
The reader is a person deciding whether to make a video — not an engineer
reading a schema. So:

- **Lead with the story.** The top of the page is a plain paragraph anyone could
  read aloud: who is on screen, what happens, what the point is. Not a thesis
  statement, not a positioning line — the video, described.
- **No raw keys, statuses, ids or slot names ever reach the page.** They are
  mapped through the label tables in `engine/review.py` (`LINT_LABELS`,
  `SLOT_LABELS`, `VISUAL_SLOT_LABELS`, `GATE_QUESTIONS`) and through
  `phrase()` in the page script. `word_band` becomes "The script fits the
  runtime"; `columnLeft.card1` becomes "card on the left"; `AWAITING_HUMAN`
  becomes "Waiting on you". Adding a new key to an artifact means adding its
  label — an unmapped key falling through to the page is a bug.
- **Technical detail is kept, not deleted.** The 5-slot shot spec, the ledger
  ids, the clip notes are the production contract and must stay reachable — but
  behind a "production detail" disclosure, never in the default view.
- **Numbers get units in words.** "14 seconds", "31 words she says", "₹275 to
  make, at most" — not "dur 14.0", "31w", "ceiling 275".
- **Say what a thing is for.** "Nobody has drawn this yet. Each moment becomes a
  still photograph first — a still costs a rupee or two, a moving clip costs a
  hundred or more, so the picture is where you change your mind." That sentence
  does more than the word "Storyboard".

## Artifacts must carry the plain fields

The page is derived, so it cannot invent plain language — the artifacts have to
carry it. Three fields are **required**, and their absence is a lint failure,
not a cosmetic gap:

| Field | Where | What it is |
|---|---|---|
| `title` | `01-brief.json` | The piece's name in plain English, 2–4 words. "The Wrong Number", not a slug. |
| `story` | `01-brief.json` | One paragraph describing the video as a person would recount it. |
| `plain` | every beat in `02-script.json` | One sentence on what a viewer actually sees and experiences in that beat. |

The `plain` line is a craft instrument, not documentation: **if a beat cannot be
said plainly in one sentence, it is not clear enough to build.** Write it before
the 5-slot spec, not after.

## It is a derived view, never a source

`engine/review.py` reads the artifacts and renders them. Nothing is authored in
the page. If a fact is not in an artifact it does not appear — which makes the
page a live audit of whether the artifacts are actually complete. Never hand-edit
`review.html`; fix the artifact and re-run. Never write a bespoke one-off HTML
for a piece — extend the generator so every piece gains the improvement.

## Regenerate after every stage write

Intake, brief, script, board, assets, cut, QC — each one changes what the page
shows. The page is explicitly built to be opened at Gate 1, when only a brief
exists, exactly as much as at Gate 4. Missing stages render as "not yet
produced" with a **What's still owed** list rather than being hidden, so an
early page is honest about the hole rather than looking finished.

## What the page has to carry

| Section | Answers | Sourced from |
|---|---|---|
| Masthead + gate strip | where is this piece, what is blocking | brief/script/board/qc `gate` |
| The idea | is this worth making | `01-brief.json` one_idea, takeaway, kill question |
| **The cut** | *what will this actually feel like* | script beats + plates, played in real time |
| Two-column script | are these the right words | `02-script.json` beats, 5-slot visual, delivery cues |
| Storyboard | is this the right look | `03-board/` keyframes, status, est_cost |
| **The swipe** (carousel posts) | does slide 1 earn slide 2 | same keyframes, drawn at 4:5 in swipe order, labelled "slide" |
| Audio & motion | does the performance land | `04-assets/`, `05-cut/` embedded players |
| Evidence ledger | is every number real | citations resolved against `evidence/manifest.json` |
| Lint | what fails | `02-script.json` lint block |
| Compliance | what can get us in trouble | brief compliance + charter never_list |
| Reference deconstruction | what did we take, what did we refuse | `templates/<code>.json` |
| Caption | ship-ready copy | script caption, one-click copy |
| What's still owed | what is left | derived from which stages exist |

**Frame shape follows the post.** `post_shape()` in `engine/review.py` reads
`post_type` (and any explicit `aspect`) and sets the `--frame-ar` CSS variable
plus the unit word: a reel is a 9:16 "moment", a carousel is a 4:5 "slide", an
image post is a "frame". Judging a carousel gate on 9:16 crops is judging it on
a lie — and the carousel craft rules live in **foundry-carousel**, not here.

## The cut is the point

The hero is a transport — play/pause, scrub, arrow-key stepping — driving a
timeline and a 9:16 frame preview side by side. Every plate is drawn at its real
coordinates at the current timecode, with the beat's VO line and delivery cue
underneath. **This lets a human watch the overlay choreography in real time
before a rupee is spent.** For overlay-led formats, where cadence is the craft
(new element every ~0.5s in a hook — see the measured reference in
`templates/DaiFzwdzDz3.json`), this is the only way to judge pacing without
generating the video. Treat it as a Gate 2/3 instrument, not a decoration.

Plate geometry comes from `personas/<slug>/persona.json` `setups[*].plates`
where a slot is named there, and from `SLOT_GEOMETRY` in `engine/review.py`
otherwise. Provisional geometry is labelled as such on the page: the board stage
re-measures against the real master still and wins.

## Extending it

Add a stage or a field to the generator, not to one piece's page. Keep it
self-contained — inline CSS/JS, media as data URIs under the embed caps, Google
Fonts as the only external host — so `review.html` opens from disk, survives
being emailed, and publishes as an Artifact unchanged. Design guidance for the
page itself lives in the `artifact-design` skill; load it before reworking the
visual layer.
