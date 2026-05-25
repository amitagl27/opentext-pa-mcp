---
description: Ship the current working tree through the full release pipeline (feature → DEV → main → tag → public sync → PyPI).
argument-hint: '[bump: patch|minor|major | explicit version e.g. 0.3.1]'
---

# /ship — release pipeline for opentext-pa-mcp

Execute the canonical six-step release pipeline end-to-end. Stop and ask the user if **any** gate fails — do not improvise around a red signal.

`$ARGUMENTS` is optional. Forms:
- empty — treat the version already in `pyproject.toml` as the target. Use this when the user bumped the version themselves before invoking.
- `patch` / `minor` / `major` — bump the current `pyproject.toml` version by that semver step and commit the bump as part of the release commit.
- `0.3.1` / `1.0.0` — set the explicit version.

---

## Pre-flight gates (refuse to ship if any fails)

Run these in parallel where possible.

1. **Working tree must contain only intended changes.** `git status --porcelain`. If there are untracked files unrelated to this release (e.g. `docs/newissue/`, scratch notes), list them and ask the user whether to add to `.gitignore`, stash, or include. Never `git add -A` blindly.
2. **Tests must pass.** `./.venv/Scripts/python.exe -m pytest tests/unit`. Any failure → stop, show the failure, fix-first.
3. **Lint must pass.** `./.venv/Scripts/python.exe -m ruff check src tests`.
4. **Format must be clean.** `./.venv/Scripts/python.exe -m ruff format --check src tests`. If reformatting is needed, run `ruff format src tests` and **re-stage** — don't ship un-formatted code.
5. **Types must pass.** `./.venv/Scripts/python.exe -m pyright src`.
6. **Version bump is sane.** Compare the target version against `git show origin/main:pyproject.toml`. If unchanged, the public repo's `publish.yml` will skip PyPI publish (its diff is the trigger). Refuse to ship a "release" without a version bump unless the user explicitly says it's a docs-only follow-up — in which case skip the tagging step at the end too.
7. **CHANGELOG + DECISIONS reflect the release.** `docs/CHANGELOG.md` should have a top entry whose heading matches the target version. Any new architectural decision should have a `DEC-NNN` entry in `docs/DECISIONS.md`. If missing, draft both from the diff and ask the user to confirm before continuing.

If `$ARGUMENTS` is `patch|minor|major` or an explicit version, edit `pyproject.toml` to the new version *before* the pre-flight gates run — so the CHANGELOG/version checks see the final state.

---

## Pipeline

Run sequentially. Each step is its own Bash call so failures stop the chain cleanly.

### 1. Branch + commit

- Derive a branch name from the diff: `feat/<slug>` for new features, `fix/<slug>` for bug fixes, `docs/<slug>` for docs-only, `chore/<slug>` otherwise. Slug = 2–4 kebab-case words from the changes.
- `git checkout -b <branch>` if not already on a feature branch. If already on a feature branch with the right shape, reuse it.
- Stage only the files this release touches (never `git add -A`). Use the explicit file list from `git status`.
- Commit with a HEREDOC message: subject line `<type>(<scope>): <summary> (vX.Y.Z)`, body with 2–4 bullet "what + why" lines drawn from the diff, and the trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.

### 2. Push + open feature PR (base: DEV)

- `git push -u origin <branch>`.
- `gh pr create --base DEV --title "<type>(<scope>): <summary> (vX.Y.Z)" --body @-` with a HEREDOC body containing:
  - **Summary** — 2–4 bullets, drawn from the actual diff.
  - **Test plan** — checklist of pytest/ruff/pyright + any post-merge verification.
  - The `🤖 Generated with [Claude Code](https://claude.com/claude-code)` footer.
- Capture the PR number from gh's output.

### 3. Merge feature PR into DEV

- `gh pr merge <num> --merge --delete-branch`. The repo uses **merge** commits (not squash) — match the existing history shape (look at recent merge commits to confirm).
- If the merge fails (branch protections, required checks), stop and surface the failure.

### 4. Open release PR DEV → main

- `git checkout main && git pull origin main`.
- `gh pr create --base main --head DEV --title "Release vX.Y.Z — <one-line summary>" --body @-` with a HEREDOC body that includes:
  - A pointer to the feature PR (`Merged #<num> into DEV.`).
  - The Summary bullets from the feature PR.
  - A **Test plan** with post-merge verification steps (sync, image publish, PyPI publish, manual smoke test against the deployed instance).

### 5. Merge release PR

- `gh pr merge <release_num> --merge`. Do NOT pass `--delete-branch` — DEV is permanent.
- `git pull origin main` to local main.

### 6. Tag and watch automations

- Only if a version bump happened: `git tag -a vX.Y.Z -m "vX.Y.Z — <summary>"` then `git push origin vX.Y.Z`. The tag triggers `publish-image.yml` to produce the semver-tagged image (`:X.Y.Z`, `:X.Y`).
- Wait briefly, then `gh run list --limit 5 --json status,conclusion,name,headBranch`. Confirm three runs are queued or succeeded on the private repo:
  - **Sync to Public Repository** (push to main).
  - **Publish container image** on `main` (`:latest`).
  - **Publish container image** on `vX.Y.Z` (semver tags).
- On the public mirror: `gh run list --repo amitagl27/opentext-pa-mcp --limit 3 --json status,conclusion,name`. Confirm the **Publish to PyPI on main** run kicked off (it triggers from the sync push).
- Final verification: `curl -fsSL https://pypi.org/pypi/opentext-pa-mcp/json | python -c "import json,sys; d=json.load(sys.stdin); print('PyPI latest:', d['info']['version'])"` and assert it matches `vX.Y.Z`.

---

## Wrap-up message to the user

A short table or bullet list:

- Feature PR #N — merged into DEV
- Release PR #M — merged into main
- Tag vX.Y.Z — pushed
- Sync to public — success
- Image `ghcr.io/amitagl27/opentext-pa-mcp:X.Y.Z` + `:latest` — published
- PyPI `opentext-pa-mcp X.Y.Z` — confirmed live
- One-line deployment hint for any existing Container App: "redeploy ARM template with `imageTag=X.Y.Z`, or restart the revision if pinned to `latest`."

---

## When NOT to use /ship

- Tests are failing or the working tree is mid-refactor — fix first.
- Version unchanged AND change isn't documentation-only — bump first.
- The change should land on DEV only (not main yet) — run steps 1–3 only and stop.
- A previous release is mid-flight (open release PR, in-progress workflow) — let it finish.
- The change touches `.github/workflows/sync-public.yml` or `publish-image.yml` — pipeline changes deserve a manual review, not an autopilot ship.

## Constraints (non-negotiable)

- Never `--no-verify`, never `--force`, never `--amend` an already-pushed commit.
- Never `git add -A` or `git add .` — always explicit file list.
- Never `gh pr merge --admin` — let branch protections do their job.
- Never push to `main` directly — always via release PR from DEV.
- Never bypass a failing test or lint check by editing config to relax it.
- If anything looks off (unexpected files, weird diff, unknown branch state), stop and ask before destructive actions.
