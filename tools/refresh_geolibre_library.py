"""Regenerate + publish the GeoLibre library JSON and QA pages from canonical GCS records.

Used as the post-harvest refresh step by the Harvester Console backend.
Cloud-first: reads canonical GCS records, writes docs mirrors, publishes web assets.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.catalogue.dataset_registry import DatasetRegistry
from src.ingestion.gcs_storage import GCSLakeStorage
from src.validation.qa_report import build_qa_summary, render_qa_html_pages
from tools.export_geolibre_project import main as export_geolibre
from tools.publish_docs_to_gcs import upload_web_assets

def main() -> int:
    reg = DatasetRegistry()
    store = GCSLakeStorage()
    summary = build_qa_summary(registry=reg, storage=store, upload_cloud=True, write_local=False)
    render_qa_html_pages(summary, storage=store, upload_cloud=True)
    try:
        export_geolibre()
    except Exception as exc:  # noqa: BLE001
        print(f"[refresh] export_geolibre_project failed: {exc}")
    upload_web_assets()
    print(f"[refresh] done: {summary['report_id']} {summary['status_counts']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
