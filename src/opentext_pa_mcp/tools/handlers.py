"""Pure async tool handler functions.

Each handler takes the catalog + HTTP client + tool-specific args, and returns a
JSON-serialisable dict. The FastMCP layer wraps these for tool registration.
"""

from __future__ import annotations

from typing import Any

from ..auth import AppworksClient
from ..catalog import EntityCatalog, EntityInfo
from ..errors import ReadOnlyViolationError

# Methods this read-only release permits through ``pa_api_call``.
_READ_METHODS: frozenset[str] = frozenset({"GET", "HEAD"})


# --- Discovery tools ----------------------------------------------------------


async def list_entities(catalog: EntityCatalog, _client: AppworksClient) -> dict:
    """List the business entities exposed by the configured Process Automation service.

    Returns:
        ``{"service": <service name>, "entities": [{"name": ..., "description": ...}, ...]}``.
        Each entry corresponds to one OpenAPI tag (a top-level business entity).
    """
    return {
        "service": catalog.service_name,
        "description": catalog.description,
        "entities": [
            {"name": info.name, "description": info.description}
            for info in sorted(catalog.entities.values(), key=lambda e: e.name)
        ],
    }


async def describe_entity(catalog: EntityCatalog, _client: AppworksClient, *, name: str) -> dict:
    """Describe one business entity in detail.

    Args:
        name: The entity name (case-sensitive). Use :func:`list_entities` to discover them.

    Returns the entity's named lists, child entities, relationships, available actions,
    and the count of REST operations attached.
    """
    info = _require_entity(catalog, name)
    return info.describe()


async def list_named_lists(catalog: EntityCatalog, _client: AppworksClient, *, entity: str) -> dict:
    """List the named query lists available for *entity*.

    Returns:
        ``{"entity": <name>, "lists": [...]}``.
    """
    info = _require_entity(catalog, entity)
    return {
        "entity": info.name,
        "lists": sorted(info.named_lists),
    }


# --- Read-data tools ----------------------------------------------------------


async def query_list(
    catalog: EntityCatalog,
    client: AppworksClient,
    *,
    entity: str,
    list_name: str = "DefaultList",
    top: int | None = None,
    skip: int | None = None,
    search: str | None = None,
) -> dict:
    """Query a named list of *entity*. Returns a flattened, LLM-friendly result.

    Args:
        entity: The entity name (e.g. ``LegalCase``).
        list_name: One of the names returned by :func:`list_named_lists`.
            Defaults to ``DefaultList`` because every entity has one.
        top: Maximum number of items to return. Server-side cap typically applies.
        skip: Number of items to skip (for pagination).
        search: Optional free-text search if the list supports full-text search.
    """
    info = _require_entity(catalog, entity)
    if list_name not in info.named_lists:
        raise ValueError(
            f"Entity {entity!r} has no named list {list_name!r}. "
            f"Available: {sorted(info.named_lists) or '(none)'}."
        )

    path = f"/{catalog.service_name}/entities/{entity}/lists/{list_name}"
    params = _odata_params(top=top, skip=skip, search=search)
    raw = await client.api_get(path, params=params)
    return _flatten_list_response(raw, list_name)


async def get_entity(
    catalog: EntityCatalog,
    client: AppworksClient,
    *,
    entity: str,
    item_id: str,
) -> dict:
    """Get a single entity item by its id."""
    _require_entity(catalog, entity)
    path = f"/{catalog.service_name}/entities/{entity}/items/{item_id}"
    return await client.api_get(path)


async def list_children(
    catalog: EntityCatalog,
    client: AppworksClient,
    *,
    entity: str,
    item_id: str,
    child_entity: str,
    top: int | None = None,
    skip: int | None = None,
) -> dict:
    """List child entities under a specific parent item.

    Example: ``list_children(entity="LegalCase", item_id="81921", child_entity="Emails")``.
    """
    info = _require_entity(catalog, entity)
    if child_entity not in info.child_entities:
        raise ValueError(
            f"Entity {entity!r} has no child entity {child_entity!r}. "
            f"Available: {sorted(info.child_entities) or '(none)'}."
        )
    path = f"/{catalog.service_name}/entities/{entity}/items/{item_id}/childEntities/{child_entity}"
    params = _odata_params(top=top, skip=skip)
    raw = await client.api_get(path, params=params)
    return _flatten_list_response(raw, child_entity)


async def get_child(
    catalog: EntityCatalog,
    client: AppworksClient,
    *,
    entity: str,
    item_id: str,
    child_entity: str,
    child_id: str,
) -> dict:
    """Get a specific child entity item under a parent."""
    info = _require_entity(catalog, entity)
    if child_entity not in info.child_entities:
        raise ValueError(
            f"Entity {entity!r} has no child entity {child_entity!r}. "
            f"Available: {sorted(info.child_entities) or '(none)'}."
        )
    path = (
        f"/{catalog.service_name}/entities/{entity}/items/{item_id}"
        f"/childEntities/{child_entity}/items/{child_id}"
    )
    return await client.api_get(path)


async def list_relationship_targets(
    catalog: EntityCatalog,
    client: AppworksClient,
    *,
    entity: str,
    item_id: str,
    relationship: str,
) -> dict:
    """List the target items of a relationship for a specific item."""
    info = _require_entity(catalog, entity)
    if relationship not in info.relationships:
        raise ValueError(
            f"Entity {entity!r} has no relationship {relationship!r}. "
            f"Available: {sorted(info.relationships) or '(none)'}."
        )
    path = f"/{catalog.service_name}/entities/{entity}/items/{item_id}/relationships/{relationship}"
    return await client.api_get(path)


# --- Escape hatch -------------------------------------------------------------


async def pa_api_call(
    _catalog: EntityCatalog,
    client: AppworksClient,
    *,
    method: str,
    path: str,
    query: dict[str, Any] | None = None,
) -> Any:
    """Read-only escape hatch — call any Process Automation API endpoint directly.

    Only ``GET`` and ``HEAD`` are permitted in v1.0. For write methods, the v1.1
    release will require ``PA_ALLOW_WRITES=true``.

    Args:
        method: HTTP method. ``"GET"`` or ``"HEAD"`` only.
        path: Path relative to the entity service REST API base.
        query: Optional query parameters dict.
    """
    upper = method.upper()
    if upper not in _READ_METHODS:
        raise ReadOnlyViolationError(upper)
    if upper == "HEAD":
        raise NotImplementedError("HEAD is reserved for future use; use GET for now.")
    return await client.api_get(path, params=query)


# --- Internals ----------------------------------------------------------------


def _require_entity(catalog: EntityCatalog, name: str) -> EntityInfo:
    info = catalog.entities.get(name)
    if info is None:
        raise ValueError(
            f"Unknown entity {name!r}. Available entities: {sorted(catalog.entities)!r}."
        )
    return info


def _odata_params(
    *,
    top: int | None = None,
    skip: int | None = None,
    search: str | None = None,
) -> dict[str, Any] | None:
    """Build the OData-style query params AppWorks list endpoints expect.

    Returns ``None`` if no params are set so callers don't send a trailing ``?``.
    """
    params: dict[str, Any] = {}
    if top is not None:
        params["$top"] = top
    if skip is not None:
        params["$skip"] = skip
    if search:
        params["$search"] = search
    return params or None


def _flatten_list_response(raw: dict, embedded_key: str) -> dict:
    """Reshape a HAL ``_embedded.<List>`` response into ``{"items": [...], ...}``.

    AppWorks list responses wrap items in ``_embedded.<ListName>`` and clutter each
    item with empty ``$Properties`` aggregations. We flatten and clean for the LLM.
    """
    page = raw.get("page", {}) if isinstance(raw, dict) else {}
    embedded = raw.get("_embedded", {}) if isinstance(raw, dict) else {}
    items_raw = embedded.get(embedded_key, [])

    items = []
    for item in items_raw:
        if not isinstance(item, dict):
            items.append(item)
            continue
        # Drop empty relationship-aggregation keys ('{Rel}$Properties': {}).
        cleaned = {k: v for k, v in item.items() if not (k.endswith("$Properties") and v == {})}
        items.append(cleaned)

    return {
        "count": page.get("count", len(items)),
        "skip": page.get("skip", 0),
        "top": page.get("top"),
        "next_skip": page.get("nextSkip"),
        "items": items,
        "_links": raw.get("_links") if isinstance(raw, dict) else None,
    }
