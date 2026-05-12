"""Tests for extracting the OpenAPI spec from the AppWorks Swagger UI HTML."""

from __future__ import annotations

import pytest

from opentext_pa_mcp.errors import SpecExtractionError
from opentext_pa_mcp.spec_extractor import extract_dyn_spec_obj


class TestExtractDynSpecObj:
    def test_extracts_full_spec_from_real_html(self, swagger_ui_html: str) -> None:
        """The captured Swagger UI page must yield a parseable OpenAPI 3.0.1 spec."""
        spec = extract_dyn_spec_obj(swagger_ui_html)

        assert spec["openapi"] == "3.0.1"
        assert spec["info"]["title"] == "ExampleLegalManagement"
        # 28 tags = 28 business entities, validated in discovery
        assert len(spec["tags"]) == 28
        # 586 unique paths from the discovery findings
        assert len(spec["paths"]) == 586
        # 652 schemas
        assert len(spec["components"]["schemas"]) == 652

    def test_raises_when_marker_missing(self) -> None:
        with pytest.raises(SpecExtractionError, match="dyn_spec_obj"):
            extract_dyn_spec_obj("<html><body>no spec here</body></html>")

    def test_raises_when_json_start_missing(self) -> None:
        html = '<script>var dyn_spec_obj = "not an object";</script>'
        with pytest.raises(SpecExtractionError, match="OpenAPI"):
            extract_dyn_spec_obj(html)

    def test_raises_when_braces_unbalanced(self) -> None:
        html = '<script>var dyn_spec_obj = {"openapi":"3.0.1", "incomplete":'
        with pytest.raises(SpecExtractionError):
            extract_dyn_spec_obj(html)

    def test_brace_matching_is_string_aware(self) -> None:
        """A `}` inside a string literal must not close the outer object early."""
        html = '<script>var dyn_spec_obj = {"openapi":"3.0.1","info":{"description":"x } y","title":"T","version":"1"},"paths":{}};</script>'
        spec = extract_dyn_spec_obj(html)
        assert spec["info"]["description"] == "x } y"

    def test_handles_escaped_quotes_inside_strings(self) -> None:
        """An escaped `\\"` must not be treated as ending the string."""
        html = (
            '<script>var dyn_spec_obj = {"openapi":"3.0.1","info":'
            '{"description":"He said \\"hello\\" and {ok}","title":"T","version":"1"},"paths":{}};</script>'
        )
        spec = extract_dyn_spec_obj(html)
        assert "hello" in spec["info"]["description"]
        assert "{ok}" in spec["info"]["description"]
