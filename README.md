# OpenText Process Automation MCP

> A Model Context Protocol server that lets Claude (and any other MCP-compatible client) work with an OpenText AppWorks Platform tenant in plain English.

Point it at one entity service, give it a username and password, and ask things like:

> *"Show me my open legal cases."*
> *"What categories are configured under the Litigation practice area?"*
> *"Describe the LegalCase entity — what fields does it have?"*

The server discovers the entire API surface (typically several hundred endpoints) at startup and exposes it through a small set of generic tools that take the entity name as an argument. No code generation, no per-endpoint maintenance.

## Status

**v0.1.0 — read-only release.** Implementation complete, build artifacts in `dist/`, ready to publish to PyPI. See `PUBLISHING.md` for the upload steps and `READ-ME-FIRST-TOMORROW.md` for the end-to-end setup checklist.

See `docs/research/findings.md` for the validated design and what we learned from probing a live AppWorks 23.4 instance.

## How it will work (v1.0)

1. You add a snippet to your MCP client config (Claude Desktop, Claude Code, Cursor, etc.) that runs `uvx opentext-pa-mcp` with three env vars.
2. `uvx` downloads the package from PyPI and runs it. No manual `pip install`, no clone.
3. On startup the server logs into your AppWorks tenant via OTDS, fetches the entity service's OpenAPI spec, builds an entity catalog, and registers ~18 generic tools.
4. You restart the MCP client. Done.

Final config snippet for Claude Desktop's `%APPDATA%\Claude\claude_desktop_config.json` (or the Mac/Linux equivalents):

```json
{
  "mcpServers": {
    "opentext-pa": {
      "command": "uvx",
      "args": ["opentext-pa-mcp"],
      "env": {
        "PA_SERVICE_URL": "http://your-host:3381/home/<tenant>/app/entityservice/<EntityServiceName>",
        "PA_USERNAME": "<username>",
        "PA_PASSWORD": "<password>"
      }
    }
  }
}
```

Optional env vars:

| Variable | Default | Purpose |
|----------|---------|---------|
| `PA_LOG_LEVEL` | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `PA_REQUEST_TIMEOUT_S` | `30` | Per-request HTTP timeout in seconds. |
| `PA_VERIFY_TLS` | `true` | Set to `false` to skip TLS certificate verification. **Insecure** — use only against dev/test servers with self-signed certs. |
| `PA_CA_BUNDLE` | *(unset)* | Path to a PEM file containing your corporate root CA. Use this when AppWorks is on `https://` behind an internal CA. Preferred over disabling verification. Mutually exclusive with `PA_VERIFY_TLS=false`. |

The `PA_SERVICE_URL` is **the exact URL you see in your browser** when looking at the Swagger UI of the entity service you want to expose. The server parses host, tenant, and service name out of it.

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
