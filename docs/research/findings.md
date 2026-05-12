# Discovery findings

Final results of the discovery phase against `api.example.com:3381`. All claims below are backed by saved artifacts under `artifacts/`.

## 1. Platform & version

- **AppWorks Platform** (Cordys lineage), not the newer OT Process Automation Cloud Edition.
- Runtime version: **23.4** (login page assets at `v=23.4.0.7446`).
- Admin tooling version: **25.1** (from `ADMIN.version` on `/home/exampletenant/app/admin`).
- Tenant: `exampletenant`.

## 2. API protocol

- The entity service exposes a **Swagger UI** at its base URL, powered by an **inline OpenAPI 3.0.1** spec.
- Earlier OData-only assumption was wrong: this is a REST-with-HAL API, fully described by an OpenAPI document.
- The spec **is not at a separate URL** — it is embedded in the Swagger UI HTML page as a JS variable: `var dyn_spec_obj = {...}`. The MCP server's discovery step must fetch the HTML, locate the variable assignment, and brace-match the JSON.
- No security scheme declared in the spec (`components.securitySchemes` is empty). Auth is enforced out-of-band by AppWorks cookies.
- Server URL declared in the spec: **`/home/exampletenant/app/entityRestService/api`**.

## 3. Auth pattern (confirmed end-to-end and reproducible)

OTDS SAML-like login over four HTTP steps. See `artifacts/Login-Appworks.ps1` for a working reference implementation.

| Step | Method | URL                                                                                  | Inputs                                                                              | Result |
|------|--------|--------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|--------|
| 1    | GET    | `:3381/home/exampletenant/app/entityservice/ExampleLegalManagement`                      | none                                                                                | Redirect chain → OTDS login page on `:2281`. HTML form, contains `otdscsrf` token + `RFA` JWT-like token. Pre-auth `defaultinst_AuthContext` cookie set on `:3381`. |
| 2    | POST   | `:2281/otdsws/login?RFA=…`                                                           | `otds_username`, `otds_password`, `otdscsrf`, `RFA`, `fragment=""`, `authhandler=""`. **NB:** field names are `otds_username` / `otds_password`, not `username` / `password` — common pitfall. | HTML with auto-submit `<form>` containing hidden `OTDSTicket` (~850 chars). |
| 3    | POST   | `:3381/home/exampletenant/com.eibus.sso.otds.TicketConsumerService.wcp?AuthContext=…&RelayState=…` | `OTDSTicket=…`                                                                      | Final response is the actual protected resource. Three cookies set on `:3381`: `defaultinst_AuthContext` (durable session), `defaultinst_SAMLart` (short-lived artifact), `defaultinst_ct` (UUID context). |
| 4    | …      | Subsequent API calls                                                                 | Send all three cookies                                                              | On 401, re-run from step 1.                                                                                                                                       |

**For the MCP server:** ship a small `OtdsClient` (a `httpx.AsyncClient` subclass or wrapping helper) that does this dance on first use and on 401. Credentials come from env vars `PA_USERNAME` / `PA_PASSWORD`.

## 4. Scale — `ExampleLegalManagement` service

| Metric                       | Value |
|------------------------------|------:|
| Tags (business entities)     | 28    |
| Unique URL paths             | 586   |
| Total operations             | 793   |
| GET                          | 282   |
| POST                         | 367   |
| PUT                          | 68    |
| DELETE                       | 76    |
| Schemas in `components`      | 652   |

Top entities by operation count: **LegalCase (175), DRD_Case (147), MM_MatterManagement (87), LegalLitigation (47), LegalCourtSummon (31)**. Full list of 28 entities saved in `openapi.json`.

This confirms the original concern — **auto-generating one MCP tool per operation is infeasible.** Modern LLMs degrade beyond ~30–60 tools; 793 is an order of magnitude past that.

## 5. URL pattern (highly uniform)

Every entity follows the same shape. Five sub-patterns observed:

```
1. Entity collection
   POST  /entities/{Entity}                       create
   (note: no GET — listing is via /lists/{ListName} below)

2. Entity item
   GET   /entities/{Entity}/items/{id}
   PUT   /entities/{Entity}/items/{id}
   DELETE /entities/{Entity}/items/{id}

3. Named lists (the AppWorks equivalent of search / GET-all)
   GET   /entities/{Entity}/lists/{ListName}      e.g. DefaultList, MyCaseList
   POST  /entities/{Entity}/lists/{ListName}      dynamic search (criteria in body)
   GET   /entities/{Entity}/childEntities/{Child}/lists/{ListName}

4. Child entities (nested up to several levels deep)
   GET   /entities/{Entity}/items/{id}/childEntities/{Child}
   POST  /entities/{Entity}/items/{parentId}/childEntities/{Child}
   GET   /entities/{Entity}/items/{parentId}/childEntities/{Child}/items/{id}
   ...recursively for Email→Contents→MarkupFiles

5. Relationships (many-to-many references)
   GET    /entities/{Entity}/items/{id}/relationships/{Rel}
   POST   /entities/{Entity}/items/{id}/relationships/{Rel}            add target
   DELETE /entities/{Entity}/items/{id}/relationships/{Rel}/targets/{targetId}

6. Custom actions (lifecycle / domain operations)
   POST  /entities/{Entity}/items/{id}/actions/{Action}                e.g. Submit, Accept, Complete
   POST  /entities/{Entity}/items/{id}/{Property}/actions/{Action}     e.g. File/Upload, Sharing/Share
   POST  /entities/{Entity}/items/{id}/TaskList/actions/TaskTypes      action namespaces
```

Common actions observed (count of distinct entities supporting each):

- Sharing: `Share`, `Unshare`, `ShareWithIdentities`, `UnshareWithIdentities`, `AssignableRoles` — **30 entities each**
- Documents: `Upload`, `Download`, `Checkout`, `CheckIn`, `DeleteDocument`, `Properties`, `AddFile`, `AddFolder` — 7–8 entities each
- Lifecycle: `Submit`, `Accept`, `Resubmit`, `Complete`, `SendEmail`, `InitiateActivityFlow`

The uniformity is the key insight: **the entire 793-operation surface collapses to ~16 URL templates parameterised by entity/list/relationship/action names.** A small set of generic tools, each taking the entity name as an argument, can drive the whole thing.

## 6. Operation metadata (spec quality)

Per operation, the OpenAPI doc provides:

- `tags` — single element = the parent entity name (good)
- `summary` — short human description (e.g., "Create LegalCase item")
- `description` — longer description (often useful)
- `parameters` — fully typed with `name`, `in`, `required`, `schema`, `description`
- `requestBody.content."application/json".schema` — `$ref` to a component schema
- `responses` — `200`/`201` with content-types and schemas; generic `400`/`500`
- **No `operationId` populated** — auto-generated tool names from operationIds won't work; the MCP server must synthesise names from `{tag} + {verb} + {sub-pattern}`.

Schema naming is noisy: `{Entity}_{32-char hex GUID}_{Operation}_{Req|Res}` (e.g., `LegalCase_000C29DBA92EA1EF8BB26F1F0DD4660C_Create_Req`). The GUID is an AppWorks model identifier — **strip it before showing schemas to the LLM**.

## 7. Live response shape (`lists/DefaultList`, HAL-style)

Sample query: `GET /home/exampletenant/app/entityRestService/api/ExampleLegalManagement/entities/LegalCategory/lists/DefaultList?$top=2`

```json
{
  "page": { "skip": 0, "nextSkip": 2, "top": 2, "count": 2, "ftsEnabled": false },
  "_links": {
    "self":  { "href": "/ExampleLegalManagement/entities/LegalCategory/lists/DefaultList?$top=2" },
    "first": { "href": "..." },
    "next":  { "href": "..." }
  },
  "_embedded": {
    "DefaultList": [
      {
        "_links": { "item": { "href": "/ExampleLegalManagement/entities/LegalCategory/items/24" } },
        "Properties": {
          "Name": "Mergers & Acquisitions",
          "Description": "...",
          "Status": true
        },
        "LegalCategoryLegalPracticeArea$Properties": { "Name": "Litigation" }
      }
    ]
  }
}
```

Observations:

- HAL envelope: `page` + `_links` + `_embedded.{ListName}` wrapping the real array.
- Each item has a HATEOAS `_links.item.href` (canonical URL — useful as an ID), a `Properties` object (business fields), an optional `Tracking` object (audit), and zero-or-more `{RelationshipName}$Properties` aggregations.
- **Polymorphic queries:** `LegalCase/lists/DefaultList` returned items pointing to *other* entities — `LegalAdvice`, `LegalCase`, `LegalDueDiligence`. `LegalCase` is effectively an abstract base — confirms the architecture is class-hierarchy-based, not table-based.
- Query syntax: **`$top` / `$skip` work as query params** (OData-flavoured). `$filter` likely supported; not yet verified.

Phase-2 reshaping opportunities:
- Flatten `_embedded.{ListName}` to a plain `items` array.
- Drop empty `{RelationshipName}$Properties: {}` keys.
- Optionally keep `_links.item.href` but rename to `id` or `selfHref` for LLM clarity.

## 8. Multi-app surface

**Status:** deferred.

The admin UI at `/home/exampletenant/app/admin` is a Backbone SPA that fetches its solution list dynamically via `ot_App.solutionManager` (likely Cordys SOAP via `/home/exampletenant/com.eibus.web.soap.Gateway.wcp` — got 502 on direct probe, so it may have moved). Reverse-engineering this is doable but not necessary for v1 — the MCP server can accept the entity service URL from config, and supporting multiple services is a flag away. Punted to phase 2.

What we already know: the tenant has at least the `ExampleLegalManagement` entity service; a ExampleApp deployment typically also includes Contracts, MatterManagement, etc., based on the `MM_*` tags inside this service.

## 9. Artifacts saved under `artifacts/`

- `login-form.html` (~10 KB) — pre-auth OTDS login form
- `post-login-response.html` (~2.6 KB) — OTDS post-ticket interstitial
- `swagger-ui-page.html` (~1.88 MB) — protected page with embedded spec
- `openapi.json` (~1.88 MB) — extracted OpenAPI 3.0.1 spec for `ExampleLegalManagement`
- `admin-page.html` (~176 KB) — admin SPA shell
- `solutions.js`, `otSolutionManager.js` — admin JS modules
- `sample_*.json` — live query responses for `lists/DefaultList`
- `Login-Appworks.ps1` — reusable PowerShell login helper

---

# Validated design — v1 MCP server

All the architectural decisions from the design conversation now have evidence behind them.

## Stack

- **Python 3.11+**, single package
- **FastMCP** (or low-level `mcp` SDK if FastMCP's tool model is too constraining) for stdio transport
- **httpx.AsyncClient** as the HTTP layer, with a small subclass that handles OTDS login + 401 retry

## Config (env vars in the Claude Desktop / Claude Code `mcpServers` block)

```
PA_BASE_URL           = https://api.example.com:3381
PA_TENANT             = exampletenant
PA_ENTITY_SERVICE     = ExampleLegalManagement
PA_USERNAME           = awpadmin
PA_PASSWORD           = …                              (or PA_PASSWORD_FILE)
PA_REQUEST_TIMEOUT_S  = 30                             (optional, default)
PA_LOG_LEVEL          = INFO                           (optional)
```

## Startup flow

1. Read env config.
2. Build `httpx.AsyncClient` with cookie jar and the `OtdsClient` auth wrapper.
3. `GET {PA_BASE_URL}/home/{PA_TENANT}/app/entityservice/{PA_ENTITY_SERVICE}` (triggering login as needed).
4. Extract `var dyn_spec_obj = {...}` from the returned HTML; brace-match to capture the JSON. Parse it.
5. Build an in-memory **EntityCatalog**: map tag → entity → {childEntities, relationships, actions, lists}.
6. Register the ~16 generic tools (below).
7. Start serving on stdio.

## Tool set (v1)

Each tool takes the entity name as a parameter — so the surface stays the same regardless of how many entities the service exposes.

| # | Tool                                | Maps to                                                              | Notes |
|---|-------------------------------------|----------------------------------------------------------------------|-------|
| 1 | `list_entities()`                   | (in-memory; from `tags`)                                             | Returns the 28 business entity names with descriptions. |
| 2 | `describe_entity(name)`             | (in-memory; synthesised from spec)                                   | Properties, child entities, relationships, actions, available lists. Strip GUIDs from schema names. |
| 3 | `list_named_lists(entity)`          | (in-memory)                                                          | Names of available `/lists/{ListName}` endpoints. |
| 4 | `query_list(entity, list, top?, skip?, filter?, search?)` | `GET /entities/{entity}/lists/{list}?...`            | The primary read path. **Most common LLM tool call.** |
| 5 | `get_entity(entity, id)`            | `GET /entities/{entity}/items/{id}`                                  |  |
| 6 | `create_entity(entity, body, draftMode?)` | `POST /entities/{entity}`                                      |  |
| 7 | `update_entity(entity, id, body)`   | `PUT /entities/{entity}/items/{id}`                                  |  |
| 8 | `delete_entity(entity, id)`         | `DELETE /entities/{entity}/items/{id}`                               |  |
| 9 | `list_children(entity, id, child)`  | `GET /entities/{entity}/items/{id}/childEntities/{child}`            |  |
| 10 | `get_child(entity, id, child, child_id)` | `GET /entities/{entity}/items/{p}/childEntities/{child}/items/{id}` |  |
| 11 | `create_child(entity, id, child, body)` | `POST /entities/{entity}/items/{p}/childEntities/{child}`         |  |
| 12 | `update_child(entity, id, child, child_id, body)` | `PUT …`                                                  |  |
| 13 | `delete_child(entity, id, child, child_id)` | `DELETE …`                                                   |  |
| 14 | `list_relationship_targets(entity, id, rel)` | `GET …/relationships/{rel}`                                 |  |
| 15 | `add_relationship_target(entity, id, rel, body)` | `POST …/relationships/{rel}`                            |  |
| 16 | `remove_relationship_target(entity, id, rel, target_id)` | `DELETE …/relationships/{rel}/targets/{target_id}` |  |
| 17 | `invoke_action(entity, id, action_path, body?)` | `POST .../items/{id}/{action_path}`                       | `action_path` is the bit after the item id, e.g. `actions/Submit`, `File/actions/Upload`, `Sharing/actions/Share`. |
| 18 | `pa_api_call(method, path, query?, body?)` | raw passthrough                                                | Escape hatch. Lets the LLM hit anything the generic tools miss. |

That is **18 tools** covering 793 operations. Well within the LLM-tool-count comfort zone.

## What is explicitly deferred to phase 2

- **Response shaping** — flatten `_embedded.{ListName}` to `items`; drop empty relationship-aggregation keys; rename `_links.item.href` → `id`. (Need a live `LegalCase` GET-one sample first to confirm full envelope shape.)
- **Multi-entity-service support** — config supports a list of services rather than one; tools accept an optional `service` parameter.
- **Per-entity hand-written tools** — e.g., `my_open_legal_cases()` that wraps `query_list("LegalCase", "MyCaseList", ...)` with a friendly name. Only worth doing for the 5–10 most-used flows.
- **Tenant app catalog discovery** — auto-enumeration of all entity services on the tenant via Cordys SOAP.
- **Full-text search** — `$filter` and the `ftsEnabled` flag in the page envelope suggest server-side FTS support; needs probing.
- **Streaming uploads/downloads** for `File/Upload` and `File/Download` actions.

## Open questions for next session

1. Should `query_list` also accept `$filter` strings and pass them through, or expose a structured `filter` shape? (Test first if `$filter` is actually supported.)
2. Does v1 need write operations (create/update/delete) enabled by default, or should it be **read-only by default with a `PA_ALLOW_WRITES=true` flag** for safety? (Recommend the latter — entity actions like `Submit` are not idempotent.)
3. For action invocation, do we want one umbrella `invoke_action` or split into `submit_entity`, `share_entity`, `upload_file` (more specific tools for the most-used actions)?
