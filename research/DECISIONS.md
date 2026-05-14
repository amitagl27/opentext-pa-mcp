# Decisions

Architectural, design, and strategic decisions. New entries get a monotonically increasing `DEC-NNN` ID. Older decisions are not deleted when superseded — they are marked superseded and link forward to the replacement.

Format per entry: ID, Date (absolute), Decision, Context, Alternatives, Rationale.

---

## DEC-001 — Language and runtime: Python 3.11+

**Date:** 2026-05-12
**Decision:** Implement the MCP server in Python 3.11 or newer.
**Context:** Need to pick the host language for the MCP server.
**Alternatives considered:**
- TypeScript / Node.js — viable, has an official MCP SDK. Rejected: heavier deployment story for non-JS shops, less natural fit for the OpenAPI-spec-parsing and HTTP-client work.
- C# / .NET — natural fit for an OpenText shop (often Windows-heavy). Rejected: smaller MCP ecosystem today; FastMCP equivalents are immature.
- Go — possible but rejected: no first-class MCP framework with the ergonomics of FastMCP yet.
**Rationale:** Python has the most mature MCP server framework (`fastmcp`), excellent async HTTP (`httpx`), trivial OpenAPI handling, and is the lingua franca of MCP examples in late 2025/early 2026. `uvx` makes distribution friction-free.

---

## DEC-002 — Transport: stdio

**Date:** 2026-05-12
**Decision:** Use the stdio transport for v1.0.
**Context:** MCP supports stdio (process-per-client) and HTTP/SSE (network-hosted). We have to pick.
**Alternatives considered:**
- HTTP/SSE — supports team-shared hosting. Rejected for v1: adds auth, TLS, deployment complexity; not needed for single-user setups.
**Rationale:** Single-user-on-laptop is the dominant MCP use case today. stdio is the default for Claude Desktop and Claude Code. HTTP transport can be added later behind a `--transport http` flag if a customer wants centralized hosting.

---

## DEC-003 — Distribution: PyPI via `uvx`. No DXT bundle.

**Date:** 2026-05-12
**Decision:** Publish the server to PyPI as `opentext-pa-mcp`. Users install it by adding a JSON snippet that runs `uvx opentext-pa-mcp` in their MCP client config. No `.dxt` Desktop Extension bundle, now or later.
**Context:** Need an install story that doesn't require users to clone the repo.
**Alternatives considered:**
- GitHub clone + `pip install .` — rejected: too many manual steps; breaks for non-developers.
- DXT bundle for one-click Claude Desktop install — explicitly rejected by project owner. Rationale on the project side: DXT is Claude-Desktop-only, adds packaging work, and the `uvx` JSON snippet is already short enough.
**Rationale:** `uvx` requires zero pre-install on the user's machine beyond `uv` itself (or a Python with `pipx`), works on every MCP client (Desktop, Code, Cursor, etc.), and is the standard distribution for new Python MCP servers in this era.

---

## DEC-004 — Configuration: single service URL + creds

**Date:** 2026-05-12
**Decision:** v1.0 config is three env vars: `PA_SERVICE_URL`, `PA_USERNAME`, `PA_PASSWORD`. Optional: `PA_LOG_LEVEL`, `PA_REQUEST_TIMEOUT_S`. (v1.1 will add `PA_ALLOW_WRITES`.)
**Context:** The user needs to tell the server which AppWorks tenant and entity service to bind to. We can ask them for many small pieces (host, port, tenant, service name) or one URL that carries everything.
**Alternatives considered:**
- Separate `PA_BASE_URL`, `PA_TENANT`, `PA_ENTITY_SERVICE` — rejected: three fields where the user already has one URL in their browser.
- Just `PA_TENANT_URL` (no service name) — rejected: a tenant usually hosts multiple entity services and we need to know which one to bind to.
- YAML/JSON config file path — rejected: doesn't survive the MCP-client `env` block well; harder to template.
**Rationale:** The user already has the entity-service URL open in their browser when they decide to set this up. One URL, two creds: minimum cognitive load. Everything else (host, tenant, OTDS login endpoint, REST API base) is derived at runtime.

---

## DEC-005 — Tool design: generic verb tools, entity name as argument

**Date:** 2026-05-12
**Decision:** Expose ~18 generic tools that take entity / list / relationship / action names as **arguments**, not 793 endpoint-specific tools. See `docs/research/findings.md` section "Validated design — v1 MCP server" for the full list.
**Context:** The `ExampleLegalManagement` entity service alone has 793 operations across 28 entities. Modern LLMs degrade past ~30–60 tools.
**Alternatives considered:**
- One MCP tool per OpenAPI operation (~793 tools) — rejected: destroys LLM tool-picking.
- One tool per entity (~28 tools, each with method as argument) — rejected: still doesn't compose well across the action / list / relationship sub-patterns; mixes too many concerns per tool.
- A single `pa_api_call(method, path, body?)` catch-all — rejected as the *only* tool: forces the LLM to construct the entire URL, which is error-prone and offers no schema hints. (We do include it as one of the 18, as an escape hatch.)
**Rationale:** AppWorks's URL pattern is uniform — every entity follows the same 6 sub-patterns (collection, item, named list, child entity, relationship, action). The whole 793-op surface collapses to ~16 URL templates parameterized by name. A small tool set + entity-name argument means infinite-scale to N entities without tool-count blow-up.

---

## DEC-006 — Spec discovery: parse `dyn_spec_obj` from Swagger UI HTML

**Date:** 2026-05-12
**Decision:** At startup, GET the entity-service URL, parse the returned HTML, locate `var dyn_spec_obj = {...}`, and brace-match the JSON to extract the OpenAPI 3.0.1 spec.
**Context:** AppWorks 23.4 does not expose the OpenAPI spec at a separate URL like `/swagger.json`. It is embedded inline in the Swagger UI HTML page as a JS variable assignment.
**Alternatives considered:**
- Probe `/swagger.json`, `/openapi.json`, `/v3/api-docs`, etc. — rejected: confirmed empirically (`docs/research/findings.md` §3) that none of these exist on AppWorks 23.4.
- Run a headless browser to render the Swagger UI and read `window.spec` — rejected as massive over-engineering.
**Rationale:** Empirically verified — a regex + string-aware brace-counter extracts the spec from the live system reliably in a single HTTP call. See `docs/research/findings.md` §3.

---

## DEC-007 — Authentication: scripted OTDS form login + 401 retry

**Date:** 2026-05-12
**Decision:** Implement a small `OtdsAuth` httpx auth class that performs the four-step OTDS login flow on first use and re-runs it on 401 responses.
**Update (2026-05-14):** This decision still stands for OTDS-fronted instances but is no longer the *only* supported flow. See `DEC-014` — the OTDS strategy now sits alongside a Cordys built-in SSO strategy with auto-detection.
**Context:** AppWorks 23.4 protects entity services with OTDS SAML-like cookie sessions. The OpenAPI spec declares no security scheme, so consumers must handle auth out-of-band.
**Alternatives considered:**
- Require the user to paste a session cookie — rejected: cookies expire (SAML artifact is short-lived); breaks repeatable startup.
- OAuth2 client credentials against OTDS directly — rejected: not configured on the target instance; would require platform-side setup the user may not control.
- Basic auth — rejected: AppWorks does not accept it on entity-REST endpoints.
**Rationale:** The flow is fully reproducible (validated end-to-end in PowerShell, see `docs/research/artifacts/Login-Appworks.ps1`). Form-POST with `otds_username`/`otds_password` + CSRF + RFA tokens, then POST `OTDSTicket` to the TicketConsumerService. Two HTTP round-trips after the initial GET; durable session cookie returned.

---

## DEC-008 — Repository layout: Python-native, not template's `codebase/` form

**Date:** 2026-05-12
**Decision:** Project root contains `pyproject.toml`, `src/opentext_pa_mcp/`, `tests/`, `research/`, `docs/`. We do **not** wrap code inside a `codebase/` directory as the original CLAUDE.md template suggested.
**Context:** Project owner provided a CLAUDE.md template (originally written for a JS/TS monorepo called ReadNest) that mandated `codebase/src/` and `codebase/tests/`.
**Alternatives considered:**
- Keep `codebase/` exactly as in the template — rejected: every Python tool (`uv`, `pip`, `pytest`, `uvx`) expects `pyproject.toml` at the project root. Wrapping in `codebase/` would break `uvx opentext-pa-mcp` (the v1.0 install story per `DEC-003`) and would require non-standard tooling configuration that every Python contributor would have to learn.
- Put `pyproject.toml` at the root but keep code in `codebase/src/` — rejected: forces awkward `[tool.hatch.build.targets.wheel] packages = ["codebase/src/opentext_pa_mcp"]` overrides; first-time-Python-contributor hostile.
**Rationale:** The *spirit* of the template's folder-integrity rule (code separated from docs/research/brand) is preserved. The *form* is Python-native. CLAUDE.md Rule 1 is updated to reflect this and explicitly explains the deviation.

---

## DEC-010 — Tool handler separation: pure functions + thin FastMCP wrapper

**Date:** 2026-05-12
**Decision:** Each MCP tool is implemented as **two layers**: a pure async handler function in `src/opentext_pa_mcp/tools/handlers.py` that takes ``(catalog, client, **kwargs)``, and a `@mcp.tool`-decorated wrapper in `src/opentext_pa_mcp/server.py` that pulls catalog/client from the FastMCP lifespan context and forwards to the handler.
**Context:** FastMCP-decorated tools couple the code to a FastMCP `Context` object. Testing them requires running a FastMCP server. We want fast, fully-mocked unit tests with no FastMCP coupling.
**Alternatives considered:**
- Put all logic inside the `@mcp.tool` body — rejected: tests would need a FastMCP server + custom Context fakes for every test.
- Use module-level globals for catalog/client — rejected: bad for testability; impossible to run two servers in one process if we ever want to.
**Rationale:** Pure handlers compose with `respx`-mocked `httpx` cleanly, and tests run in milliseconds. The thin wrapper layer is dumb glue that's exercised by the integration test suite.

---

## DEC-011 — Read-only enforcement: at the `pa_api_call` boundary, not the HTTP client

**Date:** 2026-05-12
**Decision:** The read-only constraint is enforced inside the `pa_api_call` tool handler: non-GET methods raise `ReadOnlyViolationError` before any HTTP call. `AppworksClient.api_get` (the only HTTP method we expose on the client) is the only way other tools can talk to the network.
**Context:** v1.0 must not allow LLMs to mutate data even via the escape hatch.
**Alternatives considered:**
- Block writes at the HTTP-client level (e.g. an `if method != "GET"` check in `AppworksClient.request`) — rejected: we don't have a generic `request` method; every other tool uses the focused `api_get`. Defense at the only public write surface (`pa_api_call`) is sufficient.
- Reject writes server-side and let AppWorks return 405 — rejected: tool error responses are uglier than a clean `ReadOnlyViolationError` and it still consumes a network round-trip.
**Rationale:** Single-checkpoint enforcement at the boundary where mutating requests could plausibly enter the system. v1.1 will swap `_READ_METHODS` for a `config.allow_writes`-aware check.

---

## DEC-012 — HAL response flattening as an explicit phase-2 lite

**Date:** 2026-05-12
**Decision:** `query_list` and `list_children` flatten AppWorks's `_embedded.{ListName}` wrapper into `items`, expose `count`/`skip`/`top`/`next_skip` from the `page` block, drop empty `{Rel}$Properties: {}` keys, and keep `_links`. Deeper reshaping (renaming `_links.item.href` → `id`, stripping schema-name GUIDs from descriptions) is still phase-2.
**Context:** Live samples confirmed each list response wraps items in `_embedded.<ListName>` and ships a `page` envelope. Raw HAL is readable but token-heavy.
**Alternatives considered:**
- Pass the raw HAL response through unchanged — rejected: every LLM call would re-pay the `_embedded.LongListName` envelope cost.
- Full reshaping in v1.0 (rename keys, strip GUIDs, etc.) — rejected: more risk in v1.0, deferred to phase 2 once we have real LLM usage telemetry.
**Rationale:** Cheap, high-value flattening lands in v1.0; risky transformations wait until we see how the LLM actually consumes the data.

---

## DEC-013 — TLS configuration: `PA_VERIFY_TLS` + `PA_CA_BUNDLE`

**Date:** 2026-05-12
**Decision:** Add two optional env vars governing how `httpx` verifies AppWorks TLS:
- `PA_VERIFY_TLS` (default `true`) — set to `false` to skip cert verification entirely (insecure).
- `PA_CA_BUNDLE` (default unset) — path to a PEM file containing a custom/corporate CA bundle. When set, httpx uses it as its trust store. Mutually exclusive with `PA_VERIFY_TLS=false`.
A `Config.httpx_verify()` helper produces the value to pass to `httpx.AsyncClient(verify=...)`; a custom CA bundle wins over the boolean flag. When verification is disabled, the auth layer logs a WARNING at startup.
**Context:** On-prem AppWorks installs commonly use a corporate internal CA or self-signed certs. Without an escape hatch users hit `SSLError` on the first request and have no recourse short of installing the CA into the OS trust store (which they may not have admin rights to do).
**Alternatives considered:**
- Always trust whatever cert the server presents — rejected: defeats the purpose of TLS; one default for everyone is wrong.
- Custom `httpx.SSLContext` builder env var — rejected: too much config surface; the two-knob form covers ~99% of use cases.
- Probe and auto-disable on cert error — rejected: silently downgrading security is exactly the failure mode we want to avoid.
**Rationale:** Two narrow knobs with clear precedence. CA bundle is the right answer for prod (still secure, just with a different trust root); `PA_VERIFY_TLS=false` is a clearly-labelled emergency exit for dev/test. The contradictory-config check + WARNING log keep users from foot-gunning themselves silently.

---

## DEC-014 — Auth: strategy pattern with auto-detection (OTDS + Cordys built-in)

**Date:** 2026-05-14
**Decision:** Support two authentication backends behind a single `AppworksClient`: OTDS form login (the original v1.0 flow per DEC-007) and Cordys built-in SSO (SAML 1.1 SOAP + WS-Security UsernameToken). Selection is auto by default — inspect the redirected login page; OTDS pages contain `otdscsrf`/`RFA` form fields, Cordys built-in pages land on `wcp/sso/login.htm` with `id="username"`/`id="password"` fields and no CSRF token. An optional env var `PA_AUTH_MODE` (`auto` | `otds` | `cordys`, default `auto`, case-insensitive) overrides detection.
**Context:** The original v1.0 implementation (DEC-007) assumed OTDS-fronted AppWorks 23.x. A user reported (issue #2 on the public mirror) that AppWorks 25.1 "Process Automation CE" instances using Cordys built-in auth fail at startup with `AuthenticationError: Login page did not contain the expected csrf / RFA tokens`. Discovery against a live 25.1 instance confirmed a distinct three-step flow: (1) POST a SAML 1.1 `AuthenticationQuery` envelope with WSSE UsernameToken to `{base}/home/{tenant}/com.eibus.web.soap.Gateway.wcp`; (2) POST the returned `samlp:AssertionArtifact` as a `SAMLart` header to `{base}/home/{tenant}/wcp/sso/com.eibus.sso.web.authentication.AuthenticationToken.wcp`; (3) reuse the resulting `{tenant}inst_SAMLart` + `{tenant}inst_ct` cookies on subsequent API calls. Artifacts saved under `docs/research/artifacts/cordys-*.{html,xml}`.
**Alternatives considered:**
- Always require `PA_AUTH_MODE` to be set explicitly — rejected: users already have one env var (`PA_SERVICE_URL`) carrying enough info to disambiguate at runtime; another required knob is friction for the dominant single-platform case.
- Auto-detect only, no override — rejected: a third (currently unknown) login-page shape would dead-end users with no escape hatch; an override is cheap insurance.
- Probe `/com.eibus.web.soap.Gateway.wcp` for existence to decide — rejected: that path exists on OTDS-fronted instances too; the login page itself is the cleaner discriminator and we have to fetch it anyway.
**Rationale:** Strategy pattern lets the two flows coexist without entangling their state machines (the SOAP/SAML flow has nothing in common with the form-POST/redirect-chain flow). Auto-detect is correct for ~all users on either platform; the env-var override covers the long tail without imposing on the majority. Detection runs on the same GET we already make as login-step-1, so there is zero extra HTTP cost. Reference: `src/opentext_pa_mcp/auth.py` (post-implementation) and `tests/unit/test_auth_cordys.py`.

---

## DEC-009 — v1.0 scope: read-only

**Date:** 2026-05-12
**Decision:** v1.0 ships only read tools: `list_entities`, `describe_entity`, `list_named_lists`, `query_list`, `get_entity`, `list_children`, `get_child`, `list_relationship_targets`, plus `pa_api_call` as an escape hatch (still callable for GET; write methods rejected at the tool layer if `PA_ALLOW_WRITES` is unset). Write tools (`create_entity`, `update_entity`, `delete_entity`, `invoke_action`, child/relationship writes) ship in v1.1 behind `PA_ALLOW_WRITES=true`.
**Context:** AppWorks actions like `Submit`, `Accept`, `Complete`, `Share`, `Delete` are not idempotent and have real-world consequences (case submitted, document deleted, role granted). A misbehaving or jailbroken LLM should not be able to mutate by default.
**Alternatives considered:**
- All-tools-on by default with a `PA_READ_ONLY=true` flag — rejected: secure-by-default is the right posture; opt-in to dangerous mutations.
- Ship all tools in v1.0 without a flag — rejected: too risky for a tool that's seeing first use against real production case data.
**Rationale:** Read-only is the smallest useful v1 ("show me my cases", "what's in this category?"), it's the version we can validate fastest, and it sets the precedent that writes are an explicit opt-in. v1.1 is small — add the write tools and the gating flag.
