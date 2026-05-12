"""Tests for the OTDS login flow + 401-retry wrapper.

Uses respx to mock httpx so we can verify the four-step OTDS handshake end-to-end
without touching the network.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from opentext_pa_mcp.auth import AppworksClient
from opentext_pa_mcp.config import Config
from opentext_pa_mcp.errors import AuthenticationError, HttpError, NotFoundError

ENTITY_SERVICE_URL = (
    "https://api.example.com:3381/home/exampletenant/app/entityservice/ExampleLegalManagement"
)
OTDS_LOGIN_URL = "https://api.example.com:2281/otdsws/login?RFA=abc&postTicket=true"
OTDS_LOGIN_URL_NOQUERY = "https://api.example.com:2281/otdsws/login"
TICKET_CONSUMER_URL = (
    "https://api.example.com:3381/home/exampletenant/com.eibus.sso.otds.TicketConsumerService.wcp"
    "?AuthContext=preauthctx&RelayState=relay"
)
SESSION_COOKIE_NAME = "defaultinst_AuthContext"
SESSION_COOKIE_VALUE = "session-abc"


def _make_config(
    *,
    allow_writes: bool = False,
    verify_tls: bool = True,
    ca_bundle: str | None = None,
) -> Config:
    return Config(
        service_url=ENTITY_SERVICE_URL,
        username="awpadmin",
        password="ExampleApp@123",
        host="https://api.example.com:3381",
        tenant="exampletenant",
        service_name="ExampleLegalManagement",
        api_base="https://api.example.com:3381/home/exampletenant/app/entityRestService/api",
        entity_service_url=ENTITY_SERVICE_URL,
        allow_writes=allow_writes,
        verify_tls=verify_tls,
        ca_bundle=ca_bundle,
    )


def _login_form_html() -> str:
    return """
    <html><body>
      <form method="POST" action="login" id="thisform">
        <input type="hidden" name="otdscsrf" value="csrf-token-1">
        <input type="hidden" name="RFA" value="rfa-token-1">
        <input id="otds_username" name="otds_username" type="text">
        <input id="otds_password" name="otds_password" type="password">
      </form>
    </body></html>
    """


def _ticket_form_html(action: str = TICKET_CONSUMER_URL) -> str:
    return f"""
    <html><body>
      <form action="{action}" method="post">
        <input type="hidden" name="OTDSTicket" value="*VER2*ABC123"/>
      </form>
    </body></html>
    """


def _swagger_ui_html() -> str:
    return '<html><body>var dyn_spec_obj = {"openapi":"3.0.1"};</body></html>'


class LoginState:
    """Stateful handler set: models the server's view of session validity.

    ``session_revoked`` lets tests model session expiry (the API returns 401 and the
    entity service stops accepting the cookie until a fresh login).
    """

    def __init__(self) -> None:
        self.session_revoked: bool = True  # no session at start
        self.invalidate_next_api: bool = False

    def has_session_cookie(self, request: httpx.Request) -> bool:
        cookie_header = request.headers.get("cookie", "")
        return f"{SESSION_COOKIE_NAME}={SESSION_COOKIE_VALUE}" in cookie_header

    def entity_get(self, request: httpx.Request) -> httpx.Response:
        if not self.session_revoked and self.has_session_cookie(request):
            return httpx.Response(200, text=_swagger_ui_html())
        return httpx.Response(302, headers={"location": OTDS_LOGIN_URL})

    def otds_get(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_login_form_html())

    def otds_post(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_ticket_form_html())

    def ticket_post(self, request: httpx.Request) -> httpx.Response:
        self.session_revoked = False
        return httpx.Response(
            200,
            text="ok",
            headers={
                "set-cookie": f"{SESSION_COOKIE_NAME}={SESSION_COOKIE_VALUE}; Path=/",
            },
        )


def _register_login_chain(mock: respx.Router, state: LoginState) -> None:
    mock.get(ENTITY_SERVICE_URL).mock(side_effect=state.entity_get)
    mock.get(OTDS_LOGIN_URL).mock(side_effect=state.otds_get)
    mock.post(OTDS_LOGIN_URL_NOQUERY).mock(side_effect=state.otds_post)
    mock.post(TICKET_CONSUMER_URL).mock(side_effect=state.ticket_post)


class TestEndToEndLogin:
    @respx.mock
    async def test_successful_login_returns_entity_service_html(self) -> None:
        cfg = _make_config()
        _register_login_chain(respx.mock, LoginState())

        async with AppworksClient(cfg) as client:
            html_text = await client.fetch_entity_service_html()

        assert "dyn_spec_obj" in html_text

    @respx.mock
    async def test_login_sends_correct_credentials_and_tokens(self) -> None:
        cfg = _make_config()
        _register_login_chain(respx.mock, LoginState())

        async with AppworksClient(cfg) as client:
            await client.fetch_entity_service_html()

        login_post = next(
            call
            for call in respx.mock.calls
            if call.request.method == "POST" and str(call.request.url) == OTDS_LOGIN_URL_NOQUERY
        )
        body = login_post.request.content.decode()
        assert "otds_username=awpadmin" in body
        assert "otds_password=ExampleApp%40123" in body  # url-encoded @
        assert "otdscsrf=csrf-token-1" in body
        assert "RFA=rfa-token-1" in body

    @respx.mock
    async def test_ticket_post_sends_otds_ticket(self) -> None:
        cfg = _make_config()
        _register_login_chain(respx.mock, LoginState())

        async with AppworksClient(cfg) as client:
            await client.fetch_entity_service_html()

        ticket_post = next(
            call
            for call in respx.mock.calls
            if call.request.method == "POST" and "TicketConsumerService" in str(call.request.url)
        )
        assert "OTDSTicket=" in ticket_post.request.content.decode()


class TestLoginFailures:
    @respx.mock
    async def test_login_form_missing_csrf_raises_auth_error(self) -> None:
        cfg = _make_config()
        respx.mock.get(ENTITY_SERVICE_URL).mock(
            return_value=httpx.Response(302, headers={"location": OTDS_LOGIN_URL})
        )
        respx.mock.get(OTDS_LOGIN_URL).mock(
            return_value=httpx.Response(200, text="<html>no form fields</html>")
        )

        async with AppworksClient(cfg) as client:
            with pytest.raises(AuthenticationError, match=r"(?i)csrf"):
                await client.fetch_entity_service_html()

    @respx.mock
    async def test_bad_credentials_no_ticket_form_raises_auth_error(self) -> None:
        cfg = _make_config()
        respx.mock.get(ENTITY_SERVICE_URL).mock(
            return_value=httpx.Response(302, headers={"location": OTDS_LOGIN_URL})
        )
        respx.mock.get(OTDS_LOGIN_URL).mock(
            return_value=httpx.Response(200, text=_login_form_html())
        )
        # On bad creds, OTDS re-renders the login form (no OTDSTicket).
        respx.mock.post(OTDS_LOGIN_URL_NOQUERY).mock(
            return_value=httpx.Response(200, text=_login_form_html())
        )

        async with AppworksClient(cfg) as client:
            with pytest.raises(AuthenticationError, match=r"(?i)ticket"):
                await client.fetch_entity_service_html()


class TestApiCalls:
    @respx.mock
    async def test_get_api_call_succeeds_with_session(self) -> None:
        cfg = _make_config()
        _register_login_chain(respx.mock, LoginState())
        api_url = f"{cfg.api_base}/ExampleLegalManagement/entities/LegalCategory/items/24"
        respx.mock.get(api_url).mock(
            return_value=httpx.Response(
                200, json={"Properties": {"Name": "Mergers & Acquisitions"}}
            )
        )

        async with AppworksClient(cfg) as client:
            resp = await client.api_get("/ExampleLegalManagement/entities/LegalCategory/items/24")

        assert resp["Properties"]["Name"] == "Mergers & Acquisitions"

    @respx.mock
    async def test_404_raises_not_found_error(self) -> None:
        cfg = _make_config()
        _register_login_chain(respx.mock, LoginState())
        api_url = f"{cfg.api_base}/Foo/entities/Bar/items/999"
        respx.mock.get(api_url).mock(
            return_value=httpx.Response(404, json={"message": "not found"})
        )

        async with AppworksClient(cfg) as client:
            with pytest.raises(NotFoundError):
                await client.api_get("/Foo/entities/Bar/items/999")

    @respx.mock
    async def test_500_raises_http_error(self) -> None:
        cfg = _make_config()
        _register_login_chain(respx.mock, LoginState())
        api_url = f"{cfg.api_base}/x/y"
        respx.mock.get(api_url).mock(return_value=httpx.Response(500, text="boom"))

        async with AppworksClient(cfg) as client:
            with pytest.raises(HttpError) as exc:
                await client.api_get("/x/y")
            assert exc.value.status_code == 500

    @respx.mock
    async def test_401_triggers_re_login_and_retries(self) -> None:
        cfg = _make_config()
        state = LoginState()
        _register_login_chain(respx.mock, state)
        api_url = f"{cfg.api_base}/needs/retry"

        call_count = {"n": 0}

        def api_handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Server revokes the session at the same time it returns 401.
                state.session_revoked = True
                return httpx.Response(401, json={"message": "expired"})
            return httpx.Response(200, json={"ok": True})

        respx.mock.get(api_url).mock(side_effect=api_handler)

        async with AppworksClient(cfg) as client:
            resp = await client.api_get("/needs/retry")

        assert resp == {"ok": True}
        # Verify we did re-run the full login chain.
        login_posts = [
            c
            for c in respx.mock.calls
            if c.request.method == "POST" and str(c.request.url) == OTDS_LOGIN_URL_NOQUERY
        ]
        assert len(login_posts) == 2


class TestTlsConfig:
    """AppworksClient must propagate the config's TLS settings to httpx."""

    def test_default_uses_verify_true(self) -> None:
        from opentext_pa_mcp.auth import _resolve_verify

        cfg = _make_config()
        assert _resolve_verify(cfg) is True

    def test_disabled_verify(self) -> None:
        from opentext_pa_mcp.auth import _resolve_verify

        cfg = _make_config(verify_tls=False)
        assert _resolve_verify(cfg) is False

    def test_ca_bundle_overrides(self, tmp_path) -> None:
        from opentext_pa_mcp.auth import _resolve_verify

        ca = tmp_path / "ca.crt"
        ca.write_text("x")
        cfg = _make_config(ca_bundle=str(ca))
        assert _resolve_verify(cfg) == str(ca)


class TestFormActionExtraction:
    def test_extracts_relative_action(self) -> None:
        from opentext_pa_mcp.auth import _extract_form_action

        action = _extract_form_action(_login_form_html())
        assert action == "login"

    def test_returns_none_when_no_form(self) -> None:
        from opentext_pa_mcp.auth import _extract_form_action

        assert _extract_form_action("<html>no form here</html>") is None
