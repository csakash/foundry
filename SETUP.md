# SETUP — dependencies for getting the best out of this repo

Clone → `cp .env.example .env` and fill keys → open Claude Code here → `/foundry`.
Everything below is tiered: the system degrades gracefully, but each dependency
unlocks a lane.

## 1. API keys (`.env` — see `.env.example`)

| Key | Service | Unlocks | Needed for |
|---|---|---|---|
| `APIFY_TOKEN` | Apify | Reel/profile scraping for the inspiration pipeline (`pipeline/analyze_reel.py`) | Stage 0 intake from a reel URL. **Alternative:** connect the Apify MCP instead of a raw key. |
| `ELEVENLABS_API_KEY` | ElevenLabs | Narration TTS; persona voices are locked per account | Stage 4 (produce) for any voiced piece |
| `FAL_KEY` | fal.ai | Image + video generation (Lane C: persona stills, lipsync, AI b-roll) | Stages 3–4. **Alternative/complement:** Higgsfield via its MCP connector (no key in `.env` — authorize the connector in Claude Code). |
| `GOOGLE_API_KEY` | Gemini | Video analysis of scraped reels; **Nano Banana** image generation | Stage 0 deconstruction + Stage 3 keyframes |
| `OPENAI_API_KEY` | OpenAI | ChatGPT image generation (fallback/alternative to Nano Banana) | Stage 3, optional |
| `PEXELS_API_KEY` | Pexels | Stock b-roll fallback | Stage 4, optional |

## 2. Local tools (Homebrew / pip)

| Tool | Install | Used for |
|---|---|---|
| `ffmpeg` | `brew install ffmpeg` | All cutting, assembly, audio mixing |
| `yt-dlp` | `brew install yt-dlp` | Extracting video/audio from Instagram & YouTube (quote clips, inspiration downloads) |
| Python 3 + `.venv` | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (whisper, google-genai, etc.) | The whole `engine/` + `pipeline/` |
| Node.js | `brew install node` | Remotion renders + Playwright captures |
| **Crawl4AI (optional)** | `python3.12 -m venv .venv-crawl && ./.venv-crawl/bin/pip install -U crawl4ai && ./.venv-crawl/bin/crawl4ai-setup` | **Only** for JS-gated pages and roster sweeps in the research layer. The research stage itself is stdlib-only and needs nothing installed. Apache-2.0, local, no API key; wants its own venv (Python 3.10–3.13 + its own Chromium, ~180 MB). |

## 3. Claude Code skills & MCP connectors

| Dependency | Kind | Role |
|---|---|---|
| **foundry suite** (`.claude/skills/foundry*`) | in-repo skills | The production system itself — ships with the repo, zero setup |
| **Official Remotion skill** (`remotion-best-practices`) | skill | Deterministic motion graphics — Lane A (chart replays, listicles, text plates) |
| **Official Playwright skill** | skill | Web demos & captured-evidence automation — Lane B (app walkthroughs, screen proof) |
| **Higgsfield MCP** | MCP connector | Generative video (Lane C) — authorize in Claude Code session |
| **Apify MCP** | MCP connector | Scraping without managing a raw token (either this OR `APIFY_TOKEN`) |

### Skill packs (installed by default, not optional)

The foundry borrows its writing, offer and channel craft from three public skill
repos. They ship with the install — `engine/skill_packs.json` is the manifest,
and the foundry router loads named skills from them at named stages.

| Pack | Repo | Role |
|---|---|---|
| **no-ai-slop** | [petergyang/no-ai-slop](https://github.com/petergyang/no-ai-slop) | The human-editor lint over every word a human reads — hooks, VO, on-frame text, carousel slides, captions |
| **hormozi** | [alexsmedile/hormozi-skills](https://github.com/alexsmedile/hormozi-skills) | Offer / hook / objection craft (`hormozi-hooks`, `offer-angles`, `objection-destroyer`, `value-perception`, …) |
| **marketing** | [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) | Channel + campaign craft (`social`, `copywriting`, `ad-creative`, `content-strategy`, `analytics`, …) |

```bash
python3 -m engine.skillpacks check      # what's available, what's owed
python3 -m engine.skillpacks install    # fetch only what's missing -> .claude/skills/
python3 -m engine.skillpacks install --global   # -> ~/.claude/skills/ instead
```

Install skips anything the machine already has (project or `~/.claude/skills`),
so re-running is cheap. Never edit a pack skill in place — `/foundry upgrade`
re-copies it from upstream.

## 4. Verify

Run `/foundry doctor` (or ask Claude to check): it should confirm ffmpeg, yt-dlp,
the research layer (`python3 -m engine.research news "test"` — no key needed),
the venv, each `.env` key, the skill packs (`python3 -m engine.skillpacks check`),
and which MCP connectors are live — and print exactly
what's missing and what that lane degrades to.
