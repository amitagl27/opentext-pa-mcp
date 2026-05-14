# Product Evolution Changelog

Narrative log of how the project reached its current state. New entries at the top.

---

## 2026-05-15 — v0.1.3: Cordys built-in SSO support

First post-launch bug fix. Users reported (issue #2 on the public mirror) that the server crashed at startup on AppWorks 25.x "Process Automation CE" tenants with `AuthenticationError: Login page did not contain the expected csrf / RFA tokens`. Investigation against a live 25.1 instance showed AppWorks CE uses **Cordys built-in SSO** (SAML 1.1 SOAP + WS-Security `UsernameToken`) rather than OTDS form-login. Login pages and protocols are wholly different.

**Approach** (see `DEC-014`): introduce a strategy-pattern dispatcher in `AppworksClient._login`, with auto-detection from the login-page HTML/URL markers as the default (`PA_AUTH_MODE=auto`). The original OTDS flow becomes one of two strategies; the new `CordysAuth` strategy runs three HTTP steps — POST SAML envelope to the SOAP gateway, POST returned artifact to `AuthenticationToken.wcp`, reuse the resulting `{tenant}inst_SAMLart`/`{tenant}inst_ct` cookies. New optional env var `PA_AUTH_MODE=otds|cordys` overrides detection if a custom proxy hides the markers.

**Shipped:**
- `src/opentext_pa_mcp/auth.py` — two-strategy dispatcher; new `_cordys_login`, `_detect_auth_mode`, `_build_cordys_saml_envelope` helpers.
- `src/opentext_pa_mcp/config.py` — `auth_mode` field + `PA_AUTH_MODE` env var (`auto` default, `otds`, `cordys`).
- `tests/unit/test_auth_cordys.py` — 8 new tests covering auto-detect routing, explicit-mode bypass, WSSE envelope contents, artifact handling, invalid-credentials, missing-artifact, unknown-shape errors, and 401-relogin.
- `docs/research/artifacts/cordys-*.{html,xml}` — sanitised reference artifacts (login form, SAML request template, SAML response example, token-consumer response) for future spelunkers.
- `README.md` — new "Auth modes" section + `PA_AUTH_MODE` row; status line updated to mention 25.x support.

**Quality gates that held:**
- `ruff check src tests` — clean.
- `pyright src tests` — 0 errors, 0 warnings.
- 112 unit tests passing (previously 100; the 12 new ones cover Cordys + `PA_AUTH_MODE`).
- End-to-end smoke test via TestPyPI 0.1.3.dev1 install against a live Process Automation CE 25.1 tenant: auto-detect picked Cordys, SAML login succeeded, discovery reported 3 entities / 440 operations on the entity service under test.

**Out of scope for this release:**
- Issue #1 (Developer-Role startup failure) — separate root cause, tracked for v0.1.4.
- Cordys-specific integration tests in `tests/integration/` — current integration suite is parameterised only for OTDS; needs a sweep later.

---

## 2026-05-12 (later that day) — v0.1.0 implementation complete

Overnight TDD build of the read-only v1.0 MCP server, ready to publish to PyPI.

**Code shipped:**
- `src/opentext_pa_mcp/` — config, errors, spec_extractor, auth (OTDS 4-step + 401 retry), catalog (28 entities from real OpenAPI), discovery bootstrap, 9 tool handlers, FastMCP server wiring, console-script entry point.
- `tests/unit/` — 77 tests, all green. HTTP mocked via `respx`. Fixtures sourced from the captured `openapi.json` and `swagger-ui-page.html` so assertions match the real platform.
- `tests/integration/` — 5 tests, all green against `api.example.com:3381`. End-to-end OTDS login, discovery, `list_entities`, `query_list` on `LegalCategory/DefaultList`, `describe_entity` on `LegalCase`.
- `dist/opentext_pa_mcp-0.1.0-py3-none-any.whl` + sdist, built with `hatchling` via `uv build`. Wheel install in a fresh venv works, entry point registered correctly.
- `PUBLISHING.md` — step-by-step PyPI upload instructions.
- `READ-ME-FIRST-TOMORROW.md` — handoff checklist for the user.

**Quality gates that held:**
- `ruff check` — 0 errors.
- `pyright src` — 0 errors.
- 77 unit + 5 integration tests passing.

**Things deliberately deferred** (see READ-ME-FIRST-TOMORROW.md §"Things I noticed worth a second opinion later"):
- `get_entity` skips entity-name pre-validation to support polymorphic queries.
- `list_named_lists` only returns top-level lists, not child-entity lists.
- `pa_api_call` HEAD method raises NotImplementedError instead of being silently dropped.

Branch: `feature/v1-read-only`. Not pushed to any remote; awaiting user review and publish.

---

## 2026-05-12 — Discovery complete, project rules adopted, v1.0 plan locked

After validating the architecture against a live AppWorks 23.4 tenant (`api.example.com:3381`), the v1.0 design is locked.

Highlights of the discovery (full report: `docs/research/findings.md`):
- The platform is **AppWorks Platform 23.4**, not OT Process Automation Cloud Edition.
- Each entity service publishes a **full OpenAPI 3.0.1 spec**, embedded as `var dyn_spec_obj` inside its Swagger UI HTML page. This was a pleasant surprise — the original hypothesis was OData-only.
- The `ExampleLegalManagement` service alone exposes **793 operations across 28 entities** with **652 schemas**. This fully validates the early "tool explosion" concern that ruled out auto-generating one MCP tool per endpoint.
- The URL pattern is highly uniform: every entity follows the same 6 sub-patterns (collection, item, named list, child entity, relationship, action). The 793-op surface collapses to **~16 URL templates** parameterized by entity/list/action names. This means ~18 generic MCP tools can cover the whole surface.
- Authentication is OTDS form login on a separate port, reproducible non-interactively. A working PowerShell helper was committed at `docs/research/artifacts/Login-Appworks.ps1`.

Project-level decisions locked today (see `research/DECISIONS.md`):
- DEC-001…007 — language, transport, distribution, config shape, tool design, spec discovery, auth.
- DEC-008 — Python-native repo layout (`src/`, `tests/`, `pyproject.toml` at root) instead of the template's `codebase/` wrap.
- DEC-009 — v1.0 is read-only; writes ship in v1.1 behind `PA_ALLOW_WRITES=true`.

Project conventions adopted: TDD non-negotiable (`CLAUDE.md` Rule 0), promotion-based branching `feature → DEV → SIT → main` (`CONTRIBUTING.md`), and four authoritative sources of truth (`CLAUDE.md` Rule 2).

Next: scaffold `pyproject.toml`, the empty `src/opentext_pa_mcp/` package, and the first failing tests for the OTDS auth layer and the OpenAPI-from-HTML extractor.
