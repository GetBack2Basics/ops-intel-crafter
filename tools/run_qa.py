"""CLI entrypoint to regenerate the 3-Level QA Summary JSON and Stitch HTML Inspector pages."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.catalogue.dataset_registry import DatasetRegistry
from src.ingestion.gcs_storage import GCSLakeStorage
from src.validation.qa_report import build_qa_summary, render_qa_html_pages


def main() -> int:
    registry = DatasetRegistry()
    storage = GCSLakeStorage()
    summary = build_qa_summary(registry=registry, storage=storage)
    pages = render_qa_html_pages(summary)
    print(f"QA Report ID: {summary['report_id']}")
    print(f"Status Counts: {summary['status_counts']}")
    print(f"Overview Page: {pages['index_html']}")
    print(f"MapLibre Inspector: {pages['inspect_html']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

