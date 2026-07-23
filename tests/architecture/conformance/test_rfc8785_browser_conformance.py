"""Cross-language RFC 8785 (JCS) conformance: browser JS == Python rfc8785.

Launches Chromium once, loads the vendored MIT reference canonicalizer
(`canonicalize.js`), parses the *identical* vector file text in-browser, and
asserts that in-browser `canonicalize(value)` reproduces every vector's
`canonical` string byte-for-byte. Together with
`test_rfc8785_python_conformance.py` (which pins the same vectors to the vetted
`rfc8785` library and the contract harness) this proves
Python(rfc8785) == browser(JS JCS) across the whole vector set.

G5 gate of the kernel promotion slice. If Chromium is unavailable at runtime the
test skips with a clear message rather than hard-failing; where Chromium is
present it must actually run and pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

VECTORS_PATH = Path(__file__).with_name("rfc8785-vectors.json")
CANONICALIZE_JS = Path(__file__).with_name("canonicalize.js")
VECTORS: list[dict] = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


@pytest.mark.e2e
def test_browser_js_matches_every_vector() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - environment guard
        pytest.skip(f"playwright not installed: {exc}")

    vectors_text = VECTORS_PATH.read_text(encoding="utf-8")

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as exc:  # pragma: no cover - environment guard
            pytest.skip(f"Chromium unavailable: {exc}")

        try:
            page = browser.new_page()
            page.set_content("<!DOCTYPE html><html><head></head><body></body></html>")
            page.add_script_tag(path=str(CANONICALIZE_JS))

            # ES6 number formatting is the RFC 8785 number basis: sanity-check the
            # environment before trusting the run (integral floats must collapse).
            assert page.evaluate("() => String(1.0)") == "1"
            assert page.evaluate("() => typeof canonicalize") == "function"

            # Parse the *same* file bytes in-browser so both languages canonicalize
            # values obtained from byte-identical JSON source.
            parsed_count = page.evaluate(
                "(text) => { window.__vectors = JSON.parse(text); "
                "return window.__vectors.length; }",
                vectors_text,
            )
            assert parsed_count == len(VECTORS)

            mismatches: list[dict] = []
            for index, vector in enumerate(VECTORS):
                produced = page.evaluate(
                    "(i) => canonicalize(window.__vectors[i].value)", index
                )
                if produced != vector["canonical"]:
                    mismatches.append(
                        {
                            "name": vector["name"],
                            "expected": vector["canonical"],
                            "browser": produced,
                        }
                    )
        finally:
            browser.close()

    assert not mismatches, "Python(rfc8785) != browser(JS JCS) for:\n" + "\n".join(
        f"  {m['name']}: expected {m['expected']!r} got {m['browser']!r}"
        for m in mismatches
    )
