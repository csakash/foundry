## gstack-loops (loop-engineering)

This workspace uses [gstack-loops](https://github.com/csakash/gstack-loops) on top of
[gstack](https://github.com/garrytan/gstack). Repos: foundry-upstream.

**Every feature is a loop. Never edit `main` or the root checkouts directly** — parallel
sessions share these repos; an isolated worktree per loop is what stops them clobbering each
other. Start each feature with `gloop new <slug>`, then work inside `worktrees/<slug>/`.

The loop: `/gloop-spec` (commit `SPEC.md`) → `/gloop-build` (build → `/review` + `/qa`
until green) → `/gloop-ship` (raise the PR). There's a `/gloop-*` shortcut for every step,
or just `/gloop <what you want>` to drive it conversationally. For headless runs use
`gloop run <slug> --mode <interactive|bypass|autonomous>`.

- Use `/browse` for all web browsing/QA — never `mcp__claude-in-chrome__*`.
- Definition of Done (Foundry): behavior matches `SPEC.md`; the build gate is
  `python3 -m pytest -q` + `python3 -m compileall -q foundry engine` (this repo has no
  `npm run build` and no dev server); `/review` passes; QA is the offline end-to-end run
  in `tests/test_e2e_offline.py` (fake image provider, synthetic clip), because there is
  no web app to point `/qa` at; no `.env`, persona art, or work dirs committed.
- `loops.json` stays **uncommitted** in this repo. gloop finds its workspace by walking up to
  the nearest `loops.json`; a committed copy lands in every worktree and makes each worktree
  its own workspace. The repo is a single-repo workspace (`path: "."`), so the file lives
  only in the main checkout, with `dev: null`.
- Landing several PRs at once: see [docs/PARALLEL_SHIPPING.md](docs/PARALLEL_SHIPPING.md)
  (shared-DB isolation via `hooks.preLoop`, merge order, rebase-before-ship).
- After a loop's PR merges: `gloop reap` (or `gloop drop <slug> --delete-branch`).
