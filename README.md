# OpenText Process Automation MCP

> A Model Context Protocol server that lets Claude (and any other MCP-compatible client) work with an OpenText AppWorks Platform tenant in plain English.

Point it at one entity service, give it a username and password, and ask things like:

> *"Show me my open legal cases."*
> *"What categories are configured under the Litigation practice area?"*
> *"Describe the LegalCase entity — what fields does it have?"*

The server discovers the entire API surface (typically several hundred endpoints) at startup and exposes it through a small set of generic tools that take the entity name as an argument. No code generation, no per-endpoint maintenance.

## Status

**v0.1.3 — read-only release, live on PyPI.** Install with `pip` and configure your MCP client.

Works against both OTDS-fronted AppWorks 23.x and Cordys-built-in Process Automation CE 25.x; the right login flow is picked automatically. See `docs/research/findings.md` for the validated design and what we learned from probing live instances.

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

The `PA_SERVICE_URL` is **the exact URL you see in your browser** when looking at the Swagger UI of the entity service you want to expose. The server parses host, tenant, and service name out of it.

### Auth modes

Two login flows are supported and the right one is picked automatically:

- **OTDS form login** — used on AppWorks 23.x instances where OTDS sits in front of AppWorks on a separate port. Recognised by a login page with hidden `otdscsrf` and `RFA` form fields.
- **Cordys built-in SSO** — used on Process Automation CE 25.x where AppWorks does its own SAML 1.1 SSO. Recognised by a "Process Automation Login" page served from `/wcp/sso/login.htm`.

If startup fails with `AuthenticationError: Login page did not contain the expected csrf / RFA tokens` your instance is most likely Cordys-built-in but auto-detection didn't fire (custom reverse proxy, modified login page, etc.). Set `PA_AUTH_MODE=cordys` to force it. Similarly, set `PA_AUTH_MODE=otds` if you're on OTDS and detection misfires the other way.

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
├── research/           Decisions log, evolution changelog
├── docs/
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
- `research/DECISIONS.md` — architectural decisions and why.
- `CLAUDE.md` — working rules.
