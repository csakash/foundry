"""The research layer (L0): a topic in, a sourced dossier and a plain story out.

There is no search API here, and no paid one either. Discovery is whatever
already knows how to search — in order of preference:

1. **The agent's own web search.** Claude has one; it returns real publisher
   URLs. Search, pick, then `research fetch <url>` to read and cache them.
2. **A URL the user handed over.** Same path.
3. **`research news <topic>`** — a free, dated headline map from Google News RSS
   (no key, no browser). It tells you who covered the story, when, and with what
   framing. The links are Google redirects that only open in a browser, so treat
   it as a map, not a list of URLs: take the headline and the publisher, then get
   the real article.
4. **`research seed`** — optional sweep of trusted domains (sitemaps + Common
   Crawl, BM25-scored) when Crawl4AI is installed. Good for "what does this
   regulator say about X", weak for "what happened this week".

Reading is HTTP-first: plain stdlib fetch plus a small HTML-to-text pass, which
handles most news and .gov pages with zero dependencies. Anything that comes
back too thin to be a page falls back to a headless browser via Crawl4AI
(Apache-2.0) **if it happens to be installed** — never required.

The artifact is `00-research.json` in the piece's work dir:

    queries[]        every discovery run, with its parameters
    sources[]        one row per URL, tiered, with the page text cached
    findings[]       claims / figures / questions, each with a VERBATIM quote
    candidate_seeds  which findings could seed a piece, and as what
    story            the whole thing told in plain words - Gate 0
    gate             the human's verdict on that story

The rule that makes this trustworthy: **a finding's quote must appear verbatim
in the cached page**. `check` re-reads the cache and fails any finding whose
quote it cannot find, so a fabricated figure cannot reach a brief, let alone a
slide.

    python3 -m engine.research news "SEBI F&O losses FY26"
    python3 -m engine.research fetch work/@handle/slug https://... https://...
    python3 -m engine.research finding work/@handle/slug --kind figure \\
        --text "Retail F&O losses hit Rs 91,685 crore in FY26" --quote "..." --url https://...
    python3 -m engine.research story work/@handle/slug --text "..."
    python3 -m engine.research check work/@handle/slug

Everything above runs on the repo's own interpreter. `seed`, and the browser
fallback inside `fetch`, additionally want Crawl4AI (`./.venv-crawl`, SETUP.md) —
optional extras, not dependencies.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html as html_mod
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import evidence

ROOT = evidence.ROOT
CACHE = Path(__file__).resolve().parent / "cache" / "research"
ROSTER = Path(__file__).resolve().parent / "research_sources.json"

# Fallback tiering for URLs that are not on the roster — a company's own investor
# page or a government host is primary wherever it turns up.
PRIMARY_PAT = re.compile(
    r"(\.gov(\.[a-z]{2})?$|\.gov\.|\.nic\.in$|europa\.eu$|/investor-relations|/investors?/|"
    r"^investor\.|\.sec\.gov$)", re.I)

STORY_MAX_WORDS = 120
STORY_BANNED = ("game-changer", "revolutionize", "revolutionise", "unlock", "leverage",
                "in today's", "dive into", "deep dive", "landscape", "ecosystem play",
                "seamless", "cutting-edge", "paradigm")

CRAWL4AI_HINT = ("crawl4ai is not importable by this interpreter.\n"
                 "  Crawling runs in its own venv:  ./.venv-crawl/bin/python -m engine.research ...\n"
                 "  Create it with:  python3.12 -m venv .venv-crawl && ./.venv-crawl/bin/pip install -U crawl4ai "
                 "&& ./.venv-crawl/bin/crawl4ai-setup")


def _c4a():
    try:
        import crawl4ai  # noqa: F401
        from crawl4ai import (AsyncUrlSeeder, AsyncWebCrawler, BrowserConfig,  # noqa: F401
                              CrawlerRunConfig, SeedingConfig)
    except ImportError:
        raise SystemExit(CRAWL4AI_HINT) from None
    return AsyncUrlSeeder, AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, SeedingConfig


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def roster(tier: str | None = None, beat: str | None = None) -> list[dict[str, Any]]:
    """The domains we are willing to seed from, as data."""
    doc = json.loads(ROSTER.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for t in ("primary", "secondary"):
        if tier and tier != t:
            continue
        for row in doc[t]:
            if beat and beat not in (row.get("beats") or []):
                continue
            rows.append(dict(row, tier=t))
    return rows


def tier_of(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    for row in roster():
        d = row["domain"].lower()
        if host == d or host.endswith("." + d):
            return row["tier"]
    if PRIMARY_PAT.search(host) or PRIMARY_PAT.search(url):
        return "primary"
    return "tertiary"


def cache_path(url: str) -> Path:
    return CACHE / f"{hashlib.sha1(url.encode()).hexdigest()}.md"


# ------------------------------------------------------------------ crawl4ai

async def _seed(query: str, domains: list[str], *, per_domain: int, score_threshold: float,
                source: str, live_check: bool, timeout: int = 60) -> list[dict[str, Any]]:
    """Seed domain by domain, with a per-domain timeout.

    Some hosts have no sitemap, some have a 40 MB index, and Common Crawl shards
    are slow. One bad host must not hang the stage: a domain that overruns is
    skipped loudly and the sweep keeps its other candidates.
    """
    AsyncUrlSeeder, _, _, _, SeedingConfig = _c4a()
    cfg = SeedingConfig(source=source, extract_head=True, query=query,
                        scoring_method="bm25", score_threshold=score_threshold,
                        max_urls=per_domain, live_check=live_check, filter_nonsense_urls=True,
                        concurrency=10, hits_per_sec=5, verbose=False)
    found: dict[str, Any] = {}
    async with AsyncUrlSeeder() as seeder:
        for d in domains:
            try:
                found[d] = await asyncio.wait_for(seeder.urls(d, cfg), timeout=timeout)
            except asyncio.TimeoutError:
                print(f"    .. {d}: no answer in {timeout}s — skipped", file=sys.stderr)
            except Exception as e:                                        # noqa: BLE001
                print(f"    .. {d}: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
    rows: list[dict[str, Any]] = []
    for domain, urls in (found or {}).items():
        for u in urls or []:
            head = u.get("head_data") or {}
            meta = head.get("meta") or {}
            rows.append({
                "url": u["url"],
                "title": head.get("title"),
                "publisher": domain,
                "date": meta.get("article:published_time") or meta.get("publishedTime"),
                "snippet": meta.get("description"),
                "result_kind": "seed",
                "relevance": round(u.get("relevance_score") or 0, 4),
                "live": u.get("status"),
                "tier": tier_of(u["url"]),
                "cache": None,
                "retrieved_at": now(),
            })
    # sitemap and CC routinely surface the same URL twice — keep the better score.
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        cur = best.get(r["url"])
        if cur is None or (r["relevance"] or 0) > (cur["relevance"] or 0):
            best[r["url"]] = r
    rows = sorted(best.values(), key=lambda r: r["relevance"], reverse=True)
    return rows


MIN_TEXT = 600          # below this a page is assumed JS-gated, and the browser is tried
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/120 Safari/537.36"),
      "Accept-Language": "en-IN,en;q=0.9"}


def html_to_text(doc: str) -> str:
    """Good-enough readable text, stdlib only. Most news and .gov pages are server-rendered."""
    doc = re.sub(r"(?is)<(script|style|noscript|svg|head|nav|footer|form)[^>]*>.*?</\1>", " ", doc)
    doc = re.sub(r"(?is)<!--.*?-->", " ", doc)
    doc = re.sub(r"(?i)<(br|/p|/div|/li|/h[1-6]|/tr)[^>]*>", "\n", doc)
    doc = re.sub(r"(?s)<[^>]+>", " ", doc)
    doc = html_mod.unescape(doc)
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in doc.split("\n")]
    return "\n".join(ln for ln in lines if len(ln) > 2)


def http_get(url: str, timeout: int = 30) -> tuple[str, str, int]:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), r.read().decode("utf-8", "ignore"), r.getcode()


def _browser_fetch(urls: list[str]) -> dict[str, str]:
    """Optional fallback for JS-gated pages. Uses Crawl4AI if this interpreter has it."""
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    except ImportError:
        return {}

    async def run() -> dict[str, str]:
        out: dict[str, str] = {}
        cfg = CrawlerRunConfig(page_timeout=45000)
        async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False)) as c:
            results = await c.arun_many(urls, config=cfg)
            if hasattr(results, "__aiter__"):
                results = [r async for r in results]
            for r in results:
                md = getattr(getattr(r, "markdown", None), "raw_markdown", None) or ""
                if getattr(r, "success", False) and md.strip():
                    out[r.url] = md
        return out

    return asyncio.run(run())


def fetch(urls: list[str], *, browser: bool | None = None) -> list[dict[str, Any]]:
    """Read pages into the cache. Plain HTTP first; the browser only where it must.

    `browser=None` means auto: try HTTP, and fall back to Crawl4AI for anything
    that came back too thin to be a page. `browser=True` forces the browser,
    `browser=False` forbids it (and reports the thin pages as failures).
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    thin: list[str] = []
    for u in urls:
        if browser is True:
            thin.append(u)
            out.append({"url": u, "ok": False, "cache": None, "chars": 0,
                        "via": "browser", "title": None, "error": None})
            continue
        try:
            final, body, code = http_get(u)
            text = html_to_text(body)
            title = (re.search(r"(?is)<title[^>]*>(.*?)</title>", body) or [None, None])[1]
            row = {"url": u, "final_url": final, "ok": False, "cache": None,
                   "chars": len(text), "via": "http",
                   "title": html_mod.unescape(title).strip() if title else None, "error": None}
            if len(text) >= MIN_TEXT:
                pth = cache_path(u)
                pth.write_text(text, encoding="utf-8")
                row.update(ok=True, cache=str(pth.relative_to(ROOT)))
            else:
                row["error"] = f"only {len(text)} chars of text (HTTP {code})"
                thin.append(u)
            out.append(row)
        except Exception as e:                                          # noqa: BLE001
            out.append({"url": u, "ok": False, "cache": None, "chars": 0, "via": "http",
                        "title": None, "error": f"{type(e).__name__}: {str(e)[:120]}"})
            thin.append(u)

    if thin and browser is not False:
        got = _browser_fetch(thin)
        if not got and browser is True:
            print(CRAWL4AI_HINT, file=sys.stderr)
        for row in out:
            md = got.get(row["url"])
            if not md:
                continue
            pth = cache_path(row["url"])
            pth.write_text(md, encoding="utf-8")
            row.update(ok=True, cache=str(pth.relative_to(ROOT)), chars=len(md),
                       via="browser", error=None)
    return out


def news(query: str, *, hl: str = "en-IN", gl: str = "IN", limit: int = 20) -> list[dict[str, Any]]:
    """A free, dated map of who wrote about this and when — Google News RSS, no key.

    Note what this is and is not: the `link` on each item is a Google redirect
    that only resolves in a real browser, so this is a **headline map**, not a
    list of fetchable URLs. Use it to see the shape of the coverage — which
    publishers, which days, which framing — then get the real article by
    searching for that headline, or by going to the publisher named here.
    """
    u = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": hl, "gl": gl, "ceid": f"{gl}:{hl.split('-')[0]}"})
    _, body, _ = http_get(u)
    rows: list[dict[str, Any]] = []
    for block in re.findall(r"<item>(.*?)</item>", body, re.S)[:limit]:
        def tag(name: str) -> str | None:
            m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.S)
            if not m:
                return None
            return html_mod.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))).strip()
        src = re.search(r'<source url="([^"]+)"[^>]*>(.*?)</source>', block, re.S)
        pub_url = src.group(1) if src else None
        rows.append({"title": tag("title"), "date": tag("pubDate"),
                     "publisher": (src.group(2).strip() if src else None),
                     "publisher_url": pub_url,
                     "tier": tier_of(pub_url) if pub_url else "tertiary",
                     "google_link": tag("link")})
    return rows


def seed(query: str, *, tier: str | None = None, beat: str | None = None,
         domains: list[str] | None = None, per_domain: int = 5,
         score_threshold: float = 0.3, source: str = "sitemap+cc",
         live_check: bool = False, timeout: int = 60) -> dict[str, Any]:
    doms = domains or [r["domain"] for r in roster(tier, beat)]
    if len(doms) > 6:
        print(f"  note: seeding {len(doms)} domains — narrow with --beat/--domain if this drags",
              file=sys.stderr)
    rows = asyncio.run(_seed(query, doms, per_domain=per_domain,
                             score_threshold=score_threshold, source=source,
                             live_check=live_check, timeout=timeout))
    return {"query": query, "params": {"domains": len(doms), "tier": tier, "beat": beat,
                                       "per_domain": per_domain, "source": source,
                                       "score_threshold": score_threshold},
            "ran_at": now(), "results": rows}




# ------------------------------------------------------------------ dossier

def load(work_dir: Path) -> dict[str, Any]:
    p = work_dir / "00-research.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {
        "spec_version": "research/1.0",
        "slug": work_dir.name,
        "account": work_dir.parent.name if work_dir.parent.name.startswith("@") else None,
        "topic": None,
        "created": now(),
        "queries": [], "sources": [], "findings": [], "candidate_seeds": [],
        "story": {"text": None, "words": 0, "written_at": None},
        "gate": {"n": 0, "question": "Is this a story worth telling?",
                 "status": "not reached", "note": None},
    }


def save(work_dir: Path, doc: dict[str, Any]) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    p = work_dir / "00-research.json"
    p.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return p


def sweep(work_dir: Path, topic: str, queries: list[str], *, fetch_top: int = 0,
          **kw: Any) -> dict[str, Any]:
    """Seed candidate URLs for each query, record them, then crawl the top N."""
    doc = load(work_dir)
    doc["topic"] = topic or doc.get("topic")
    seen = {s["url"] for s in doc["sources"]}
    fresh: list[dict[str, Any]] = []
    for q in queries:
        run = seed(q, **kw)
        doc["queries"].append({k: run[k] for k in ("query", "params", "ran_at")}
                              | {"n_results": len(run["results"])})
        added = 0
        for row in run["results"]:
            if row["url"] in seen:
                continue
            row["id"] = f"s{len(doc['sources']) + 1}"
            doc["sources"].append(row)
            fresh.append(row)
            seen.add(row["url"])
            added += 1
        print(f"  {q!r}: {len(run['results'])} candidates, +{added} new")
    save(work_dir, doc)

    if fetch_top and fresh:
        shortlist = sorted(fresh, key=lambda r: r.get("relevance") or 0, reverse=True)[:fetch_top]
        print(f"  crawling the top {len(shortlist)} by relevance…")
        by_url = {s["url"]: s for s in doc["sources"]}
        for got in fetch([r["url"] for r in shortlist]):
            row = by_url.get(got["url"])
            if row is None:
                continue
            row["cache"] = got["cache"]
            row["title"] = row.get("title") or got.get("title")
            row["crawl_error"] = got.get("error")
            print(f"    {'ok ' if got['ok'] else 'FAIL'} {got['chars']:>7} chars  {got['url']}")
        save(work_dir, doc)
    return doc


def add_finding(work_dir: Path, kind: str, text: str, quote: str, url: str,
                note: str | None = None) -> dict[str, Any]:
    doc = load(work_dir)
    src = next((s for s in doc["sources"] if s["url"] == url), None)
    if src is None:
        src = {"id": f"s{len(doc['sources']) + 1}", "url": url, "title": None,
               "publisher": urllib.parse.urlparse(url).netloc, "date": None,
               "snippet": None, "result_kind": "manual", "tier": tier_of(url),
               "cache": str(cache_path(url).relative_to(ROOT)) if cache_path(url).exists() else None,
               "retrieved_at": now()}
        doc["sources"].append(src)
    f = {"id": f"f{len(doc['findings']) + 1}", "kind": kind, "text": text,
         "quote": quote, "source": src["id"], "tier": src["tier"],
         "evidence_id": None, "note": note, "added_at": now()}
    doc["findings"].append(f)
    save(work_dir, doc)
    return f


def set_story(work_dir: Path, text: str) -> dict[str, Any]:
    doc = load(work_dir)
    doc["story"] = {"text": text.strip(), "words": len(text.split()), "written_at": now()}
    doc["gate"]["status"] = "awaiting"
    save(work_dir, doc)
    return doc["story"]


# ------------------------------------------------------------------ the lint

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").replace("’", "'").replace("—", "-").strip().lower()


def check(work_dir: Path) -> tuple[list[str], list[str]]:
    doc = load(work_dir)
    fails: list[str] = []
    owed: list[str] = []
    by_id = {s["id"]: s for s in doc["sources"]}

    if not doc["sources"]:
        owed.append("no sources yet — run a sweep")
    if not doc["findings"]:
        owed.append("no findings yet — a dossier with sources but no findings is a reading list")

    for f in doc["findings"]:
        src = by_id.get(f.get("source"))
        if not src:
            fails.append(f"{f['id']}: cites source {f.get('source')} which is not in the dossier")
            continue
        if not f.get("quote"):
            fails.append(f"{f['id']}: no verbatim quote — a finding without one is a memory, not a source")
            continue
        cache = src.get("cache")
        if not cache or not (ROOT / cache).exists():
            owed.append(f"{f['id']}: {src['url']} was never scraped — cannot verify the quote")
            continue
        body = _norm((ROOT / cache).read_text(encoding="utf-8", errors="ignore"))
        if _norm(f["quote"]) not in body:
            fails.append(f"{f['id']}: quote does not appear in the scraped page ({src['url']}) — "
                         f"fabricated, paraphrased, or the page changed")
        if f["kind"] == "figure" and not re.search(r"\d", f.get("text", "")):
            fails.append(f"{f['id']}: kind=figure but the text carries no number")

    cited = {f.get("source") for f in doc["findings"]}
    tiers = [by_id[s]["tier"] for s in cited if s in by_id]
    if doc["findings"] and "primary" not in tiers:
        secondaries = {by_id[s]["publisher"] for s in cited
                       if s in by_id and by_id[s]["tier"] == "secondary"}
        if len(secondaries) < 2:
            fails.append("no primary source, and fewer than two independent secondaries — "
                         "this does not yet support a figure on a slide")

    story = (doc.get("story") or {}).get("text")
    if not story:
        owed.append("story: tell it in plain words before anything is designed (Gate 0)")
    else:
        words = len(story.split())
        if words > STORY_MAX_WORDS:
            fails.append(f"story is {words} words — Gate 0 is {STORY_MAX_WORDS} or fewer; "
                         f"if it cannot be told short it is not clear yet")
        low = story.lower()
        for b in STORY_BANNED:
            if b in low:
                fails.append(f"story uses marketing language ('{b}') — Gate 0 is how you would "
                             f"tell a friend, not how you would sell it")
        sentences = [s for s in re.split(r"[.!?]+", story) if s.strip()]
        if sentences:
            longest = max(len(s.split()) for s in sentences)
            if longest > 28:
                fails.append(f"story has a {longest}-word sentence — plain words means short sentences")
        if doc["gate"]["status"] in ("not reached",):
            owed.append("story written but never put to the human — surface Gate 0")

    return fails, owed


def cmd_check(work_dir: Path) -> int:
    doc = load(work_dir)
    fails, owed = check(work_dir)
    n_src = len(doc["sources"])
    tiers = {}
    for s in doc["sources"]:
        tiers[s["tier"]] = tiers.get(s["tier"], 0) + 1
    print(f"{doc.get('topic') or work_dir.name}: {n_src} sources "
          f"({', '.join(f'{v} {k}' for k, v in sorted(tiers.items())) or 'none'}), "
          f"{len(doc['findings'])} findings, gate {doc['gate']['status']}")
    if fails:
        print("\nfails:")
        for f in fails:
            print(f"  x {f}")
    if owed:
        print("\nstill owed:")
        for o in owed:
            print(f"  ? {o}")
    if not fails and not owed:
        print("\nDossier is sourced, quoted and verifiable, and the story is written. "
              "Put Gate 0 to the human before any brief.")
    return 1 if fails or owed else 0


def cmd_show(work_dir: Path) -> int:
    doc = load(work_dir)
    print(f"topic: {doc.get('topic')}")
    story = (doc.get("story") or {}).get("text")
    if story:
        print(f"\nTHE STORY ({doc['story']['words']} words, gate: {doc['gate']['status']})\n{story}\n")
    for f in doc["findings"]:
        src = next((s for s in doc["sources"] if s["id"] == f["source"]), {})
        print(f"[{f['id']}] {f['kind']:8} {f['text']}")
        print(f"          \"{(f.get('quote') or '')[:110]}\"")
        print(f"          {src.get('tier','?')} · {src.get('publisher','?')} · {src.get('url','?')}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("domains", help="the roster we are willing to seed from")
    d.add_argument("--tier", choices=("primary", "secondary"), default=None)
    d.add_argument("--beat", default=None)

    def seed_args(pr):
        pr.add_argument("--tier", choices=("primary", "secondary"), default=None)
        pr.add_argument("--beat", default=None, help="india_regulator | india_markets | india_policy | us_markets | global_macro | global_markets")
        pr.add_argument("--domain", action="append", dest="domains", default=None,
                        help="seed this domain instead of the roster (repeatable)")
        pr.add_argument("--per-domain", type=int, default=5)
        pr.add_argument("--score", type=float, default=0.3, help="BM25 threshold")
        pr.add_argument("--source", default="sitemap+cc", choices=("sitemap", "cc", "sitemap+cc"))
        pr.add_argument("--live-check", action="store_true")
        pr.add_argument("--timeout", type=int, default=60, help="per-domain seconds before skipping")

    s = sub.add_parser("seed", help="discover candidate URLs for a query (nothing written)")
    s.add_argument("query")
    seed_args(s)

    w = sub.add_parser("sweep", help="seed every query into the dossier, then crawl the best")
    w.add_argument("work_dir")
    w.add_argument("--topic", required=True)
    w.add_argument("-q", "--query", action="append", required=True, dest="queries")
    w.add_argument("--fetch-top", type=int, default=0,
                   help="crawl the N highest-scoring new candidates to markdown")
    seed_args(w)

    n = sub.add_parser("news", help="free headline map for a topic (Google News RSS, no key)")
    n.add_argument("query")
    n.add_argument("--limit", type=int, default=20)
    n.add_argument("--gl", default="IN", help="country bias, e.g. IN / US")
    n.add_argument("--hl", default="en-IN")

    g = sub.add_parser("fetch", help="read explicit URLs into the cache and the dossier")
    g.add_argument("work_dir")
    g.add_argument("urls", nargs="+")
    g.add_argument("--browser", action="store_true", help="force the browser (JS-gated pages)")
    g.add_argument("--no-browser", action="store_true", help="plain HTTP only; never fall back")

    f = sub.add_parser("finding", help="record a claim/figure/question with its verbatim quote")
    f.add_argument("work_dir")
    f.add_argument("--kind", required=True, choices=("claim", "figure", "question", "url"))
    f.add_argument("--text", required=True)
    f.add_argument("--quote", required=True)
    f.add_argument("--url", required=True)
    f.add_argument("--note", default=None)

    st = sub.add_parser("story", help="write the plain-words telling (Gate 0)")
    st.add_argument("work_dir")
    st.add_argument("--text", required=True)

    for name in ("check", "show"):
        c = sub.add_parser(name)
        c.add_argument("work_dir")

    a = ap.parse_args()
    kw = {}
    if a.cmd in ("seed", "sweep"):
        kw = {"tier": a.tier, "beat": a.beat, "domains": a.domains,
              "per_domain": a.per_domain, "score_threshold": a.score,
              "source": a.source, "live_check": a.live_check, "timeout": a.timeout}

    if a.cmd == "domains":
        for r in roster(a.tier, a.beat):
            print(f"{r['tier'][:4]:5} {r['domain']:32} {','.join(r.get('beats') or [])}"
                  f"{'  · ' + r['note'] if r.get('note') else ''}")
    elif a.cmd == "seed":
        run = seed(a.query, **kw)
        for r in run["results"]:
            print(f"[{r['tier'][:4]} {r['relevance']:.2f}] {r['title'] or '(no title)'}\n"
                  f"      {r['url']}")
        print(f"\n{len(run['results'])} candidates for {a.query!r} "
              f"across {run['params']['domains']} domains")
    elif a.cmd == "sweep":
        doc = sweep(Path(a.work_dir), a.topic, a.queries, fetch_top=a.fetch_top, **kw)
        crawled = sum(1 for s in doc["sources"] if s.get("cache"))
        print(f"-> {Path(a.work_dir) / '00-research.json'} "
              f"({len(doc['sources'])} sources, {crawled} crawled)")
    elif a.cmd == "news":
        rows = news(a.query, hl=a.hl, gl=a.gl, limit=a.limit)
        for r in rows:
            print(f"[{r['tier'][:4]}] {(r['date'] or '')[:16]}  {r['publisher'] or '?'}")
            print(f"       {r['title']}")
        print(f"\n{len(rows)} headlines for {a.query!r}. These links are Google redirects — "
              f"take the headline and publisher, get the real URL, then `research fetch` it.")
    elif a.cmd == "fetch":
        wd = Path(a.work_dir)
        doc = load(wd)
        by_url = {s["url"]: s for s in doc["sources"]}
        mode = True if a.browser else (False if a.no_browser else None)
        for got in fetch(a.urls, browser=mode):
            row = by_url.get(got["url"])
            if row is None:
                row = {"id": f"s{len(doc['sources']) + 1}", "url": got["url"],
                       "publisher": urllib.parse.urlparse(got["url"]).netloc,
                       "result_kind": "manual", "tier": tier_of(got["url"]),
                       "date": None, "snippet": None, "retrieved_at": now()}
                doc["sources"].append(row)
            row.update({"cache": got["cache"], "title": row.get("title") or got.get("title"),
                        "via": got.get("via"), "crawl_error": got.get("error")})
            print(f"  {'ok ' if got['ok'] else 'FAIL'} {got['chars']:>7} chars via {got.get('via','?'):7} "
                  f"{got['url'][:80]}" + (f"  ({got['error']})" if got.get("error") else ""))
        save(wd, doc)
    elif a.cmd == "finding":
        fi = add_finding(Path(a.work_dir), a.kind, a.text, a.quote, a.url, a.note)
        print(f"-> {fi['id']} ({fi['tier']})")
    elif a.cmd == "story":
        story = set_story(Path(a.work_dir), a.text)
        print(f"-> story, {story['words']} words. Gate 0 is now awaiting the human.")
    elif a.cmd == "check":
        raise SystemExit(cmd_check(Path(a.work_dir)))
    else:
        raise SystemExit(cmd_show(Path(a.work_dir)))


if __name__ == "__main__":
    main()
