#!/usr/bin/env python3
"""Inspiration pipeline (L4), carousel branch: Instagram image post(s) -> template JSON.

The reel analyzer (`analyze_reel.py`) filters to items with a `videoUrl`, so every
carousel it is handed is silently dropped. Carousels are decomposed here instead:
Apify -> slide images on disk -> a template that records the swipe, the caption and
the engagement, so a carousel reference is judged from the actual slides rather
than from memory of scrolling past it (router rule 9).

Usage:
  analyze_carousel.py <post_url> [<post_url> ...]
  analyze_carousel.py @<username> [n]          # n latest posts (default 6)

Requires env: APIFY_TOKEN. Outputs: templates/<shortCode>.json + slides in
templates/raw/<shortCode>/NN.jpg (downscaled copies alongside, for reading).

HARD REQUIREMENT, mirroring the reel rule: a template is never written from a post
whose slides did not download. A carousel analysed from its cover alone is the
image-post equivalent of a deaf template — the swipe IS the artifact.
"""
import json, os, subprocess, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TDIR = os.path.join(ROOT, "templates")
RAW = os.path.join(TDIR, "raw")
APIFY = os.environ.get("APIFY_TOKEN")   # only the scrape needs it; re-reads work offline
UA = {"User-Agent": "Mozilla/5.0"}


def http_json(url, payload=None, timeout=300):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data,
        headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_items(args):
    if not APIFY:
        raise SystemExit("APIFY_TOKEN not set — needed to scrape (not to re-read a template)")
    if args[0].startswith("@"):
        n = int(args[1]) if len(args) > 1 else 6
        inp = {"directUrls": [f"https://www.instagram.com/{args[0][1:]}/"],
               "resultsType": "posts", "resultsLimit": n, "addParentData": False}
    else:
        inp = {"directUrls": args, "resultsType": "posts",
               "resultsLimit": len(args), "addParentData": False}
    url = (f"https://api.apify.com/v2/acts/apify~instagram-scraper/"
           f"run-sync-get-dataset-items?token={APIFY}&timeout=240")
    items = http_json(url, inp, timeout=300)
    good, bad = [], []
    for i in items:
        (good if i.get("type") in ("Sidecar", "Image") and not i.get("error") else bad).append(i)
    for b in bad:
        print(f"  !! skipped {b.get('url','?')}: {b.get('errorDescription') or b.get('type') or 'not an image post'}")
    return good


def slide_urls(item):
    """Sidecar children first (full resolution per slide), else the single image."""
    kids = item.get("childPosts") or []
    urls = [k.get("displayUrl") for k in kids if k.get("displayUrl")]
    return urls or [u for u in (item.get("images") or []) if u] or [item["displayUrl"]]


def download(url, path):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
        open(path, "wb").write(r.read())


def thumb(src, dst, width=720):
    """A readable copy: slide text has to survive the downscale or it isn't evidence."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", f"scale={width}:-1",
                    "-q:v", "3", dst], check=False)


def analyse(item):
    code = item["shortCode"]
    outdir = os.path.join(RAW, code)
    os.makedirs(outdir, exist_ok=True)
    urls = slide_urls(item)
    slides = []
    for n, u in enumerate(urls, 1):
        p = os.path.join(outdir, f"{n:02d}.jpg")
        t = os.path.join(outdir, f"{n:02d}.sm.jpg")
        try:
            download(u, p)
            thumb(p, t)
        except Exception as e:                                     # noqa: BLE001
            print(f"  !! slide {n} of {code} failed: {e}")
            continue
        slides.append({"n": n, "file": os.path.relpath(p, ROOT),
                       "small": os.path.relpath(t, ROOT) if os.path.exists(t) else None})
    if len(slides) != len(urls):
        raise SystemExit(f"{code}: {len(slides)}/{len(urls)} slides downloaded — "
                         f"refusing to write a partial template")
    likes = item.get("likesCount") or 0
    tpl = {
        "kind": "carousel",
        "shortCode": code,
        "url": item.get("url"),
        "account": item.get("ownerUsername"),
        "posted_at": item.get("timestamp"),
        "slide_count": len(slides),
        "dimensions": {"w": item.get("dimensionsWidth"), "h": item.get("dimensionsHeight")},
        "engagement": {"likes": likes, "comments": item.get("commentsCount") or 0,
                       "comment_ratio": round((item.get("commentsCount") or 0) / likes, 4) if likes else None},
        "caption": item.get("caption"),
        "hashtags": item.get("hashtags") or [],
        "mentions": item.get("mentions") or [],
        "alt": item.get("alt"),
        "slides": slides,
        "provenance": {"source": "apify~instagram-scraper", "slides_downloaded": len(slides)},
        # Filled in by whoever reads the slides — the analysis is not the scrape.
        "read": {"roles": None, "headline_ladder": None, "keeper": None, "notes": None},
    }
    path = os.path.join(TDIR, f"{code}.json")
    json.dump(tpl, open(path, "w"), indent=1, ensure_ascii=False)
    print(f"-> {os.path.relpath(path, ROOT)}  ({len(slides)} slides, "
          f"{likes} likes, {tpl['engagement']['comments']} comments)")
    return tpl


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    os.makedirs(RAW, exist_ok=True)
    items = fetch_items(args)
    if not items:
        raise SystemExit("no image posts returned")
    for it in items:
        analyse(it)


if __name__ == "__main__":
    main()
