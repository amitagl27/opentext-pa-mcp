"""Entry point for the ``opentext-pa-mcp`` console script.

Reads configuration from environment variables (see :mod:`opentext_pa_mcp.config`),
builds the FastMCP server, and runs it on stdio — the transport expected by Claude
Desktop and Claude Code.
"""

from __future__ import annotations

import sys

from .errors import ConfigurationError
from .server import build_server


def main() -> None:
    """Build and run the MCP server. Used as the console script entry point."""
    try:
        server = build_server()
    except ConfigurationError as exc:
        # Configuration errors at startup are user-facing — print to stderr and exit
        # with a non-zero status so the MCP client surfaces the failure.
        print(f"[opentext-pa-mcp] Configuration error: {exc}", file=sys.stderr)
        sys.exit(2)

    server.run()  # default transport = stdio


if __name__ == "__main__":
    main()
