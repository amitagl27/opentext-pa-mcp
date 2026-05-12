# Discovery plan — OpenText AppWorks Process Automation MCP

## Goal

Validate the architectural assumptions made in the design discussion against the real `api.example.com:3381` AppWorks instance before writing any MCP server code.

Specifically, we need to answer:

1. **Platform & version** — is this AppWorks Platform (Cordys lineage) or the newer OT Process Automation Cloud Edition? What version?
2. **API protocol** — does the entity service expose OData v2, OData v4, OpenAPI/Swagger, SOAP/WSDL, or something else?
3. **Discovery document** — what URL returns a machine-readable schema, and what is its format?
4. **Scale** — how many entity sets / endpoints does a real service expose? Does it justify our "generic verb tools" plan over per-endpoint tool generation?
5. **Auth pattern** — how does OTDS authenticate a service account, which cookies carry the session, and how long do they live?
6. **Multi-app surface** — beyond `ExampleLegalManagement`, how many other entity services exist on this tenant?
7. **Response shape** — does the real payload contain verbose envelopes (`__metadata`, Cordys-style wrappers) that will need phase-2 reshaping?

## Target

- Base host: `https://api.example.com:3381`
- Tenant / org: `exampletenant`
- Primary entity service: `/home/exampletenant/app/entityservice/ExampleLegalManagement`
- Admin / app catalog: `/home/exampletenant/app/admin`
- Service account: `awpadmin` (credentials kept out of this repo)

## Method

1. **Set up docs scaffold** (this folder). Save raw artifacts (HTML, XML, JSON) under `artifacts/` so findings stay reproducible.
2. **Script the OTDS login** — POST to the auth service login form, capture the persistent session cookie, and confirm we can re-authenticate non-interactively.
3. **Hit the entity service** with the live session: base URL, `$metadata`, and the service document (`/`). Save the metadata XML and parse it.
4. **Enumerate apps** from `/home/exampletenant/app/admin` to see the full surface this MCP server might cover.
5. **Run one live query** against a real entity set to capture the response envelope.
6. **Write findings.md** with the validated design.

## Artifacts we expect to capture

- `artifacts/login-form.html` — OTDS login page, to confirm CSRF/RFA token names
- `artifacts/login-response-headers.txt` — Set-Cookie + Location chain from a successful login
- `artifacts/entityservice-root.json` — OData service document (list of entity sets)
- `artifacts/entityservice-metadata.xml` — full `$metadata` schema
- `artifacts/sample-query.json` — one live `$top=1` response, raw
- `artifacts/admin-apps.html` (or json) — tenant app catalog

## Out of scope for this phase

- Writing the MCP server itself
- Any response reshaping / output beautification
- Per-entity friendly tools
- Multi-tenant / multi-service runtime support

## Status

See `findings.md` for the running log of what we've confirmed vs. what's still unknown.
