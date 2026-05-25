"""Tests for the generic business-id -> internal-int item-id resolver.

The AppWorks REST API addresses items by their internal BigInteger primary key
(e.g. ``9175042``), but humans (and LLMs) usually have the business identifier
the platform shows in the UI (e.g. ``PI2526-000102``). To bridge this without
hard-coding per-entity field names, the resolver:

1. Pass-through when ``item_id`` is already all-digits.
2. Otherwise, call ``DefaultList?$search=<item_id>`` and accept the call only
   if exactly one returned item has a string ``Properties.*`` value equal to
   the input. Extract the internal int from ``_links.item.href``.
3. Ambiguous (>1 match) or unresolved (0 matches) -> structured error listing
   the candidates.

These tests use respx to mock the AppWorks HTTP surface.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from opentext_pa_mcp.auth import AppworksClient
from opentext_pa_mcp.catalog import build_catalog
from opentext_pa_mcp.config import Config
from opentext_pa_mcp.errors import ItemIdResolutionError
from opentext_pa_mcp.tools import handlers
from tests.unit.test_auth import (
    LoginState,
    _make_config,
    _register_login_chain,
)


@pytest.fixture
def catalog(openapi_spec: dict):
    return build_catalog(openapi_spec)


@pytest.fixture
def config() -> Config:
    return _make_config()


@pytest.fixture
async def authed_client(config: Config):
    state = LoginState()
    _register_login_chain(respx.mock, state)
    async with AppworksClient(config) as client:
        yield client


def _default_list_url(config: Config, entity: str) -> str:
    return f"{config.api_base}/ExampleLegalManagement/entities/{entity}/lists/DefaultList"


def _item_url(config: Config, entity: str, internal_id: str) -> str:
    return f"{config.api_base}/ExampleLegalManagement/entities/{entity}/items/{internal_id}"


def _list_response(items: list[dict]) -> dict:
    return {
        "page": {"skip": 0, "top": len(items), "count": len(items)},
        "_embedded": {"DefaultList": items},
        "_links": {"self": {"href": "..."}},
    }


def _item(internal_id: str, properties: dict) -> dict:
    return {
        "_links": {"item": {"href": f"/ExampleLegalManagement/entities/X/items/{internal_id}"}},
        "Properties": properties,
    }


class TestGetEntityResolution:
    """``get_entity`` accepts both internal-int IDs and business IDs."""

    @respx.mock
    async def test_digit_id_passes_through_without_resolution(
        self, catalog, authed_client, config
    ) -> None:
        """Pure-digit item_id => single GET on /items/<id>, no DefaultList call."""
        item_url = _item_url(config, "LegalCategory", "9175042")
        item_route = respx.mock.get(item_url).mock(
            return_value=httpx.Response(200, json={"Properties": {"Name": "Mergers"}})
        )
        # If the resolver erroneously hits DefaultList, this route would be a leak.
        list_url = _default_list_url(config, "LegalCategory")
        list_route = respx.mock.get(list_url).mock(
            return_value=httpx.Response(500, json={"message": "should not be called"})
        )

        result = await handlers.get_entity(
            catalog, authed_client, entity="LegalCategory", item_id="9175042"
        )

        assert item_route.called
        assert not list_route.called
        assert result["Properties"]["Name"] == "Mergers"

    @respx.mock
    async def test_business_id_resolves_to_internal_int_via_default_list(
        self, catalog, authed_client, config
    ) -> None:
        """Single exact match in DefaultList => detail fetch uses the href's int."""
        list_url = _default_list_url(config, "LegalCategory")
        respx.mock.get(list_url).mock(
            return_value=httpx.Response(
                200,
                json=_list_response(
                    [_item("9175042", {"Code": "PI2526-000102", "Name": "Mergers"})]
                ),
            )
        )
        item_url = _item_url(config, "LegalCategory", "9175042")
        item_route = respx.mock.get(item_url).mock(
            return_value=httpx.Response(
                200, json={"Properties": {"Name": "Mergers", "Code": "PI2526-000102"}}
            )
        )

        result = await handlers.get_entity(
            catalog, authed_client, entity="LegalCategory", item_id="PI2526-000102"
        )

        assert item_route.called
        assert result["Properties"]["Code"] == "PI2526-000102"

    @respx.mock
    async def test_business_id_with_no_matches_raises_resolution_error(
        self, catalog, authed_client, config
    ) -> None:
        """Zero matches => actionable error, no detail call made."""
        list_url = _default_list_url(config, "LegalCategory")
        respx.mock.get(list_url).mock(return_value=httpx.Response(200, json=_list_response([])))

        with pytest.raises(ItemIdResolutionError) as excinfo:
            await handlers.get_entity(
                catalog,
                authed_client,
                entity="LegalCategory",
                item_id="NOPE-999",
            )
        assert "NOPE-999" in str(excinfo.value)
        assert excinfo.value.candidates == []

    @respx.mock
    async def test_business_id_with_multiple_matches_raises_with_candidates(
        self, catalog, authed_client, config
    ) -> None:
        """Two items both contain the search string in Properties, neither exactly
        equal to it => ambiguous => error lists the candidates so the caller can
        re-query with a more precise id."""
        list_url = _default_list_url(config, "LegalCategory")
        respx.mock.get(list_url).mock(
            return_value=httpx.Response(
                200,
                json=_list_response(
                    [
                        _item("100", {"Code": "PI2526-A", "Name": "Alpha PI2526 foo"}),
                        _item("200", {"Code": "PI2526-B", "Name": "Beta PI2526 bar"}),
                    ]
                ),
            )
        )

        with pytest.raises(ItemIdResolutionError) as excinfo:
            await handlers.get_entity(
                catalog,
                authed_client,
                entity="LegalCategory",
                item_id="PI2526",
            )

        candidates = excinfo.value.candidates
        assert len(candidates) == 2
        internal_ids = {c["internal_id"] for c in candidates}
        assert internal_ids == {"100", "200"}

    @respx.mock
    async def test_exact_property_match_wins_over_partial_matches(
        self, catalog, authed_client, config
    ) -> None:
        """When DefaultList returns multiple items but exactly ONE has a string
        Properties value equal to the input, that one wins. The fuzzy hits are
        discarded."""
        list_url = _default_list_url(config, "LegalCategory")
        respx.mock.get(list_url).mock(
            return_value=httpx.Response(
                200,
                json=_list_response(
                    [
                        _item("100", {"Code": "PI2526-000102", "Name": "Exact one"}),
                        _item("200", {"Name": "Description mentions PI2526-000102 too"}),
                    ]
                ),
            )
        )
        item_route = respx.mock.get(_item_url(config, "LegalCategory", "100")).mock(
            return_value=httpx.Response(200, json={"Properties": {"Code": "PI2526-000102"}})
        )

        result = await handlers.get_entity(
            catalog,
            authed_client,
            entity="LegalCategory",
            item_id="PI2526-000102",
        )

        assert item_route.called
        assert result["Properties"]["Code"] == "PI2526-000102"


class TestListChildrenResolution:
    """``list_children`` resolves the parent item_id too — the BigInteger PK lives
    in the URL path, same trap as ``get_entity``."""

    @respx.mock
    async def test_business_parent_id_is_resolved(self, catalog, authed_client, config) -> None:
        list_url = _default_list_url(config, "LegalCase")
        respx.mock.get(list_url).mock(
            return_value=httpx.Response(
                200,
                json=_list_response([_item("81921", {"CaseNumber": "LC-2026-007"})]),
            )
        )
        children_url = (
            f"{config.api_base}/ExampleLegalManagement/entities/LegalCase"
            f"/items/81921/childEntities/Emails"
        )
        children_route = respx.mock.get(children_url).mock(
            return_value=httpx.Response(200, json={"_embedded": {"Emails": []}})
        )

        result = await handlers.list_children(
            catalog,
            authed_client,
            entity="LegalCase",
            item_id="LC-2026-007",
            child_entity="Emails",
        )

        assert children_route.called
        assert "items" in result

    @respx.mock
    async def test_digit_parent_id_passes_through(self, catalog, authed_client, config) -> None:
        children_url = (
            f"{config.api_base}/ExampleLegalManagement/entities/LegalCase"
            f"/items/81921/childEntities/Emails"
        )
        children_route = respx.mock.get(children_url).mock(
            return_value=httpx.Response(200, json={"_embedded": {"Emails": []}})
        )
        list_url = _default_list_url(config, "LegalCase")
        list_route = respx.mock.get(list_url).mock(
            return_value=httpx.Response(500, json={"message": "should not be called"})
        )

        await handlers.list_children(
            catalog,
            authed_client,
            entity="LegalCase",
            item_id="81921",
            child_entity="Emails",
        )

        assert children_route.called
        assert not list_route.called


class TestGetChildResolution:
    """``get_child`` resolves both parent and child IDs."""

    @respx.mock
    async def test_business_parent_and_child_ids_resolve(
        self, catalog, authed_client, config
    ) -> None:
        parent_list_url = _default_list_url(config, "LegalCase")
        respx.mock.get(parent_list_url).mock(
            return_value=httpx.Response(
                200,
                json=_list_response([_item("81921", {"CaseNumber": "LC-2026-007"})]),
            )
        )
        # Child resolution: DefaultList on the child entity is the same convention.
        child_list_url = _default_list_url(config, "Emails")
        respx.mock.get(child_list_url).mock(
            return_value=httpx.Response(
                200,
                json=_list_response([_item("999", {"Subject": "EM-001"})]),
            )
        )
        detail_url = (
            f"{config.api_base}/ExampleLegalManagement/entities/LegalCase"
            f"/items/81921/childEntities/Emails/items/999"
        )
        detail_route = respx.mock.get(detail_url).mock(
            return_value=httpx.Response(200, json={"Properties": {"Subject": "EM-001"}})
        )

        result = await handlers.get_child(
            catalog,
            authed_client,
            entity="LegalCase",
            item_id="LC-2026-007",
            child_entity="Emails",
            child_id="EM-001",
        )

        assert detail_route.called
        assert result["Properties"]["Subject"] == "EM-001"
