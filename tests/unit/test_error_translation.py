"""Tests for translating opaque Cordys errors into actionable structured errors.

When AppWorks rejects a request because the path id failed to parse as a
BigInteger primary key (the user/LLM passed a business id), the server returns
HTTP 500 with a message like ``EXPRESSION_PARSE_BIGINTEGER_ERROR?value=...``.
The HTTP layer recognises that pattern and raises ``InvalidItemIdError`` with
a message explaining the dual-id convention, so the tool layer can surface a
useful hint rather than just ``HTTP 500``.

The check is keyed on the error message shape (a platform invariant), not on
any specific endpoint.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from opentext_pa_mcp.auth import AppworksClient
from opentext_pa_mcp.errors import HttpError, InvalidItemIdError
from tests.unit.test_auth import (
    LoginState,
    _make_config,
    _register_login_chain,
)


@pytest.fixture
async def authed_client():
    config = _make_config()
    state = LoginState()
    _register_login_chain(respx.mock, state)
    async with AppworksClient(config) as client:
        yield client


class TestBigIntegerParseError:
    @respx.mock
    async def test_500_with_bigint_marker_raises_invalid_item_id_error(self, authed_client) -> None:
        url = (
            "https://api.example.com:3381/home/exampletenant/app/entityRestService/api"
            "/ExampleLegalManagement/entities/PolicyIntimation/items/PI2526-000102"
        )
        respx.mock.get(url).mock(
            return_value=httpx.Response(
                500,
                json={
                    "message": "EXPRESSION_PARSE_BIGINTEGER_ERROR?value=PI2526-000102",
                    "status": 500,
                },
            )
        )

        with pytest.raises(InvalidItemIdError) as excinfo:
            await authed_client.api_get(
                "/ExampleLegalManagement/entities/PolicyIntimation/items/PI2526-000102"
            )
        msg = str(excinfo.value)
        # Must explain the dual-id convention and the recovery path.
        assert "PI2526-000102" in msg
        assert "_links.item.href" in msg or "internal" in msg.lower()

    @respx.mock
    async def test_invalid_item_id_error_is_an_http_error(self, authed_client) -> None:
        """InvalidItemIdError must remain catchable as HttpError so the existing
        tool-layer error translator (_dispatch in server.py) keeps the URL/status
        details when surfacing it."""
        assert issubclass(InvalidItemIdError, HttpError)

    @respx.mock
    async def test_500_without_bigint_marker_still_raises_plain_http_error(
        self, authed_client
    ) -> None:
        """Unrelated 500s must NOT be remapped; this protects the translation
        from over-reaching."""
        url = (
            "https://api.example.com:3381/home/exampletenant/app/entityRestService/api"
            "/ExampleLegalManagement/entities/LegalCategory/items/24"
        )
        respx.mock.get(url).mock(
            return_value=httpx.Response(
                500,
                json={"message": "Internal server error", "status": 500},
            )
        )

        with pytest.raises(HttpError) as excinfo:
            await authed_client.api_get("/ExampleLegalManagement/entities/LegalCategory/items/24")
        assert not isinstance(excinfo.value, InvalidItemIdError)
        assert excinfo.value.status_code == 500
