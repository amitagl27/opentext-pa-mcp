# Contributing Guide — OpenText Process Automation MCP

## Branching Strategy

Promotion-based branching:

```
feature/xxx  -->  PR  -->  DEV  -->  PR  -->  SIT  -->  PR  -->  main
(development)          (integration)      (testing)       (production)
```

| Branch  | Purpose                        | Who merges PRs       |
|---------|--------------------------------|----------------------|
| `main`  | Production-ready, what PyPI publishes from | Project lead only    |
| `SIT`   | System integration testing against a live tenant | Project lead only    |
| `DEV`   | Integration of all dev work    | Any senior developer |

**No one pushes directly to `main`, `SIT`, or `DEV`.** All changes go through pull requests.

## Developer Workflow

### 1. Initial Setup (one-time)

```bash
git clone <repo-url>
cd opentext-processautomation-mcp
git checkout DEV

# Python toolchain (uv is the recommended manager — handles venv + lock):
uv sync                      # creates .venv, installs deps from uv.lock
uv run pytest                # sanity check unit tests
```

If `uv` is not installed: `pip install uv` or follow https://docs.astral.sh/uv/.

### 2. Starting New Work

Always branch off `DEV`:

```bash
git checkout DEV
git pull origin DEV
git checkout -b feature/<short-description>
```

Branch name prefixes:

| Prefix      | Use for                          |
|-------------|----------------------------------|
| `feature/`  | New functionality                |
| `bugfix/`   | Bug fixes                        |
| `hotfix/`   | Urgent production fixes (off main) |
| `refactor/` | Code cleanup, no behavior change |
| `test/`     | Test-only additions or fixes     |
| `docs/`     | Documentation-only changes       |

### 3. Making Changes

Per `CLAUDE.md` Rule 0 (TDD non-negotiable): **write the failing test first**, in `tests/unit/` or `tests/integration/`. Only then write implementation in `src/opentext_pa_mcp/`.

- Commit often with clear messages.
- Keep commits focused — one logical change per commit.
- Before committing, run:
  ```bash
  uv run ruff format .
  uv run ruff check .
  uv run pyright            # type check
  uv run pytest             # unit tests
  ```
  CI runs the same checks; failing them locally first is faster.

```bash
git add <files>
git commit -m "feat: short description of what and why"
```

### 4. Pushing Your Work

```bash
git push origin feature/<short-description>
```

Push often to back up your work. Pushing does **not** mean the feature is ready for review.

### 5. Creating a Pull Request

Only when the feature is **fully implemented, tested locally, and lint/type-check clean**.

- GitHub CLI: `gh pr create --base DEV --title "Your title"`
- GitHub UI: New pull request, base = `DEV`.

PR description must include:
- What changed and why
- Manual test steps (especially for anything touching auth or live API calls)
- New or updated env vars
- Linked decision (`DEC-NNN`) if the change implements one

### 6. PR Review Rules

Since branch protection isn't enforceable on free private repos, we follow these manually:

- Every PR to `DEV` must be reviewed and approved by **at least 1 other developer** before merging.
- Every PR to `SIT` or `main` must be reviewed and approved by the **project lead**.
- **Never merge your own PR** without at least one approval.
- **Never push directly** to `DEV`, `SIT`, or `main`.
- Use **squash and merge** for feature branches.

### 7. After Your PR Is Merged

```bash
git checkout DEV
git pull origin DEV
git branch -d feature/<short-description>
git push origin --delete feature/<short-description>
```

## Promotion Workflow

1. **DEV → SIT:** when a set of features in DEV is ready for live-tenant testing, the project lead creates a PR from `DEV` to `SIT`.
2. **SIT → main:** after manual testing against a live AppWorks instance passes, the project lead creates a PR from `SIT` to `main`. Merging to `main` triggers the PyPI release workflow (once configured).

## Commit Message Guidelines

```
<type>: <short summary>

<optional longer description, including rationale and any DEC-NNN reference>
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `build`, `ci`

Examples:
- `feat: parse dyn_spec_obj from Swagger UI HTML`
- `feat: implement OTDS auth flow for httpx.AsyncClient`
- `fix: strip GUID suffix from schema names in describe_entity`
- `test: add unit tests for entity catalog builder`
- `refactor: move HAL envelope flattening into response_shaping.py`
- `docs: log DEC-009 — go with FastMCP instead of low-level mcp SDK`

## Tests

Per `CLAUDE.md`:

- `tests/unit/` — fast, no network. HTTP mocked via `respx`. Must pass on every push.
- `tests/integration/` — runs against a live AppWorks tenant. Requires:
  ```
  PA_SERVICE_URL=http://...
  PA_USERNAME=...
  PA_PASSWORD=...
  ```
  Place these in `tests/integration/.env` (gitignored). Skipped if env vars are missing.

Run:
```bash
uv run pytest tests/unit                      # always
uv run pytest tests/integration               # only with valid creds
uv run pytest --cov=opentext_pa_mcp           # with coverage
```

## Do's and Don'ts

**Do:**
- Pull latest `DEV` before creating a feature branch.
- Keep PRs small and focused.
- Write a clear PR description explaining what changed and why.
- Link to the related `DEC-NNN` if your PR implements a logged decision.
- Run lint + type-check + tests locally before pushing.

**Don't:**
- Push directly to `DEV`, `SIT`, or `main`.
- Merge your own PR without review.
- Leave stale feature branches — clean them up after merge.
- Force-push to shared branches.
- Commit credentials, even in `tests/integration/` fixtures — use placeholders and document the env-var pattern.
