"""CLI entrypoint to ingest one or all catalogued datasets into GeoParquet and update QA pages."""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.catalogue.dataset_registry import DatasetRegistry
from src.ingestion.gcs_storage import GCSLakeStorage
from src.ingestion.snapshot_ingest import ingest_dataset_snapshot
from src.validation.qa_report import build_qa_summary, render_qa_html_pages


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest emergency spatial datasets into GeoParquet 1.1.0")
    parser.add_argument("--dataset", "-d", help="Specific dataset_key to ingest (or --all)")
    parser.add_argument("--all", action="store_true", help="Ingest all datasets in config/dataset_manifest.json")
    parser.add_argument("--upload-gcs", action="store_true", help="Upload artifacts to GCS bucket after local staging")
    parser.add_argument("--max-pages", type=int, default=3, help="Max pagination pages per ArcGIS layer")
    args = parser.parse_args()

    registry = DatasetRegistry()
    storage = GCSLakeStorage()

    if args.all:
        keys = registry.list_keys()
    elif args.dataset:
        keys = [args.dataset]
    else:
        parser.error("Specify either --dataset <dataset_key> or --all")
        return 1

    print(f"=== Operational Intelligence Crafter — GeoParquet Ingestion ({len(keys)} dataset(s)) ===")
    for k in keys:
        print(f"\n[INGEST] Processing '{k}' ...")
        try:
            rec = ingest_dataset_snapshot(
                dataset_key=k,
                registry=registry,
                storage=storage,
                upload_cloud=args.upload_gcs,
                max_pages=args.max_pages,
            )
            status = rec.get("overall_qa_status")
            rows = rec.get("feature_count", 0)
            l1_err = (rec.get("level1_source_contract") or {}).get("error_message")
            if status == "FAIL":
                print(f"  -> [QA={status}] Source Contract Failed (recorded truthfully): {l1_err}")
            else:
                print(
                    f"  -> [QA={status}] Stored {rows} features in {rec.get('stored_crs')} | "
                    f"Path: {rec.get('local_parquet_path')} | SHA256: {rec.get('sha256', '')[:16]}..."
                )
        except Exception as exc:
            print(f"  -> [ERROR] {k}: {exc}")

    summary = build_qa_summary(registry=registry, storage=storage)
    pages = render_qa_html_pages(summary)
    print(f"\n[QA REPORT] Generated {pages['index_html']} and {pages['inspect_html']}")
    print(f"[QA SUMMARY] Status counts: {summary['status_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

