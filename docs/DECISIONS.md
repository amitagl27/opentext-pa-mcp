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
**Update (2026-05-15):** The root-level `research/` folder has been retired and its `DECISIONS.md` + `CHANGELOG.md` moved to `docs/DECISIONS.md` and `docs/CHANGELOG.md`. Discovery artifacts continue to live under `docs/research/`. The Python-native spirit of this decision is unchanged — only the location of decision/changelog files has consolidated under `docs/`. See `CLAUDE.md` Rule 1.
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

## DEC-015 — HTTP transport + per-request credentials for hosted deployments

**Date:** 2026-05-15
**Decision:** Add a Streamable HTTP transport behind a new `PA_TRANSPORT=stdio|http` env var (default `stdio`). In HTTP mode the server does **not** read tenant credentials from environment variables at startup; instead each MCP request carries them as HTTP headers:

- `Authorization: Basic <base64(username:password)>` — required.
- `X-PA-Service-URL: <full entity-service URL>` — required (or pre-set via `PA_SERVICE_URL` for single-tenant deployments).
- `X-PA-Auth-Mode: auto|otds|cordys` — optional, overrides `PA_AUTH_MODE`.

A process-local in-memory `SessionCache` keyed on `(service_url, username)` reuses warm `AppworksClient` instances (and their already-discovered `EntityCatalog`) across successive requests from the same user. Two new env vars `PA_HTTP_HOST` (default `127.0.0.1`) and `PA_HTTP_PORT` (default `8000`) bind the HTTP listener. Stdio mode is unchanged — the v0.1.x install story for Claude Desktop / Claude Code continues to work as documented.

**Context:** Users (issue tracked outside the repo) want to plug this MCP into hosted clients — Microsoft Copilot Studio, custom web agents, internal portals — that can only consume MCP servers over HTTP, not by spawning a subprocess over stdio. They also want each end-user's *own* AppWorks credentials to authorise *their* requests, so audit trails, permissions, and security building-block enforcement at AppWorks remain user-scoped (not service-account-scoped). The original `PA_USERNAME` / `PA_PASSWORD` env-var model assumed one process per user — fundamentally incompatible with a long-lived hosted server.

**Alternatives considered:**
- **Fork into a separate `opentext-processautomation-mcp-copilot` repo** — rejected: ~95 % of the code (discovery, catalog, OTDS + Cordys auth strategies, tools, error model, TLS handling) is identical across the two flavours. Maintaining two repos doubles patch surface for every bug fix (the Cordys auth fix shipped in v0.1.3 would have to land twice) and creates documentation / version confusion. Industry pattern in the wider MCP ecosystem (GitHub MCP, Pulumi MCP, Notion MCP, the Anthropic-maintained `modelcontextprotocol/servers`) is one repo with transport selected at runtime.
- **OAuth 2.0 / OIDC bearer tokens via Entra ID** — rejected for v1: only works when OTDS is configured as a SAML/OIDC federation endpoint with Entra (a deployment-specific config the user may not control). Many AppWorks 23.x customers only have OTDS form-login with Entra-synced *passwords*, not federated identity. Bearer mode is a natural future addition once the per-request auth pathway exists.
- **Per-tool-call credential arguments** — rejected: leaks credentials into the LLM's conversation history and tool-call traces; pollutes every tool signature.
- **Distributed session cache (Redis / Memcached)** — rejected for v1: overkill for the single-process deployment model; sessions are cheap to rebuild on restart (one OTDS or SAML login + one OpenAPI discovery, ~1-2 s). Can be added later behind an abstraction if multi-replica deployments emerge.
- **Bind to `0.0.0.0` by default** — rejected: surprising default for a server that previously only ran on a user's laptop. `127.0.0.1` is the safer default; deployment hosts override with `PA_HTTP_HOST=0.0.0.0` explicitly.

**Rationale:** A single env-var switch (`PA_TRANSPORT`) keeps the v0.1.x stdio experience pristine while unlocking hosted deployments without forking. Per-request HTTP Basic auth is the lowest-common-denominator scheme — works with any MCP client that supports Power Platform custom connectors / generic HTTP MCP clients, and lines up directly with the same OTDS + Cordys credentials AppWorks already accepts (no new auth surface in AppWorks itself). The session cache makes repeat requests cheap (one OTDS login per user per service instead of per call). Failure responses on the auth path raise `AuthenticationError`, which the tool-layer error translator already maps to a structured response — clients get a clean `"AuthenticationError"` reply rather than an HTTP 500. Reference: `src/opentext_pa_mcp/{config,session_cache,request_config,server}.py`, `tests/unit/test_{config,session_cache,request_config,server_http_mode}.py`.

---

## DEC-016 — Deployment: customer-hosted Azure Container Apps as the primary target

**Date:** 2026-05-16
**Decision:** Distribute the HTTP-mode MCP server as a public OCI image at `ghcr.io/tlcfworks/process-automation-mcp` and ship an ARM template + Deploy-to-Azure button under `deploy/azure/`. Each customer deploys their own instance into their own Azure subscription, pins their AppWorks tenant via the `PA_SERVICE_URL` env var on the Container App, and imports the Power Platform custom connector under `deploy/copilot-studio/connector.yaml` after replacing the `host:` line with their app's FQDN. The previously-used Hugging Face Space (`deploy/huggingface/`) is retired in the same change.
**Context:** Hosting a single shared MCP server on a public platform (HF Space) forced the network chain `user (corp VPN) → Copilot Studio (corp cloud) → MCP (public internet) → OTDS/AppWorks (?)` to traverse the public internet purely because of where the MCP lived. Pinning the AppWorks URL via env var on the public host worked technically but ruled out multi-tenancy. Power Platform's MCP custom-connector path also ignores additional `securityDefinitions` beyond the primary scheme (Basic Auth), so it cannot pass a per-tenant URL header from Copilot Studio. The combination forced a choice: either build a multi-tenant SaaS with its own auth (large project), or move hosting into each customer's own network.
**Alternatives considered:**
- Stay on the public HF Space, pin a single tenant — rejected: violates the multi-tenant requirement and forces the customer's AppWorks onto the public internet.
- Stand up an OAuth 2.0 / Dynamic Client Registration layer in front of the public MCP — rejected: still leaves the AppWorks ↔ MCP hop crossing the public internet, doesn't solve the topology problem, and requires OTDS-to-Entra federation that many customers don't have. Worth revisiting in a later decision once SSO is the focus.
- Power Platform On-Premises Data Gateway — rejected as the primary path: adds an opaque proprietary hop, requires a gateway machine on-prem, and only helps customers fully invested in Power Platform's gateway model. Still viable as a documented fallback for customers who can't use Azure.
- Customer builds their own container infra from the published Docker image, without Azure templates — rejected as primary: viable for cloud-savvy customers but high-touch for everyone else. The published image (`ghcr.io/tlcfworks/process-automation-mcp`) supports this path; the ARM template just makes it one click.
**Rationale:** Customer-hosted Azure Container Apps collapses the network chain to a single VNet — the MCP can reach on-prem AppWorks privately (Private Link / VPN / ExpressRoute), Copilot Studio talks to the MCP over public HTTPS, and AppWorks itself never leaves the customer's perimeter. Single-tenant per deployment matches the existing `PA_SERVICE_URL` model exactly; no `src/` code changes needed for this pivot. Distribution via a Deploy-to-Azure button + ARM template is a well-understood pattern that costs the customer near-zero on the Container Apps consumption plan and costs us nothing to publish. SSO via OAuth/OBO is naturally additive on top of this topology — defer to a follow-up decision when a customer environment with OTDS federated to Entra is available to validate against.

**Update (2026-05-21):** the published image namespace moved from `ghcr.io/tlcfworks/process-automation-mcp` to `ghcr.io/amitagl27/opentext-pa-mcp` — see DEC-017.

---

## DEC-017 — Container image published under the public-mirror account (amitagl27)

**Date:** 2026-05-21
**Decision:** Publish the OCI image to `ghcr.io/amitagl27/opentext-pa-mcp` (the public-mirror account) instead of `ghcr.io/tlcfworks/process-automation-mcp`. `publish-image.yml` still runs in the private `tlcfworks` repo, but logs in to GHCR with the `amitagl27` PAT (`DESTINATION_REPO_PAT` — the same secret `sync-public.yml` already uses) so the package lands under the public account. `azuredeploy.json` and every deploy doc reference the new path.
**Context:** The Deploy-to-Azure button and the whole public deployment story live in the public repo `amitagl27/opentext-pa-mcp`. An image namespaced under `tlcfworks` — a private account external users never see — on a public repo's one-click button is confusing and leaves the public repo not self-contained. The image belongs under the same account as the public repo.
**Alternatives considered:**
- Keep the image at `ghcr.io/tlcfworks/process-automation-mcp` — rejected: works, but leaves a private-account namespace on public-facing artifacts.
- Add a second `publish-image.yml` to the public repo so its own `GITHUB_TOKEN` builds the image — rejected: the public repo's `.github/` is hand-maintained (the sync strips it), so this splits image-build config across two repos. Cross-pushing from the single workflow in `tlcfworks` keeps it single-sourced and version-controlled.
**Rationale:** Reuses the existing `DESTINATION_REPO_PAT`, keeps all CI config in `tlcfworks/DEV`, and makes the public repo's deploy button reference an image in its own account. Requires that PAT to carry the `write:packages` scope. Supersedes the registry choice in DEC-016.

---

## DEC-018 — MCP encodes platform invariants, not entity-specific semantics

**Date:** 2026-05-25
**Decision:** When AppWorks behaviour bites the LLM — e.g. `/items/{id}` rejecting `PI2526-000102` with `EXPRESSION_PARSE_BIGINTEGER_ERROR` because the path expects the internal BigInteger primary key, not the human-readable business id — the fix lives in the MCP **only if it follows from a platform invariant** (a rule that holds for every entity on every tenant). Hard-coded per-entity / per-field / per-tenant logic stays out. Concretely, three things landed in this release: (1) a generic item-id resolver in `handlers.py` that passes through all-digit ids and otherwise searches DefaultList for an exact, case-insensitive Properties match before extracting the int from `_links.item.href`; (2) an HTTP-layer translator in `auth.py` that maps the `EXPRESSION_PARSE_BIGINTEGER_ERROR` marker to `InvalidItemIdError` with an actionable message; (3) tool descriptions + server `instructions` that name the dual-id convention so even less-capable LLMs (e.g. Copilot Studio) learn the rule once.
**Context:** A real Copilot Studio session passed a customer's RequestID to `get_entity`, the server returned an opaque 500, and Copilot surfaced "technical error" to the end user. Claude on the same data was clever enough to fall back to `query_list($search=...)` and recover, but the workaround returns the list-view item, not the full entity detail. The dual-id trap is not specific to PolicyIntimation — every entity exposes the same BigInteger PK / `_links.item.href` shape, so the fix scales without naming entities.
**Alternatives considered:**
- Just improve the error message and rely on the LLM to retry. Rejected: protects Claude but leaves Copilot users stuck — many LLM clients don't perform multi-step recovery.
- Hard-code per-entity "business id field" mappings (e.g. `PolicyIntimation → RequestID`). Rejected: doesn't scale across 700+ endpoints and breaks the moment a tenant adds a new entity; this is exactly the entity-specific logic this DEC rules out.
- Add a new `resolve_item_id` tool. Rejected: pushes the dual-id trap onto the LLM instead of solving it; auto-resolution inside `get_entity` is a strictly better surface.
**Rationale:** The MCP's job is to encode the rules of the *platform* (HAL shape, OpenAPI tag = entity, DefaultList convention, BigInteger PK invariant, Cordys error vocabulary) so every client benefits without per-tenant configuration. The line "if I'm writing `if entity_name == 'PolicyIntimation'` I've crossed the line" is now on record. Future platform-shaped gotchas (e.g. additional `EXPRESSION_PARSE_*` codes, new HAL shapes) extend the translator in one place and benefit every tool.

---

## DEC-009 — v1.0 scope: read-only

**Date:** 2026-05-12
**Decision:** v1.0 ships only read tools: `list_entities`, `describe_entity`, `list_named_lists`, `query_list`, `get_entity`, `list_children`, `get_child`, `list_relationship_targets`, plus `pa_api_call` as an escape hatch (still callable for GET; write methods rejected at the tool layer if `PA_ALLOW_WRITES` is unset). Write tools (`create_entity`, `update_entity`, `delete_entity`, `invoke_action`, child/relationship writes) ship in v1.1 behind `PA_ALLOW_WRITES=true`.
**Context:** AppWorks actions like `Submit`, `Accept`, `Complete`, `Share`, `Delete` are not idempotent and have real-world consequences (case submitted, document deleted, role granted). A misbehaving or jailbroken LLM should not be able to mutate by default.
**Alternatives considered:**
- All-tools-on by default with a `PA_READ_ONLY=true` flag — rejected: secure-by-default is the right posture; opt-in to dangerous mutations.
- Ship all tools in v1.0 without a flag — rejected: too risky for a tool that's seeing first use against real production case data.
**Rationale:** Read-only is the smallest useful v1 ("show me my cases", "what's in this category?"), it's the version we can validate fastest, and it sets the precedent that writes are an explicit opt-in. v1.1 is small — add the write tools and the gating flag.
