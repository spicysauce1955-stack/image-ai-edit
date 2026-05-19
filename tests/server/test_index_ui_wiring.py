"""Static-wiring regression tests for the main upload UI.

Cheap guards to make sure the AR picker integration (Phase 3.C) stays
present in ``index.html`` / ``app.js`` — without these, an accidental
deletion would only surface during manual smoke.

Full UI behaviour is verified by manual phone smoke (see
``docs/runbook.md``).
"""

from __future__ import annotations

from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[2] / "src" / "ai_edit" / "server" / "static"


class TestIndexHtmlWiring:
    def test_ar_row_element_present(self) -> None:
        index_html = (STATIC_DIR / "index.html").read_text()
        # The AR picker hook. If this disappears, app.js can't populate
        # the picker and the integration silently breaks.
        assert 'id="ar-row"' in index_html


class TestAppJsWiring:
    def test_calls_api_catalog(self) -> None:
        app_js = (STATIC_DIR / "app.js").read_text()
        assert "/api/catalog" in app_js

    def test_render_ar_row_function_present(self) -> None:
        app_js = (STATIC_DIR / "app.js").read_text()
        assert "renderArRow" in app_js
        assert "pickArCategoryFromInstruction" in app_js

    def test_render_ar_row_called_from_render_result(self) -> None:
        # Regression: it's easy to add the helper but forget to call
        # it. Verify the wiring.
        app_js = (STATIC_DIR / "app.js").read_text()
        # Look at the renderResult body specifically.
        start = app_js.find("function renderResult")
        assert start != -1, "renderResult function not found"
        end = app_js.find("\nfunction ", start + 1)
        body = app_js[start:end] if end != -1 else app_js[start:]
        assert "renderArRow" in body, "renderArRow not invoked from renderResult"
