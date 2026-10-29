"""Regenerate publishable onboarding examples and the source access matrix."""

from pathlib import Path

from biomedmcp.onboarding import investigations_markdown, matrix_markdown
from biomedmcp.source_licensing import matrix_markdown as license_markdown

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    (root / "docs/investigations.md").write_text(investigations_markdown())
    (root / "docs/source-access.md").write_text(matrix_markdown())
    (root / "docs/source-licenses.md").write_text(license_markdown())
