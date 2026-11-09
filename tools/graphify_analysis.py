"""AST Dependency Graph, Anti-Mock Scanner, and Secret Leak Auditor for operational_intelligence_crafter."""

import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
    re.compile(r"wbts-[a-zA-Z0-9]{20,}"),
]

FORBIDDEN_MOCK_CALLS = {
    "faker",
    "Faker",
}


def scan_repository() -> Dict[str, object]:
    py_files = list((PROJECT_ROOT / "src").rglob("*.py")) + list((PROJECT_ROOT / "tools").rglob("*.py"))
    imports_graph: Dict[str, List[str]] = {}
    secret_hits: List[str] = []
    mock_hits: List[str] = []

    for py_file in py_files:
        rel = str(py_file.relative_to(PROJECT_ROOT)).replace("\\", "/")
        text = py_file.read_text(encoding="utf-8", errors="ignore")

        for pat in SECRET_PATTERNS:
            if pat.search(text):
                secret_hits.append(f"{rel}: matched {pat.pattern}")

        try:
            tree = ast.parse(text, filename=rel)
            file_imports: List[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        file_imports.append(alias.name)
                        if alias.name in FORBIDDEN_MOCK_CALLS:
                            mock_hits.append(f"{rel}: imports forbidden mock library '{alias.name}'")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    file_imports.append(node.module)
                    if node.module in FORBIDDEN_MOCK_CALLS:
                        mock_hits.append(f"{rel}: imports forbidden mock library '{node.module}'")
            imports_graph[rel] = sorted(set(file_imports))
        except SyntaxError as se:
            mock_hits.append(f"{rel}: SyntaxError {se}")

    report = {
        "files_scanned": len(py_files),
        "secret_leaks_detected": len(secret_hits),
        "mock_violations_detected": len(mock_hits),
        "secret_hits": secret_hits,
        "mock_hits": mock_hits,
        "module_dependency_graph": imports_graph,
    }
    out_dir = PROJECT_ROOT / "docs" / "architecture"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "graphify_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    report = scan_repository()
    print(
        f"[GRAPHIFY] Scanned {report['files_scanned']} Python modules | "
        f"Secrets={report['secret_leaks_detected']} | MockViolations={report['mock_violations_detected']}"
    )
    if report["secret_leaks_detected"] > 0 or report["mock_violations_detected"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

