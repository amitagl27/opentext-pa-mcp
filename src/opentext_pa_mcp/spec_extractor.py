"""Extract the inlined OpenAPI 3.0.1 spec from an AppWorks entity service's Swagger UI HTML.

AppWorks 23.x renders the Swagger UI for each entity service with the OpenAPI document
baked into the page as a JavaScript variable assignment::

    var dyn_spec_obj = {"openapi":"3.0.1",...};

This module locates that assignment and brace-matches the JSON literal out of the HTML
without parsing the surrounding JavaScript. It is string-aware (skips ``{``/``}`` inside
string literals) and respects backslash escapes.

Why not a real JS parser? Because the spec is well-formed JSON inside an assignment;
the only thing we have to be careful about is the brace count and string boundaries.
A 30-line scanner is more reliable than a full parser dependency.
"""

from __future__ import annotations

import json
from typing import Final

from .errors import SpecExtractionError

_VARIABLE_MARKER: Final = "dyn_spec_obj"
_JSON_START: Final = '{"openapi"'


def extract_dyn_spec_obj(html: str) -> dict:
    """Return the OpenAPI dict embedded as ``var dyn_spec_obj = {...}`` in *html*.

    Raises:
        SpecExtractionError: if the marker is missing, the JSON start cannot be located,
            the JSON object is unterminated, or :mod:`json` cannot parse it.
    """
    marker_idx = html.find(_VARIABLE_MARKER)
    if marker_idx == -1:
        raise SpecExtractionError(
            "Could not find 'dyn_spec_obj' in the response. "
            "The URL may not be an AppWorks entity service Swagger UI page, "
            "or the AppWorks version may have changed how it embeds the spec."
        )

    json_start = html.find(_JSON_START, marker_idx)
    if json_start == -1:
        raise SpecExtractionError(
            "Found 'dyn_spec_obj' but could not locate the start of the OpenAPI JSON "
            f"(expected to find {_JSON_START!r} after the marker)."
        )

    json_end = _find_matching_brace(html, json_start)
    raw_json = html[json_start : json_end + 1]

    try:
        return json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise SpecExtractionError(
            f"Located the OpenAPI JSON block but could not parse it as JSON: {exc.msg} "
            f"at position {exc.pos}."
        ) from exc


def _find_matching_brace(text: str, start: int) -> int:
    """Find the index of the ``}`` that closes the ``{`` at *start*.

    The scanner is string-aware (does not count braces inside ``"..."``) and respects
    backslash escapes inside string literals.

    Raises:
        SpecExtractionError: if EOF is reached with braces still open.
    """
    if text[start] != "{":
        raise SpecExtractionError(
            f"Internal error: expected '{{' at position {start}, got {text[start]!r}."
        )

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i

    raise SpecExtractionError("Reached end of HTML with unterminated 'dyn_spec_obj' JSON object.")
