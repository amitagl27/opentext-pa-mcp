"""Tests for the read-only tool handlers.

Handlers are pure async functions: ``handler(catalog, client, **kwargs) -> dict``.
We test them by building a real :class:`EntityCatalog` from the captured OpenAPI
spec and mocking the HTTP layer with respx.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from opentext_pa_mcp.auth import AppworksClient
from opentext_pa_mcp.catalog import build_catalog
from opentext_pa_mcp.config import Config
from opentext_pa_mcp.errors import ReadOnlyViolationError
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
    """An AppworksClient with respx pre-wired for OTDS login."""
    state = LoginState()
    _register_login_chain(respx.mock, state)
    async with AppworksClient(config) as client:
        yield client


class TestListEntities:
    @respx.mock
    async def test_returns_28_entities(self, catalog, authed_client) -> None:
        result = await handlers.list_entities(catalog, authed_client)

        assert result["service"] == "ExampleLegalManagement"
        assert len(result["entities"]) == 28
        names = {e["name"] for e in result["entities"]}
        assert "LegalCase" in names
        assert "LegalCategory" in names


class TestDescribeEntity:
    @respx.mock
    async def test_returns_full_shape(self, catalog, authed_client) -> None:
        result = await handlers.describe_entity(catalog, authed_client, name="LegalCategory")

        assert result["name"] == "LegalCategory"
        assert "DefaultList" in result["named_lists"]

    @respx.mock
    async def test_unknown_entity_raises(self, catalog, authed_client) -> None:
        with pytest.raises(ValueError, match="DoesNotExist"):
            await handlers.describe_entity(catalog, authed_client, name="DoesNotExist")


class TestListNamedLists:
    @respx.mock
    async def test_legal_case_named_lists(self, catalog, authed_client) -> None:
        result = await handlers.list_named_lists(catalog, authed_client, entity="LegalCase")

        names = set(result["lists"])
        assert "DefaultList" in names
        assert "MyCaseList" in names


class TestQueryList:
    @respx.mock
    async def test_query_default_list(self, catalog, authed_client, config) -> None:
        api_url = (
            f"{config.api_base}/ExampleLegalManagement/entities/LegalCategory/lists/DefaultList"
        )
        respx.mock.get(api_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "page": {"skip": 0, "top": 2, "count": 2},
                    "_links": {"self": {"href": "..."}},
                    "_embedded": {
                        "DefaultList": [
                            {
                                "_links": {"item": {"href": "/.../items/24"}},
                                "Properties": {"Name": "Mergers"},
                            }
                        ]
                    },
                },
            )
        )

        result = await handlers.query_list(
            catalog, authed_client, entity="LegalCategory", list_name="DefaultList", top=2
        )

        assert result["count"] == 2
        assert len(result["items"]) == 1
        assert result["items"][0]["Properties"]["Name"] == "Mergers"

    @respx.mock
    async def test_unknown_entity_raises(self, catalog, authed_client) -> None:
        with pytest.raises(ValueError, match="Nope"):
            await handlers.query_list(
                catalog, authed_client, entity="Nope", list_name="DefaultList"
            )

    @respx.mock
    async def test_unknown_list_raises(self, catalog, authed_client) -> None:
        with pytest.raises(ValueError, match="NotAList"):
            await handlers.query_list(
                catalog, authed_client, entity="LegalCategory", list_name="NotAList"
            )

    @respx.mock
    async def test_top_param_is_passed_through(self, catalog, authed_client, config) -> None:
        api_url = (
            f"{config.api_base}/ExampleLegalManagement/entities/LegalCategory/lists/DefaultList"
        )
        route = respx.mock.get(api_url).mock(
            return_value=httpx.Response(
                200,
                json={"page": {"skip": 0, "top": 5, "count": 0}, "_embedded": {"DefaultList": []}},
            )
        )

        await handlers.query_list(
            catalog, authed_client, entity="LegalCategory", list_name="DefaultList", top=5, skip=10
        )

        request = route.calls.last.request
        assert "%24top=5" in str(request.url) or "$top=5" in str(request.url)
        assert "%24skip=10" in str(request.url) or "$skip=10" in str(request.url)


class TestGetEntity:
    @respx.mock
    async def test_get_by_id(self, catalog, authed_client, config) -> None:
        api_url = f"{config.api_base}/ExampleLegalManagement/entities/LegalCategory/items/24"
        respx.mock.get(api_url).mock(
            return_value=httpx.Response(
                200, json={"Properties": {"Name": "Mergers & Acquisitions"}}
            )
        )

        result = await handlers.get_entity(
            catalog, authed_client, entity="LegalCategory", item_id="24"
        )
        assert result["Properties"]["Name"] == "Mergers & Acquisitions"


class TestListChildren:
    @respx.mock
    async def test_lists_emails_under_legalcase(self, catalog, authed_client, config) -> None:
        api_url = (
            f"{config.api_base}/ExampleLegalManagement/entities/LegalCase"
            f"/items/81921/childEntities/Emails"
        )
        respx.mock.get(api_url).mock(
            return_value=httpx.Response(200, json={"_embedded": {"Emails": []}})
        )

        result = await handlers.list_children(
            catalog,
            authed_client,
            entity="LegalCase",
            item_id="81921",
            child_entity="Emails",
        )
        assert "items" in result


class TestPaApiCall:
    @respx.mock
    async def test_get_passthrough(self, catalog, authed_client, config) -> None:
        api_url = f"{config.api_base}/ExampleLegalManagement/entities/LegalCategory/items/24"
        respx.mock.get(api_url).mock(return_value=httpx.Response(200, json={"ok": True}))

        result = await handlers.pa_api_call(
            catalog,
            authed_client,
            method="GET",
            path="/ExampleLegalManagement/entities/LegalCategory/items/24",
        )
        assert result["ok"] is True

    @respx.mock
    async def test_post_rejected_in_readonly(self, catalog, authed_client) -> None:
        with pytest.raises(ReadOnlyViolationError):
            await handlers.pa_api_call(
                catalog,
                authed_client,
                method="POST",
                path="/anything",
            )

    @respx.mock
    async def test_method_is_case_insensitive(self, catalog, authed_client) -> None:
        with pytest.raises(ReadOnlyViolationError):
            await handlers.pa_api_call(catalog, authed_client, method="delete", path="/x")
