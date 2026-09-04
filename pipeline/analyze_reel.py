#!/usr/bin/env python3
"""Inspiration pipeline (L4): Instagram reel(s) -> format-template JSON.

Usage:
  analyze_reel.py <reel_url> [<reel_url> ...]        # specific reels
  analyze_reel.py @<username> [n]                    # a creator's n latest reels (default 3)

Requires env: APIFY_TOKEN, GOOGLE_API_KEY. Whisper via ./.venv (faster-whisper).
Requires binaries: ffmpeg/ffprobe, and ./.venv/bin/yt-dlp for the audio-recovery fallback.

HARD REQUIREMENT: a template is never written from a video with no audio track. Apify can
hand back a video-only DASH representation, after which whisper silently returns 0 segments
and the Gemini pass analyses the reel deaf. Every download is probed for an audio stream and
re-fetched via yt-dlp when one is missing; a reel that still has no audio is SKIPPED, loudly,
and the run exits non-zero. Deaf templates are worse than no template.
Outputs: templates/<shortCode>.json (+ raw video in templates/raw/).
"""
import base64, json, os, re, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TDIR = os.path.join(ROOT, "templates")
RAW = os.path.join(TDIR, "raw")
os.makedirs(RAW, exist_ok=True)
APIFY = os.environ["APIFY_TOKEN"]
GKEY = os.environ["GOOGLE_API_KEY"]
GMODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

def http_json(url, payload=None, timeout=300):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data,
        headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

# ---------- 1. Apify fetch ----------
def fetch_items(args):
    if args[0].startswith("@"):
        n = int(args[1]) if len(args) > 1 else 3
        actor, inp = "apify~instagram-reel-scraper", {"username": [args[0][1:]], "resultsLimit": n}
    else:
        actor, inp = "apify~instagram-scraper", {"directUrls": args, "resultsType": "posts",
                                                 "resultsLimit": len(args), "addParentData": False}
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={APIFY}&timeout=240"
    items = http_json(url, inp, timeout=300)
    good = [i for i in items if not i.get("error") and i.get("videoUrl")]
    bad = [i for i in items if i.get("error") or not i.get("videoUrl")]
    for b in bad:
        print(f"  !! skipped {b.get('url','?')}: {b.get('errorDescription', b.get('error','no videoUrl'))}")
    return good

# ---------- 2. local decomposition ----------
def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
        f.write(r.read())

def has_audio(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip()
    return bool(out)

def ytdlp_fetch(url, path):
    """Fallback when Apify returns a video-only DASH stream: pull a muxed copy."""
    ytdlp = os.path.join(ROOT, ".venv", "bin", "yt-dlp")
    if not os.path.exists(ytdlp):
        print("  !! .venv/bin/yt-dlp missing - cannot recover audio")
        return False
    tmp = path + ".ytdlp.mp4"
    r = subprocess.run([ytdlp, "-f", "bv*+ba/b", "--merge-output-format", "mp4",
                        "--force-overwrites", "-o", tmp, url],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(tmp):
        print(f"  !! yt-dlp failed: {(r.stderr or r.stdout).strip().splitlines()[-1:]}")
        return False
    os.replace(tmp, path)
    return True

def ensure_audio(sc, url, vpath):
    """Probe for an audio stream; recover via yt-dlp if Apify gave us a deaf copy."""
    if has_audio(vpath):
        return "apify"
    print(f"[{sc}] !! no audio stream (Apify DASH video-only) - refetching via yt-dlp...")
    if ytdlp_fetch(url, vpath) and has_audio(vpath):
        print(f"[{sc}] audio recovered via yt-dlp")
        return "yt-dlp"
    return None

def scene_cuts(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-f", "lavfi",
        f"movie={path},select=gt(scene\\,0.25)", "-show_entries", "frame=pts_time",
        "-of", "csv=p=0"], capture_output=True, text=True).stdout
    return [round(float(t), 2) for t in out.split() if t.strip()]

def transcribe(path):
    venv_py = os.path.join(ROOT, ".venv", "bin", "python")
    code = ("import json,sys\nfrom faster_whisper import WhisperModel\n"
            "m=WhisperModel('small',device='cpu',compute_type='int8')\n"
            "segs,info=m.transcribe(sys.argv[1],word_timestamps=False)\n"
            "out=[[round(s.start,2),round(s.end,2),s.text.strip()] for s in segs]\n"
            "print(json.dumps({'language':info.language,'segments':out}))")
    r = subprocess.run([venv_py, "-c", code, path], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else {"language": "?", "segments": []}

# ---------- 3. Gemini video analysis ----------
PROMPT = """You are a short-form video format analyst for a content studio.
You are given an Instagram reel (video), its caption, engagement metrics, machine-detected
cut timestamps, and an ASR transcript. Produce a REUSABLE FORMAT TEMPLATE as JSON.

Rules:
- Describe structure, never copy expression: hook as an ARCHETYPE with a {{placeholder}} template,
  script skeleton with placeholders only, generic subject roles. Zero verbatim sentences.
- HARD RULE: never reproduce any dialogue line from the video, even partially. Every
  script_skeleton line must be a generic PARAPHRASE of the beat's function with {{placeholders}}
  (e.g. "{{character_a}} teases {{character_b}} about {{trait}}"), never the actual words spoken.
- Time everything in seconds from the actual video.
- similar_ideas must be EDUCATIONAL finance ideas for GM Markets (tokenized US stocks for global
  investors): no stock picks, no return promises, no urgency/FOMO, no "guaranteed"; concepts only.

Return ONLY JSON with this exact shape:
{
 "concept": "<1-2 sentences: what the video IS as an idea>",
 "direction": "<2-3 sentences: how it is directed - energy, camera, cuts, on-screen elements>",
 "why_it_works": ["<retention/share mechanic>", "..."],
 "hook": {"type": "<archetype>", "window_s": [0, 0], "delivery": "<spoken|text_plate|visual|combo>",
          "template": "<{{placeholder}} version>"},
 "beats": [{"beat": "<hook|setup|escalation|proof|payoff|cta>", "t": [0, 0], "summary": "<generic>"}],
 "visual_flow": [{"t": [0, 0], "framing": "<closeup|medium|wide|screen_rec|broll|text_plate>",
                  "action": "<generic subject action>", "overlay": "<none|caption|plate|graphic>"}],
 "pacing": {"cut_count": 0, "avg_shot_s": 0, "energy": "<low|medium|high|variable>"},
 "captions": {"style": "<karaoke_word|phrase_block|static_plate|none>", "position": "<top|center|lower>"},
 "audio": {"bed": "<voiceover|trending_sound|both|dialogue>", "language": "<detected>"},
 "script_skeleton": [{"beat": "<name>", "template": "<{{placeholder}} line>"}],
 "similar_ideas": [{"title": "<idea>", "premise": "<1 line>", "format": "<talking_head|faceless|screen_share>"}]
}"""

def gemini_analyze(video_path, meta, cuts, tr):
    size = os.path.getsize(video_path)
    ctx = (f"CAPTION: {meta.get('caption','')[:800]}\n"
           f"METRICS: plays={meta.get('videoPlayCount')} likes={meta.get('likesCount')} "
           f"comments={meta.get('commentsCount')} duration={meta.get('videoDuration')}s\n"
           f"CUT TIMESTAMPS (s): {cuts}\n"
           f"ASR ({tr.get('language')}): " + " | ".join(f"[{s[0]}-{s[1]}] {s[2]}" for s in tr.get("segments", [])[:60]))
    if size <= 15_000_000:
        video_part = {"inline_data": {"mime_type": "video/mp4",
                      "data": base64.b64encode(open(video_path, "rb").read()).decode()}}
    else:  # Files API for big reels
        up = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={GKEY}",
            data=open(video_path, "rb").read(),
            headers={"Content-Type": "video/mp4", "X-Goog-Upload-Protocol": "raw"})
        f = json.load(urllib.request.urlopen(up, timeout=300))["file"]
        while f.get("state") == "PROCESSING":
            time.sleep(4)
            f = http_json(f"https://generativelanguage.googleapis.com/v1beta/{f['name']}?key={GKEY}")
        video_part = {"file_data": {"mime_type": "video/mp4", "file_uri": f["uri"]}}
    payload = {"contents": [{"parts": [video_part, {"text": PROMPT + "\n\n" + ctx}]}],
               "generationConfig": {"response_mime_type": "application/json", "temperature": 0.4}}
    resp = http_json(f"https://generativelanguage.googleapis.com/v1beta/models/{GMODEL}:generateContent?key={GKEY}",
                     payload, timeout=600)
    txt = resp["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(txt)

# ---------- main ----------
def main():
    items = fetch_items(sys.argv[1:])
    print(f"fetched {len(items)} reel(s) via Apify")
    failed = []
    for it in items:
        sc = it.get("shortCode") or re.sub(r"\W", "", it.get("url", ""))[-11:]
        vpath = os.path.join(RAW, f"{sc}.mp4")
        if not os.path.exists(vpath):
            print(f"[{sc}] downloading video...")
            download(it["videoUrl"], vpath)
        audio_source = ensure_audio(sc, it.get("url"), vpath)
        if audio_source is None:
            print(f"[{sc}] SKIPPED: no audio track recoverable - refusing to write a deaf template")
            failed.append(sc)
            continue
        print(f"[{sc}] scene cuts + transcript...")
        cuts = scene_cuts(vpath)
        tr = transcribe(vpath)
        print(f"[{sc}] {len(cuts)} cuts, {len(tr['segments'])} ASR segments ({tr['language']}); Gemini analysis...")
        spec = gemini_analyze(vpath, it, cuts, tr)
        out = {
            "spec_version": "format-template/1.1",
            "provenance": {
                "source_url": it.get("url"), "short_code": sc,
                "owner": it.get("ownerUsername"), "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "metrics": {k: it.get(k) for k in
                            ["videoPlayCount", "likesCount", "commentsCount", "videoDuration", "timestamp"]},
                "caption": (it.get("caption") or "")[:1000],
                "asr_language": tr.get("language"), "cut_timestamps": cuts,
                "audio_source": audio_source,
            },
            "transcript": tr.get("segments"),
            "format": spec,
        }
        path = os.path.join(TDIR, f"{sc}.json")
        json.dump(out, open(path, "w"), indent=1, ensure_ascii=False)
        print(f"[{sc}] -> templates/{sc}.json | concept: {spec.get('concept','')[:110]}")
    if failed:
        sys.exit(f"FAILED (no recoverable audio): {', '.join(failed)}")

if __name__ == "__main__":
    main()
