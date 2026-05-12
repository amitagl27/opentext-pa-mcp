"""FastMCP wiring: lifespan, tool registration, server bootstrap."""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastmcp import Context, FastMCP

from .auth import AppworksClient
from .catalog import EntityCatalog
from .config import Config, load_config
from .discovery import discover_catalog
from .errors import AppworksError, HttpError, NotFoundError
from .tools import handlers

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Runtime state shared across tool calls."""

    config: Config
    client: AppworksClient
    catalog: EntityCatalog


def _setup_logging(level: int) -> None:
    """Route logs to stderr — stdout is reserved for the MCP protocol over stdio."""
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(level)
    # Replace any existing handlers (FastMCP may add its own; we want a clean stderr setup).
    root.handlers = [handler]
    # Silence very chatty libraries below INFO unless explicitly enabled.
    if level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


def build_server(config: Config | None = None) -> FastMCP:
    """Construct a configured :class:`FastMCP` server. Used by ``__main__`` and tests."""
    config = config or load_config()
    _setup_logging(config.log_level)

    @asynccontextmanager
    async def lifespan(_app: FastMCP) -> AsyncIterator[AppContext]:
        logger.info(
            "Starting opentext-pa-mcp: service=%s tenant=%s host=%s",
            config.service_name,
            config.tenant,
            config.host,
        )
        client = AppworksClient(config)
        try:
            catalog = await discover_catalog(client)
            yield AppContext(config=config, client=client, catalog=catalog)
        finally:
            await client.aclose()

    mcp = FastMCP(
        name=f"OpenText PA — {config.service_name}",
        instructions=_build_server_instructions(config),
        lifespan=lifespan,
    )

    _register_tools(mcp)
    return mcp


def _build_server_instructions(config: Config) -> str:
    return (
        f"OpenText AppWorks Process Automation MCP server, bound to entity service "
        f"'{config.service_name}' on tenant '{config.tenant}'.\n\n"
        "Read-only release (v1.0). To query data:\n"
        "  1. Call `list_entities` to see what business entities are available.\n"
        "  2. Call `describe_entity(name=...)` to see one entity's fields, child entities, "
        "relationships, lists, and actions.\n"
        "  3. Call `query_list(entity=..., list_name='DefaultList', top=10)` to fetch a page of items.\n"
        "  4. Use `get_entity`, `list_children`, `list_relationship_targets` to drill in.\n"
        "  5. `pa_api_call(method='GET', path='/...')` is an escape hatch for any GET endpoint.\n\n"
        "Write operations (create/update/delete/invoke_action) are not in this release. "
        "Re-run with PA_ALLOW_WRITES=true in the v1.1 release to enable them."
    )


def _register_tools(mcp: FastMCP) -> None:
    """Register every v1.0 tool with FastMCP. Tools resolve catalog + client from lifespan."""

    @mcp.tool(
        name="list_entities",
        description=(
            "List the business entities exposed by the configured Process Automation service. "
            "Use this first to discover what's available. Returns a list of entity names and "
            "descriptions parsed from the OpenAPI tags."
        ),
    )
    async def list_entities(ctx: Context) -> dict:
        app = _app_context(ctx)
        return await _call(handlers.list_entities(app.catalog, app.client))

    @mcp.tool(
        name="describe_entity",
        description=(
            "Describe one business entity in detail: its named lists, child entities, "
            "relationships, available actions, and total operation count. "
            "Use list_entities first to find valid names."
        ),
    )
    async def describe_entity(name: str, ctx: Context) -> dict:
        app = _app_context(ctx)
        return await _call(handlers.describe_entity(app.catalog, app.client, name=name))

    @mcp.tool(
        name="list_named_lists",
        description=(
            "List the named query lists (server-side views like 'DefaultList', 'MyCaseList') "
            "available on a specific entity. Use query_list to fetch one."
        ),
    )
    async def list_named_lists(entity: str, ctx: Context) -> dict:
        app = _app_context(ctx)
        return await _call(handlers.list_named_lists(app.catalog, app.client, entity=entity))

    @mcp.tool(
        name="query_list",
        description=(
            "Query a named list on an entity. Returns paginated results with each item's "
            "Properties and a canonical _links.item.href. Defaults to 'DefaultList' which every "
            "entity has. Supports OData-style $top and $skip for pagination."
        ),
    )
    async def query_list(
        entity: str,
        ctx: Context,
        list_name: str = "DefaultList",
        top: int | None = None,
        skip: int | None = None,
        search: str | None = None,
    ) -> dict:
        app = _app_context(ctx)
        return await _call(
            handlers.query_list(
                app.catalog,
                app.client,
                entity=entity,
                list_name=list_name,
                top=top,
                skip=skip,
                search=search,
            )
        )

    @mcp.tool(
        name="get_entity",
        description="Fetch a single entity item by its id.",
    )
    async def get_entity(entity: str, item_id: str, ctx: Context) -> dict:
        app = _app_context(ctx)
        return await _call(
            handlers.get_entity(app.catalog, app.client, entity=entity, item_id=item_id)
        )

    @mcp.tool(
        name="list_children",
        description=(
            "List child entities under a specific parent item. "
            "Example: list_children(entity='LegalCase', item_id='81921', child_entity='Emails')."
        ),
    )
    async def list_children(
        entity: str,
        item_id: str,
        child_entity: str,
        ctx: Context,
        top: int | None = None,
        skip: int | None = None,
    ) -> dict:
        app = _app_context(ctx)
        return await _call(
            handlers.list_children(
                app.catalog,
                app.client,
                entity=entity,
                item_id=item_id,
                child_entity=child_entity,
                top=top,
                skip=skip,
            )
        )

    @mcp.tool(
        name="get_child",
        description="Fetch a specific child item under a parent entity item.",
    )
    async def get_child(
        entity: str, item_id: str, child_entity: str, child_id: str, ctx: Context
    ) -> dict:
        app = _app_context(ctx)
        return await _call(
            handlers.get_child(
                app.catalog,
                app.client,
                entity=entity,
                item_id=item_id,
                child_entity=child_entity,
                child_id=child_id,
            )
        )

    @mcp.tool(
        name="list_relationship_targets",
        description="List the target items of a relationship for a specific item.",
    )
    async def list_relationship_targets(
        entity: str, item_id: str, relationship: str, ctx: Context
    ) -> dict:
        app = _app_context(ctx)
        return await _call(
            handlers.list_relationship_targets(
                app.catalog,
                app.client,
                entity=entity,
                item_id=item_id,
                relationship=relationship,
            )
        )

    @mcp.tool(
        name="pa_api_call",
        description=(
            "Read-only escape hatch: call any GET endpoint of the Process Automation API "
            "directly. Use only when no other tool fits. v1.0 rejects non-GET methods."
        ),
    )
    async def pa_api_call(
        method: str, path: str, ctx: Context, query: dict[str, Any] | None = None
    ) -> Any:
        app = _app_context(ctx)
        return await _call(
            handlers.pa_api_call(app.catalog, app.client, method=method, path=path, query=query)
        )


def _app_context(ctx: Context) -> AppContext:
    """Extract the :class:`AppContext` from the FastMCP request context."""
    return ctx.request_context.lifespan_context  # type: ignore[return-value]


async def _call(coro: Any) -> Any:
    """Translate AppworksError subclasses into LLM-friendly responses.

    FastMCP returns the dict back to the LLM directly. By catching our own exceptions
    and shaping a structured ``error`` object, the LLM gets actionable info rather than
    a generic Python traceback.
    """
    try:
        return await coro
    except NotFoundError as exc:
        return {
            "error": {
                "kind": "not_found",
                "message": str(exc),
                "url": exc.url,
            }
        }
    except HttpError as exc:
        return {
            "error": {
                "kind": "http_error",
                "status_code": exc.status_code,
                "message": str(exc),
                "url": exc.url,
            }
        }
    except AppworksError as exc:
        return {
            "error": {
                "kind": type(exc).__name__,
                "message": str(exc),
            }
        }
