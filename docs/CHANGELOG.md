# Product Evolution Changelog

Narrative log of how the project reached its current state. New entries at the top.

---

## 2026-05-25 (later) — v0.3.0: auto-resolve business ids; translate Cordys BigInteger errors

Driven by a Copilot Studio failure on the deployed Container App: a customer pasted a `PolicyIntimation` request id (`PI2526-000102`) into chat, the LLM called `get_entity(entity='PolicyIntimation', item_id='PI2526-000102')`, and the AppWorks API returned `EXPRESSION_PARSE_BIGINTEGER_ERROR` (HTTP 500) because `/items/{id}` only accepts the internal BigInteger primary key visible inside `_links.item.href`. Claude on the same workload recovered by falling back to `query_list(search=...)`; Copilot did not and surfaced "technical error" to the end user.

**Decision in scope:** DEC-018 — the MCP encodes *platform invariants*, never per-entity semantics. The dual-id pain is a platform invariant (every entity has the same BigInteger PK / `_links.item.href` shape and the same DefaultList convention), so a single generic fix scales without naming entities, fields, or tenants.

**Changed (`src/opentext_pa_mcp/tools/handlers.py`):**
- New `_resolve_item_id(catalog, client, entity, item_id)` helper. Pass-through for all-digit ids. Otherwise GETs `/{entity}/lists/DefaultList?$search=<item_id>`, looks for items whose string `Properties.*` values equal the input exactly (case-insensitive), and extracts the internal int from `_links.item.href`. Single match wins; zero or many → structured error with the candidates so the LLM can re-query.
- `get_entity`, `list_children`, `get_child`, `list_relationship_targets` now route their `item_id` (and `child_id`) through the resolver. The raw `pa_api_call` escape hatch is deliberately untouched.

**Changed (`src/opentext_pa_mcp/auth.py`, `src/opentext_pa_mcp/errors.py`):**
- New `InvalidItemIdError` (subclass of `HttpError`) and `ItemIdResolutionError` (subclass of `AppworksError`).
- `_raise_or_parse` detects the `EXPRESSION_PARSE_BIGINTEGER_ERROR` marker in error response bodies and raises `InvalidItemIdError` with an actionable message naming the offending id and pointing to `_links.item.href`. The detection is keyed on the Cordys error vocabulary, not on endpoint, so any future caller that bypasses auto-resolution still gets a useful response.

**Changed (`src/opentext_pa_mcp/server.py`):**
- Tool descriptions for `get_entity`, `list_children`, `get_child`, `list_relationship_targets` now name the dual-id convention and the auto-resolution behaviour.
- Server `instructions` (both stdio + http transports) carry the convention up front, so even LLMs that never read the per-tool docs (some Copilot connectors) learn the rule once at session start.
- `_dispatch` adds dedicated mappings for `InvalidItemIdError` → `{"kind": "invalid_item_id", "attempted_id": ..., ...}` and `ItemIdResolutionError` → `{"kind": "item_id_resolution_failed", "attempted_id": ..., "entity": ..., "candidates": [...]}`.

**Tests (per Rule 0, written first):**
- `tests/unit/test_id_resolver.py` — eight cases: digit pass-through, single-match resolution (exact Properties match wins), zero matches, ambiguous multi-match (error lists candidates), exact-vs-partial-match disambiguation, plus equivalent parent-id resolution for `list_children` and parent+child for `get_child`.
- `tests/unit/test_error_translation.py` — three cases: the BigInteger marker remaps to `InvalidItemIdError`, the new class is still an `HttpError` (so existing catch-broadly callers keep working), and unrelated 500s are left as plain `HttpError` (the translator must not over-reach).

---

## 2026-05-25 — v0.2.2: harden the API auth path + add response diagnostics

Patch release driven by a real Copilot Studio failure against the hosted Container App. The Power Platform connector surfaced `Error calling tool 'query_list': Expecting value: line 1 column 1 (char 0)` after a few minutes of idle. Container logs confirmed the exception originated server-side in our `_raise_or_parse` → `resp.json()` path; the response body that triggered it was never captured. The most plausible cause — an AppWorks session-expiry redirect resolving to `200 + text/html` because `httpx` follows redirects — fit the timeline but was **not proven**. AppWorks session cookies in this tenant are valid for 24h, which weakens the idle-expiry story; the underlying trigger could also be a stale connection-pool entry, a transient backend error returning HTML with 200, or something on the network path between Azure Container Apps and the AppWorks instance.

**Changed (`src/opentext_pa_mcp/auth.py`):**
- `api_get` now treats `(2xx + non-JSON Content-Type)` as a stale-session signal in addition to the existing 401 path. On either signal it invalidates `_authenticated`, re-runs the configured login flow, and retries the GET once. If the retry **also** returns non-JSON, it raises `AuthenticationError` with a clear message instead of letting `JSONDecodeError` bubble up.
- Two helpers, `_is_non_json_success` and `_looks_like_session_expired`, factor the detection logic out of `api_get`.
- Diagnostic logging on three paths so the next recurrence captures what AppWorks actually returned:
  - `INFO` on the session-expired signal: `status`, `content-type`, `content-length`, `body[:200]`.
  - `WARNING` when the retry after re-login still returns non-JSON: same fields with `body[:500]`.
  - `WARNING` in `_raise_or_parse` if `resp.json()` raises despite a JSON Content-Type — catches malformed-payload cases that the Content-Type check would let through. The original `JSONDecodeError` is re-raised after logging.
- New `_body_preview` helper bounds the logged body at the chosen char limit (200 or 500) and falls back to `repr(content)` for non-text payloads, keeping container logs bounded and limiting PII exposure.

**Tests (`tests/unit/test_auth.py`):**
- `test_200_with_html_body_triggers_re_login_and_retries` — mirror of the existing 401-retry test, but the first response is `200 + text/html`. Asserts the client re-runs the full login chain and returns the second response's JSON.
- `test_persistent_html_after_retry_raises_auth_error` — backend keeps expiring the session. Asserts we raise a clean `AuthenticationError`.

**Honest framing:** the defensive fix only solves one specific failure mode. The diagnostic logging is the bigger value — when the failure recurs against the redeployed container, the log lines will reveal whether the response was an OTDS/Cordys login page (defensive fix was on target), an HTML error page (server-side issue), a truncated JSON payload (network/pool issue), or something else.

**Deployment note:** existing Container App deployments pick up the fix on the next image pull. If you pinned `imageTag` to `0.2.1`, redeploy the ARM template with `imageTag=0.2.2`. If you deployed with `imageTag=latest`, restart the revision to force a re-pull.

---

## 2026-05-21 (later) — v0.2.1: README links to the Copilot deployment guide

Patch release. The root `README.md` hosted-deployment section now links to `docs/azure-copilot-deployment-guide.md`, so anyone connecting the server to Microsoft Copilot or Teams lands on the end-to-end walkthrough directly. No `src/` changes. This release also deliberately exercises the full delivery path — feature branch → PR to DEV → PR to main → public-repo sync → automatic PyPI publish — to validate the CI/CD chain.

---

## 2026-05-21 — v0.2.0 public release: container image moves to the public account

The Azure Container Apps deployment path is promoted to `main` and the public mirror. It was verified end-to-end first: a one-click deployment was exercised from the SIT branch, and a Microsoft Copilot Studio agent successfully queried live `PolicyIntimation` records through the deployed MCP server against a real AppWorks tenant.

**Changed** (see `DEC-017`): the OCI image is now published to `ghcr.io/amitagl27/opentext-pa-mcp` — the same account as the public repo — instead of `ghcr.io/tlcfworks/process-automation-mcp`. `publish-image.yml` still runs in the private `tlcfworks` repo but logs in to GHCR with the `amitagl27` PAT (`DESTINATION_REPO_PAT`) so the package lands under the public account and links to the public repo. `azuredeploy.json`, `deploy/azure/README.md`, the Dockerfile, the Power Platform connector, the root `README.md`, and the new deployment guide all reference the new path.

**Added:**
- `docs/azure-copilot-deployment-guide.md` — end-to-end walkthrough: one-click Azure deploy, Power Platform custom connector, Copilot agent creation, test/publish, and a troubleshooting table built from the issues hit during the first real wiring.

Merging this to `main` triggers the public-repo sync, builds the image under `amitagl27`, and publishes `0.2.0` to PyPI.

---

## 2026-05-16 — Deployment pivot: Azure Container Apps replaces Hugging Face Space

Brief detour to wire up Microsoft Copilot Studio against the v0.2.0 HTTP-mode server exposed the structural problem with the original deployment shape. A shared MCP on a public host (Hugging Face Space) only works in a multi-tenant world if Copilot Studio can pass the per-tenant AppWorks URL at request time — and Power Platform's MCP custom-connector path ignores additional `securityDefinitions` beyond the primary one (Basic Auth), so it cannot. The two visible workarounds (pin a single tenant via env var on the public Space, or stand up our own OAuth / DCR layer in front of the MCP) each forced an unwanted property — single-tenancy in the first case, full-public-internet AppWorks exposure in the second.

**Approach** (see `DEC-016`): Stop trying to host a single shared MCP. Ship the MCP as a public container image (`ghcr.io/tlcfworks/process-automation-mcp`) and an ARM template + Deploy-to-Azure button under `deploy/azure/`. Each customer deploys their own Container App into their own Azure subscription, pins their AppWorks URL via env var, and customises the Power Platform connector under `deploy/copilot-studio/connector.yaml` to point at their app's FQDN. AppWorks never leaves the customer's network — the Container App egresses to it privately (VNet integration / Private Link / VPN) while Copilot Studio talks to the MCP over public HTTPS.

**Shipped:**
- `deploy/azure/Dockerfile` — multi-stage build from repo source; runtime image installs the freshly-built wheel as a non-root user, listens on `:7860` in HTTP transport mode (`PA_TRANSPORT=http`, `PA_HTTP_HOST=0.0.0.0`).
- `deploy/azure/azuredeploy.json` — ARM template provisioning a Log Analytics workspace, Container Apps Environment, and Container App pulling the pinned image tag. Required parameter `paServiceUrl`; optional `paAuthMode`, `paLogLevel`, `imageTag`, `minReplicas`, `maxReplicas`. Outputs the deployed FQDN and the `/mcp` endpoint URL.
- `deploy/azure/azuredeploy.parameters.json` — example parameters file customers copy and edit before deploying from the CLI.
- `deploy/azure/README.md` — Deploy-to-Azure badge, prerequisites (Azure subscription, AppWorks reachability from Container Apps egress, required AppWorks role), post-deploy connector setup walkthrough.
- `.github/workflows/publish-image.yml` — GitHub Action that builds and pushes to GHCR on tag (`v*`) and `main` pushes. Tags: full semver, `major.minor`, `latest` from `main`.
- `deploy/copilot-studio/connector.yaml` — `host:` rewritten to a placeholder customers must replace; description rewritten for the customer-hosted model.
- `README.md` — Deploy section now points at `deploy/azure/README.md` as the production path for hosted MCP clients (Copilot Studio).

**Retired:**
- `deploy/huggingface/` — the Space, its Dockerfile, HOWTO, and bundled wheel are gone. The corresponding `.gitignore` line is removed. Anyone who wants a public demo can `docker run ghcr.io/tlcfworks/process-automation-mcp:latest` locally or spin up a sandbox Container App from the same template.

**Out of scope (deliberately deferred):**
- OAuth 2.0 / OBO SSO via Entra ID ↔ OTDS federation — natural next step but depends on a customer environment with OTDS already federated to Entra. Tracked as a follow-up once such an environment is available to validate against.
- A future v0.3 PyPI release that switches the Dockerfile from "build wheel from source" to `pip install opentext-pa-mcp>=0.3` — the multi-stage build already covers source builds, so this is bookkeeping rather than a blocker.

**No `src/` changes** — this milestone is deployment artefacts and docs only. Existing v0.2.0 HTTP transport + per-request credentials code already supports the customer-hosted topology (single `PA_SERVICE_URL` default + Basic Auth header passthrough).

---

## 2026-05-15 (evening) — v0.2.0: HTTP transport + per-request credentials

Users want to plug this MCP into Microsoft Copilot Studio and other hosted MCP clients that can only consume MCP servers over HTTPS (not by spawning a stdio subprocess). They also want each end-user's *own* AppWorks credentials to drive *their* requests, so AppWorks audit trails and per-user security-building-block enforcement remain intact. The v0.1.x design (one process per user, credentials from env vars at startup) was fundamentally incompatible with both of those requirements.

**Approach** (see `DEC-015`): one repo, one package, new `PA_TRANSPORT=stdio|http` switch. Stdio is unchanged. In HTTP mode the server runs FastMCP's Streamable HTTP transport on `PA_HTTP_HOST:PA_HTTP_PORT` (defaults `127.0.0.1:8000`) and reads tenant credentials from each MCP request's headers — `Authorization: Basic <base64(user:pass)>`, `X-PA-Service-URL: <url>`, optional `X-PA-Auth-Mode: auto|otds|cordys`. A process-local in-memory `SessionCache` keyed on `(service_url, username)` reuses already-authenticated `AppworksClient`s and their warm catalogs across successive requests from the same user, so OTDS/Cordys login + OpenAPI discovery only run once per user per restart.

**Shipped:**
- `src/opentext_pa_mcp/config.py` — `transport`, `http_host`, `http_port` fields + parsers; in `http` mode the tenant fields (`service_url`, `username`, `password`) become **optional defaults** rather than required startup vars.
- `src/opentext_pa_mcp/session_cache.py` — `Session` + `SessionCache` (asyncio-lock-protected, factory-injectable for tests, half-built sessions closed cleanly on discovery failure so retries don't leak clients).
- `src/opentext_pa_mcp/request_config.py` — `build_request_config(headers, defaults)` merges Authorization / `X-PA-Service-URL` / `X-PA-Auth-Mode` headers with server defaults; all parse failures raise `AuthenticationError` for clean MCP-layer translation.
- `src/opentext_pa_mcp/server.py` — split lifespan into `StdioAppContext` (existing single-session) and `HttpAppContext` (defaults + cache); new `_resolve_session(ctx)` returns the right `(catalog, client)` for the current request; tool wrappers collapsed onto a single `_dispatch` helper.
- `src/opentext_pa_mcp/__main__.py` — honours `config.transport`, runs `server.run(transport="streamable-http", host=..., port=...)` when http.
- `tests/unit/test_config.py` — 17 new tests under `TestTransport` covering parsing, validation, and the http-mode optional-tenant-fields branch.
- `tests/unit/test_session_cache.py` — 9 new tests covering keying, concurrent first-time callers (single shared session via `asyncio.Lock`), close semantics, and discovery-failure isolation.
- `tests/unit/test_request_config.py` — 21 new tests covering Basic-auth parsing, header → Config merge, service-URL precedence, auth-mode override, server-default fallbacks, and password redaction in `repr`.
- `tests/unit/test_server_http_mode.py` — 6 new tests covering `_resolve_session` routing: stdio short-circuits (`get_http_headers` must not be called), http mode resolves per-request, same user reuses session, different users / different URLs get isolated sessions, missing auth raises cleanly.

**Quality gates that held:**
- `ruff check src tests` — clean.
- `pyright src tests` — TBD final run before tagging.
- 172 unit tests passing (previously 112; the 60 new ones cover the new module surface).
- No regression in existing OTDS / Cordys auth paths — the strategy dispatcher is unchanged; per-request `Config` plugs in *above* it.

**Out of scope (deliberately deferred to a later release):**
- OAuth / Entra bearer-token mode — natural future addition once we see customer demand and confirm OTDS federation availability per deployment.
- Distributed session cache (Redis / Memcached) — current cache is process-local and fine for single-replica deployments; multi-replica is not yet a stated need.
- Cordys-specific deployment recipe under `docs/integrations/copilot-studio/` — the connector YAML and deployment screenshots will land in a follow-up doc PR.

---

## 2026-05-15 (later) — Docs: required AppWorks role + folder reorganisation

While investigating public-mirror issue #1 ("server doesn't start without Developer Role"), we walked the deployed `entityRestService` webapp and the embedded `entityCore.jar` and found the exact gate: `EntityRestResourceService.getAPI()` does an `isInRole("OpenText Entity Runtime#Entity REST API Developer")` check before serving `/api/{Service}/docs`. Per OpenText's own documentation the role only grants the API *channel* (URL access + Swagger doc visibility) — it does **not** bypass entity-level Security / Sharing building blocks. So granting it adds no real data exposure beyond what the user already has via their functional roles.

**Outcome:** documented the requirement in `README.md` under "Required AppWorks role" with the exact role string and the reassurance text from OpenText's own docs. No code change. Issue #1 closeable as "configuration requirement, not a bug."

**Folder reorg landed in the same commit:**
- Root-level `research/` retired. `research/DECISIONS.md` → `docs/DECISIONS.md`, `research/CHANGELOG.md` → `docs/CHANGELOG.md`. All project documentation now lives under `docs/`.
- New `docs/fromcustomer/` directory for vendor- and customer-supplied reference material (platform docs, decompiled webapps, env probes). Gitignored — used during investigation, never shipped in the public repo.
- `CLAUDE.md` Rule 1 updated to match. `DEC-008` carries a 2026-05-15 supersession note for the same reason.

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

Project-level decisions locked today (see `docs/DECISIONS.md`):
- DEC-001…007 — language, transport, distribution, config shape, tool design, spec discovery, auth.
- DEC-008 — Python-native repo layout (`src/`, `tests/`, `pyproject.toml` at root) instead of the template's `codebase/` wrap.
- DEC-009 — v1.0 is read-only; writes ship in v1.1 behind `PA_ALLOW_WRITES=true`.

Project conventions adopted: TDD non-negotiable (`CLAUDE.md` Rule 0), promotion-based branching `feature → DEV → SIT → main` (`CONTRIBUTING.md`), and four authoritative sources of truth (`CLAUDE.md` Rule 2).

Next: scaffold `pyproject.toml`, the empty `src/opentext_pa_mcp/` package, and the first failing tests for the OTDS auth layer and the OpenAPI-from-HTML extractor.
