"""Regression guard for SCE-37: the Tailwind CDN is gone.

These tests confirm the dev-time Tailwind CDN has been replaced by a compiled,
purged production asset and that the CSP no longer needs to allow the CDN host.
See docs/specs/sce-37-tailwind-production-build.md and ADR-0005.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"
CDN_HOST = "cdn.tailwindcss.com"


@pytest.fixture()
def client():
    from app.main import app

    with (
        patch("app.main.init_db"),
        TestClient(app, raise_server_exceptions=False) as c,
    ):
        yield c


def _all_template_files() -> list[Path]:
    return sorted(TEMPLATES_DIR.rglob("*.html"))


class TestTemplatesHaveNoCdn:
    def test_no_template_references_tailwind_cdn(self):
        offenders = [
            str(p.relative_to(REPO_ROOT))
            for p in _all_template_files()
            if CDN_HOST in p.read_text(encoding="utf-8")
        ]
        assert not offenders, f"Tailwind CDN still referenced in: {offenders}"

    def test_cdn_partial_is_deleted(self):
        assert not (TEMPLATES_DIR / "partials" / "_tailwind_cdn.html").exists()

    def test_base_templates_use_compiled_assets(self):
        base = (TEMPLATES_DIR / "base.html").read_text(encoding="utf-8")
        assert "dist/tailwind.css" in base
        assert "dist/app.js" in base

    def test_public_templates_use_compiled_css(self):
        for name in ("base_public.html", "index.html", "auth/login.html", "auth/register.html"):
            text = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
            assert "dist/tailwind.css" in text, f"{name} missing compiled Tailwind link"


class TestCspExcludesCdn:
    def test_csp_header_has_no_tailwind_cdn(self, client: TestClient):
        resp = client.get("/health")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert csp, "CSP header missing"
        assert CDN_HOST not in csp, "CSP still allows the Tailwind CDN host"
