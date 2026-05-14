# OpenText Process Automation MCP — Project Rules

Working agreement for everyone (humans and AI agents) contributing to this repo.

## Rule 0: Test-Driven Development (TDD) — Non-Negotiable

No feature code in `src/` shall be written, considered "Done", or merged unless accompanied by a **passing test suite** in `tests/`.

**Enforcement protocol:**
1. When asked to implement a feature, **create the test file first** (`tests/unit/` or `tests/integration/`).
2. Write failing tests that define the expected behavior.
3. Only then write the minimum implementation in `src/opentext_pa_mcp/` to make tests pass.
4. Refactor while keeping tests green.

**Refuse** to write implementation code if the corresponding test file does not exist.

**Test stack:** `pytest`, `pytest-asyncio` (this is async-heavy code), `respx` for httpx HTTP mocking. Integration tests against the live AppWorks instance go in `tests/integration/` and require env vars to be set; unit tests must not need network.

---

## Rule 1: Folder Integrity

| Folder | Purpose | What belongs here | What does NOT belong here |
|--------|---------|-------------------|---------------------------|
| `docs/` | Project documentation — decisions, evolution, and discovery, all under one roof | `DECISIONS.md`, `CHANGELOG.md`, and anything else that documents the project | Code, secrets, generated build output |
| `docs/research/` | Reproducible discovery findings | Captured artifacts (`openapi.json`, sample responses, helper scripts), `findings.md`, `discovery-plan.md` | Active exploration; vendor-supplied material |
| `docs/technical/` | Architecture documentation | System design, sequence diagrams, deployment notes | Application code |
| `docs/product/` | Product specifications | Feature specs, user-facing config docs | Code, raw brainstorming |
| `docs/fromcustomer/` | **Gitignored.** Vendor / customer-supplied reference material (platform docs, decompiled webapps, env probes) used during investigation but not part of the public repo | Vendor PDFs, decompiled JARs, screenshots of admin UIs, customer-shipped helper scripts | Anything we want to publish |
| `src/opentext_pa_mcp/` | The Python package — production code | Domain modules: `auth/`, `discovery/`, `tools/`, `server.py`, `__main__.py` | Tests, docs, dead code |
| `tests/unit/` | Fast, no-network tests | Pure-Python tests; HTTP mocked with `respx` | Integration tests |
| `tests/integration/` | Tests against a live AppWorks tenant | End-to-end OTDS login, real `lists/DefaultList` calls | Tests that don't need a real server |

**Root directory rule:** the workspace root contains ONLY `.claude/`, `.gitignore`, `.python-version`, `CLAUDE.md`, `README.md`, `CONTRIBUTING.md`, `LICENSE`, `pyproject.toml`, `uv.lock`, and the three top-level directories (`docs/`, `src/`, `tests/`). No build artifacts, no `__pycache__`, no `dist/` checked in. The earlier root-level `research/` folder has been retired — its `DECISIONS.md` and `CHANGELOG.md` now live at `docs/DECISIONS.md` and `docs/CHANGELOG.md`.

**Note for readers of the original template:** This deviates from the template's `codebase/src/` and `codebase/tests/` layout. Reason: every Python tool (`uv`, `pip`, `pytest`, `uvx`) expects `pyproject.toml` at the project root. Putting it inside `codebase/` works but breaks `uvx opentext-pa-mcp` (our v1.0 install story) and tooling defaults. We keep the *spirit* of the rule (code separated from docs) but use the Python-native layout.

---

## Rule 2: Source-of-Truth Hierarchy

When making architectural choices, consult these in order. Lower-numbered sources override higher-numbered ones.

1. **`docs/DECISIONS.md`** — accepted decisions with rationale. Authoritative for "what did we agree to and why".
2. **`docs/research/findings.md`** — what we know to be true about the live AppWorks API (validated by saved artifacts). Authoritative for "how does the platform actually behave".
3. **The OpenAPI spec at `docs/research/artifacts/openapi.json`** — authoritative for "what endpoints exist and what shape do they have".
4. **The code itself** — authoritative for "what does this codebase currently do".

If you find a conflict between these, log it in `docs/DECISIONS.md` and resolve it explicitly. Do not silently paper over.

---

## Rule 3: Decision Traceability

Any significant architectural, design, or strategic decision must be logged in `docs/DECISIONS.md` with:
- **ID** (`DEC-NNN`, monotonically increasing)
- **Date** (absolute, not relative)
- **Decision** (what was chosen)
- **Context** (why it was needed)
- **Alternatives considered** (with one-line rejection reason for each)
- **Rationale** (why this option won)

Additionally, every significant milestone must be recorded in `docs/CHANGELOG.md` — a narrative product evolution journal that documents how and why the product reached its current state.

---

## Rule 4: Code Quality Standards (Python)

- **Prefer explicit over implicit.** Type-hint every public function. Use `from __future__ import annotations` so types can reference forward declarations cheaply.
- **Functions should do one thing.** If a function needs an "and" in its docstring summary, split it.
- **Name variables and functions descriptively** — no abbreviations except for ubiquitous ones (`req`, `resp`, `url`, `id`).
- **All public APIs need docstrings.** Google or NumPy style — pick one and be consistent (pyproject.toml `[tool.ruff]` enforces). Modules and classes get a one-paragraph docstring; functions get summary + args + returns + raises.
- **No `print()` in production code.** Use the `logging` module via a package-level logger. MCP servers MUST log to stderr (stdout is reserved for the protocol).
- **Async by default.** The HTTP layer is `httpx.AsyncClient`; tool handlers are `async def`. Sync code only for pure-computation helpers.
- **Strict typing.** `ruff` for lint + format, `pyright` (basic mode minimum) for type checking. CI fails on either.
- **No `Any` unless justified by comment.** If you must use `Any`, add `# type: ignore[reason]` or `# noqa: ANN401` with a one-line reason.
- **Errors raise, don't return tuples.** Use exception types from `src/opentext_pa_mcp/errors.py` (to be created). Tool-level handlers catch and translate into structured MCP error responses at the boundary.

---

## Rule 5: Secrets handling

- **Never commit credentials, cookies, or tokens.** `.gitignore` covers `.env`, `*.env.local`, `tests/integration/.env`.
- **Don't log credentials or full cookie values.** When logging requests, redact `defaultinst_AuthContext`, `OTDSTicket`, and the `Authorization` header.
- **Config comes from env vars only.** No hard-coded URLs, usernames, or hostnames in code. Test fixtures use placeholder values.

---

## Project Context

**Product:** OpenText Process Automation MCP — a Model Context Protocol server that exposes any AppWorks Platform entity service as a small, generic toolset, so Claude (and any other MCP-compatible client) can interact with it in plain English.

**Stage:** Discovery complete; v1.0 implementation pending. See `docs/research/findings.md` for the validated architecture.

**Target platform:** OpenText AppWorks Platform 23.x (Cordys lineage). Each entity service publishes an OpenAPI 3.0.1 spec embedded in its Swagger UI HTML page as `var dyn_spec_obj = {...}`. Auth is OTDS form login on a separate port, returning a session cookie scheme.

**Validated v1.0 design:**
- **Stack:** Python 3.11+, `fastmcp` (or low-level `mcp` SDK), `httpx`, stdio transport
- **Config (env vars):** `PA_SERVICE_URL`, `PA_USERNAME`, `PA_PASSWORD`, optional `PA_LOG_LEVEL`
- **Distribution:** PyPI, installed via `uvx opentext-pa-mcp`. No DXT bundles.
- **Tool surface:** ~18 generic verb tools covering 700+ underlying endpoints by passing entity/list/action names as arguments. See `docs/DECISIONS.md: DEC-005`.

**v1.0 scope: read-only.** Write operations (create, update, delete, invoke_action) ship in v1.1 behind a `PA_ALLOW_WRITES=true` flag. Rationale: AppWorks actions like `Submit` and `Accept` are not idempotent; a misbehaving LLM should not be able to mutate cases until users explicitly opt in.
