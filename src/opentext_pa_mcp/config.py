"""Environment-variable-driven configuration.

The MCP server is configured exclusively via env vars passed by the MCP client
(e.g. Claude Desktop's `mcpServers.*.env` block). The single :func:`load_config`
entry point parses and validates them at startup; everything downstream consumes
a frozen :class:`Config` dataclass.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .errors import ConfigurationError

# Env var names — kept in one place so the README, error messages, and code stay in sync.
ENV_SERVICE_URL = "PA_SERVICE_URL"
ENV_USERNAME = "PA_USERNAME"
ENV_PASSWORD = "PA_PASSWORD"
ENV_LOG_LEVEL = "PA_LOG_LEVEL"
ENV_REQUEST_TIMEOUT_S = "PA_REQUEST_TIMEOUT_S"
ENV_ALLOW_WRITES = "PA_ALLOW_WRITES"
ENV_VERIFY_TLS = "PA_VERIFY_TLS"
ENV_CA_BUNDLE = "PA_CA_BUNDLE"


@dataclass(frozen=True)
class Config:
    """Parsed and validated runtime configuration."""

    service_url: str
    """The exact URL the user pasted, normalised (no trailing slash)."""

    username: str
    password: str

    host: str
    """Scheme + host + port. Example: 'https://api.example.com:3381'."""

    tenant: str
    """The AppWorks organisation (parsed from `/home/<tenant>/`)."""

    service_name: str
    """The entity service name (last path segment of the input URL)."""

    api_base: str
    """REST API base URL, derived from host + tenant. Tools build paths underneath this."""

    entity_service_url: str
    """The URL we GET on first startup to retrieve the Swagger UI HTML containing the spec."""

    log_level: int = logging.INFO
    request_timeout_s: float = 30.0
    allow_writes: bool = False

    verify_tls: bool = True
    """Whether to verify TLS certificates. Default: True. Disable only for self-signed
    dev/test environments where you cannot install the corporate CA."""

    ca_bundle: str | None = None
    """Path to a custom CA bundle file (PEM). Use this for AppWorks installs behind
    a corporate internal CA. Overrides system trust store. Mutually exclusive with
    ``verify_tls=False``."""

    def __repr__(self) -> str:
        # Custom repr keeps the password out of any log lines or crash dumps.
        return (
            f"Config(service_url={self.service_url!r}, username={self.username!r}, "
            f"password='***REDACTED***', host={self.host!r}, tenant={self.tenant!r}, "
            f"service_name={self.service_name!r}, allow_writes={self.allow_writes}, "
            f"verify_tls={self.verify_tls}, ca_bundle={self.ca_bundle!r})"
        )

    def httpx_verify(self) -> bool | str:
        """Return the value to pass as ``httpx.AsyncClient(verify=...)``.

        Resolution: a custom CA bundle wins; otherwise the boolean ``verify_tls`` flag.
        """
        if self.ca_bundle:
            return self.ca_bundle
        return self.verify_tls


def load_config(env: dict[str, str] | None = None) -> Config:
    """Build a :class:`Config` from the process environment (or an injected dict for tests).

    Raises:
        ConfigurationError: if any required variable is missing or any value is malformed.
    """
    env = env if env is not None else dict(os.environ)

    service_url = _require(env, ENV_SERVICE_URL).rstrip("/")
    username = _require(env, ENV_USERNAME)
    password = _require(env, ENV_PASSWORD)

    host, tenant, service_name = _split_service_url(service_url)
    api_base = f"{host}/home/{tenant}/app/entityRestService/api"

    log_level = _parse_log_level(env.get(ENV_LOG_LEVEL))
    timeout = _parse_timeout(env.get(ENV_REQUEST_TIMEOUT_S))
    allow_writes = _parse_bool(env.get(ENV_ALLOW_WRITES), default=False)
    verify_tls, ca_bundle = _parse_tls_settings(env.get(ENV_VERIFY_TLS), env.get(ENV_CA_BUNDLE))

    return Config(
        service_url=service_url,
        username=username,
        password=password,
        host=host,
        tenant=tenant,
        service_name=service_name,
        api_base=api_base,
        entity_service_url=service_url,
        log_level=log_level,
        request_timeout_s=timeout,
        allow_writes=allow_writes,
        verify_tls=verify_tls,
        ca_bundle=ca_bundle,
    )


def _require(env: dict[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigurationError(
            f"Required environment variable {name} is missing or empty. "
            f"Set it in your MCP client config (e.g. Claude Desktop mcpServers.*.env)."
        )
    return value


def _split_service_url(url: str) -> tuple[str, str, str]:
    """Parse PA_SERVICE_URL into (host, tenant, service_name).

    Accepts:
        http://host[:port]/home/<tenant>/app/entityservice/<ServiceName>
    """
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ConfigurationError(f"{ENV_SERVICE_URL} is not a valid http(s) URL: {url!r}")

    path_segments = [seg for seg in parts.path.split("/") if seg]
    # Expected: ['home', '<tenant>', 'app', 'entityservice', '<ServiceName>']
    if len(path_segments) < 5 or path_segments[0] != "home" or path_segments[2] != "app":
        raise ConfigurationError(
            f"{ENV_SERVICE_URL} does not look like an AppWorks entity service URL. "
            f"Expected '.../home/<tenant>/app/entityservice/<ServiceName>', got: {url!r}"
        )
    if path_segments[3] != "entityservice":
        raise ConfigurationError(
            f"{ENV_SERVICE_URL} points at '/{path_segments[3]}/' but this server only supports "
            f"'/entityservice/<ServiceName>' URLs (e.g. the URL shown in the Swagger UI). Got: {url!r}"
        )

    host = f"{parts.scheme}://{parts.netloc}"
    tenant = path_segments[1]
    service_name = path_segments[4]
    return host, tenant, service_name


def _parse_log_level(raw: str | None) -> int:
    if not raw:
        return logging.INFO
    level = logging.getLevelNamesMapping().get(raw.strip().upper())
    if level is None:
        raise ConfigurationError(
            f"{ENV_LOG_LEVEL}={raw!r} is not a valid level. "
            f"Expected one of: DEBUG, INFO, WARNING, ERROR, CRITICAL."
        )
    return level


def _parse_timeout(raw: str | None) -> float:
    if not raw:
        return 30.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{ENV_REQUEST_TIMEOUT_S}={raw!r} is not a number.") from exc
    if value <= 0:
        raise ConfigurationError(f"{ENV_REQUEST_TIMEOUT_S} must be positive, got {value}.")
    return value


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_tls_settings(
    verify_raw: str | None, ca_bundle_raw: str | None
) -> tuple[bool, str | None]:
    """Parse and validate the TLS-related env vars.

    Returns a tuple ``(verify_tls, ca_bundle)``.

    Rules:
    - Defaults are ``(True, None)`` — TLS on, use system trust store.
    - ``PA_VERIFY_TLS=false`` disables verification entirely (insecure).
    - ``PA_CA_BUNDLE=/path/to/ca.pem`` points httpx at a custom CA file.
    - Setting both ``PA_VERIFY_TLS=false`` AND ``PA_CA_BUNDLE`` is contradictory and raises.
    - A non-existent ``PA_CA_BUNDLE`` path raises.
    """
    verify_tls = _parse_bool(verify_raw, default=True)
    ca_bundle = (ca_bundle_raw or "").strip() or None

    if ca_bundle is not None and verify_raw is not None and not verify_tls:
        raise ConfigurationError(
            f"{ENV_VERIFY_TLS}=false and {ENV_CA_BUNDLE} are both set, which is contradictory. "
            f"Either drop {ENV_VERIFY_TLS} to use the CA bundle, or drop {ENV_CA_BUNDLE} "
            f"to skip verification entirely."
        )

    if ca_bundle is not None and not Path(ca_bundle).is_file():
        raise ConfigurationError(
            f"{ENV_CA_BUNDLE}={ca_bundle!r} does not point to a readable file."
        )

    return verify_tls, ca_bundle
