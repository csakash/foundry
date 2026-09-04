---
name: foundry-carousel
description: Carousel craft — the locked six-role ladder (provocation, proof, mechanism, example, widen, open loop), the five-line feature-post ladder, the one-seed/six-slot input contract, the so-what gate, the 1080x1080 house style (statue on every slide, floating diagrams, no cards), the renderer and figure generator, and the swipe gate. Load whenever the post type is carousel or multi-image, when deciding whether an input can even become a carousel, when turning an approved board into a carousel derivative, or when reviewing/rewriting slides.
---

# Carousel — the cheapest post that still has to be written

A carousel is **not a video with the motion removed**. It is its own format with
its own physics: the reader is holding the swipe, every slide has to buy the
next one, and the payoff has to be worth saving. Measured on the accounts this
repo studies (`drevon-findings/outputs/trading_instagram_carousel_accounts.md`):
carousels land ~10% engagement vs ~7% single image and ~6% reels, ~+22% saves,
and get re-served to people who didn't engage the first time — the "second
chance" on slide 2. That re-serve is the whole reason the format exists, and
it's why slide 2 is a design problem, not filler.

Cost-wise the carousel sits at the bottom of the pyramid: an 8-slide Lane-A
carousel is ₹0–40 all in. **That is not permission to make it thoughtlessly** —
it means the only scarce input is the writing, so all the craft budget goes
there.

## Canvas and crop law

- **1080×1080 (1:1)** is the render size for this account — matched to the
  house style, not chosen from theory. 4:5 buys more feed height, and the
  general argument for it stands, but an account with an existing visual
  language does not get a new aspect ratio because a skill prefers one.
  Decompose the account's own posts first (`pipeline/analyze_carousel.py`) and
  follow what is there.
- **Nothing is safe outside the square.** At 1:1 the feed and the profile grid
  show the same frame, so the only crop risk is the platform UI at the edges.
- **Margins are 96px** on all sides. The bottom-right ~200×200 is reserved for
  the swipe affordance and platform UI — no text, no logo, no number there.
- **Slide count 7–10.** The ladder below sets it: six roles, of which three may
  take an extra slide when the story needs it. Under 7 usually means a slot is
  unfilled; over 10 means two carousels or a reel.
- **Legible at thumbnail.** Shrink the cover to 120px wide and read it. If the
  headline doesn't survive, the font is too small or the line is too long.

## The ladder — locked

Six roles, in this order. Every slide declares exactly one; an untyped slide is
a bug. Derived from four `@groww_official` carousels decomposed slide by slide
(`catalog/briefs/groww-carousel-formula.md`, raw slides in
`templates/raw/<code>/`) — this is measured practice, not a theory of carousels.

| # | Role | Job | Fails when |
|---|---|---|---|
| 1 | `provocation` | The hook. ≤8 plain words stating something that shouldn't be true, or a why-question about something the reader half-knows. The illustration carries the wit; the words stay flat. **It must survive the so-what gate below.** | It carries a number, says "you", restates the source headline, or raises nothing. |
| 2 | `proof` | The one sourced figure that makes it real — as a table where possible — plus a one-line gloss of the jargon inside it. **This is the keeper**, and it arrives at slide 2, not at the end: front-loading the proof is what buys slides 3–10. | The number has no ledger row, or its table doesn't paint the reader's row. |
| 3 | `mechanism` | How it actually works, in two or three causal steps. May expand to two slides. | It restates the event instead of explaining it. |
| 4 | `example` | A real, nameable entity and what happened to it. May expand to two slides (name it, then price it: what it cost, at what scale). | "A company", "some firms" — anything unnameable. |
| 5 | `widen` | The same pattern one level out: another country, another scale, a precedent. May expand. | It introduces a second discovery instead of widening the first. |
| 6 | `open_loop` | A question the account would actually read the answers to — or, when there is nothing honest to ask, end on `widen` and stop. | "What do you think?", "Comment below", or a save/follow/link CTA. |

**No ask slide, no hashtags, no link.** The measured account runs zero hashtags
across every post scanned, and its one product-bearing carousel was its weakest.
Sell at most once, only where the proof has already made the argument, and only
inside `mechanism` or after `widen` — never as slide 1 and never as the ender.

Two transfer rules apply to every slide that carries a number:

- **Paint the reader's row.** The local index, the current year, the bracket the
  reader is standing in — highlighted, in every table.
- **Convert foreign numbers into felt ones.** Not "$58B" but "nearly 6× the
  local giant's entire annual profit", drawn as two bars.

### The so-what gate

A cover can be true, short, on-brand and still dead, because the reader finishes
it and thinks *so what*. The line has to leave a hole the reader wants filled.

The check is not a feeling. **Write down the question the reader asks in their
head after reading the cover** — `provocation.raises` in `00-intake.json`, and
`carousel_intake check` fails a cover whose question is a shrug. If you cannot
write that question in a few words, the line raises nothing, and no amount of
rewording will fix it: the problem is the choice of fact, not the phrasing.

Four things reliably open the hole:

- **A contradiction** — something that should not be true. *"Apple sells in 110
  countries, but not in the one it's from."* → *how is that possible?*
- **A withheld referent** — name the effect, hide the subject. *"Americans
  aren't allowed to buy them."* → *buy what?*
- **A number that is off** — a figure that does not match what the reader
  assumes. *"9 out of 10 lost money."* → *why?*
- **A cost they did not know they were paying** — *"Your money reaches a US
  stock in three cuts."* → *which three, and how much?*

And the reliable ways to produce a shrug, all of which read as advertising:

- A feature stated as a fact (*"Start investing with one dollar"*) — the
  sentence completes itself; there is nothing left to want.
- A generic problem (*"Investing abroad is expensive"*) — the reader already
  knows, so nothing has been added.
- A benefit claim (*"Lower fees, faster settlement"*) — discounted on sight.
- A definition or a run-up (*"Forex conversion charges are…"*) — no tension.

**Slide 2 must answer that exact question.** A cover that raises "buy what?"
and a slide 2 that talks about regulation has broken its own promise; the
question and the payoff are one design, not two. `answered_on` records which
slide closes it.

This gate applies to any first line, not only a carousel cover — the opening
line of a five-line feature post is judged the same way.

## The input contract — one seed, six slots

The input question has an exact answer: **an input is valid iff it can fill the
six slots.** What the human hands over is a *seed*; the fill is the system's
job, and the human is asked only about what would not resolve.

**Accepted seeds** (exactly one is enough):

| Seed | Example | Resolves best |
|---|---|---|
| `url` | a news story, filing, regulator report, exchange notice | everything — the default |
| `claim` | "Samsung made $58B in one quarter" | proof, then work outward |
| `figure` | a number with a source the user pasted | proof; mechanism must be found |
| `question` | "why did K-markets fall?" | provocation + mechanism |
| `document` | a PDF report, a chart image, a screenshot | proof + example |
| `reference_post` | an IG/LinkedIn post to borrow the *shape* of, never the content | nothing — it sets form, so it still needs a content seed |
| `topic` | "do something on PSUs" | nothing on its own — it routes to `/foundry research` first, which crawls, sources and tells the story; the fill is then built from the approved dossier's findings |

**The door test.** A seed is a carousel only if it is *a thing in the news the
reader has already half-heard, plus one layer underneath it they haven't*. No
layer underneath → it is a single-image post (one chart, one claim, one
caption). A layer that is a process the reader must watch happen → reel. The
intake decides the post type; the user does not have to know the difference.

**Where the fill comes from.** When the piece went through `/foundry research`,
the six slots are already sitting in `00-research.json`: a `figure` finding is
the proof, a `claim` finding is the mechanism, a named `url`/entity is the
example, the precedent query's finding is the widen. Copy them across with their
evidence ids — never re-source what the dossier already verified, and never add
a slot the dossier does not support.

**Resolution, in order:** `provocation` and `open_loop` are authored from the
resolved slots — write them last, never first. `proof` is sourced and registered
via `engine/evidence.py` (`put_figure()`) before it is written anywhere.
`mechanism`, `example` and `widen` come from the seed's own source document, or
from one hop out of it; anything that cannot be attributed does not go on a
slide.

Run it:

```bash
python3 -m engine.carousel_intake scaffold work/@handle/slug \
    --seed-type url --seed "https://…" --ask "<the user's own words>"
python3 -m engine.carousel_intake check work/@handle/slug
```

`check` is the Gate-1 lint: it resolves evidence ids against the ledger, lints
the provocation (word band, no number, no "you", not the headline verbatim),
rejects dead open loops, enforces both transfer rules, prints the routing
verdict (carousel / single image / not yet) and lists **only** the slots still
owed. Those unresolved slots are the questions to put to the human — in the
plain language of `foundry-interview`, one round, with a recommended default.

## The second ladder — the feature post

The six-role ladder above is the **news explainer**: third person, story-led,
no CTA. An account also has to talk about its own product, and that is a
different ladder with a different job (consideration, not reach). It is the
founder's five-line brief, kept verbatim in shape, one line per slide:

| # | Line | Job |
|---|---|---|
| 1 | **friction** | the thing the reader already feels — and it must still pass the so-what gate |
| 2 | **why it happens** | the mechanism. A process, never a villain |
| 3 | **not your fault** | takes the blame off the reader without pointing it at anyone |
| 4 | **what changes** | the product, with the real number |
| 5 | **the ask** | the sign-off slide: one relatable line, then *Download gm.markets to start trading* |

His test, worth keeping word for word: *read only line 5 and you can infer
the argument; read the argument and you can write line 5.* A feature that cannot
support that does not get a post.

Rules that came out of writing nine of these (`catalog/briefs/feature-posts-copy.md`):

- **Positive still has to be curious.** The gap a positive line opens is
  *disbelief at good news* — the reader's question is "really? how?" instead of
  "why is that wrong?". A feature stated as a fact ("Start with $1") is a shrug.
- **Punch at the friction, never at a party.** "Your money takes three cuts on
  the way" is fair and sourceable. "Your broker is ripping you off" is a claim we
  cannot support and a fight we do not need.
- **One countable thing beats every concept.** Leverage became "$100 that
  trades like $5,000, and a 2% move doubles it or wipes it out". Custody became
  "one token, one real share, a claim ticket and a coat". 24/7 became "open 32
  hours of 168". If a line explains in concepts, find its number.
- **Simple English, and no em dashes anywhere** on a slide or in a caption —
  split the sentence instead. The dash is the most reliable tell of machine
  writing in short copy.
- **The honest sentence stays.** Leverage's both-ways line, 24/7's "quiet hours
  can cost a bit more", sign-in's "checks come later for higher limits". Each is
  what makes its post publishable; none is optional copy.
- **A feature absent from the product's own Terms is HOLD**, however well it
  writes. Two of nine were.

## The headline ladder (Gate 2's real test)

Strip every slide to its headline and read them top to bottom as a list. **That
list must deliver the complete idea on its own** — most people skim headlines and
never read a body line, and they must still leave with the whole story, not a
teaser for it. Every fact the piece depends on (what the thing is, why it
happens, who it happens to) belongs in a headline; the body adds detail,
qualification and colour, never load-bearing information.

The ladder runs provocation → proof → mechanism → example → widen → open loop,
each line handing over to the next. If it reads as a table of contents, the
carousel is a deck, not a post. Record the headline-only reading in
`02-script.json` as `ladder_test`, and fix the ladder before anyone renders a
pixel.

Also lint the ladder for:

- **Cliffhanger continuity** — each slide's last line creates the reason to
  swipe. Not "next slide!" — an open loop the next headline closes.
- **No orphan slide** — remove any slide whose deletion nobody would notice.
- **One idea per carousel.** N slides is depth on one discovery, never N
  discoveries stacked (same rule as one video = one discovery).
- **Word bands** — provocation ≤8 words; body ≤25 words per slide; bold is the
  only emphasis system (two type sizes per slide, three across the set), and
  colour is reserved for tables and the one brand word.
- **`no-ai-slop` over every word**, cover to caption. Slide copy is where AI
  cadence is most visible: no "unlock", no "in today's fast-paced", no
  three-item lists of abstractions, no em-dash-joined hedging.
- **`hormozi-hooks`** generates provocation candidates; **`objection-destroyer`**
  owns the slide where the reader's resistance is named; **`copywriting`** and
  **`marketing-psychology`** for the widen and the open loop.

## Caption is slide zero

The caption ships with the post and is judged with it (the `ambient_loop`
lesson: on some formats the caption *is* the product). Structure:

1. First line = the hook echo, written to survive the "more" truncation.
2. Payload — the part that makes the caption worth reading after the swipe.
3. The ask, matching slide n.
4. Compliance: the AI-generated disclosure and the disclaimer text from
   `brand/brand.tokens.json` compliance config.
5. ≤5 hashtags, none of them decorative.

Alt text per slide is authored, not auto — it is also the only thing a screen
reader gets.

## Evidence and compliance on a slide

Slides are the highest-risk surface in the stack: a number on a still frame gets
screenshotted and travels without its context.

- Every figure on a slide is registered via `engine/evidence.py`
  (`put_figure()`), and the slide carries its evidence id. Unsourced number =
  build failure, not a copy note.
- Charter + `brand.tokens.json` banned phrases lint every slide and the caption.
- Education framing only — no recommendation, no return promise, no
  performance claim the ledger can't back.
- The AI-generated label sits on the **cover** (it is the slide that travels)
  and the disclaimer on the **last slide plus the caption**. Never only in the
  caption, and never in the bottom-right dead zone.

## The house style (decomposed, not invented)

`templates/DcnjhnmFdiS.json` is the reference post; the palette below was
**sampled from its pixels**, never eyeballed. `templates/carousel/slide.html`
implements it and `pipeline/render_carousel.mjs` drives it.

| Element | Spec |
|---|---|
| Canvas | 1080×1080, cream `#f6f0e4`, 74px graph-paper grid at 6% ink |
| Ink | `#161511` · body `#585448` · small print `#8b8578` |
| Green | mint `#1BD688` (chip, logo, highlights) · deep `#138957` (headline words, charts) |
| Chip | top-left, mint fill, ink text, uppercase, `.14em` tracking |
| Type | **One family: Archivo.** Headlines 700, sentence case, `text-wrap: balance`; punch words in deep green (`*asterisks*` in the script). Body 400 with `**inline bold**`. The caps-heavy Archivo Black of the original reference was retired 2026-08-31 as too loud. |
| Figure | greyscale classical statue, **on every content slide**, cut out, bleeding off an edge. Alternates sides on text slides; on a big-number slide the number and ticks sit left and the statue right. Text and figure never touch: the layout measures every rendered line against the figure after the font and the image have both loaded, and shrinks the figure until clear. |
| Diagrams | three blocks, all floating on the ground with **no cards, borders or shadows**: `receipt` (rows with dotted leaders, green *shown* / red *not shown*), `journey` (thin green line icons in a row with arrows, a short label and a red cost under each), `bignum` (one huge green figure, a 40px sub-line, optional green ticks). The background is the container. |
| Motifs | green stepped line (cover only), `SWIPE →` bottom-left on the cover |
| Last slide | centred sign-off in Archivo 600: one relatable line, the ask, the logo. No disclaimer line (owner decision 2026-08-31); the leverage post alone keeps its "multiplies losses as well as gains" sentence because it *is* the argument. |

That last row matters: **this account ends on a sign-off slide**, which the
generic ladder above forbids. The house style wins. The six-role ladder then
runs across slides 1–5 and the sign-off is slide 6.

**Figures are generated, and that has consequences.** `pipeline/gen_figures.py`
calls `gpt-image-2` with one locked STYLE string plus a per-slide subject, asks
for a transparent background, and trims the transparent margin so the statue
(not its canvas) sits at the edge. One string in one place is what keeps thirty
separately generated statues in the same world. Three things learned the hard
way, all now in the code:

- The style string says **"fully draped in carved robes"** — classical nudity
  trips the safety filter and a reclining pose gets rejected as "sexual".
- A rejected or throttled image is **skipped and reported, never fatal**, and
  the script saves after every image so a run that dies late keeps what it paid
  for. On a 429 the generator backs off and retries before giving up.
- When the quota is gone, **reuse the cast**: every figure in
  `brand/assets/figures/` is a candidate for any slide whose line it fits, and a
  reused figure is recorded in the script with the original subject so it can be
  regenerated later. A recurring cast is the house pattern anyway.

## Render routes and what they cost

| Lane | Route | Use for | Cost |
|---|---|---|---|
| **A** | `npx remotion still` of the carousel composition with real props | text, data, charts, tables, checklists — the default for most slides | ~₹0 |
| **B** | `pipeline/capture_assets.mjs` (Playwright/CDP) | product proof: real app screens, real order tickets, real site states | ~₹0 |
| **C** | Nano Banana / persona stills (`foundry-storyboard` sourcing rules) | cover art, persona presence, a scene that must be photographed | ₹2–20/frame |

**Never spend Lane C money on a slide that is text.** A generated image of a
text plate is worse than the deterministic render and costs real money. Lane C
appears on covers and on at most one or two scene slides.

**The renderer is `pipeline/render_carousel.mjs`** over
`templates/carousel/slide.html`: Playwright, 1080×1080, every asset inlined as a
data URI (a `file://` image never loads from `setContent`). It waits for the
page's own `__layoutSettled` flag, which the template raises only after the
font and the statue have both loaded and the collision pass has run —
screenshotting earlier is how text ends up under a statue. Diagram blocks,
icons and the sign-off are all template features; a post never needs a
one-off page.

## Artifacts and gates

Carousels use the same journey, not a side pipeline:

- `00-intake.json` — the `carousel` block: the seed, the six-slot `fill`, and
  the locks. Written and linted by `engine/carousel_intake.py`; nothing
  downstream starts until `check` routes the seed to CAROUSEL.
- `01-brief.json` — `post_type: "carousel"`, target slide count, the one layer
  underneath the headline, the intended save trigger.
- `02-script.json` — beats **are** slides: `{n, role, headline, body, visual,
  plain, evidence[], alt}` where `role` is one of the six, in order, plus the
  `caption` block. The two-column discipline
  from `foundry-screenwriting` still applies: what it says | what it shows.
- `03-board/` — one rendered 1080×1080 slide per beat, plus `board.json` with
  `est_cost` and `status` per slide. The sum is still the invoice.
- Review page — `python3 engine/review.py <work_dir>` draws the slides at 4:5 in
  swipe order under "The swipe" when `post_type` is carousel. Judge the gate
  there, never from JSON or a chat summary.

Gates: **1** the fill (`carousel_intake check` clean, and the routing verdict
is CAROUSEL) → **2** headline ladder + caption →  **3** rendered swipe →
**4** publish check (order correct, cover crops safely to 1:1, labels and
disclaimer present, alt text authored, caption compliant). There is no render
conformance pass because there is no render — Gate 4 is the publish checklist.

## Self-score before the human sees it

Loop "revise" automatically on any of these:

1. Cover fails the thumbnail read, or fails the so-what gate, or its line isn't
   inside the center 1:1.
2. Slide 2 is not the proof — the sourced figure arrived late, or never.
3. Nothing on the set is worth screenshotting; no table paints the reader's row.
4. Headline ladder reads as a contents page, or a role is missing/duplicated,
   or a fact the story depends on lives only in a body line.
5. Two consecutive slides with identical layout **and** identical visual weight
   (variation, without breaking the system — a carousel should look like one
   set, not eight unrelated posters).
6. Any figure without an evidence id; any banned phrase; missing label or
   disclaimer.
7. Any text inside the margins or the bottom-right dead zone.

## Derivatives, both directions

- **Board → carousel.** Any approved video board with ≥5 plate-complete frames
  is a carousel for free — but only after the frames are re-cropped to 4:5 and
  the copy is rewritten to the slide roles. A 9:16 frame dropped into a 4:5
  canvas with its VO line pasted on is the failure mode, not the derivative.
- **Carousel → reel.** Slides become beats: the ladder is already a script
  spine, and the proof slide becomes the evidence beat. Route through
  `foundry-screenwriting`; don't just pan across the stills.
- Always offer the derivative when a piece clears its gate, and always offer
  `/foundry save <name>` — a carousel that worked is a series.
