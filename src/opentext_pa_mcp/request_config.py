"""Build a per-request :class:`Config` from inbound HTTP headers (DEC-015).

In http transport mode, the MCP server does not know any tenant credentials at
startup — each MCP request carries them in headers:

- ``Authorization: Basic <base64(username:password)>`` *(required)*
- ``X-PA-Service-URL: <full entity-service URL>`` *(required, or supplied via
  ``PA_SERVICE_URL`` on the server)*
- ``X-PA-Auth-Mode: auto|otds|cordys`` *(optional; overrides ``PA_AUTH_MODE``)*

The builder merges those headers with the server-level :class:`Config` (transport,
TLS settings, timeout, log level, allow_writes) to produce a new :class:`Config`
that can drive an :class:`opentext_pa_mcp.auth.AppworksClient`.

All errors raise :class:`AuthenticationError` so the MCP layer returns a clean
``"AuthenticationError"`` to the caller — never a 500.
"""

from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import replace

from .config import AuthMode, Config, _split_service_url
from .errors import AuthenticationError, ConfigurationError

logger = logging.getLogger(__name__)

HEADER_AUTHORIZATION = "authorization"
HEADER_SERVICE_URL = "x-pa-service-url"
HEADER_AUTH_MODE = "x-pa-auth-mode"


def build_request_config(headers: dict[str, str], *, defaults: Config) -> Config:
    """Return a fully-populated :class:`Config` for one MCP request.

    Args:
        headers: HTTP request headers. Keys are matched case-insensitively, so the
            dict produced by ``fastmcp.server.dependencies.get_http_headers()``
            (lowercased) works directly.
        defaults: The server-level :class:`Config` from :func:`load_config` — its
            TLS, timeout, log-level, allow_writes, transport, and any preset
            tenant fields are used as fallbacks.

    Raises:
        AuthenticationError: when required headers are missing or malformed.
        ConfigurationError: when a header value parses but is invalid (e.g.
            malformed service URL).
    """
    lowered = {k.lower(): v for k, v in headers.items()}

    username, password = _parse_basic_authorization(lowered.get(HEADER_AUTHORIZATION))
    service_url = _resolve_service_url(lowered.get(HEADER_SERVICE_URL), defaults)
    auth_mode = _resolve_auth_mode(lowered.get(HEADER_AUTH_MODE), defaults)

    try:
        host, tenant, service_name = _split_service_url(service_url)
    except ConfigurationError as exc:
        # Re-raise as AuthenticationError so the client sees a single error class
        # for "your request inputs were bad", consistent with auth/URL failures.
        raise AuthenticationError(
            f"X-PA-Service-URL is not a valid AppWorks entity service URL: {exc}"
        ) from exc
    api_base = f"{host}/home/{tenant}/app/entityRestService/api"

    return replace(
        defaults,
        service_url=service_url,
        username=username,
        password=password,
        host=host,
        tenant=tenant,
        service_name=service_name,
        api_base=api_base,
        entity_service_url=service_url,
        auth_mode=auth_mode,
    )


def _parse_basic_authorization(raw: str | None) -> tuple[str, str]:
    """Decode the ``Authorization: Basic …`` header into ``(username, password)``."""
    if not raw:
        raise AuthenticationError(
            "Missing Authorization header. Send 'Authorization: Basic "
            "<base64(username:password)>' on every request."
        )
    parts = raw.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "basic":
        raise AuthenticationError(
            "Only Basic authentication is supported in http mode. "
            "Send 'Authorization: Basic <base64(username:password)>'."
        )
    try:
        decoded = base64.b64decode(parts[1].strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AuthenticationError("Authorization header credentials are not valid base64.") from exc
    try:
        text = decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuthenticationError("Authorization header credentials are not valid UTF-8.") from exc
    if ":" not in text:
        raise AuthenticationError(
            "Authorization credentials must be in 'username:password' format "
            "(no colon found after base64 decode)."
        )
    username, password = text.split(":", 1)
    if not username:
        raise AuthenticationError("Authorization header carried an empty username.")
    return username, password


def _resolve_service_url(header_value: str | None, defaults: Config) -> str:
    """Pick the request's service URL: header takes precedence, then server default."""
    candidate = (header_value or "").strip().rstrip("/")
    if candidate:
        return candidate
    if defaults.service_url:
        return defaults.service_url
    raise AuthenticationError(
        "Missing X-PA-Service-URL header and no PA_SERVICE_URL default is set "
        "on the server. Send the full entity-service URL on every request."
    )


def _resolve_auth_mode(header_value: str | None, defaults: Config) -> AuthMode:
    """Override ``defaults.auth_mode`` if X-PA-Auth-Mode is supplied."""
    if header_value is None:
        return defaults.auth_mode
    value = header_value.strip().lower()
    if value not in {"auto", "otds", "cordys"}:
        raise AuthenticationError(
            f"X-PA-Auth-Mode={header_value!r} is not valid. "
            "Expected one of: auto, otds, cordys (case-insensitive)."
        )
    return value  # type: ignore[return-value]
