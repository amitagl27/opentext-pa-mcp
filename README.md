# OpenText Process Automation MCP

> A Model Context Protocol server that lets Claude (and any other MCP-compatible client) work with an OpenText AppWorks Platform tenant in plain English.

Point it at one entity service, give it a username and password, and ask things like:

> *"Show me my open legal cases."*
> *"What categories are configured under the Litigation practice area?"*
> *"Describe the LegalCase entity — what fields does it have?"*

The server discovers the entire API surface (typically several hundred endpoints) at startup and exposes it through a small set of generic tools that take the entity name as an argument. No code generation, no per-endpoint maintenance.

## Status

**v0.2.0 — read-only release, live on PyPI.** Install with `pip` and configure your MCP client.

Works against both OTDS-fronted AppWorks 23.x and Cordys-built-in Process Automation CE 25.x; the right login flow is picked automatically. Ships **two transports** out of the box — `stdio` (the default, for Claude Desktop / Code / Cursor / Cline / any local MCP client) and `http` (Streamable HTTP for hosted clients like Microsoft Copilot Studio). See [Deployment modes](#deployment-modes) below and `docs/research/findings.md` for the validated design.

## Install

The package is on PyPI as [`opentext-pa-mcp`](https://pypi.org/project/opentext-pa-mcp/). Anyone with Python 3.11+ can install it:

```powershell
pip install --user opentext-pa-mcp
```

That's it — no `uv`, `uvx`, `pipx`, or virtualenv tooling required. The package's entry point is reachable as `python -m opentext_pa_mcp`, so no `Scripts/` folder needs to be on PATH.

To upgrade later when a new version is released:

```powershell
pip install --user --upgrade opentext-pa-mcp
```

## Configure your MCP client

Add this snippet to your Claude Desktop config (`%APPDATA%\Claude\claude_desktop_config.json` on Windows, `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS). Same shape works in Claude Code, Cursor, and any other MCP client that supports stdio servers.

```json
{
  "mcpServers": {
    "opentext-pa": {
      "command": "python",
      "args": ["-m", "opentext_pa_mcp"],
      "env": {
        "PA_SERVICE_URL": "https://your-host:3381/home/<tenant>/app/entityservice/<EntityServiceName>",
        "PA_USERNAME": "<username>",
        "PA_PASSWORD": "<password>"
      }
    }
  }
}
```

Fully quit Claude Desktop (system tray → Quit) and relaunch. On startup the server logs into your AppWorks tenant (OTDS or Cordys built-in SSO — auto-detected), fetches the entity service's OpenAPI spec, builds an entity catalog, and registers all 9 tools.

If your machine has multiple Python installations and Claude can't find the right one, replace `"command": "python"` with the full path to the interpreter, e.g. `"command": "C:\\Users\\you\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"`.

Optional env vars:

| Variable | Default | Purpose |
|----------|---------|---------|
| `PA_LOG_LEVEL` | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `PA_REQUEST_TIMEOUT_S` | `30` | Per-request HTTP timeout in seconds. |
| `PA_VERIFY_TLS` | `true` | Set to `false` to skip TLS certificate verification. **Insecure** — use only against dev/test servers with self-signed certs. |
| `PA_CA_BUNDLE` | *(unset)* | Path to a PEM file containing your corporate root CA. Use this when AppWorks is on `https://` behind an internal CA. Preferred over disabling verification. Mutually exclusive with `PA_VERIFY_TLS=false`. |
| `PA_AUTH_MODE` | `auto` | Login strategy. `auto` (default) inspects the login page and picks `otds` (AppWorks 23.x, OTDS-fronted) or `cordys` (Process Automation CE 25.x, Cordys built-in SSO). Set explicitly to `otds` or `cordys` only if auto-detection misfires. |
| `PA_TRANSPORT` | `stdio` | `stdio` (default) for Claude Desktop / Code / Cursor; `http` for hosted MCP clients (Copilot Studio, web agents). See [Deployment modes](#deployment-modes). |
| `PA_HTTP_HOST` | `127.0.0.1` | Only used when `PA_TRANSPORT=http`. Bind address; set to `0.0.0.0` to accept remote connections. |
| `PA_HTTP_PORT` | `8000` | Only used when `PA_TRANSPORT=http`. |

The `PA_SERVICE_URL` is **the exact URL you see in your browser** when looking at the Swagger UI of the entity service you want to expose. The server parses host, tenant, and service name out of it.

### Auth modes

Two login flows are supported and the right one is picked automatically:

- **OTDS form login** — used on AppWorks 23.x instances where OTDS sits in front of AppWorks on a separate port. Recognised by a login page with hidden `otdscsrf` and `RFA` form fields.
- **Cordys built-in SSO** — used on Process Automation CE 25.x where AppWorks does its own SAML 1.1 SSO. Recognised by a "Process Automation Login" page served from `/wcp/sso/login.htm`.

If startup fails with `AuthenticationError: Login page did not contain the expected csrf / RFA tokens` your instance is most likely Cordys-built-in but auto-detection didn't fire (custom reverse proxy, modified login page, etc.). Set `PA_AUTH_MODE=cordys` to force it. Similarly, set `PA_AUTH_MODE=otds` if you're on OTDS and detection misfires the other way.

### Required AppWorks role

At startup the server discovers the entity catalog by fetching the OpenAPI spec from `…/app/entityRestService/api/{Service}/docs`. That endpoint is gated by a narrow AppWorks platform role:

> **`OpenText Entity Runtime` → `Entity REST API Developer`**

Grant this role (under the `OpenText Entity Runtime` namespace) to every user who will run the MCP server. If you don't, startup fails with:

```
HttpError: Access denied. You do not have permissions to view this page. (HTTP 403)
```

**This role is the minimum needed and grants nothing dangerous.** Per OpenText's own documentation, `Entity REST API Developer` only enables the *channel* — the ability to call REST URLs and read the OpenAPI spec. All actual operations on entity data (create, read, update, delete, list, share, action invocation) remain governed by the entity's **Security building block** and **Sharing building block** configurations. In other words: a user with this role but no per-entity security grants can see *which* APIs exist, but they cannot read or change any data they wouldn't already be able to access.

Practical guidance for admins:

- Add `Entity REST API Developer` (namespace `OpenText Entity Runtime`) to your existing functional user roles, or to a dedicated `MCP Server User` group.
- No other "Developer Role" / "Administrator" assignment is needed for the MCP server to work.
- After granting the role, restart the MCP server — startup discovery will succeed and the catalog will reflect only the entities the user already has functional access to.

## Deployment modes

Pick a transport based on who calls the server:

### `stdio` (default) — Claude Desktop / Code / Cursor / Cline / any local MCP client

This is what the **Install** and **Configure your MCP client** sections above describe. One process per end-user, credentials supplied as env vars in the client's JSON config. Nothing else to set; `PA_TRANSPORT` does not need to appear.

### `http` — Microsoft Copilot Studio, web agents, hosted clients

When the client cannot spawn a local subprocess (Copilot Studio, custom web agents, internal portals), run the server as a long-lived HTTP service. Credentials come in **on each MCP request** as HTTP headers instead of from env vars, so every end-user authenticates with their *own* AppWorks identity (audit trails and security-building-block permissions stay user-scoped).

**For production deployments, use the Azure Container Apps recipe at [`deploy/azure/README.md`](deploy/azure/README.md)** — it ships an ARM template + Deploy-to-Azure button, pulls the prebuilt image from `ghcr.io/amitagl27/opentext-pa-mcp`, and includes the Power Platform connector setup walkthrough. The instructions below are for running the HTTP server directly (development, custom hosting).

Start the server in http mode:

```powershell
$env:PA_TRANSPORT = "http"
$env:PA_HTTP_HOST = "0.0.0.0"     # bind to all interfaces; omit for loopback only
$env:PA_HTTP_PORT = "8000"
python -m opentext_pa_mcp
```

The server logs `Starting opentext-pa-mcp (http) on 0.0.0.0:8000. Credentials expected per-request.` and stays running. It is now reachable over Streamable HTTP at `http://<host>:8000/mcp/`.

Every inbound MCP request must include the following headers:

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization: Basic <base64(username:password)>` | yes | The user's AppWorks credentials. Same credentials they would type into the OTDS / Cordys login page. |
| `X-PA-Service-URL: <full entity-service URL>` | yes* | The exact URL you would see in the AppWorks Swagger UI of the entity service you want to query. \*Optional if `PA_SERVICE_URL` is set on the server as a single-tenant default. |
| `X-PA-Auth-Mode: auto \| otds \| cordys` | no | Overrides the auto-detected login strategy. Use only if auto-detection misfires behind a custom proxy. |

The server keeps one warm `AppworksClient` + OpenAPI catalog **per `(service_url, username)` pair** in memory, so repeat calls from the same user don't re-run OTDS / Cordys login on every request. The cache is process-local and is cleared on restart.

**Authorization failures** (missing header, malformed credentials, invalid service URL) come back as a structured `"AuthenticationError"` reply on the MCP channel — clients should treat them like any other tool-level error.

**Security notes:**
- Always front the HTTP server with TLS in production (a reverse proxy, an API gateway, or Cloud Run's built-in HTTPS). The server itself speaks plain HTTP; certificate termination is up to your hosting layer.
- The server has **no internal authentication** beyond forwarding credentials to AppWorks. Anyone who can reach the listener can attempt a login. Restrict access at the network layer (firewall, private VPC, authenticated reverse proxy) or in front of the connector.
- AppWorks itself enforces all per-entity authorisation via its Security and Sharing building blocks — the MCP is not a security boundary, just a translation layer.

## Try it

After restarting Claude Desktop, ask things like:

> *"What entities does opentext-pa expose?"*
> *"Show me the first 5 legal categories."*
> *"Describe the LegalCase entity."*

## v1.0 tool surface (9 tools)

| Group | Tools |
|-------|-------|
| Discovery | `list_entities`, `describe_entity`, `list_named_lists` |
| Read | `query_list`, `get_entity`, `list_children`, `get_child`, `list_relationship_targets` |
| Escape hatch | `pa_api_call` (GET-only passthrough) |

**Read-only by default.** Write tools (`create_entity`, `update_entity`, `delete_entity`, `invoke_action`, child/relationship writes) arrive in v1.1 behind `PA_ALLOW_WRITES=true`.

## Workspace structure

```
opentext-processautomation-mcp/
├── CLAUDE.md           Working rules (TDD, folder layout, code standards)
├── CONTRIBUTING.md     Branching, PRs, commit conventions
├── README.md           This file
├── pyproject.toml      Package manifest, dependencies, tool config
├── deploy/
│   ├── azure/          Azure Container Apps deployment (ARM template, Dockerfile, README)
│   └── copilot-studio/ Power Platform custom connector (Swagger 2.0 YAML)
├── docs/
│   ├── DECISIONS.md    Architectural decisions (DEC-NNN entries)
│   ├── CHANGELOG.md    Narrative product evolution log
│   ├── research/       Validated discovery findings + reproducible artifacts
│   ├── technical/      Architecture docs (future)
│   └── product/        Feature specs (future)
├── src/opentext_pa_mcp/   The Python package
└── tests/
    ├── unit/           Fast, no-network (httpx mocked via respx)
    └── integration/    Against a live AppWorks tenant (gated by env vars)
```

## What it is not

- **Not a UI.** It exposes tools to an LLM; the LLM is the interface.
- **Not a generic OpenAPI-to-MCP bridge.** It's specifically tuned for AppWorks's uniform `entities / items / lists / childEntities / relationships / actions` URL pattern, which lets us cover 700+ endpoints with a tiny tool count.
- **Not multi-tenant.** One server instance = one entity service. Run multiple instances if you need multiple services.

## Authoritative references

- `docs/research/findings.md` — what's true about the live AppWorks API.
- `docs/DECISIONS.md` — architectural decisions and why.
- `CLAUDE.md` — working rules.
