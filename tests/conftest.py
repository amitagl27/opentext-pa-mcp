"""Shared pytest fixtures for opentext-pa-mcp tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "docs" / "research" / "artifacts"


@pytest.fixture(scope="session")
def swagger_ui_html() -> str:
    """The full Swagger UI HTML page captured during discovery.

    Contains the inlined `var dyn_spec_obj = {...}` OpenAPI spec.
    """
    path = ARTIFACTS_DIR / "swagger-ui-page.html"
    return path.read_text(encoding="utf-8-sig")


@pytest.fixture(scope="session")
def login_form_html() -> str:
    """The OTDS login form HTML page captured during discovery."""
    path = ARTIFACTS_DIR / "login-form.html"
    return path.read_text(encoding="utf-8-sig")


@pytest.fixture(scope="session")
def openapi_spec() -> dict:
    """Parsed OpenAPI spec for the ExampleLegalManagement service."""
    path = ARTIFACTS_DIR / "openapi.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))


@pytest.fixture(scope="session")
def sample_legalcategory_response() -> dict:
    """Live response captured from GET .../LegalCategory/lists/DefaultList?$top=2."""
    path = (
        ARTIFACTS_DIR
        / "sample_ExampleLegalManagement_entities_LegalCategory_lists_DefaultList__top_2.json"
    )
    return json.loads(path.read_text(encoding="utf-8-sig"))
