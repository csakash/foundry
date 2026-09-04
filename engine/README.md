# engine/

Production libraries for the content engine. Everything here is deterministic:
same inputs, same bytes out. The model's job is upstream of this directory.

```
engine/
  evidence.py        the ledger — every fact that reaches a frame has a row here
  research.py        the research layer — Crawl4AI seeding + crawling, tiered sources,
                     quote-verified findings, and the plain-words story that is Gate 0
  research_sources.json  the domain roster the seeder is allowed to discover from
  carousel_intake.py the carousel input contract — one seed in, a six-slot fill out
  skillpacks.py      borrowed craft — installs/verifies the three shipped skill packs
  skill_packs.json   the pack manifest (repo, skills, which stages load them)
  marketdata.py      free-tier OHLCV with caching + provenance
  inbox.py           ingest screenshots / screen recordings you hand over
  prompts/           versioned, linted prompt library
  cache/             content-addressed fetch cache (gitignore the payloads)
```

## Quick reference

```bash
# market data — cached, hashed, registered as evidence
python -m engine.marketdata providers
python -m engine.marketdata fetch binance:BTCUSDT --interval 1h --limit 200
python -m engine.marketdata fetch ecb:USD/INR --start 2026-06-01

# assets you want in a specific reel
python -m engine.inbox add ~/Desktop/trade.mov --note "the fill at 0:04" --push
python -m engine.inbox scan --push          # ingest everything in assets/inbox/
python -m engine.inbox list

# research — a bare topic becomes a sourced dossier + the Gate-0 story (free, no keys)
python3 -m engine.research news "SEBI F&O losses FY26"            # dated headline map, no key
python3 -m engine.research fetch work/@handle/slug https://...    # HTTP first, browser only if needed
python3 -m engine.research finding work/@handle/slug --kind figure --text "..." --quote "..." --url https://...
python3 -m engine.research story work/@handle/slug --text "..."   # <= 120 plain words
python3 -m engine.research check work/@handle/slug                # verifies every quote against the cache

# optional, needs Crawl4AI in .venv-crawl: sweep trusted domains by sitemap + Common Crawl
./.venv-crawl/bin/python -m engine.research seed "F&O losses study" --tier primary

# carousel intake — is this input even a carousel?
python3 -m engine.carousel_intake scaffold work/@handle/slug --seed-type url --seed "https://..."
python3 -m engine.carousel_intake check work/@handle/slug

# skill packs — the borrowed craft the foundry ships with
python3 -m engine.skillpacks check
python3 -m engine.skillpacks install [no-ai-slop|hormozi|marketing] [--global] [--force]

# prompts
python -m engine.prompts list
python -m engine.prompts show shot          # the craft guidance, not just the template
python -m engine.prompts build hook --set archetype=negative_frame --set claim="..."
```

## Provider posture

| Provider | Keyless | Verdict |
|---|---|---|
| `binance` | yes | **Use it.** Crypto OHLCV, generous limits, stable. |
| `ecb` | yes | **Use it.** Daily FX reference rates, fully open. |
| `coingecko` | yes | Fine. OHLC only, no volume, 365d on free. |
| `yahoo` | yes | **Dev only.** Rate-limits by IP *and* TLS fingerprint — it 429s httpx while serving curl. Unofficial, no SLA, not cleared for redistribution. |
| `alphavantage` | no | Free key, no card. 5/min, 25/day. |
| `fmp` | no | Free key, no card. 250/day. |
| `gmmarkets` | n/a | **The production source.** You already hold redistribution rights on your own feed. Stub — wire the endpoint. |

The licensing distinction matters more than the rate limits. A published video
showing a price is redistribution. Free tiers are for development and for the
formats where the number is illustrative; anything you publish should come from
`gmmarkets` or a provider whose terms cover it.

## Two invariants

1. **Nothing calls a provider from a render template.** All data goes through
   `marketdata.fetch()`, which caches and registers. A chart rendered today
   renders identically in six months.
2. **A claim without an evidence id fails the build.** `evidence.resolve_all()`
   is the linter's core call. This is the whole reason the ledger exists.
