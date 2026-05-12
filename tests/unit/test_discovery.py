"""Tests for the discovery bootstrap step."""

from __future__ import annotations

import httpx
import pytest
import respx

from opentext_pa_mcp.auth import AppworksClient
from opentext_pa_mcp.discovery import discover_catalog
from opentext_pa_mcp.errors import DiscoveryError
from tests.unit.test_auth import (
    ENTITY_SERVICE_URL,
    LoginState,
    _make_config,
    _register_login_chain,
)


class TestDiscoverCatalog:
    @respx.mock
    async def test_full_path_against_real_html(self, swagger_ui_html: str) -> None:
        """Login + extract + build catalog using the real captured Swagger UI HTML."""
        cfg = _make_config()
        state = LoginState()
        # Use the shared login chain so OTDS URL constants match.
        _register_login_chain(respx.mock, state)

        # After login, the entity service serves the real swagger HTML (with embedded spec).
        # Override the default entity_get to return the real fixture content.
        from tests.unit.test_auth import ENTITY_SERVICE_URL as ES_URL

        def entity_get(request: httpx.Request) -> httpx.Response:
            if not state.session_revoked and state.has_session_cookie(request):
                return httpx.Response(200, text=swagger_ui_html)
            from tests.unit.test_auth import OTDS_LOGIN_URL

            return httpx.Response(302, headers={"location": OTDS_LOGIN_URL})

        respx.mock.get(ES_URL).mock(side_effect=entity_get)

        async with AppworksClient(cfg) as client:
            catalog = await discover_catalog(client)

        assert catalog.service_name == "ExampleLegalManagement"
        assert len(catalog.entities) == 28

    @respx.mock
    async def test_wraps_http_failure_as_discovery_error(self) -> None:
        cfg = _make_config()
        respx.mock.get(ENTITY_SERVICE_URL).mock(return_value=httpx.Response(500, text="boom"))

        async with AppworksClient(cfg) as client:
            with pytest.raises(DiscoveryError):
                await discover_catalog(client)
