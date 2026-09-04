# The Groww carousel formula (reverse-engineered)

**Source:** `@groww_official` — four posts the user supplied, decomposed slide by
slide with `pipeline/analyze_carousel.py` (templates `DcoCYZZjM3_`,
`DcbKb_Rk9IB`, `DcTbzkpk-M2`, `DaiMK8YjICm`; slides in `templates/raw/<code>/`),
plus a scan of their 18 most recent posts for cadence and format mix.
**Read:** 2026-08-31. Engagement figures are likes/comments at read time, not
reach; treat them as relative, not absolute.

| Post | Slides | Likes | Comments | Ender |
|---|---|---|---|---|
| ISRO stops making rockets (`DcoCYZZjM3_`) | 10 | 6,768 | 240 | widen (NASA did this first) |
| Government companies that do nothing (`DcbKb_Rk9IB`) | 8 | 4,054 | 43 | question to reader |
| Korean market crash (`DaiMK8YjICm`) | 7 | 2,739 | 71 | widen (other Asian markets) |
| SEBI: 9 of 10 traders lose (`DcTbzkpk-M2`) | 7 | 2,185 | 22 | **product** (3 Groww features) |

## The one-line formula

> Take a headline the reader has already half-heard, and give them **the one
> layer underneath it** — in 7–10 slides of plain sentences and one editorial
> cartoon each, where slide 2 is the proof, every foreign number is converted
> into an Indian one, and the last slide widens instead of selling.

## The ladder (holds across all four)

| Slide | Role | What it actually does |
|---|---|---|
| 1 | **Provocation** | ≤8 words, no number, no "you". A flat statement that shouldn't be true ("ISRO doesn't want to make rockets anymore", "Government companies that do nothing") or a why-question ("Why did K-markets Pop 5% today?"). The *illustration* carries the wit; the words stay plain. |
| 2 | **Proof + definition** | The number that makes it real, plus a one-line gloss of the jargon inside that number. Every one of the four does this on slide 2 — the table, the stat, the SEBI percentage. This is the slide most playbooks save for the end. |
| 3 | **Mechanism** | How the thing works, in causal sentences. "A CPSE may be declared inoperative if… it may then be considered for closure." |
| 4 | **Named example** | A real, checkable entity: MMTC, the HAL–L&T consortium, Samsung Electronics. Never "a company". |
| 5–6 | **Stakes, then scale** | What it costs (₹36,000 Cr; 87.7% of traders), then the same pattern one level wider (state-level SPSEs; income brackets; KOSPI concentration). Usually a second table. |
| 7–9 | **Widen** | "This has happened elsewhere" — NASA, other Asian markets. The reader leaves with a frame, not a fact. |
| last | **Open loop or product** | Either a question the reader can answer in comments, or — rarely — the product, when the data has already made the case for it. Never a follow/save/link CTA. |

**Where the "keeper" sits.** The screenshot-worthy artifact (the table) is at
slide **2**, not at the end. The bet is that a saved post is one whose *proof*
was worth returning to, and that front-loading it is what buys slides 3–10.

## Seven mechanics worth stealing

1. **Zero hashtags.** 18 of 18 recent posts. No hashtags, no link-in-bio push,
   no "double tap if…".
2. **1440×1800**, not 1080×1350 — the same 4:5 shape uploaded at 1.33× so text
   stays crisp after Instagram's re-encode.
3. **Fixed chrome.** Brand mark top-left on every slide; headline block in the
   top ~35%; art in the bottom ~60%; a small grey slot bottom-right used for
   definitions ("(CPSE: Central Public Sector Enterprise)") and scope stamps
   ("For H1, 2026"). Jargon is glossed without breaking the sentence.
4. **One weight, no colour.** Body is regular, the payload words are bold, and
   that is the entire emphasis system. Colour appears only in tables (green/red
   numbers) and on the brand word itself — the single green "Groww" on the pivot
   slide is the only branded colour in a 7-slide post.
5. **Highlight the reader's row.** The index table highlights SENSEX in blue;
   the loss table highlights FY26 in red. Whatever row the reader is standing
   in gets painted.
6. **Convert every foreign number into an Indian one.** Samsung's best quarter
   ever isn't "$58B" — it's "nearly 6× Reliance's entire FY26 profit", drawn as
   two bars. This is the single most repeatable trick in the set.
7. **The illustration is a joke about the concept**, drawn from a recurring
   cast: a scientist breaking up with a rocket over dinner, a bureaucrat
   plucking "sell / close" petals, a bear mauling an AI robot. Scenes get
   *re-used with modifications* as callbacks — the space post's slide 2 crowd
   scene returns on slide 7 with question marks and a ghosted rocket. Style
   varies by series (painterly editorial vs flat manga); layout never does.

## The caption is a second post

Three to five short paragraphs, standalone — someone who never swipes still
gets the story. It never repeats the slides verbatim, it carries the sourcing
that wouldn't fit on a frame (the IN-SPACe chairman quote, named), and it ends
on either a question ("Do you know of any government companies that no longer
really work??") or that quote. No hashtags. No link.

## How they sell (barely)

One product moment per post, maximum, and only where the data has already made
the argument: the SEBI post diagnoses overtrading for five slides, pivots on
"That's why we've introduced a few guardrails for F&O traders on **Groww**",
then ends on three named features. That post is also the **lowest performing of
the four** — 2,185 likes against 6,768 for the one with no product at all. The
tax on selling is visible in the numbers, which is presumably why they pay it
about once a week.

## Topic selection

Every one of the four sits on the same seam: **an event the reader has already
seen a headline about, plus exactly one layer they haven't.** Korea crashed →
Samsung alone is ~28% of KOSPI. ISRO is a source of pride → it is trying to stop
manufacturing. Everyone knows traders lose → 35% of F&O traders hold zero equity.
The format is *not* explainer-of-a-concept; it is explainer-of-a-thing-in-the-news.

Cadence from the 18-post scan: roughly one post a day, published 12:50–15:30 UTC
(18:20–21:00 IST); mix is ~50% carousels, ~33% single images (one chart, one
claim), ~17% video. Slide counts run 5–10, median 7–8.

## What they never do

No "you" hooks, no listicles, no advice, no predictions, no CTA slides, no
hashtags, no emojis in slide copy, no photographs, no faces of employees, no
motion, no music, no memes, no urgency. Typos survive to publication (slide 4 of
the space post reads "and HAL - L&T consortium") — production speed is clearly
valued over polish.

## For a gm.markets adaptation

The transferable core, in the order a piece should be built:

1. Pick a story in this week's news that our reader half-knows (a US listing, an
   index move, an RBI/SEBI rule, a tokenisation ruling).
2. Find the one layer underneath it, and check it resolves to a registerable
   figure (`engine/evidence.py put_figure()`).
3. Cover: ≤8 plain words that shouldn't be true. No number, no "you".
4. Slide 2: that figure as a table, with the row our reader stands in
   highlighted, and any jargon glossed bottom-right.
5. Slides 3–6: mechanism → named example → stakes → wider scale.
6. Convert every foreign number into an Indian one the reader can feel.
7. End by widening, or by asking a question we would actually read the answers
   to. Sell at most once, and only where the data has already argued for us.
8. Caption: the whole story again in five short paragraphs, sourced, ending on
   the question. No hashtags.
9. Render 1440×1800, one illustration per slide, brand mark top-left, bold as
   the only emphasis.

**Compliance note for our use:** their SEBI post cites a regulator's own report
and then names products as a remedy. We can cite regulator data the same way,
but every figure needs a ledger row first, and our product framing stays
education-only — no implied outcome, no "counter your losses with X".
