"""Bootstrap step that runs once at server startup.

Fetches the entity service's Swagger UI HTML, extracts the embedded OpenAPI spec,
and builds the entity catalog. Cached for the life of the process.
"""

from __future__ import annotations

import logging

from .auth import AppworksClient
from .catalog import EntityCatalog, build_catalog
from .errors import DiscoveryError
from .spec_extractor import extract_dyn_spec_obj

logger = logging.getLogger(__name__)


async def discover_catalog(client: AppworksClient) -> EntityCatalog:
    """Login (if needed), fetch the Swagger UI HTML, extract the spec, build the catalog.

    Raises:
        DiscoveryError: if any of the steps fail.
    """
    try:
        html = await client.fetch_entity_service_html()
    except Exception as exc:
        raise DiscoveryError(f"Could not fetch the entity service HTML: {exc}") from exc

    spec = extract_dyn_spec_obj(html)
    catalog = build_catalog(spec)
    logger.info(
        "Discovery complete: service=%s, entities=%d, total operations=%d",
        catalog.service_name,
        len(catalog.entities),
        sum(len(e.operations) for e in catalog.entities.values()),
    )
    return catalog
