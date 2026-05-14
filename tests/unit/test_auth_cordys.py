"""Tests for the Cordys built-in SSO login flow (DEC-014).

The Cordys flow is three HTTP steps once the strategy is selected:

1. POST a SAML 1.1 ``AuthenticationQuery`` SOAP envelope with WS-Security
   ``UsernameToken`` to ``{host}/home/{tenant}/com.eibus.web.soap.Gateway.wcp``
   → returns ``<samlp:AssertionArtifact>``.
2. POST the artifact in the ``SAMLart`` header (empty body) to
   ``{host}/home/{tenant}/wcp/sso/com.eibus.sso.web.authentication.AuthenticationToken.wcp``
   → sets ``{tenant.lower()}inst_SAMLart`` + ``{tenant.lower()}inst_ct`` cookies.
3. GET the entity service URL with those cookies → 200 with the Swagger UI HTML.

These tests use ``respx`` to mock httpx, with a stateful LoginState that models
the server's cookie-validity view (so 401-retry can be exercised).
"""

from __future__ import annotations

import httpx
import pytest
import respx

from opentext_pa_mcp.auth import AppworksClient
from opentext_pa_mcp.config import AuthMode, Config
from opentext_pa_mcp.errors import AuthenticationError

HOST = "http://pa.example.com:8081"
TENANT = "exampletenant"
SERVICE_NAME = "ExampleLegalManagement"
ENTITY_SERVICE_URL = f"{HOST}/home/{TENANT}/app/entityservice/{SERVICE_NAME}"
API_BASE = f"{HOST}/home/{TENANT}/app/entityRestService/api"
LOGIN_PAGE_URL = f"{HOST}/home/{TENANT}/wcp/sso/login.htm"
GATEWAY_URL = f"{HOST}/home/{TENANT}/com.eibus.web.soap.Gateway.wcp"
TOKEN_URL = (
    f"{HOST}/home/{TENANT}/wcp/sso/com.eibus.sso.web.authentication.AuthenticationToken.wcp"
)

# Cookies the server sets after the AuthenticationToken.wcp step. Cookie name prefix
# is the tenant name lowercased + "inst".
COOKIE_SAMLART = f"{TENANT.lower()}inst_SAMLart"
COOKIE_CT = f"{TENANT.lower()}inst_ct"
ARTIFACT_VALUE = "FAKE-ARTIFACT-1234567890abcdef"
CT_VALUE = "fake-ct-uuid-0000-1111-2222"


def _make_config(*, auth_mode: AuthMode = "auto") -> Config:
    return Config(
        service_url=ENTITY_SERVICE_URL,
        username="awpadmin@ExampleAuth With Spaces",
        password="P@ss w0rd!",
        host=HOST,
        tenant=TENANT,
        service_name=SERVICE_NAME,
        api_base=API_BASE,
        entity_service_url=ENTITY_SERVICE_URL,
        auth_mode=auth_mode,
    )


def _cordys_login_html() -> str:
    """Cordys built-in SSO login page — no otdscsrf/RFA, plain username/password fields."""
    return """
    <!DOCTYPE html>
    <html><head><title>Process Automation Login</title></head>
    <body>
      <div class="login-form-wrapper">
        <input id="username" name="username" type="text">
        <input id="password" name="password" type="password">
        <input type="button" id="buttonOK" onclick="doOnClick(event)" value="Sign In">
      </div>
    </body></html>
    """


def _saml_success_response(artifact: str = ARTIFACT_VALUE) -> str:
    return f"""<SOAP:Envelope xmlns:SOAP="http://schemas.xmlsoap.org/soap/envelope/">
  <SOAP:Body>
    <samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:1.0:protocol">
      <samlp:Status><samlp:StatusCode Value="samlp:Success"/></samlp:Status>
      <samlp:AssertionArtifact>{artifact}</samlp:AssertionArtifact>
    </samlp:Response>
  </SOAP:Body>
</SOAP:Envelope>"""


def _saml_invalid_credentials_fault() -> str:
    return """<SOAP:Envelope xmlns:SOAP="http://schemas.xmlsoap.org/soap/envelope/">
  <SOAP:Body>
    <SOAP:Fault>
      <faultcode xmlns:ns0="http://schemas.xmlsoap.org/soap/envelope/">ns0:Client</faultcode>
      <faultstring xml:lang="en-US">The username or password you entered is incorrect.</faultstring>
      <detail>
        <cordys:FaultDetails xmlns:cordys="http://schemas.cordys.com/General/1.0/">
          <cordys:LocalizableMessage>
            <cordys:MessageCode>Cordys.ESBServer.Messages.invalidCredentials</cordys:MessageCode>
          </cordys:LocalizableMessage>
        </cordys:FaultDetails>
      </detail>
    </SOAP:Fault>
  </SOAP:Body>
</SOAP:Envelope>"""


def _swagger_ui_html() -> str:
    return '<html><body>var dyn_spec_obj = {"openapi":"3.0.1"};</body></html>'


class CordysLoginState:
    """Stateful mock of a Cordys-protected AppWorks instance.

    Tracks whether the client has been issued session cookies. ``session_revoked``
    flips back to True when an API call returns 401 so the test can verify the
    relogin path.
    """

    def __init__(self) -> None:
        self.session_revoked: bool = True

    def has_session(self, request: httpx.Request) -> bool:
        cookie_header = request.headers.get("cookie", "")
        return (
            f"{COOKIE_SAMLART}={ARTIFACT_VALUE}" in cookie_header
            and f"{COOKIE_CT}={CT_VALUE}" in cookie_header
        )

    def entity_get(self, request: httpx.Request) -> httpx.Response:
        """Mimic the platform: serve Swagger UI if logged-in, else redirect to login page."""
        if not self.session_revoked and self.has_session(request):
            return httpx.Response(200, text=_swagger_ui_html())
        # Redirect chain ends at the Cordys login page.
        return httpx.Response(302, headers={"location": LOGIN_PAGE_URL})

    def login_page_get(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_cordys_login_html())

    def gateway_post(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_saml_success_response())

    def token_post(self, request: httpx.Request) -> httpx.Response:
        # The server returns Success and sets cookies on this host.
        self.session_revoked = False
        return httpx.Response(
            200,
            text="<Response><Result>Success</Result></Response>",
            headers=[
                ("set-cookie", f"{COOKIE_SAMLART}={ARTIFACT_VALUE}; Path=/; HttpOnly"),
                ("set-cookie", f"{COOKIE_CT}={CT_VALUE}; Path=/"),
            ],
        )


def _register_cordys_chain(mock: respx.Router, state: CordysLoginState) -> None:
    mock.get(ENTITY_SERVICE_URL).mock(side_effect=state.entity_get)
    mock.get(LOGIN_PAGE_URL).mock(side_effect=state.login_page_get)
    mock.post(GATEWAY_URL).mock(side_effect=state.gateway_post)
    mock.post(TOKEN_URL).mock(side_effect=state.token_post)


class TestEndToEndCordysLogin:
    @respx.mock
    async def test_auto_detect_routes_to_cordys_and_returns_swagger_html(self) -> None:
        cfg = _make_config(auth_mode="auto")
        _register_cordys_chain(respx.mock, CordysLoginState())

        async with AppworksClient(cfg) as client:
            html_text = await client.fetch_entity_service_html()

        assert "dyn_spec_obj" in html_text

    @respx.mock
    async def test_explicit_cordys_mode_skips_detection_and_succeeds(self) -> None:
        """With auth_mode='cordys', the client must POST the SAML envelope without
        first inspecting the login page shape."""
        cfg = _make_config(auth_mode="cordys")
        state = CordysLoginState()
        _register_cordys_chain(respx.mock, state)

        async with AppworksClient(cfg) as client:
            await client.fetch_entity_service_html()

        # In forced 'cordys' mode the strategy does not need to fetch the login.htm.
        # We only assert the SOAP gateway was hit (detection is optional in this mode).
        gateway_posts = [
            c for c in respx.mock.calls if str(c.request.url) == GATEWAY_URL
        ]
        assert len(gateway_posts) >= 1

    @respx.mock
    async def test_saml_envelope_contains_wsse_username_and_password(self) -> None:
        cfg = _make_config()
        _register_cordys_chain(respx.mock, CordysLoginState())

        async with AppworksClient(cfg) as client:
            await client.fetch_entity_service_html()

        gateway_post = next(c for c in respx.mock.calls if str(c.request.url) == GATEWAY_URL)
        body = gateway_post.request.content.decode("utf-8")
        # Username/password sit in the WS-Security UsernameToken in the SOAP header.
        assert "<wsse:Username>awpadmin@ExampleAuth With Spaces</wsse:Username>" in body
        assert "<wsse:Password>P@ss w0rd!</wsse:Password>" in body
        # And the username also appears as the SAML NameIdentifier subject.
        assert "<saml:NameIdentifier" in body
        assert "awpadmin@ExampleAuth With Spaces" in body
        # SOAPAction header is required by Cordys (can be empty).
        assert "SOAPAction" in gateway_post.request.headers
        # Content type must signal SOAP/XML.
        assert "xml" in gateway_post.request.headers.get("content-type", "").lower()

    @respx.mock
    async def test_token_post_sends_artifact_in_samlart_header(self) -> None:
        cfg = _make_config()
        _register_cordys_chain(respx.mock, CordysLoginState())

        async with AppworksClient(cfg) as client:
            await client.fetch_entity_service_html()

        token_post = next(c for c in respx.mock.calls if str(c.request.url) == TOKEN_URL)
        assert token_post.request.headers.get("SAMLart") == ARTIFACT_VALUE
        # Body should be empty (or near-empty); request type per Cordys reference impl.
        assert token_post.request.content in (b"", b" ")


class TestCordysLoginFailures:
    @respx.mock
    async def test_invalid_credentials_soap_fault_raises_auth_error(self) -> None:
        cfg = _make_config(auth_mode="cordys")
        # Redirect chain still resolves (in case strategy fetches login page), then SOAP fault.
        respx.mock.get(ENTITY_SERVICE_URL).mock(
            return_value=httpx.Response(302, headers={"location": LOGIN_PAGE_URL})
        )
        respx.mock.get(LOGIN_PAGE_URL).mock(
            return_value=httpx.Response(200, text=_cordys_login_html())
        )
        respx.mock.post(GATEWAY_URL).mock(
            return_value=httpx.Response(200, text=_saml_invalid_credentials_fault())
        )

        async with AppworksClient(cfg) as client:
            with pytest.raises(AuthenticationError, match=r"(?i)(credential|password|invalid)"):
                await client.fetch_entity_service_html()

    @respx.mock
    async def test_missing_artifact_in_success_response_raises_auth_error(self) -> None:
        """If the SOAP response is 200 but the artifact element is missing, fail loudly."""
        cfg = _make_config(auth_mode="cordys")
        respx.mock.get(ENTITY_SERVICE_URL).mock(
            return_value=httpx.Response(302, headers={"location": LOGIN_PAGE_URL})
        )
        respx.mock.get(LOGIN_PAGE_URL).mock(
            return_value=httpx.Response(200, text=_cordys_login_html())
        )
        no_artifact = """<SOAP:Envelope xmlns:SOAP="http://schemas.xmlsoap.org/soap/envelope/">
          <SOAP:Body><samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:1.0:protocol">
          <samlp:Status><samlp:StatusCode Value="samlp:Success"/></samlp:Status>
          </samlp:Response></SOAP:Body></SOAP:Envelope>"""
        respx.mock.post(GATEWAY_URL).mock(return_value=httpx.Response(200, text=no_artifact))

        async with AppworksClient(cfg) as client:
            with pytest.raises(AuthenticationError, match=r"(?i)artifact"):
                await client.fetch_entity_service_html()


class TestAutoDetect:
    @respx.mock
    async def test_unknown_login_page_shape_raises_auth_error(self) -> None:
        """Auto-detect must give a clear error when neither OTDS nor Cordys markers are present.

        The redirect must end on a URL that contains *neither* ``/otdsws/`` nor
        ``/wcp/sso/login.htm`` — otherwise the URL-based fallback would route to a
        specific strategy. We use a deliberately neutral path here.
        """
        cfg = _make_config(auth_mode="auto")
        unknown_login_url = f"{HOST}/home/{TENANT}/some/unfamiliar/login-page"
        respx.mock.get(ENTITY_SERVICE_URL).mock(
            return_value=httpx.Response(302, headers={"location": unknown_login_url})
        )
        respx.mock.get(unknown_login_url).mock(
            return_value=httpx.Response(200, text="<html>no recognised form here</html>")
        )

        async with AppworksClient(cfg) as client:
            with pytest.raises(AuthenticationError, match=r"(?i)(auth.?mode|recognis|detect)"):
                await client.fetch_entity_service_html()


class TestCordysApiCalls:
    @respx.mock
    async def test_401_triggers_cordys_relogin_and_retries(self) -> None:
        cfg = _make_config()
        state = CordysLoginState()
        _register_cordys_chain(respx.mock, state)
        api_url = f"{cfg.api_base}/needs/retry"
        call_count = {"n": 0}

        def api_handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] == 1:
                state.session_revoked = True
                return httpx.Response(401, json={"message": "expired"})
            return httpx.Response(200, json={"ok": True})

        respx.mock.get(api_url).mock(side_effect=api_handler)

        async with AppworksClient(cfg) as client:
            resp = await client.api_get("/needs/retry")

        assert resp == {"ok": True}
        # Two full SAML logins (initial + retry).
        gateway_posts = [c for c in respx.mock.calls if str(c.request.url) == GATEWAY_URL]
        assert len(gateway_posts) == 2
