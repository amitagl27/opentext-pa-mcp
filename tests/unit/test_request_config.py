"""Tests for the per-HTTP-request :class:`Config` builder (DEC-015).

In http mode each MCP request carries the tenant fields as HTTP headers:

- ``Authorization: Basic <base64(username:password)>`` — required.
- ``X-PA-Service-URL: <full entity-service URL>`` — required (or server-side default).
- ``X-PA-Auth-Mode: auto|otds|cordys`` — optional, overrides the server default.

``build_request_config(headers, defaults)`` merges those headers with the server-level
defaults (transport / TLS / timeout / log level) to produce a complete :class:`Config`
ready to drive an :class:`AppworksClient`.
"""

from __future__ import annotations

import base64

import pytest

from opentext_pa_mcp.config import Config, load_config
from opentext_pa_mcp.errors import AuthenticationError, ConfigurationError
from opentext_pa_mcp.request_config import build_request_config

VALID_SERVICE_URL = (
    "https://api.example.com:3381/home/exampletenant/app/entityservice/ExampleLegalManagement"
)


@pytest.fixture
def http_mode_defaults(monkeypatch: pytest.MonkeyPatch) -> Config:
    """A server-level Config loaded in http mode (no tenant credentials)."""
    for key in [
        "PA_SERVICE_URL",
        "PA_USERNAME",
        "PA_PASSWORD",
        "PA_AUTH_MODE",
        "PA_HTTP_HOST",
        "PA_HTTP_PORT",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PA_TRANSPORT", "http")
    return load_config()


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode("ascii")


class TestBasicCredentials:
    def test_parses_username_and_password_from_authorization(
        self, http_mode_defaults: Config
    ) -> None:
        headers = {
            "authorization": _basic("alice", "wonderland"),
            "x-pa-service-url": VALID_SERVICE_URL,
        }
        cfg = build_request_config(headers, defaults=http_mode_defaults)
        assert cfg.username == "alice"
        assert cfg.password == "wonderland"

    def test_password_containing_colon_is_preserved(self, http_mode_defaults: Config) -> None:
        """Credential payload must be split on the FIRST colon only."""
        headers = {
            "authorization": _basic("alice", "p:a:s:s"),
            "x-pa-service-url": VALID_SERVICE_URL,
        }
        cfg = build_request_config(headers, defaults=http_mode_defaults)
        assert cfg.username == "alice"
        assert cfg.password == "p:a:s:s"

    def test_unicode_username_supported(self, http_mode_defaults: Config) -> None:
        """OTDS deployments routinely have usernames like ``awpadmin@Tenant`` —
        ensure non-ASCII passes through cleanly."""
        headers = {
            "authorization": _basic("user@Some Realm", "пароль"),
            "x-pa-service-url": VALID_SERVICE_URL,
        }
        cfg = build_request_config(headers, defaults=http_mode_defaults)
        assert cfg.username == "user@Some Realm"
        assert cfg.password == "пароль"

    def test_header_name_is_case_insensitive(self, http_mode_defaults: Config) -> None:
        """RFC 7230: HTTP header names are case-insensitive. Builder must
        not depend on a specific casing."""
        headers = {
            "Authorization": _basic("alice", "pw"),
            "X-PA-Service-URL": VALID_SERVICE_URL,
        }
        cfg = build_request_config(headers, defaults=http_mode_defaults)
        assert cfg.username == "alice"


class TestAuthorizationFailures:
    def test_missing_authorization_header_raises_auth_error(
        self, http_mode_defaults: Config
    ) -> None:
        headers = {"x-pa-service-url": VALID_SERVICE_URL}
        with pytest.raises(AuthenticationError, match=r"(?i)authorization"):
            build_request_config(headers, defaults=http_mode_defaults)

    def test_non_basic_scheme_raises(self, http_mode_defaults: Config) -> None:
        headers = {
            "authorization": "Bearer some.jwt.token",
            "x-pa-service-url": VALID_SERVICE_URL,
        }
        with pytest.raises(AuthenticationError, match=r"(?i)basic"):
            build_request_config(headers, defaults=http_mode_defaults)

    def test_malformed_base64_raises(self, http_mode_defaults: Config) -> None:
        headers = {
            "authorization": "Basic !!!not-valid-base64!!!",
            "x-pa-service-url": VALID_SERVICE_URL,
        }
        with pytest.raises(AuthenticationError, match=r"(?i)(base64|decode|credentials)"):
            build_request_config(headers, defaults=http_mode_defaults)

    def test_credentials_without_colon_raises(self, http_mode_defaults: Config) -> None:
        # Base64 of "noColonHere" — no separator between user and password.
        encoded = base64.b64encode(b"noColonHere").decode("ascii")
        headers = {
            "authorization": f"Basic {encoded}",
            "x-pa-service-url": VALID_SERVICE_URL,
        }
        with pytest.raises(AuthenticationError, match=r"(?i)(colon|format|credentials)"):
            build_request_config(headers, defaults=http_mode_defaults)

    def test_empty_username_raises(self, http_mode_defaults: Config) -> None:
        encoded = base64.b64encode(b":onlypassword").decode("ascii")
        headers = {
            "authorization": f"Basic {encoded}",
            "x-pa-service-url": VALID_SERVICE_URL,
        }
        with pytest.raises(AuthenticationError, match=r"(?i)username"):
            build_request_config(headers, defaults=http_mode_defaults)


class TestServiceUrl:
    def test_service_url_header_derives_host_tenant_service(
        self, http_mode_defaults: Config
    ) -> None:
        headers = {
            "authorization": _basic("alice", "pw"),
            "x-pa-service-url": VALID_SERVICE_URL,
        }
        cfg = build_request_config(headers, defaults=http_mode_defaults)
        assert cfg.service_url == VALID_SERVICE_URL
        assert cfg.host == "https://api.example.com:3381"
        assert cfg.tenant == "exampletenant"
        assert cfg.service_name == "ExampleLegalManagement"
        assert (
            cfg.api_base
            == "https://api.example.com:3381/home/exampletenant/app/entityRestService/api"
        )
        assert cfg.entity_service_url == VALID_SERVICE_URL

    def test_service_url_trailing_slash_normalised(self, http_mode_defaults: Config) -> None:
        headers = {
            "authorization": _basic("alice", "pw"),
            "x-pa-service-url": VALID_SERVICE_URL + "/",
        }
        cfg = build_request_config(headers, defaults=http_mode_defaults)
        assert cfg.service_url == VALID_SERVICE_URL

    def test_missing_service_url_with_no_default_raises(self, http_mode_defaults: Config) -> None:
        headers = {"authorization": _basic("alice", "pw")}
        with pytest.raises(AuthenticationError, match=r"(?i)(service.?url|X-PA-Service-URL)"):
            build_request_config(headers, defaults=http_mode_defaults)

    def test_server_default_service_url_used_when_header_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Operators running a single-tenant http deployment can preset
        PA_SERVICE_URL — clients only need to send Authorization."""
        for key in [
            "PA_USERNAME",
            "PA_PASSWORD",
            "PA_AUTH_MODE",
            "PA_HTTP_HOST",
            "PA_HTTP_PORT",
        ]:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("PA_TRANSPORT", "http")
        monkeypatch.setenv("PA_SERVICE_URL", VALID_SERVICE_URL)
        defaults = load_config()

        headers = {"authorization": _basic("alice", "pw")}
        cfg = build_request_config(headers, defaults=defaults)
        assert cfg.service_url == VALID_SERVICE_URL
        assert cfg.tenant == "exampletenant"

    def test_header_overrides_server_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in ["PA_USERNAME", "PA_PASSWORD", "PA_AUTH_MODE"]:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("PA_TRANSPORT", "http")
        monkeypatch.setenv("PA_SERVICE_URL", VALID_SERVICE_URL)
        defaults = load_config()

        other_url = "https://other.example.com/home/acme/app/entityservice/InvoiceService"
        headers = {
            "authorization": _basic("alice", "pw"),
            "x-pa-service-url": other_url,
        }
        cfg = build_request_config(headers, defaults=defaults)
        assert cfg.service_url == other_url
        assert cfg.tenant == "acme"
        assert cfg.service_name == "InvoiceService"

    def test_malformed_service_url_raises_configuration_error(
        self, http_mode_defaults: Config
    ) -> None:
        headers = {
            "authorization": _basic("alice", "pw"),
            "x-pa-service-url": "not://a/valid/url",
        }
        with pytest.raises((AuthenticationError, ConfigurationError)):
            build_request_config(headers, defaults=http_mode_defaults)


class TestAuthMode:
    def test_default_falls_through_to_server_default(self, http_mode_defaults: Config) -> None:
        headers = {
            "authorization": _basic("alice", "pw"),
            "x-pa-service-url": VALID_SERVICE_URL,
        }
        cfg = build_request_config(headers, defaults=http_mode_defaults)
        # No header set, defaults.auth_mode is "auto" -> "auto".
        assert cfg.auth_mode == "auto"

    @pytest.mark.parametrize("value,expected", [("otds", "otds"), ("cordys", "cordys")])
    def test_header_overrides_default(
        self, http_mode_defaults: Config, value: str, expected: str
    ) -> None:
        headers = {
            "authorization": _basic("alice", "pw"),
            "x-pa-service-url": VALID_SERVICE_URL,
            "x-pa-auth-mode": value,
        }
        cfg = build_request_config(headers, defaults=http_mode_defaults)
        assert cfg.auth_mode == expected

    def test_invalid_auth_mode_header_raises(self, http_mode_defaults: Config) -> None:
        headers = {
            "authorization": _basic("alice", "pw"),
            "x-pa-service-url": VALID_SERVICE_URL,
            "x-pa-auth-mode": "kerberos",
        }
        with pytest.raises((AuthenticationError, ConfigurationError), match=r"(?i)auth.?mode"):
            build_request_config(headers, defaults=http_mode_defaults)


class TestServerLevelFieldsPreserved:
    """Server-level fields (TLS, timeout, log level, allow_writes, transport) must
    be carried over from defaults — clients can't override them per-request."""

    def test_tls_settings_inherited_from_defaults(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        ca = tmp_path / "ca.crt"  # type: ignore[attr-defined]
        ca.write_text("-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n")
        for key in [
            "PA_SERVICE_URL",
            "PA_USERNAME",
            "PA_PASSWORD",
            "PA_AUTH_MODE",
        ]:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("PA_TRANSPORT", "http")
        monkeypatch.setenv("PA_CA_BUNDLE", str(ca))
        defaults = load_config()

        headers = {
            "authorization": _basic("alice", "pw"),
            "x-pa-service-url": VALID_SERVICE_URL,
        }
        cfg = build_request_config(headers, defaults=defaults)
        assert cfg.ca_bundle == str(ca)
        assert cfg.verify_tls is True

    def test_transport_marker_carried_through(self, http_mode_defaults: Config) -> None:
        headers = {
            "authorization": _basic("alice", "pw"),
            "x-pa-service-url": VALID_SERVICE_URL,
        }
        cfg = build_request_config(headers, defaults=http_mode_defaults)
        assert cfg.transport == "http"

    def test_repr_redacts_password(self, http_mode_defaults: Config) -> None:
        headers = {
            "authorization": _basic("alice", "very-secret"),
            "x-pa-service-url": VALID_SERVICE_URL,
        }
        cfg = build_request_config(headers, defaults=http_mode_defaults)
        assert "very-secret" not in repr(cfg)
