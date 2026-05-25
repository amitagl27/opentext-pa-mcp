"""Exception hierarchy for the OpenText PA MCP server.

All custom exceptions derive from :class:`AppworksError` so callers (including the
tool-layer error translator) can catch broadly. More specific subclasses are used
internally to drive different responses to the LLM (404 = "not found", 401 = retry
auth, 5xx = "platform problem", etc.).
"""

from __future__ import annotations


class AppworksError(Exception):
    """Base class for every error raised by this package."""


class ConfigurationError(AppworksError):
    """The runtime environment is missing or has an invalid configuration value."""


class AuthenticationError(AppworksError):
    """AppWorks login failed or the session expired and could not be renewed.

    Covers both OTDS form-login (AppWorks 23.x) and Cordys built-in SSO (Process
    Automation CE 25.x). See DEC-014.
    """

    def __init__(self, message: str = "Authentication with AppWorks failed.") -> None:
        super().__init__(message)


class DiscoveryError(AppworksError):
    """Something went wrong while bootstrapping the entity catalog from the live service."""


class SpecExtractionError(DiscoveryError):
    """The OpenAPI spec could not be located or parsed inside the Swagger UI HTML."""


class HttpError(AppworksError):
    """A non-2xx response was returned by the AppWorks API.

    Carries the HTTP status code and the originating URL so callers can decide what to do.
    """

    def __init__(self, status_code: int, message: str, *, url: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url

    def __str__(self) -> str:
        base = super().__str__()
        if self.url:
            return f"{base} (HTTP {self.status_code} at {self.url})"
        return f"{base} (HTTP {self.status_code})"


class NotFoundError(HttpError):
    """Specialised :class:`HttpError` for 404 responses."""

    def __init__(self, message: str = "Resource not found.", *, url: str | None = None) -> None:
        super().__init__(404, message, url=url)


class InvalidItemIdError(HttpError):
    """The platform rejected an item-id path segment as un-parseable.

    AppWorks REST endpoints address items by their internal BigInteger primary
    key (e.g. ``9175042``). When a caller passes the human-readable business id
    instead (e.g. ``PI2526-000102``), the platform returns HTTP 500 with a
    Cordys-specific ``EXPRESSION_PARSE_BIGINTEGER_ERROR`` marker. The HTTP layer
    detects that marker and raises this exception with an actionable message so
    the tool layer can hint the caller toward auto-resolution rather than
    surfacing an opaque 500.
    """

    def __init__(
        self,
        attempted_id: str,
        *,
        url: str | None = None,
    ) -> None:
        message = (
            f"AppWorks rejected item id {attempted_id!r} because the endpoint "
            "expects the internal numeric id from `_links.item.href` (a "
            "BigInteger), not the human-readable business id. Either pass the "
            "numeric id, or call get_entity / list_children with the business "
            "id and let the server auto-resolve it via DefaultList."
        )
        super().__init__(500, message, url=url)
        self.attempted_id = attempted_id


class ItemIdResolutionError(AppworksError):
    """Auto-resolution from a business id to the internal numeric id failed.

    Raised when the resolver searched ``DefaultList`` for the supplied string
    and found zero or more-than-one matches. The :attr:`candidates` list lets
    the caller (or the LLM through the tool error response) see what the
    platform actually returned and re-query with a more precise id.
    """

    def __init__(
        self,
        attempted_id: str,
        candidates: list[dict],
        *,
        entity: str,
    ) -> None:
        if not candidates:
            message = (
                f"Could not resolve business id {attempted_id!r} on entity "
                f"{entity!r}: DefaultList returned no items containing that "
                "value. Confirm the id, or call `query_list` with a broader "
                "`search` term to discover it."
            )
        else:
            preview = ", ".join(
                f"{c['internal_id']} ({c.get('summary', '')!r})" for c in candidates[:5]
            )
            message = (
                f"Business id {attempted_id!r} on entity {entity!r} matched "
                f"{len(candidates)} DefaultList items; need exactly one. "
                f"Candidates: {preview}. Retry with the internal id or a more "
                "precise business id."
            )
        super().__init__(message)
        self.attempted_id = attempted_id
        self.candidates = candidates
        self.entity = entity


class ReadOnlyViolationError(AppworksError):
    """A tool tried to perform a write while PA_ALLOW_WRITES was not enabled.

    In v1.0 the package ships read-only by default; the v1.1 release will add
    create/update/delete tools that respect this flag.
    """

    def __init__(self, attempted_method: str) -> None:
        super().__init__(
            f"Write operations are disabled (attempted: {attempted_method}). "
            "Set PA_ALLOW_WRITES=true to enable mutating tools."
        )
        self.attempted_method = attempted_method
