"""AppWorks HTTP client with pluggable login strategies + on-401 re-login.

Two strategies are supported (see DEC-014):

**OTDS** (AppWorks 23.x, OTDS-fronted). Four HTTP steps:

1. GET the protected entity-service URL. The platform redirects through OTDS and ends on
   an HTML login page that contains an ``otdscsrf`` token and an ``RFA`` JWT-like token.
2. POST credentials (``otds_username``, ``otds_password``) plus the two tokens to the
   OTDS login endpoint. The response is HTML containing an auto-submit form with a
   hidden ``OTDSTicket``.
3. POST that ticket to the AppWorks TicketConsumerService. The session cookie is set.
4. Use the resulting session cookie for subsequent API calls. On 401, re-run from step 1.

**Cordys built-in SSO** (Process Automation CE 25.x). Three HTTP steps:

1. POST a SAML 1.1 ``AuthenticationQuery`` SOAP envelope with a WS-Security
   ``UsernameToken`` to ``{host}/home/{tenant}/com.eibus.web.soap.Gateway.wcp``.
2. Take the returned ``<samlp:AssertionArtifact>`` value and POST it as the ``SAMLart``
   header (with empty body) to ``.../wcp/sso/com.eibus.sso.web.authentication.AuthenticationToken.wcp``;
   the server replies with session cookies.
3. Use those cookies on subsequent API calls. On 401, re-run from step 1.

Auto-detection (``PA_AUTH_MODE=auto``, the default) inspects the login page reached after
the initial GET and routes to OTDS or Cordys based on the markers in the HTML.

Reference: ``docs/research/artifacts/Login-Appworks.ps1`` (OTDS),
``docs/research/artifacts/cordys-saml-request.xml`` (Cordys).
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import uuid
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from urllib.parse import urljoin

import httpx

from .config import Config
from .errors import AuthenticationError, HttpError, NotFoundError

logger = logging.getLogger(__name__)


# --- OTDS patterns ----------------------------------------------------------------------
_CSRF_PATTERN = re.compile(r'name="otdscsrf"\s+value="([^"]+)"')
_RFA_PATTERN = re.compile(r'name="RFA"\s+value="([^"]+)"')
# Locate the OTDS login form's action attribute. The form has id="thisform" and method=POST.
_LOGIN_FORM_ACTION_PATTERN = re.compile(
    r'<form[^>]*id="thisform"[^>]*action="([^"]+)"|<form[^>]*action="([^"]+)"[^>]*id="thisform"',
    re.IGNORECASE,
)
_TICKET_FORM_PATTERN = re.compile(
    r'<form\s+action="([^"]+)"\s+method="post">.*?name="OTDSTicket"\s+value="([^"]+)"',
    re.DOTALL | re.IGNORECASE,
)

# --- Cordys patterns --------------------------------------------------------------------
# Auto-detect markers: OTDS pages embed an otdscsrf hidden input; Cordys built-in pages
# carry the "Process Automation Login" title or end up under wcp/sso/login.htm.
_OTDS_MARKER_PATTERN = re.compile(r'name="otdscsrf"', re.IGNORECASE)
_CORDYS_MARKER_PATTERN = re.compile(
    r"<title>\s*Process Automation Login\s*</title>|/wcp/sso/login\.htm",
    re.IGNORECASE,
)
# SAML response parsers.
_SAML_ARTIFACT_PATTERN = re.compile(
    r"<samlp:AssertionArtifact[^>]*>([^<]+)</samlp:AssertionArtifact>",
    re.IGNORECASE,
)
_SOAP_FAULTSTRING_PATTERN = re.compile(
    r"<faultstring[^>]*>([^<]+)</faultstring>",
    re.IGNORECASE,
)

# SAML 1.1 AuthenticationQuery body used by the Cordys built-in SSO flow. See
# docs/research/artifacts/cordys-saml-request.xml for the annotated template.
_CORDYS_SAML_ENVELOPE = (
    '<SOAP:Envelope xmlns:SOAP="http://schemas.xmlsoap.org/soap/envelope/">'
    "<SOAP:Header>"
    '<wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
    "<wsse:UsernameToken>"
    "<wsse:Username>{username}</wsse:Username>"
    "<wsse:Password>{password}</wsse:Password>"
    "</wsse:UsernameToken>"
    "</wsse:Security>"
    "</SOAP:Header>"
    "<SOAP:Body>"
    '<samlp:Request xmlns:samlp="urn:oasis:names:tc:SAML:1.0:protocol"'
    ' MajorVersion="1" MinorVersion="1"'
    ' IssueInstant="{issue_instant}" RequestID="{request_id}">'
    "<samlp:AuthenticationQuery>"
    '<saml:Subject xmlns:saml="urn:oasis:names:tc:SAML:1.0:assertion">'
    '<saml:NameIdentifier Format="urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified">'
    "{username}"
    "</saml:NameIdentifier>"
    "</saml:Subject>"
    "</samlp:AuthenticationQuery>"
    "</samlp:Request>"
    "</SOAP:Body>"
    "</SOAP:Envelope>"
)


class AppworksClient:
    """Async HTTP client that maintains an authenticated AppWorks session.

    Use as an async context manager so the underlying :class:`httpx.AsyncClient` is closed::

        async with AppworksClient(config) as client:
            html = await client.fetch_entity_service_html()
            data = await client.api_get("/.../entities/Foo/lists/DefaultList?$top=1")
    """

    def __init__(self, config: Config, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            timeout=config.request_timeout_s,
            follow_redirects=True,
            verify=_resolve_verify(config),
        )
        self._login_lock = asyncio.Lock()
        self._authenticated = False
        if config.verify_tls is False and config.ca_bundle is None:
            logger.warning(
                "TLS verification is DISABLED (PA_VERIFY_TLS=false). "
                "Traffic is still encrypted but vulnerable to MITM. "
                "Use only against dev/test instances with self-signed certs."
            )

    async def __aenter__(self) -> AppworksClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    # --- Public surface -------------------------------------------------------------------

    async def fetch_entity_service_html(self) -> str:
        """Return the Swagger UI HTML for the configured entity service.

        Logs in if necessary. The HTML contains the inlined OpenAPI spec; pass it to
        :func:`opentext_pa_mcp.spec_extractor.extract_dyn_spec_obj` to get the dict.
        """
        await self._ensure_logged_in()
        # After login, the cookie jar is set; a fresh GET returns the actual page.
        resp = await self._http.get(self._config.entity_service_url)
        resp.raise_for_status()
        return resp.text

    async def api_get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """GET *path* under the entity-service REST API. Returns parsed JSON.

        On 401, re-run the configured login flow once and retry.

        Args:
            path: Path under the API base, beginning with ``/`` (e.g. ``/<Service>/entities/Foo/lists/DefaultList``).
            params: Optional query parameters to append.
        """
        await self._ensure_logged_in()
        url = self._build_url(path)
        resp = await self._http.get(url, params=params, headers={"Accept": "application/json"})

        if resp.status_code == 401:
            logger.info("API call returned 401; re-running login and retrying once.")
            self._authenticated = False
            await self._ensure_logged_in()
            resp = await self._http.get(url, params=params, headers={"Accept": "application/json"})

        return _raise_or_parse(resp)

    # --- Internal login flow --------------------------------------------------------------

    async def _ensure_logged_in(self) -> None:
        if self._authenticated:
            return
        async with self._login_lock:
            if self._authenticated:
                return
            await self._login()
            self._authenticated = True

    async def _login(self) -> None:
        """Dispatch to the configured login strategy.

        - ``cordys``: POST the SAML envelope directly (no preliminary page fetch).
        - ``otds``: GET the entity URL, then run the OTDS form-login dance.
        - ``auto``: GET the entity URL, inspect the resulting HTML, and route.
        """
        mode = self._config.auth_mode
        if mode == "cordys":
            await self._cordys_login()
            return

        # 'otds' and 'auto' both need the initial GET — for OTDS to find the form
        # tokens, and for auto-detect to decide which strategy to run.
        resp = await self._http.get(self._config.entity_service_url)
        login_html = resp.text
        page_url = str(resp.url)

        resolved = mode if mode != "auto" else _detect_auth_mode(login_html, page_url)
        if resolved == "otds":
            await self._otds_login(login_html, page_url)
        else:
            await self._cordys_login()

    async def _otds_login(self, login_html: str, page_url: str) -> None:
        """Run the four-step OTDS form-login flow against an already-fetched login page."""
        logger.info("Starting OTDS login for user %s.", self._config.username)

        csrf_match = _CSRF_PATTERN.search(login_html)
        rfa_match = _RFA_PATTERN.search(login_html)
        if not csrf_match or not rfa_match:
            raise AuthenticationError(
                "Login page did not contain the expected csrf / RFA tokens. "
                "Either the URL is not protected by OTDS, or the OTDS UI has changed. "
                "If this server uses Cordys built-in SSO, set PA_AUTH_MODE=cordys "
                "or leave PA_AUTH_MODE unset to auto-detect."
            )

        # Parse the form action and resolve it relative to the page URL. The login form
        # typically uses action="login" (relative) so urljoin against the page URL is
        # essential — the page URL is on a different host/port than the entity service.
        form_action = _extract_form_action(login_html) or "login"
        post_url = urljoin(page_url, html.unescape(form_action))

        # Step 2: POST credentials.
        login_form = {
            "otds_username": self._config.username,
            "otds_password": self._config.password,
            "otdscsrf": csrf_match.group(1),
            "RFA": rfa_match.group(1),
            "fragment": "",
            "authhandler": "",
        }
        resp = await self._http.post(post_url, data=login_form)
        ticket_html = resp.text

        ticket_match = _TICKET_FORM_PATTERN.search(ticket_html)
        if not ticket_match:
            raise AuthenticationError(
                "OTDS did not return an OTDSTicket form after submitting credentials. "
                "This usually means the username or password was rejected."
            )
        ticket_action = html.unescape(ticket_match.group(1))
        otds_ticket = ticket_match.group(2)

        # Step 3: POST the ticket to the TicketConsumerService.
        await self._http.post(ticket_action, data={"OTDSTicket": otds_ticket})
        logger.info("OTDS login complete; session cookies stored.")

    async def _cordys_login(self) -> None:
        """Run the three-step Cordys built-in SSO flow."""
        logger.info("Starting Cordys built-in SSO login for user %s.", self._config.username)
        envelope = _build_cordys_saml_envelope(
            username=self._config.username, password=self._config.password
        )
        gateway_url = (
            f"{self._config.host}/home/{self._config.tenant}/com.eibus.web.soap.Gateway.wcp"
        )
        resp = await self._http.post(
            gateway_url,
            content=envelope,
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
        )
        body = resp.text

        # Failure: SOAP fault with an invalidCredentials message code.
        fault_match = _SOAP_FAULTSTRING_PATTERN.search(body)
        if fault_match:
            message = fault_match.group(1).strip()
            raise AuthenticationError(f"Cordys SSO rejected the supplied credentials: {message}")

        # Success: extract the assertion artifact.
        artifact_match = _SAML_ARTIFACT_PATTERN.search(body)
        if not artifact_match:
            raise AuthenticationError(
                "Cordys SSO response did not contain a SAML AssertionArtifact. "
                f"Gateway returned HTTP {resp.status_code}; the response shape is unexpected."
            )
        artifact = artifact_match.group(1).strip()

        # Step 2: consume the artifact -> server sets the durable session cookies.
        token_url = (
            f"{self._config.host}/home/{self._config.tenant}"
            f"/wcp/sso/com.eibus.sso.web.authentication.AuthenticationToken.wcp"
        )
        await self._http.post(
            token_url,
            content=b"",
            headers={"SAMLart": artifact, "Content-Type": "text/plain"},
        )
        logger.info("Cordys SSO login complete; session cookies stored.")

    # --- Helpers --------------------------------------------------------------------------

    def _build_url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._config.api_base}{path}"


def _raise_or_parse(resp: httpx.Response) -> Any:
    """Convert an httpx response into parsed JSON or raise an :class:`HttpError`."""
    if 200 <= resp.status_code < 300:
        if not resp.content:
            return None
        return resp.json()

    message = _extract_error_message(resp)
    url = str(resp.url)
    if resp.status_code == 404:
        raise NotFoundError(message, url=url)
    raise HttpError(resp.status_code, message, url=url)


def _resolve_verify(config: Config) -> bool | str:
    """Resolve the value to pass to ``httpx.AsyncClient(verify=...)`` from *config*.

    A thin pass-through to :meth:`Config.httpx_verify` exposed at module scope so unit
    tests can assert the value without constructing an :class:`AppworksClient`.
    """
    return config.httpx_verify()


def _detect_auth_mode(login_html: str, page_url: str) -> str:
    """Return ``"otds"`` or ``"cordys"`` based on markers in the fetched login page.

    Raises:
        AuthenticationError: when neither set of markers is found. The caller is then
            expected to instruct the user to set ``PA_AUTH_MODE`` explicitly.
    """
    if _OTDS_MARKER_PATTERN.search(login_html) or "/otdsws/" in page_url:
        return "otds"
    if _CORDYS_MARKER_PATTERN.search(login_html) or _CORDYS_MARKER_PATTERN.search(page_url):
        return "cordys"
    raise AuthenticationError(
        "Could not auto-detect the AppWorks auth mode from the login page. "
        "Set PA_AUTH_MODE=otds or PA_AUTH_MODE=cordys to override detection."
    )


def _build_cordys_saml_envelope(*, username: str, password: str) -> str:
    """Render the SAML 1.1 AuthenticationQuery envelope for the Cordys SSO flow.

    The username and password are XML-escaped; a fresh request ID and UTC timestamp
    are generated per call so the server cannot reject as replay.
    """
    request_id = f"a{uuid.uuid4().hex}"
    issue_instant = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _CORDYS_SAML_ENVELOPE.format(
        username=html.escape(username, quote=False),
        password=html.escape(password, quote=False),
        request_id=request_id,
        issue_instant=issue_instant,
    )


def _extract_form_action(html_text: str) -> str | None:
    """Return the ``action`` attribute of the OTDS login form, or ``None`` if not found.

    Handles both attribute orderings (``id="thisform" action="..."`` and the reverse).
    """
    match = _LOGIN_FORM_ACTION_PATTERN.search(html_text)
    if not match:
        return None
    return match.group(1) or match.group(2)


def _extract_error_message(resp: httpx.Response) -> str:
    """Pull a useful error message out of an AppWorks error response.

    AppWorks REST errors are typically ``{"message": "...", "status": <code>}``. Falls back
    to the raw text or a generic placeholder.
    """
    try:
        body = resp.json()
    except ValueError:
        text = resp.text.strip()
        return text or f"HTTP {resp.status_code}"
    if isinstance(body, dict):
        for key in ("message", "error", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
    return f"HTTP {resp.status_code}"
