"""Build an in-memory entity catalog from the OpenAPI spec of an AppWorks entity service.

The catalog is the bridge between the raw OpenAPI document (700+ operations, 600+
schemas with GUID-decorated names) and the small set of generic MCP tools we expose.
Each tool consumes the catalog at call time to:

- enumerate entities and their named lists / child entities / relationships / actions
  (``describe_entity``, ``list_named_lists`` …);
- validate that the entity / list / action the LLM asked about actually exists before
  making an HTTP request.

The catalog is built once at server startup; it is immutable thereafter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

# AppWorks tags every schema name with a 32-hex-character GUID (the model identifier).
# Example: ``LegalCase_000C29DBA92EA1EF8BB26F1F0DD4660C_Create_Req``. We strip these so
# names shown to the LLM are readable.
_SCHEMA_GUID = re.compile(r"_([0-9A-F]{32})_")


# URL pattern recognisers. The catalog walks every path in the OpenAPI document and
# classifies it into one of these buckets. The first segment after ``/{ServiceName}/``
# is always ``entities``; the second is the entity name (== tag name).
_PATH_PATTERNS: Final = {
    # /{Service}/entities/{Entity}                                   POST -> create
    "entity_collection": re.compile(r"^/(?P<service>[^/]+)/entities/(?P<entity>[^/]+)$"),
    # /{Service}/entities/{Entity}/items/{id}                        item CRUD
    "entity_item": re.compile(r"^/(?P<service>[^/]+)/entities/(?P<entity>[^/]+)/items/\{id\}$"),
    # /{Service}/entities/{Entity}/lists/{ListName}
    "entity_list": re.compile(
        r"^/(?P<service>[^/]+)/entities/(?P<entity>[^/]+)/lists/(?P<list>[^/]+)$"
    ),
    # /{Service}/entities/{Entity}/items/{id}/childEntities/{Child}
    "child_collection": re.compile(
        r"^/(?P<service>[^/]+)/entities/(?P<entity>[^/]+)/items/\{[^/]+\}/childEntities/(?P<child>[^/]+)$"
    ),
    # /{Service}/entities/{Entity}/items/{id}/relationships/{Rel}
    "relationship_collection": re.compile(
        r"^/(?P<service>[^/]+)/entities/(?P<entity>[^/]+)/items/\{[^/]+\}/relationships/(?P<rel>[^/]+)$"
    ),
    # /{Service}/entities/{Entity}/items/{id}/<Property>/actions/<Action>
    # /{Service}/entities/{Entity}/items/{id}/actions/<Action>
    "action": re.compile(
        r"^/(?P<service>[^/]+)/entities/(?P<entity>[^/]+)/items/\{[^/]+\}/(?:(?P<prop>[^/]+)/)?actions/(?P<action>[^/]+)$"
    ),
    # Lists on child entities: /{Service}/entities/{Entity}/childEntities/{Child}/lists/{ListName}
    "child_list": re.compile(
        r"^/(?P<service>[^/]+)/entities/(?P<entity>[^/]+)/childEntities/(?P<child>[^/]+)/lists/(?P<list>[^/]+)$"
    ),
}


@dataclass(frozen=True)
class OperationRef:
    """A single OpenAPI operation, summarised for catalog use."""

    method: str
    path: str
    summary: str
    description: str
    tag: str


@dataclass(frozen=True)
class ActionRef:
    """A custom action invokable on an entity item.

    ``property_name`` is None for entity-level actions (e.g. ``Submit``) and set for
    property-scoped actions (e.g. ``File/Upload`` -> property_name="File", action_name="Upload").
    """

    action_name: str
    property_name: str | None
    path_template: str  # e.g. ".../items/{id}/File/actions/Upload"


@dataclass(frozen=True)
class EntityInfo:
    """All catalog data for one business entity."""

    name: str
    description: str = ""
    named_lists: list[str] = field(default_factory=list)
    child_entities: list[str] = field(default_factory=list)
    relationships: list[str] = field(default_factory=list)
    actions: list[ActionRef] = field(default_factory=list)
    operations: list[OperationRef] = field(default_factory=list)

    def describe(self) -> dict:
        """Return a JSON-serialisable summary for the ``describe_entity`` MCP tool."""
        return {
            "name": self.name,
            "description": self.description,
            "named_lists": sorted(self.named_lists),
            "child_entities": sorted(self.child_entities),
            "relationships": sorted(self.relationships),
            "actions": sorted({a.action_name for a in self.actions}),
            "actions_detail": [
                {
                    "action": a.action_name,
                    "on_property": a.property_name,
                }
                for a in self.actions
            ],
            "operation_count": len(self.operations),
        }


@dataclass(frozen=True)
class EntityCatalog:
    """The whole entity catalog for one entity service."""

    service_name: str
    description: str
    entities: dict[str, EntityInfo]

    @property
    def entity_names(self) -> list[str]:
        return sorted(self.entities.keys())


def strip_schema_guid(name: str) -> str:
    """Remove AppWorks model GUIDs from a schema name.

    >>> strip_schema_guid("LegalCase_000C29DBA92EA1EF8BB26F1F0DD4660C_Create_Req")
    'LegalCase_Create_Req'
    """
    return _SCHEMA_GUID.sub("_", name)


def build_catalog(spec: dict) -> EntityCatalog:
    """Walk *spec* and build the in-memory :class:`EntityCatalog`.

    Args:
        spec: A parsed OpenAPI 3.x document (the dict returned by
            :func:`opentext_pa_mcp.spec_extractor.extract_dyn_spec_obj`).
    """
    service_name = spec.get("info", {}).get("title") or _detect_service_name_from_paths(spec)
    service_description = spec.get("info", {}).get("description", "")

    # Seed entity records from the `tags` array (these are the user-visible entity names).
    entities: dict[str, dict] = {}
    for tag in spec.get("tags", []):
        name = tag.get("name")
        if not name:
            continue
        entities[name] = {
            "name": name,
            "description": tag.get("description", ""),
            "named_lists": set(),
            "child_entities": set(),
            "relationships": set(),
            "actions": [],
            "operations": [],
        }

    # Walk every path and bucket operations into the right entity record.
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not isinstance(op, dict):
                continue

            tags = op.get("tags") or []
            tag = tags[0] if tags else None
            entity = _classify_path(path, entities, tag)
            if entity is None:
                continue

            entity["operations"].append(
                OperationRef(
                    method=method.upper(),
                    path=path,
                    summary=op.get("summary", "") or "",
                    description=op.get("description", "") or "",
                    tag=tag or "",
                )
            )

            # Catch deeply nested actions that the top-level pattern matcher missed.
            # Example: /Service/entities/LegalCase/items/{p}/childEntities/Emails/items/{c}/
            #          childEntities/Contents/items/{id}/File/actions/Upload
            # These are attributed to the operation's tag (the parent entity).
            _record_nested_action_if_any(entity, path)

    return EntityCatalog(
        service_name=service_name,
        description=service_description,
        entities={
            name: EntityInfo(
                name=rec["name"],
                description=rec["description"],
                named_lists=sorted(rec["named_lists"]),
                child_entities=sorted(rec["child_entities"]),
                relationships=sorted(rec["relationships"]),
                actions=list(rec["actions"]),
                operations=list(rec["operations"]),
            )
            for name, rec in entities.items()
        },
    )


def _classify_path(path: str, entities: dict[str, dict], tag: str | None) -> dict | None:
    """Match *path* against the known patterns and update the relevant entity record.

    Returns the entity dict the operation was attributed to (so the caller can append the
    OperationRef), or ``None`` if the path did not match any known pattern.
    """
    # Try patterns in priority order; more-specific patterns first.
    if m := _PATH_PATTERNS["entity_list"].match(path):
        return _record_named_list(entities, m.group("entity"), m.group("list"))
    if m := _PATH_PATTERNS["child_list"].match(path):
        return _record_named_list(
            entities,
            m.group("entity"),
            m.group("list"),
            child=m.group("child"),
        )
    if m := _PATH_PATTERNS["action"].match(path):
        return _record_action(
            entities,
            m.group("entity"),
            m.group("action"),
            prop=m.group("prop"),
            path_template=path,
        )
    if m := _PATH_PATTERNS["child_collection"].match(path):
        return _record_child(entities, m.group("entity"), m.group("child"))
    if m := _PATH_PATTERNS["relationship_collection"].match(path):
        return _record_relationship(entities, m.group("entity"), m.group("rel"))
    if m := _PATH_PATTERNS["entity_item"].match(path):
        return _ensure_entity(entities, m.group("entity"))
    if m := _PATH_PATTERNS["entity_collection"].match(path):
        return _ensure_entity(entities, m.group("entity"))

    # Fallback: attribute to the operation's tag if we have one. This catches deeply
    # nested paths (grand-children, action on relationship, etc.) without losing the op.
    if tag and tag in entities:
        return entities[tag]
    return None


def _ensure_entity(entities: dict[str, dict], name: str) -> dict:
    """Return the entity record for *name*, creating an empty one if needed."""
    if name not in entities:
        entities[name] = {
            "name": name,
            "description": "",
            "named_lists": set(),
            "child_entities": set(),
            "relationships": set(),
            "actions": [],
            "operations": [],
        }
    return entities[name]


def _record_named_list(
    entities: dict[str, dict], entity: str, list_name: str, *, child: str | None = None
) -> dict:
    rec = _ensure_entity(entities, entity)
    rec["named_lists"].add(list_name)
    if child:
        rec["child_entities"].add(child)
    return rec


def _record_child(entities: dict[str, dict], entity: str, child: str) -> dict:
    rec = _ensure_entity(entities, entity)
    rec["child_entities"].add(child)
    return rec


def _record_relationship(entities: dict[str, dict], entity: str, rel: str) -> dict:
    rec = _ensure_entity(entities, entity)
    rec["relationships"].add(rel)
    return rec


def _record_action(
    entities: dict[str, dict],
    entity: str,
    action: str,
    *,
    prop: str | None,
    path_template: str,
) -> dict:
    rec = _ensure_entity(entities, entity)
    # Deduplicate (some actions appear under multiple paths).
    existing = {(a.property_name, a.action_name) for a in rec["actions"]}
    if (prop, action) not in existing:
        rec["actions"].append(
            ActionRef(action_name=action, property_name=prop, path_template=path_template)
        )
    return rec


_NESTED_ACTION_PATTERN = re.compile(r"/(?:([A-Za-z][\w]*)/)?actions/([A-Za-z][\w]*)$")


def _record_nested_action_if_any(entity_record: dict, path: str) -> None:
    """If *path* ends in ``.../actions/<Action>``, record it on the entity record.

    Captures actions on nested child entities that the top-level pattern matcher
    skipped (e.g. ``File/actions/Upload`` inside Email/Contents).
    """
    m = _NESTED_ACTION_PATTERN.search(path)
    if not m:
        return
    prop, action = m.group(1), m.group(2)
    existing = {(a.property_name, a.action_name) for a in entity_record["actions"]}
    if (prop, action) not in existing:
        entity_record["actions"].append(
            ActionRef(action_name=action, property_name=prop, path_template=path)
        )


def _detect_service_name_from_paths(spec: dict) -> str:
    """Fallback: read the service name from the first path segment if `info.title` is missing."""
    for path in spec.get("paths", {}):
        parts = [p for p in path.split("/") if p]
        if parts:
            return parts[0]
    return ""
