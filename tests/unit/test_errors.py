"""Tests for the exception hierarchy."""

from __future__ import annotations

import pytest

from opentext_pa_mcp.errors import (
    AppworksError,
    AuthenticationError,
    ConfigurationError,
    DiscoveryError,
    HttpError,
    NotFoundError,
    ReadOnlyViolationError,
    SpecExtractionError,
)


class TestExceptionHierarchy:
    """All custom exceptions should derive from AppworksError so callers can catch broadly."""

    @pytest.mark.parametrize(
        "exc_cls",
        [
            ConfigurationError,
            AuthenticationError,
            DiscoveryError,
            SpecExtractionError,
            HttpError,
            NotFoundError,
            ReadOnlyViolationError,
        ],
    )
    def test_subclass_of_appworks_error(self, exc_cls: type[Exception]) -> None:
        assert issubclass(exc_cls, AppworksError)

    def test_discovery_error_parents(self) -> None:
        """SpecExtractionError is a DiscoveryError (more specific)."""
        assert issubclass(SpecExtractionError, DiscoveryError)

    def test_http_error_carries_status_code(self) -> None:
        """HttpError should carry the HTTP status code and a message."""
        err = HttpError(404, "not found", url="http://x/")
        assert err.status_code == 404
        assert "not found" in str(err)
        assert err.url == "http://x/"

    def test_not_found_is_http_error_404(self) -> None:
        """NotFoundError is a specialised HttpError for 404 responses."""
        assert issubclass(NotFoundError, HttpError)
        err = NotFoundError("missing", url="http://x/y")
        assert err.status_code == 404

    def test_authentication_error_default_message(self) -> None:
        err = AuthenticationError()
        assert str(err)  # not empty

    def test_read_only_violation_includes_attempted_method(self) -> None:
        err = ReadOnlyViolationError("POST")
        assert "POST" in str(err)
