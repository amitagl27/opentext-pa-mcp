"""End-to-end tests against a live AppWorks tenant.

Marker: ``@pytest.mark.integration`` so they can be selected/excluded easily.
Skipped automatically when PA_* env vars are missing (see ``conftest.py``).
"""

from __future__ import annotations

import pytest

from opentext_pa_mcp.discovery import discover_catalog
from opentext_pa_mcp.tools import handlers

pytestmark = pytest.mark.integration


class TestLiveLogin:
    async def test_login_and_fetch_swagger_html(self, live_client) -> None:
        html = await live_client.fetch_entity_service_html()
        assert "dyn_spec_obj" in html


class TestLiveDiscovery:
    async def test_discover_catalog(self, live_client) -> None:
        catalog = await discover_catalog(live_client)
        # We don't assert == 28 because the tenant can change; just check it's non-trivial.
        assert len(catalog.entities) >= 5
        assert catalog.service_name


class TestLiveTools:
    async def test_list_entities(self, live_client) -> None:
        catalog = await discover_catalog(live_client)
        result = await handlers.list_entities(catalog, live_client)
        assert result["service"]
        assert len(result["entities"]) >= 5

    async def test_query_legal_category_default_list(self, live_client) -> None:
        catalog = await discover_catalog(live_client)
        result = await handlers.query_list(
            catalog, live_client, entity="LegalCategory", list_name="DefaultList", top=2
        )
        # We expect at least one category on this tenant.
        assert isinstance(result["items"], list)
        if result["items"]:
            first = result["items"][0]
            assert "Properties" in first or "_links" in first

    async def test_describe_legal_case(self, live_client) -> None:
        catalog = await discover_catalog(live_client)
        result = await handlers.describe_entity(catalog, live_client, name="LegalCase")
        assert result["name"] == "LegalCase"
        assert "DefaultList" in result["named_lists"]
