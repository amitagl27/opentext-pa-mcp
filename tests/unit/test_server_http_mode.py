"""Tests for the http-transport branch of :func:`opentext_pa_mcp.server._resolve_session`.

In http mode each tool call must look up the inbound HTTP request's headers, build
a per-user :class:`Config`, and pull the matching :class:`Session` out of the cache
(creating it on first call). These tests stub :func:`fastmcp.server.dependencies.get_http_headers`
and the :class:`AppworksClient` / :func:`discover_catalog` factories so no real
network or FastMCP HTTP server is required.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, ClassVar

import pytest

from opentext_pa_mcp.config import Config, load_config
from opentext_pa_mcp.errors import AuthenticationError
from opentext_pa_mcp.server import (
    HttpAppContext,
    StdioAppContext,
    _resolve_session,
)
from opentext_pa_mcp.session_cache import SessionCache

VALID_SERVICE_URL = (
    "https://api.example.com:3381/home/exampletenant/app/entityservice/ExampleLegalManagement"
)
OTHER_SERVICE_URL = "https://api.example.com:3381/home/other/app/entityservice/InvoiceManagement"


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode("ascii")


@dataclass
class _FakeRequestContext:
    lifespan_context: Any


@dataclass
class _FakeCtx:
    request_context: _FakeRequestContext


class _FakeClient:
    instances: ClassVar[list[_FakeClient]] = []

    def __init__(self, config: Config) -> None:
        self.config = config
        _FakeClient.instances.append(self)

    async def aclose(self) -> None:  # pragma: no cover - close path not exercised here
        pass


class _FakeCatalog:
    def __init__(self, label: str) -> None:
        self.label = label


async def _fake_discover(client: _FakeClient) -> _FakeCatalog:
    return _FakeCatalog(label=f"catalog-{client.config.username}-{client.config.tenant}")


@pytest.fixture(autouse=True)
def _reset_fakes() -> None:
    _FakeClient.instances = []


@pytest.fixture
def http_defaults(monkeypatch: pytest.MonkeyPatch) -> Config:
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


def _ctx(defaults: Config) -> tuple[_FakeCtx, SessionCache]:
    cache = SessionCache(client_factory=_FakeClient, discover=_fake_discover)
    app = HttpAppContext(defaults=defaults, cache=cache)
    return _FakeCtx(_FakeRequestContext(lifespan_context=app)), cache


class TestStdioPath:
    """In stdio mode :func:`_resolve_session` must return the lifespan's single
    pre-built pair without ever looking at HTTP headers."""

    async def test_returns_lifespan_pair_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _FakeClient(
            Config(
                service_url=VALID_SERVICE_URL,
                username="root",
                password="x",
                host="https://api.example.com:3381",
                tenant="exampletenant",
                service_name="ExampleLegalManagement",
                api_base="https://api.example.com:3381/home/exampletenant/app/entityRestService/api",
                entity_service_url=VALID_SERVICE_URL,
            )
        )
        catalog = _FakeCatalog(label="static")
        app = StdioAppContext(config=client.config, client=client, catalog=catalog)  # type: ignore[arg-type]
        ctx = _FakeCtx(_FakeRequestContext(lifespan_context=app))

        # Ensure even calling get_http_headers would fail loudly in stdio mode:
        # _resolve_session must short-circuit before reaching it.
        def boom() -> dict[str, str]:
            raise AssertionError("get_http_headers must not be called in stdio mode")

        monkeypatch.setattr("opentext_pa_mcp.server.get_http_headers", boom)

        got_catalog, got_client = await _resolve_session(ctx)  # type: ignore[arg-type]
        assert got_catalog is catalog
        assert got_client is client


class TestHttpPath:
    async def test_resolves_session_from_basic_auth_headers(
        self, monkeypatch: pytest.MonkeyPatch, http_defaults: Config
    ) -> None:
        ctx, _ = _ctx(http_defaults)
        monkeypatch.setattr(
            "opentext_pa_mcp.server.get_http_headers",
            lambda: {
                "authorization": _basic("alice", "wonderland"),
                "x-pa-service-url": VALID_SERVICE_URL,
            },
        )

        catalog, client = await _resolve_session(ctx)  # type: ignore[arg-type]

        assert isinstance(catalog, _FakeCatalog)
        assert catalog.label == "catalog-alice-exampletenant"
        assert isinstance(client, _FakeClient)
        assert client.config.username == "alice"
        assert client.config.password == "wonderland"
        assert client.config.service_url == VALID_SERVICE_URL

    async def test_repeat_calls_for_same_user_reuse_session(
        self, monkeypatch: pytest.MonkeyPatch, http_defaults: Config
    ) -> None:
        ctx, _ = _ctx(http_defaults)
        monkeypatch.setattr(
            "opentext_pa_mcp.server.get_http_headers",
            lambda: {
                "authorization": _basic("alice", "wonderland"),
                "x-pa-service-url": VALID_SERVICE_URL,
            },
        )

        _, c1 = await _resolve_session(ctx)  # type: ignore[arg-type]
        _, c2 = await _resolve_session(ctx)  # type: ignore[arg-type]

        # Same user + URL => one session, one client.
        assert c1 is c2
        assert len(_FakeClient.instances) == 1

    async def test_different_users_get_isolated_sessions(
        self, monkeypatch: pytest.MonkeyPatch, http_defaults: Config
    ) -> None:
        ctx, _ = _ctx(http_defaults)

        # First call: alice.
        monkeypatch.setattr(
            "opentext_pa_mcp.server.get_http_headers",
            lambda: {
                "authorization": _basic("alice", "x"),
                "x-pa-service-url": VALID_SERVICE_URL,
            },
        )
        _, alice_client = await _resolve_session(ctx)  # type: ignore[arg-type]

        # Second call from the same process: bob.
        monkeypatch.setattr(
            "opentext_pa_mcp.server.get_http_headers",
            lambda: {
                "authorization": _basic("bob", "y"),
                "x-pa-service-url": VALID_SERVICE_URL,
            },
        )
        _, bob_client = await _resolve_session(ctx)  # type: ignore[arg-type]

        assert alice_client is not bob_client
        assert alice_client.config.username == "alice"  # type: ignore[attr-defined]
        assert bob_client.config.username == "bob"  # type: ignore[attr-defined]
        assert len(_FakeClient.instances) == 2

    async def test_different_service_urls_isolate_sessions(
        self, monkeypatch: pytest.MonkeyPatch, http_defaults: Config
    ) -> None:
        ctx, _ = _ctx(http_defaults)

        monkeypatch.setattr(
            "opentext_pa_mcp.server.get_http_headers",
            lambda: {
                "authorization": _basic("alice", "x"),
                "x-pa-service-url": VALID_SERVICE_URL,
            },
        )
        _, c1 = await _resolve_session(ctx)  # type: ignore[arg-type]

        monkeypatch.setattr(
            "opentext_pa_mcp.server.get_http_headers",
            lambda: {
                "authorization": _basic("alice", "x"),
                "x-pa-service-url": OTHER_SERVICE_URL,
            },
        )
        _, c2 = await _resolve_session(ctx)  # type: ignore[arg-type]

        assert c1 is not c2
        assert c1.config.tenant == "exampletenant"  # type: ignore[attr-defined]
        assert c2.config.tenant == "other"  # type: ignore[attr-defined]

    async def test_missing_authorization_raises_auth_error(
        self, monkeypatch: pytest.MonkeyPatch, http_defaults: Config
    ) -> None:
        ctx, _ = _ctx(http_defaults)
        monkeypatch.setattr(
            "opentext_pa_mcp.server.get_http_headers",
            lambda: {"x-pa-service-url": VALID_SERVICE_URL},
        )
        with pytest.raises(AuthenticationError, match=r"(?i)authorization"):
            await _resolve_session(ctx)  # type: ignore[arg-type]
