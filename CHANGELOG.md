# Changelog

## [Unreleased] - Higgsfield API route

When the Higgsfield API is available Foundry now always uses it for video; otherwise it uses the Higgsfield MCP, as before. See SPEC.md "Higgsfield API route".

### Added

- `foundry route [piece]` says which video route a build takes now and why. "Available" is a live, free check against Higgsfield's estimate endpoint, never cached.
- `foundry generate <piece> --shot <id>` runs the whole API path in one command: price, reserve, upload the approved frame, submit, wait, download, ingest. The build agent never holds the key or a generate tool, which closes the "tie video generations to reservations" gap for this route.
- A stdlib Higgsfield client (`engine/providers/higgsfield_api.py`). Credentials go only to the API host; presigned uploads and downloads never see them; redirects on authenticated calls are refused. A submit is never retried: every 4xx (and 503) is a refusal, any other failure is an unknown outcome that is recorded as spent and parked for a human. Status polls never run past the call's deadline.
- Crash safety: a phased, fsynced job file per shot. A kill before the POST voids the reservation, a kill inside it parks the shot, a kill after it resumes; a clip already ingested finishes cleanly; a clip from a replaced first frame is charged but not ingested. One `generate` call fits in 100 s so the agent's shell never kills it mid-step.
- `void` settle state for calls that never reached the provider; it does not count against the ceiling.
- The build agent's environment no longer carries `HF_KEY` / `HF_API_KEY` / `HF_API_SECRET`.
- `video_usd` ledger unit. Specs now plan and freeze a ceiling in both currencies, so either route (and a fallback part-way) is capped. `foundry ls` shows both.
- `foundry doctor`: `Higgsfield API` and `video route` rows; the MCP row is only a note when the API works.
- `HF_KEY` in `.env.example`; `providers.video.route` (`auto` | `api` | `mcp`, default `auto`).

### Changed

- The build prompt and `/foundry-build` ask `foundry route` per shot. Headless builds need `providers.video.mcp_server` only on the MCP route.
- Each video unit pays only on its own route: `ingest-clip`/`fetch` consume `video_credits`, only `foundry generate` consumes `video_usd`. An `unknown-…` charge never pays for a clip, and a shot with an API request in flight or parked refuses any other clip.
- `foundry settle` refuses `video_usd` entries (only `foundry generate` settles them). The shipped recipe's `cost_per_run` includes `video_usd`.
- Pieces approved before this change have no `video_usd` ceiling, so they stay on the MCP route.

## [1.0.0.0] - 2026-09-17

Foundry Loops: Creator Foundry rebuilt as a loop. Four verbs, one spec per piece, one human gate, and a build loop that never ships red.

### Added

- `foundry` CLI (Python 3.11+) with four verbs, `cast`, `spec`, `build` and `ship`, plus `doctor`, `status`, `reap` and the loop's helper commands. Exit codes are 0 for ok, 1 for a failed check, 2 for a refusal and 3 for blocked.
- `/foundry` driver skill and four verb skills. A piece goes from idea to posted reel with two human touches: the cast pick and the storyboard/first-frame sheet.
- Fail-closed casting. A creator sheet is measured against the master portrait before it can be approved. The face on the sheet is found by template matching, so hair and background are never measured as skin.
- Five-question spec resolver for the `hook_reel` format. It checks text lint, the caption band, cut length, assets and audio before anything is spent.
- Sheet gate. Approving the sheet freezes the spec hash, input hashes, QC targets, fix-cycle limit, charter snapshot and spend ceiling into `approved.lock.json`.
- QC-driven build loop with nine machine gates: skin, first-frame match, drift, hands, duration, caption band, loudness (-14 LUFS), safety lint and text lint. A red gate triggers a fix; a piece that runs out of fix cycles is blocked, never shipped.
- Headless build mode (`claude -p`, `dontAsk`). The agent is scoped to its own piece and gets only `foundry` commands, read access to its piece and six named Higgsfield video tools.
- Invoice with reservation before every paid call, one-way settlement, finite amounts only, a per-clip floor and a ceiling fixed at approval.
- Clip transfer by upload or by HTTPS fetch. Non-global addresses and redirects to them are refused, and hosts can optionally be allow-listed.
- `foundry doctor` checks tools, keys and the Higgsfield MCP connection, and links every setup step instead of printing warnings.
- Offline end-to-end test and 156 tests total.

### Changed

- Image model is `gpt-image-2.5-sunburst`.
- The first-frame prompt now avoids wording that the safety lint read as the opposite of what was meant.

### Known gaps

- The unattended headless build has only run in tests; the in-session build is the one proven on real providers. See TODOS.md.
