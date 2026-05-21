"""Tests for the per-(service_url, username) :class:`SessionCache` (DEC-015).

In http mode the server doesn't hold a single ``AppworksClient``. Instead, on each
inbound MCP request a session is fetched-or-created from this cache, keyed on the
tuple ``(service_url, username)``. The cache lives in process memory and is closed
when the server shuts down.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest

from opentext_pa_mcp.config import Config
from opentext_pa_mcp.session_cache import Session, SessionCache


def _make_config(*, service_url: str, username: str) -> Config:
    return Config(
        service_url=service_url,
        username=username,
        password=f"pwd-of-{username}",
        host="http://example.com",
        tenant="exampletenant",
        service_name="ExampleService",
        api_base="http://example.com/home/exampletenant/app/entityRestService/api",
        entity_service_url=service_url,
    )


class _FakeClient:
    """Stands in for :class:`AppworksClient` — records construction and close calls."""

    instances: ClassVar[list[_FakeClient]] = []

    def __init__(self, config: Config, **kwargs: Any) -> None:
        self.config = config
        self.closed = False
        _FakeClient.instances.append(self)

    async def aclose(self) -> None:
        self.closed = True


class _FakeCatalog:
    def __init__(self, label: str) -> None:
        self.label = label


@pytest.fixture(autouse=True)
def _reset_fake_client_state() -> None:
    _FakeClient.instances = []


async def _discover(client: _FakeClient) -> _FakeCatalog:
    return _FakeCatalog(label=f"catalog-for-{client.config.username}")


class TestKeying:
    async def test_same_url_and_username_returns_same_session(self) -> None:
        cache = SessionCache(client_factory=_FakeClient, discover=_discover)
        cfg = _make_config(service_url="http://a.example/svc/Foo", username="alice")

        first = await cache.get_or_create(cfg)
        second = await cache.get_or_create(cfg)

        assert first is second
        # Client was instantiated exactly once.
        assert len(_FakeClient.instances) == 1

    async def test_different_users_get_different_sessions(self) -> None:
        cache = SessionCache(client_factory=_FakeClient, discover=_discover)
        cfg_alice = _make_config(service_url="http://a.example/svc/Foo", username="alice")
        cfg_bob = _make_config(service_url="http://a.example/svc/Foo", username="bob")

        a = await cache.get_or_create(cfg_alice)
        b = await cache.get_or_create(cfg_bob)

        assert a is not b
        assert len(_FakeClient.instances) == 2

    async def test_different_service_urls_get_different_sessions(self) -> None:
        cache = SessionCache(client_factory=_FakeClient, discover=_discover)
        cfg1 = _make_config(service_url="http://a.example/svc/Foo", username="alice")
        cfg2 = _make_config(service_url="http://a.example/svc/Bar", username="alice")

        s1 = await cache.get_or_create(cfg1)
        s2 = await cache.get_or_create(cfg2)

        assert s1 is not s2
        assert len(_FakeClient.instances) == 2

    async def test_session_carries_client_catalog_and_config(self) -> None:
        cache = SessionCache(client_factory=_FakeClient, discover=_discover)
        cfg = _make_config(service_url="http://a.example/svc/Foo", username="alice")

        session = await cache.get_or_create(cfg)

        assert isinstance(session, Session)
        assert session.config is cfg
        assert session.client is _FakeClient.instances[0]
        assert isinstance(session.catalog, _FakeCatalog)
        assert session.catalog.label == "catalog-for-alice"


class TestClose:
    async def test_aclose_closes_every_cached_client(self) -> None:
        cache = SessionCache(client_factory=_FakeClient, discover=_discover)
        await cache.get_or_create(_make_config(service_url="http://a/svc/X", username="alice"))
        await cache.get_or_create(_make_config(service_url="http://a/svc/X", username="bob"))
        await cache.get_or_create(_make_config(service_url="http://a/svc/Y", username="alice"))

        await cache.aclose()

        assert len(_FakeClient.instances) == 3
        assert all(client.closed for client in _FakeClient.instances)

    async def test_aclose_clears_the_cache(self) -> None:
        cache = SessionCache(client_factory=_FakeClient, discover=_discover)
        cfg = _make_config(service_url="http://a/svc/X", username="alice")
        await cache.get_or_create(cfg)
        await cache.aclose()

        # After close, a subsequent get_or_create rebuilds — old instance is gone.
        await cache.get_or_create(cfg)
        assert len(_FakeClient.instances) == 2


class TestConcurrency:
    async def test_concurrent_callers_for_same_key_share_one_session(self) -> None:
        """Two awaits racing on the same key must not both create clients —
        the second waiter should see the first's result."""
        discover_started = asyncio.Event()
        discover_release = asyncio.Event()

        async def slow_discover(client: _FakeClient) -> _FakeCatalog:
            discover_started.set()
            await discover_release.wait()
            return _FakeCatalog(label="slow")

        cache = SessionCache(client_factory=_FakeClient, discover=slow_discover)
        cfg = _make_config(service_url="http://a/svc/X", username="alice")

        task1 = asyncio.create_task(cache.get_or_create(cfg))
        # Wait for the first call to be mid-discovery before launching the second.
        await discover_started.wait()
        task2 = asyncio.create_task(cache.get_or_create(cfg))

        # Give task2 a chance to enter the lock waiter list.
        await asyncio.sleep(0)
        discover_release.set()

        s1, s2 = await asyncio.gather(task1, task2)
        assert s1 is s2
        # Only one client constructed across both callers.
        assert len(_FakeClient.instances) == 1


class TestDiscoveryFailure:
    async def test_failed_discovery_is_not_cached(self) -> None:
        """If discovery raises we must not cache the half-built session — the next
        call has to retry from scratch."""
        attempts = {"n": 0}

        async def flaky_discover(client: _FakeClient) -> _FakeCatalog:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("transient discovery failure")
            return _FakeCatalog(label="ok")

        cache = SessionCache(client_factory=_FakeClient, discover=flaky_discover)
        cfg = _make_config(service_url="http://a/svc/X", username="alice")

        with pytest.raises(RuntimeError, match="transient"):
            await cache.get_or_create(cfg)

        # The half-built client from the failed attempt should be closed cleanly.
        assert _FakeClient.instances[0].closed is True

        # A retry must succeed.
        session = await cache.get_or_create(cfg)
        assert session.catalog.label == "ok"  # type: ignore[attr-defined]
        # Two clients ever existed — first one failed and was discarded, second succeeded.
        assert len(_FakeClient.instances) == 2
