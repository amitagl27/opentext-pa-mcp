"""Tool handlers for the v1.0 read-only MCP server.

Each handler is a pure async function that takes the EntityCatalog and AppworksClient
as explicit dependencies plus the tool-specific keyword arguments. This keeps the
handlers fully unit-testable without dragging in FastMCP machinery.

The FastMCP registration layer (in :mod:`opentext_pa_mcp.server`) wraps these handlers
into `@mcp.tool`-decorated functions that fetch the catalog and client from the
server's lifespan context.
"""

from __future__ import annotations

from . import handlers

__all__ = ["handlers"]
