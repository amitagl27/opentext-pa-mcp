"""Per-``(service_url, username)`` cache of authenticated AppWorks sessions.

Used by the http transport (DEC-015) so that successive MCP requests from the same
user against the same entity service reuse a warm :class:`AppworksClient` and the
already-discovered :class:`EntityCatalog` instead of re-running OTDS/Cordys login
and OpenAPI parsing on every call.

The cache is process-local and in-memory — sessions are lost on restart. That's a
deliberate v1 simplification (DEC-015 §"In-memory session cache"); a distributed
cache would only matter when running multiple replicas.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .auth import AppworksClient
from .catalog import EntityCatalog
from .config import Config
from .discovery import discover_catalog

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """An authenticated, catalog-warm session bound to one user + service."""

    config: Config
    client: AppworksClient
    catalog: EntityCatalog


# Factory signatures kept simple so callers can inject test doubles without
# matching every kwarg of AppworksClient.
ClientFactory = Callable[[Config], Any]
DiscoverFn = Callable[[Any], Awaitable[Any]]


class SessionCache:
    """In-memory cache of :class:`Session` keyed on ``(service_url, username)``.

    Thread-safety: protected by a single :class:`asyncio.Lock`. Building a session
    runs login + discovery, both async I/O, so contention is rare; the lock prevents
    two concurrent first-time callers from each constructing a duplicate client.
    """

    def __init__(
        self,
        *,
        client_factory: ClientFactory = AppworksClient,
        discover: DiscoverFn = discover_catalog,
    ) -> None:
        self._client_factory = client_factory
        self._discover = discover
        self._sessions: dict[tuple[str, str], Session] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, config: Config) -> Session:
        """Return a cached :class:`Session` for ``(config.service_url, config.username)``
        or build a fresh one (login + discovery) and cache it.

        If discovery fails, the half-built client is closed and the failure
        propagates without leaving a broken entry in the cache.
        """
        key = (config.service_url, config.username)
        async with self._lock:
            cached = self._sessions.get(key)
            if cached is not None:
                return cached

            client = self._client_factory(config)
            try:
                catalog = await self._discover(client)
            except BaseException:
                await _safe_close(client)
                raise

            session = Session(config=config, client=client, catalog=catalog)
            self._sessions[key] = session
            logger.info(
                "SessionCache: built new session for user=%s service=%s (total=%d)",
                config.username,
                config.service_url,
                len(self._sessions),
            )
            return session

    async def aclose(self) -> None:
        """Close every cached client and empty the cache."""
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            await _safe_close(session.client)


async def _safe_close(client: Any) -> None:
    """Close *client* without letting cleanup exceptions mask the original error."""
    aclose = getattr(client, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except Exception:
        logger.warning("SessionCache: error closing client; ignored.", exc_info=True)
