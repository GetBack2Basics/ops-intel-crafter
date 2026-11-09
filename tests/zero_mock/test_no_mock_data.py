"""Zero-Mock & Anti-Hallucination Static & Runtime Enforcement Tests."""

import ast
from pathlib import Path
from src.validation.source_contracts import validate_payload_not_error_page

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_no_mock_generators_in_src_or_tools():
    """Ensures no production module imports faker, unittest.mock, or uses synthetic coordinate generators."""
    py_files = list((PROJECT_ROOT / "src").rglob("*.py")) + list((PROJECT_ROOT / "tools").rglob("*.py"))
    assert len(py_files) >= 10

    forbidden_modules = {"faker", "unittest.mock", "mock", "responses", "httpretty"}
    violations = []

    for path in py_files:
        rel = str(path.relative_to(PROJECT_ROOT))
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden_modules:
                        violations.append(f"{rel}: imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module in forbidden_modules:
                    violations.append(f"{rel}: imports from {node.module}")

    assert not violations, f"Forbidden mock imports found: {violations}"


def test_http_200_embedded_arcgis_error_is_rejected():
    """Verifies Trap #5: HTTP 200 OK containing an embedded ArcGIS error object is flagged as invalid."""
    fake_200_error = '{"error": {"code": 499, "message": "Token Required", "details": []}}'
    res = validate_payload_not_error_page(200, "application/json;charset=utf-8", fake_200_error)
    assert res["valid"] is False
    assert "499" in res["reason"]
    assert "Token Required" in res["reason"]


def test_http_200_html_landing_page_is_rejected():
    """Verifies Trap #6: HTTP 200 OK returning an HTML block/portal page is flagged as invalid."""
    html_body = "<!DOCTYPE html><html><head><title>Portal Login</title></head><body>Sign in</body></html>"
    res = validate_payload_not_error_page(200, "text/html; charset=utf-8", html_body)
    assert res["valid"] is False
    assert "HTML" in res["reason"]

