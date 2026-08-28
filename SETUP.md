# SETUP — dependencies for getting the best out of the Foundry

The skills are the craft layer and work on their own, but each dependency below
unlocks a production lane. Everything is tiered: the system degrades gracefully,
and `/foundry doctor` tells you exactly what's missing and what that costs you.

Quick start: clone into your project → `cp .env.example .env` and fill keys →
open Claude Code → `/foundry`.

## 1. API keys (`.env` — see `.env.example`)

| Key | Service | Unlocks | Needed for |
|---|---|---|---|
| `APIFY_TOKEN` | [Apify](https://apify.com) | Reel/profile scraping for the inspiration pipeline | Stage 0 intake from a reel URL. **Alternative:** connect the Apify MCP instead of a raw key. |
| `ELEVENLABS_API_KEY` | [ElevenLabs](https://elevenlabs.io) | Narration TTS; locked persona voices | Stage 4 (produce) for any voiced piece |
| `FAL_KEY` | [fal.ai](https://fal.ai) | Image + video generation (Lane C: persona stills, lipsync, AI b-roll) | Stages 3–4. **Alternative/complement:** Higgsfield via its MCP connector (no key in `.env` — authorize the connector in Claude Code). |
| `GOOGLE_API_KEY` | Gemini | Video analysis of scraped reels; **Nano Banana** image generation | Stage 0 deconstruction + Stage 3 keyframes |
| `OPENAI_API_KEY` | OpenAI | ChatGPT image generation (fallback/alternative to Nano Banana) | Stage 3, optional |
| `PEXELS_API_KEY` | [Pexels](https://pexels.com) | Stock b-roll fallback | Stage 4, optional |

## 2. Local tools

| Tool | Install (macOS) | Used for |
|---|---|---|
| `ffmpeg` | `brew install ffmpeg` | All cutting, assembly, audio mixing, frame-exact measurement |
| `yt-dlp` | `brew install yt-dlp` | Extracting video/audio from Instagram & YouTube (quote clips, inspiration downloads, audio-recovery when scrapes come back video-only) |
| Python 3 + venv | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (+ `brew install yt-dlp` symlinked or on PATH) | The bundled `engine/` + `pipeline/` modules |
| Node.js | `brew install node` | Remotion renders + Playwright captures |

## 3. Claude Code skills & MCP connectors

| Dependency | Kind | Role |
|---|---|---|
| **foundry suite** (this repo, `skills/`) | skills | The production system itself |
| **Official Remotion skill** | skill | Deterministic motion graphics — Lane A (chart replays, listicles, text plates) |
| **Official Playwright skill** | skill | Web demos & captured-evidence automation — Lane B (app walkthroughs, screen proof) |
| **Higgsfield MCP** | MCP connector | Generative video — Lane C (authorize in your Claude Code session) |
| **Apify MCP** | MCP connector | Scraping without managing a raw token (either this OR `APIFY_TOKEN`) |

## 4. Verify — `/foundry doctor`

Ask the router for a doctor pass: it checks each row above (ffmpeg, yt-dlp, venv,
every `.env` key, which MCP connectors are live, which official skills are
installed) and reports what's missing **and which lane it degrades** — e.g. no
`FAL_KEY` and no Higgsfield MCP means Lane C pieces stop at the storyboard.
