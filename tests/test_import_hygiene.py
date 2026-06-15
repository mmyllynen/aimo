from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_SOURCE_ROOTS = ("adapters", "app", "core", "llm", "storage", "tests", "visualization", "workflows", "workout")
FORBIDDEN_IMPORT_ROOTS = {
    "discord",
    "legacy",
    "openai",
}


class ImportHygieneTests(unittest.TestCase):
    def test_foundation_code_does_not_import_runtime_integrations_or_legacy(self) -> None:
        violations: list[str] = []

        for root in PYTHON_SOURCE_ROOTS:
            for path in (PROJECT_ROOT / root).rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    imported_roots = _imported_roots(node)
                    for imported_root in imported_roots:
                        if imported_root in FORBIDDEN_IMPORT_ROOTS:
                            relative = path.relative_to(PROJECT_ROOT)
                            violations.append(f"{relative}: imports {imported_root}")

        self.assertEqual(violations, [])


def _imported_roots(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name.split(".", 1)[0] for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module:
        return (node.module.split(".", 1)[0],)
    return ()


if __name__ == "__main__":
    unittest.main()
