"""Pure async tool handler functions.

Each handler takes the catalog + HTTP client + tool-specific args, and returns a
JSON-serialisable dict. The FastMCP layer wraps these for tool registration.
"""

from __future__ import annotations

import re
from typing import Any

from ..auth import AppworksClient
from ..catalog import EntityCatalog, EntityInfo
from ..errors import ItemIdResolutionError, ReadOnlyViolationError

# Methods this read-only release permits through ``pa_api_call``.
_READ_METHODS: frozenset[str] = frozenset({"GET", "HEAD"})

# AppWorks addresses items by an internal BigInteger primary key in the URL
# (``/items/<int>``). All-digits => use as-is; anything else => resolve via
# DefaultList. Keyed on shape (digit-ness), not on entity name.
_DIGIT_ID_PATTERN = re.compile(r"^\d+$")
_HREF_INTERNAL_ID_PATTERN = re.compile(r"/items/(\d+)(?:$|[/?#])")


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
    """Get a single entity item by its id.

    ``item_id`` may be either the internal numeric id (from a list response's
    ``_links.item.href``) or a human-readable business id. Business ids are
    auto-resolved via DefaultList; ambiguous matches raise
    :class:`ItemIdResolutionError` with the candidate list.
    """
    _require_entity(catalog, entity)
    resolved = await _resolve_item_id(catalog, client, entity, item_id)
    path = f"/{catalog.service_name}/entities/{entity}/items/{resolved}"
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
    resolved = await _resolve_item_id(catalog, client, entity, item_id)
    path = (
        f"/{catalog.service_name}/entities/{entity}/items/{resolved}/childEntities/{child_entity}"
    )
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
    parent_resolved = await _resolve_item_id(catalog, client, entity, item_id)
    child_resolved = await _resolve_item_id(catalog, client, child_entity, child_id)
    path = (
        f"/{catalog.service_name}/entities/{entity}/items/{parent_resolved}"
        f"/childEntities/{child_entity}/items/{child_resolved}"
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
    resolved = await _resolve_item_id(catalog, client, entity, item_id)
    path = (
        f"/{catalog.service_name}/entities/{entity}/items/{resolved}/relationships/{relationship}"
    )
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


async def _resolve_item_id(
    catalog: EntityCatalog,
    client: AppworksClient,
    entity: str,
    item_id: str,
) -> str:
    """Return the internal numeric id for *item_id* on *entity*.

    Pass-through for all-digit ids. For any other shape, search ``DefaultList``
    on the entity and look for exactly one item whose string ``Properties.*``
    value equals *item_id* (exact, case-insensitive); use the int from that
    item's ``_links.item.href``. Zero or multiple matches raise
    :class:`ItemIdResolutionError` with the candidate list.

    The logic is entity-agnostic — it relies only on platform invariants
    (DefaultList exists on every entity, ``_links.item.href`` carries the int).
    """
    if _DIGIT_ID_PATTERN.match(item_id):
        return item_id

    path = f"/{catalog.service_name}/entities/{entity}/lists/DefaultList"
    raw = await client.api_get(path, params={"$search": item_id})
    items = _extract_embedded_items(raw, "DefaultList")

    exact = [it for it in items if _has_exact_property_match(it, item_id)]
    pool = exact if len(exact) == 1 else items

    if len(pool) == 1:
        internal = _extract_internal_id(pool[0])
        if internal is not None:
            return internal

    candidates = [_summarise_candidate(it) for it in items]
    raise ItemIdResolutionError(item_id, candidates, entity=entity)


def _extract_embedded_items(raw: Any, list_name: str) -> list[dict]:
    if not isinstance(raw, dict):
        return []
    embedded = raw.get("_embedded", {})
    if not isinstance(embedded, dict):
        return []
    items = embedded.get(list_name, [])
    return [it for it in items if isinstance(it, dict)]


def _has_exact_property_match(item: dict, needle: str) -> bool:
    """True when any string value under ``Properties`` equals *needle* exactly.

    Case-insensitive so callers like ``pi2526-000102`` still match the
    canonical ``PI2526-000102``.
    """
    properties = item.get("Properties")
    if not isinstance(properties, dict):
        return False
    needle_cf = needle.casefold()
    for value in properties.values():
        if isinstance(value, str) and value.casefold() == needle_cf:
            return True
    return False


def _extract_internal_id(item: dict) -> str | None:
    href = item.get("_links", {}).get("item", {}).get("href")
    if not isinstance(href, str):
        return None
    match = _HREF_INTERNAL_ID_PATTERN.search(href)
    return match.group(1) if match else None


def _summarise_candidate(item: dict) -> dict:
    """Compact representation used in the resolver error message.

    Keeps the internal id (so the caller can retry directly) plus the first
    few Property string values for human/LLM disambiguation.
    """
    properties = item.get("Properties") or {}
    summary_parts = [f"{k}={v!r}" for k, v in properties.items() if isinstance(v, str)][:3]
    return {
        "internal_id": _extract_internal_id(item) or "<unknown>",
        "summary": ", ".join(summary_parts),
    }


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
