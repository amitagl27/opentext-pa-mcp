"""Tests for environment-variable-driven configuration loading."""

from __future__ import annotations

import logging

import pytest

from opentext_pa_mcp.config import load_config
from opentext_pa_mcp.errors import ConfigurationError

VALID_URL = (
    "https://api.example.com:3381/home/exampletenant/app/entityservice/ExampleLegalManagement"
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Strip every PA_* env var so each test starts from zero."""
    for key in [
        "PA_SERVICE_URL",
        "PA_USERNAME",
        "PA_PASSWORD",
        "PA_LOG_LEVEL",
        "PA_REQUEST_TIMEOUT_S",
        "PA_ALLOW_WRITES",
        "PA_AUTH_MODE",
        "PA_VERIFY_TLS",
        "PA_CA_BUNDLE",
    ]:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


class TestParseServiceUrl:
    """The single PA_SERVICE_URL should yield host, tenant, service name, and derived API base."""

    def test_parses_canonical_url(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "awpadmin")
        clean_env.setenv("PA_PASSWORD", "<YOUR_PASSWORD>")

        cfg = load_config()

        assert cfg.service_url == VALID_URL
        assert cfg.host == "https://api.example.com:3381"
        assert cfg.tenant == "exampletenant"
        assert cfg.service_name == "ExampleLegalManagement"
        # The OpenAPI spec's declared server URL is /home/{tenant}/app/entityRestService/api
        assert (
            cfg.api_base
            == "https://api.example.com:3381/home/exampletenant/app/entityRestService/api"
        )
        # Entity service URL (where the Swagger UI HTML and login redirect live) is the input itself
        assert cfg.entity_service_url == VALID_URL

    def test_trailing_slash_is_tolerated(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL + "/")
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")

        cfg = load_config()

        assert cfg.service_name == "ExampleLegalManagement"
        assert cfg.entity_service_url == VALID_URL  # normalised — trailing slash stripped

    def test_https_url_is_supported(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv(
            "PA_SERVICE_URL",
            "https://pa.example.com/home/acme/app/entityservice/InvoiceManagement",
        )
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")

        cfg = load_config()

        assert cfg.host == "https://pa.example.com"
        assert cfg.tenant == "acme"
        assert cfg.service_name == "InvoiceManagement"


class TestValidation:
    def test_missing_service_url_raises(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        with pytest.raises(ConfigurationError, match="PA_SERVICE_URL"):
            load_config()

    def test_missing_username_raises(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_PASSWORD", "p")
        with pytest.raises(ConfigurationError, match="PA_USERNAME"):
            load_config()

    def test_missing_password_raises(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        with pytest.raises(ConfigurationError, match="PA_PASSWORD"):
            load_config()

    def test_malformed_url_raises(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", "not-a-url")
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        with pytest.raises(ConfigurationError):
            load_config()

    def test_url_without_entity_service_segment_raises(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv(
            "PA_SERVICE_URL", "https://api.example.com:3381/home/exampletenant/app/admin"
        )
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        with pytest.raises(ConfigurationError, match="entityservice"):
            load_config()


class TestOptionalDefaults:
    def test_log_level_defaults_to_info(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        cfg = load_config()
        assert cfg.log_level == logging.INFO

    def test_log_level_overridable(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        clean_env.setenv("PA_LOG_LEVEL", "DEBUG")
        cfg = load_config()
        assert cfg.log_level == logging.DEBUG

    def test_invalid_log_level_raises(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        clean_env.setenv("PA_LOG_LEVEL", "NOTALEVEL")
        with pytest.raises(ConfigurationError, match="PA_LOG_LEVEL"):
            load_config()

    def test_timeout_default(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        cfg = load_config()
        assert cfg.request_timeout_s == 30.0

    def test_timeout_overridable(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        clean_env.setenv("PA_REQUEST_TIMEOUT_S", "60")
        cfg = load_config()
        assert cfg.request_timeout_s == 60.0

    def test_allow_writes_default_false(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        cfg = load_config()
        assert cfg.allow_writes is False

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("true", True),
            ("TRUE", True),
            ("1", True),
            ("false", False),
            ("0", False),
            ("no", False),
        ],
    )
    def test_allow_writes_truthy_parsing(
        self, clean_env: pytest.MonkeyPatch, value: str, expected: bool
    ) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        clean_env.setenv("PA_ALLOW_WRITES", value)
        cfg = load_config()
        assert cfg.allow_writes is expected


class TestTlsConfig:
    """PA_VERIFY_TLS and PA_CA_BUNDLE control httpx TLS verification."""

    def test_verify_tls_defaults_to_true(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        cfg = load_config()
        assert cfg.verify_tls is True
        assert cfg.ca_bundle is None

    def test_verify_tls_can_be_disabled(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        clean_env.setenv("PA_VERIFY_TLS", "false")
        cfg = load_config()
        assert cfg.verify_tls is False

    def test_ca_bundle_path_is_loaded(self, clean_env: pytest.MonkeyPatch, tmp_path) -> None:
        ca = tmp_path / "corp-ca.crt"
        ca.write_text("-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n")
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        clean_env.setenv("PA_CA_BUNDLE", str(ca))
        cfg = load_config()
        assert cfg.ca_bundle == str(ca)
        # PA_VERIFY_TLS unset => still default True (CA bundle implies verification on).
        assert cfg.verify_tls is True

    def test_ca_bundle_nonexistent_path_raises(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        clean_env.setenv("PA_CA_BUNDLE", r"C:\does\not\exist.crt")
        with pytest.raises(ConfigurationError, match="PA_CA_BUNDLE"):
            load_config()

    def test_ca_bundle_with_verify_false_is_contradictory(
        self, clean_env: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Setting both PA_VERIFY_TLS=false and PA_CA_BUNDLE is nonsense — fail fast."""
        ca = tmp_path / "ca.crt"
        ca.write_text("x")
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        clean_env.setenv("PA_VERIFY_TLS", "false")
        clean_env.setenv("PA_CA_BUNDLE", str(ca))
        with pytest.raises(ConfigurationError, match=r"(?i)both"):
            load_config()


class TestHttpxVerifyValue:
    """The Config exposes an ``httpx_verify`` helper that produces the value
    to pass to ``httpx.AsyncClient(verify=...)``."""

    def test_default_verify_is_true(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        cfg = load_config()
        assert cfg.httpx_verify() is True

    def test_disabled_verify_is_false(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        clean_env.setenv("PA_VERIFY_TLS", "false")
        cfg = load_config()
        assert cfg.httpx_verify() is False

    def test_ca_bundle_returns_path_string(self, clean_env: pytest.MonkeyPatch, tmp_path) -> None:
        ca = tmp_path / "ca.crt"
        ca.write_text("x")
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        clean_env.setenv("PA_CA_BUNDLE", str(ca))
        cfg = load_config()
        assert cfg.httpx_verify() == str(ca)


class TestAuthMode:
    """PA_AUTH_MODE selects which login strategy to use (DEC-014)."""

    def test_defaults_to_auto(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        cfg = load_config()
        assert cfg.auth_mode == "auto"

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("auto", "auto"),
            ("AUTO", "auto"),
            ("otds", "otds"),
            ("OTDS", "otds"),
            ("Otds", "otds"),
            ("cordys", "cordys"),
            ("Cordys", "cordys"),
            ("CORDYS", "cordys"),
            ("  otds  ", "otds"),  # whitespace tolerated
        ],
    )
    def test_accepted_values_normalise_to_lowercase(
        self, clean_env: pytest.MonkeyPatch, value: str, expected: str
    ) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        clean_env.setenv("PA_AUTH_MODE", value)
        cfg = load_config()
        assert cfg.auth_mode == expected

    @pytest.mark.parametrize("value", ["saml", "basic", "ntlm", "true", "", "  "])
    def test_invalid_value_raises(
        self, clean_env: pytest.MonkeyPatch, value: str
    ) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "p")
        clean_env.setenv("PA_AUTH_MODE", value)
        with pytest.raises(ConfigurationError, match="PA_AUTH_MODE"):
            load_config()


class TestSecrecyOfRepr:
    def test_password_not_in_repr(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("PA_SERVICE_URL", VALID_URL)
        clean_env.setenv("PA_USERNAME", "u")
        clean_env.setenv("PA_PASSWORD", "supersecret")
        cfg = load_config()
        assert "supersecret" not in repr(cfg)
        assert "***" in repr(cfg) or "REDACTED" in repr(cfg)
