"""FastMCP wiring: lifespan, tool registration, server bootstrap.

Supports two transports (selected by ``Config.transport``):

- ``stdio`` (default, DEC-002) — one client = one process. Credentials supplied via
  env vars at startup; a single :class:`AppworksClient` + :class:`EntityCatalog` are
  built in the lifespan and shared across tool calls.
- ``http`` (DEC-015) — long-lived Streamable HTTP server for hosted deployments
  (Copilot Studio, public URLs). Credentials arrive on each MCP request as HTTP
  headers; the lifespan holds a :class:`SessionCache` and each tool call resolves
  ``(client, catalog)`` for the requesting user.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.server.dependencies import get_http_headers

from .auth import AppworksClient
from .catalog import EntityCatalog
from .config import Config, load_config
from .discovery import discover_catalog
from .errors import AppworksError, HttpError, NotFoundError
from .request_config import build_request_config
from .session_cache import SessionCache
from .tools import handlers

logger = logging.getLogger(__name__)


@dataclass
class StdioAppContext:
    """Lifespan state for stdio mode — single tenant, single shared session."""

    config: Config
    client: AppworksClient
    catalog: EntityCatalog


@dataclass
class HttpAppContext:
    """Lifespan state for http mode — server-level defaults plus per-user cache."""

    defaults: Config
    cache: SessionCache


AppContext = StdioAppContext | HttpAppContext


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
    lifespan = (
        _build_stdio_lifespan(config)
        if config.transport == "stdio"
        else _build_http_lifespan(config)
    )

    mcp = FastMCP(
        name=_build_server_name(config),
        instructions=_build_server_instructions(config),
        lifespan=lifespan,
    )
    _register_tools(mcp)
    return mcp


def _build_stdio_lifespan(
    config: Config,
) -> Callable[[FastMCP], Any]:
    @asynccontextmanager
    async def lifespan(_app: FastMCP):
        logger.info(
            "Starting opentext-pa-mcp (stdio): service=%s tenant=%s host=%s",
            config.service_name,
            config.tenant,
            config.host,
        )
        client = AppworksClient(config)
        try:
            catalog = await discover_catalog(client)
            yield StdioAppContext(config=config, client=client, catalog=catalog)
        finally:
            await client.aclose()

    return lifespan


def _build_http_lifespan(
    config: Config,
) -> Callable[[FastMCP], Any]:
    @asynccontextmanager
    async def lifespan(_app: FastMCP):
        logger.info(
            "Starting opentext-pa-mcp (http) on %s:%d. Credentials expected per-request.",
            config.http_host,
            config.http_port,
        )
        cache = SessionCache()
        try:
            yield HttpAppContext(defaults=config, cache=cache)
        finally:
            await cache.aclose()

    return lifespan


def _build_server_name(config: Config) -> str:
    if config.transport == "stdio":
        return f"OpenText PA — {config.service_name}"
    return "OpenText PA (hosted)"


def _build_server_instructions(config: Config) -> str:
    if config.transport == "stdio":
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
    return (
        "OpenText AppWorks Process Automation MCP server (hosted/http mode).\n\n"
        "Every MCP request must include credentials as HTTP headers:\n"
        "  Authorization: Basic <base64(username:password)>\n"
        "  X-PA-Service-URL: <full entity-service URL>\n"
        "  X-PA-Auth-Mode: auto|otds|cordys  (optional)\n\n"
        "Read-only release (v1.0). Discover the surface with `list_entities`, "
        "`describe_entity`, `list_named_lists`, then query via `query_list`, "
        "`get_entity`, `list_children`, `get_child`, `list_relationship_targets`. "
        "`pa_api_call(method='GET', path='/...')` is the escape hatch."
    )


# --- Per-request session resolution -------------------------------------------------------


async def _resolve_session(ctx: Context) -> tuple[EntityCatalog, AppworksClient]:
    """Return ``(catalog, client)`` for the current MCP request.

    In stdio mode the lifespan-built pair is reused. In http mode the request's
    ``Authorization`` / ``X-PA-Service-URL`` / ``X-PA-Auth-Mode`` headers are merged
    with the server defaults to build a per-user :class:`Config`, and the
    :class:`SessionCache` returns (or creates) the matching session.
    """
    app: AppContext = ctx.request_context.lifespan_context  # type: ignore[assignment]
    if isinstance(app, StdioAppContext):
        return app.catalog, app.client
    headers = get_http_headers()
    request_cfg = build_request_config(headers, defaults=app.defaults)
    session = await app.cache.get_or_create(request_cfg)
    return session.catalog, session.client


def _register_tools(mcp: FastMCP) -> None:
    """Register every v1.0 tool with FastMCP."""

    @mcp.tool(
        name="list_entities",
        description=(
            "List the business entities exposed by the configured Process Automation service. "
            "Use this first to discover what's available. Returns a list of entity names and "
            "descriptions parsed from the OpenAPI tags."
        ),
    )
    async def list_entities(ctx: Context) -> dict:
        return await _dispatch(ctx, lambda cat, cli: handlers.list_entities(cat, cli))

    @mcp.tool(
        name="describe_entity",
        description=(
            "Describe one business entity in detail: its named lists, child entities, "
            "relationships, available actions, and total operation count. "
            "Use list_entities first to find valid names."
        ),
    )
    async def describe_entity(name: str, ctx: Context) -> dict:
        return await _dispatch(ctx, lambda cat, cli: handlers.describe_entity(cat, cli, name=name))

    @mcp.tool(
        name="list_named_lists",
        description=(
            "List the named query lists (server-side views like 'DefaultList', 'MyCaseList') "
            "available on a specific entity. Use query_list to fetch one."
        ),
    )
    async def list_named_lists(entity: str, ctx: Context) -> dict:
        return await _dispatch(
            ctx, lambda cat, cli: handlers.list_named_lists(cat, cli, entity=entity)
        )

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
        return await _dispatch(
            ctx,
            lambda cat, cli: handlers.query_list(
                cat,
                cli,
                entity=entity,
                list_name=list_name,
                top=top,
                skip=skip,
                search=search,
            ),
        )

    @mcp.tool(
        name="get_entity",
        description="Fetch a single entity item by its id.",
    )
    async def get_entity(entity: str, item_id: str, ctx: Context) -> dict:
        return await _dispatch(
            ctx,
            lambda cat, cli: handlers.get_entity(cat, cli, entity=entity, item_id=item_id),
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
        return await _dispatch(
            ctx,
            lambda cat, cli: handlers.list_children(
                cat,
                cli,
                entity=entity,
                item_id=item_id,
                child_entity=child_entity,
                top=top,
                skip=skip,
            ),
        )

    @mcp.tool(
        name="get_child",
        description="Fetch a specific child item under a parent entity item.",
    )
    async def get_child(
        entity: str, item_id: str, child_entity: str, child_id: str, ctx: Context
    ) -> dict:
        return await _dispatch(
            ctx,
            lambda cat, cli: handlers.get_child(
                cat,
                cli,
                entity=entity,
                item_id=item_id,
                child_entity=child_entity,
                child_id=child_id,
            ),
        )

    @mcp.tool(
        name="list_relationship_targets",
        description="List the target items of a relationship for a specific item.",
    )
    async def list_relationship_targets(
        entity: str, item_id: str, relationship: str, ctx: Context
    ) -> dict:
        return await _dispatch(
            ctx,
            lambda cat, cli: handlers.list_relationship_targets(
                cat,
                cli,
                entity=entity,
                item_id=item_id,
                relationship=relationship,
            ),
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
        return await _dispatch(
            ctx,
            lambda cat, cli: handlers.pa_api_call(cat, cli, method=method, path=path, query=query),
        )


# --- Error translation --------------------------------------------------------------------


async def _dispatch(
    ctx: Context,
    build: Callable[[EntityCatalog, AppworksClient], Awaitable[Any]],
) -> Any:
    """Resolve the session, call *build*, translate any AppworksError to a dict.

    Centralises the auth-failure + http-error + not-found mapping so each tool stays
    short. In http mode the resolution step can itself raise (bad headers); we
    surface those as ``AuthenticationError``-shaped responses.
    """
    try:
        catalog, client = await _resolve_session(ctx)
        return await build(catalog, client)
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
