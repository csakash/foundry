# Changelog

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
