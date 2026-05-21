"""Entry point for the ``opentext-pa-mcp`` console script.

Reads configuration from environment variables (see :mod:`opentext_pa_mcp.config`),
builds the FastMCP server, and runs it on the configured transport:

- ``PA_TRANSPORT=stdio`` (default) — stdio transport, used by Claude Desktop / Code.
- ``PA_TRANSPORT=http`` — Streamable HTTP on ``PA_HTTP_HOST:PA_HTTP_PORT``, used
  for hosted deployments (Copilot Studio, public URLs). Credentials are then
  supplied per-request as HTTP headers, not env vars. See DEC-015.
"""

from __future__ import annotations

import sys

from .config import load_config
from .errors import ConfigurationError
from .server import build_server


def main() -> None:
    """Build and run the MCP server. Used as the console script entry point."""
    try:
        config = load_config()
        server = build_server(config)
    except ConfigurationError as exc:
        # Configuration errors at startup are user-facing — print to stderr and exit
        # with a non-zero status so the MCP client surfaces the failure.
        print(f"[opentext-pa-mcp] Configuration error: {exc}", file=sys.stderr)
        sys.exit(2)

    if config.transport == "stdio":
        server.run()
    else:
        server.run(
            transport="streamable-http",
            host=config.http_host,
            port=config.http_port,
        )


if __name__ == "__main__":
    main()
