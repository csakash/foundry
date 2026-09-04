---
name: foundry-research
description: The research craft — turning a bare topic into a sourced dossier and the plain-words story a human approves before anything is designed. Free and keyless: your own web search plus a dated headline map, HTTP-first page reading, source tiering, verbatim-quote findings that are re-verified against the cached page, candidate seeds for the six-slot fill, and Gate 0. Load at /foundry research, whenever the seed is a topic rather than a URL or a claim, and before any brief that cites a number nobody has sourced yet.
---

# Research — find the story before you make anything

The stack's cheapest mistake is the one it used to make first: taking a topic
straight to a brief. A topic is not a story. This stage crawls, reads, sources
and **tells the story in plain words** — and a human says yes or no to that
telling before a single rupee, prompt or slide is spent.

Deterministic half: `engine/research.py` — free, no API key, and no search
service. Judgement half: this skill. Artifact: `00-research.json`, written
before `00-intake.json`.

**You are the search engine.** The single most reliable discovery tool in this
stack is your own web search: it returns real publisher URLs, costs nothing, and
needs no setup. Search, choose the two or three sources that actually matter,
then `research fetch <url>` to read, cache and tier them. Everything else is a
helper around that:

- **`research news "<topic>"`** — a free, dated headline map (Google News RSS,
  no key, no browser). It shows who covered the story, when, and how they framed
  it, tiered by publisher, in about a second. Its links are Google redirects that
  only open in a browser, so use it as a map: take the headline and publisher,
  then find the real article and `fetch` it.
- **`research fetch <urls>`** — reads pages HTTP-first with a stdlib
  HTML-to-text pass (zero dependencies, handles most news and .gov pages) and
  falls back to a headless browser only for JS-gated pages, and only if Crawl4AI
  happens to be installed.
- **`research seed`** — optional. Sweeps the sitemaps and Common Crawl index of
  the roster in `engine/research_sources.json`, BM25-scored. Answers "what does
  this regulator say about X"; weak for "what happened this week", and needs
  Crawl4AI.

The roster is data: a domain worth sweeping belongs in `research_sources.json`
with a tier and a beat, never hard-coded in a query.

## The query ladder

One topic becomes at least four searches, in this order. Never one.

| # | Step | Looking for | How |
|---|---|---|---|
| 0 | **The shape of the coverage** | who wrote about this, when, how they framed it | `research news "<topic>"` — one second, free, dated, tiered |
| 1 | **The event** | what actually happened, and when | search for it yourself, or take the user's URL → `research fetch <work_dir> <url>` |
| 2 | **The primary** | the regulator/ministry/exchange/filing everyone else is quoting | search `<topic> site:sebi.gov.in` (or the relevant host), then `fetch` — this is the one step worth extra effort |
| 3 | **The number** | the one figure that makes it real | usually inside the primary document you just fetched; if not, search for the report itself, `fetch` the PDF page |
| 4 | **The precedent** | the widen slot, and whatever contradicts the story | search `<topic> other countries / earlier / criticism`, `fetch` the best one |

Two or three well-chosen sources beat twenty scraped ones. Read the headline map
first, decide which two publishers and which primary document actually matter,
fetch those, and stop. A dossier of twenty pages nobody quoted from is a bill for
disk, not research.

**Reading is HTTP-first.** Most news and .gov pages come back complete with no
dependencies at all. A page that returns under ~600 characters of text is
JS-gated: `fetch` retries it through a headless browser if Crawl4AI is
installed, and otherwise reports it as thin — go find the same fact somewhere
that renders server-side rather than fighting the page.

**Stop rules.** Stop when (a) the figure traces to a primary source, (b) the
mechanism is stated by someone who would know, (c) one named example is
confirmed, and (d) the last query returned nothing new. Two consecutive empty
queries means the seam is dry — say so and offer a different angle rather than
padding the dossier.

## Source tiers, and the rule that uses them

`engine/research.py` tiers every URL: **primary** (regulator, ministry,
exchange, court, filing, company IR), **secondary** (a named news organisation
with a masthead), **tertiary** (everything else — blogs, aggregators, content
farms, SEO pages).

> A figure that will appear on a slide traces to a **primary** source, or to
> **two independent secondaries**. `check` enforces this.

Tertiary sources are allowed to *point* you somewhere. They are never the
citation. When an aggregator quotes a report, go get the report.

## What a finding is

A finding is a claim, figure, question or URL **plus the verbatim sentence from
the page that supports it**. Not a paraphrase, not a summary, not what you
remember the page saying.

```bash
# crawling runs in the Crawl4AI venv; recording and linting run anywhere
python3 -m engine.research finding work/@handle/slug --kind figure \
  --text "India's space economy is about \$9B, ~2% of the global market" \
  --quote "India's space economy is about \$9 billion today" \
  --url https://pib.gov.in/...
```

`check` re-reads the cached page and **fails any finding whose quote it cannot
find**. This is the anti-hallucination mechanism of the whole stack: a
fabricated figure cannot reach a brief, so it cannot reach a slide. If a quote
fails, the fix is to go back to the page — never to soften the quote until it
matches.

Four kinds, and what each is for downstream:

- `figure` → the **proof** slot. One number, its units, its period, its source.
- `claim` → the **mechanism** slot. How the thing works, said by someone who
  would know.
- `question` → the **open loop**, or the reason for another query.
- `url` → a named **example**, a document to scrape next, or a visual reference.

## The layer test

The dossier's job is not the headline — the reader has already seen the
headline. It is **the one layer underneath it**: Korea crashed → *Samsung alone
is 28% of KOSPI*. ISRO is a point of pride → *it is trying to stop
manufacturing*. Everyone knows traders lose → *35% of F&O traders hold no
equity at all*.

Write `candidate_seeds` explicitly: which finding is the layer, and what it
could become (`carousel` when there is a mechanism and an example under it,
`single image` when there is a great number and nothing under it, `reel` when
the reader has to watch it happen). If nothing in the dossier is a layer, the
honest output is "there is no story here yet" — say it, and offer the two
angles that came closest.

## Gate 0 — the story, in plain words

Before a brief, before a hook, before any post type is chosen, write the whole
thing the way you would tell a friend who does not work in markets:

```bash
python3 -m engine.research story work/@handle/slug --text "..."
```

Rules, all linted:

- **≤120 words**, and no sentence over 28 words. If it cannot be told short, it
  is not understood yet.
- **No marketing language.** "Unlock", "game-changer", "deep dive",
  "landscape", "paradigm" — the lint rejects them, and it is right to.
- **Plain words only.** Jargon gets replaced or explained in the same breath.
- **It contains the surprise**, and it says why it matters to this reader.
- It is **not a structure**. No slide numbers, no roles, no "hook / payoff".
  Those come after the human says yes.

Then surface it — on the review page, in the account's own voice, with the
sources listed underneath — and ask one question: *is this a story worth
telling?* Three answers matter:

- **Yes** → proceed to `00-intake.json` and the six-slot fill; the findings map
  straight onto proof / mechanism / example / widen.
- **Not yet, but close** → the note becomes the next query, not a rewrite of
  the same paragraph in nicer words.
- **No** → drop it. A rejected story at Gate 0 has cost a few search credits.
  The same rejection at Gate 3 has cost a board.

**Never skip ahead.** Producing slides, hooks or thumbnails for a story the
human has not approved is the same violation as skipping a lint — and it is
worse, because the polish makes a weak story harder to kill.

## Anti-patterns

- Researching from memory, or from what a model "knows" about the topic. If it
  is not in a scraped page in the cache, it does not exist.
- Citing the aggregator when the primary is one click away.
- A dossier of twelve sources and no findings — a reading list, not research.
- Stacking three topics because they all came up. One piece = one discovery.
- Writing the hook while researching. The provocation is authored last, from
  what actually resolved (see **foundry-carousel**).
- Letting a stale number pass: every figure carries its period, and anything
  older than the topic's news cycle is flagged, not quietly used.
