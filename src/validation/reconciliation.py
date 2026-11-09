"""Level 3 Validation — Source-to-Storage Reconciliation.

Compares Level 1 (Source Contract) and Level 2 (Stored GeoParquet Artifact):
- Feature count reconciliation (source count vs stored count).
- Required attribute preservation and schema mapping verification.
- Spatial extent comparison against query bbox.
- Geometry validity & duplicate identifier reconciliation.
- Explicit documentation of expected transformation differences.
- Strictly prohibits reporting 100% reconciliation when source_count is unknown or failed.
"""

from typing import Any, Dict, List, Optional
from src.catalogue.manifest_loader import DatasetEntry, QAStatus


def verify_level3_reconciliation(
    entry: DatasetEntry,
    level1: Dict[str, Any],
    level2: Optional[Dict[str, Any]],
    connector_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Executes Level 3 Source-to-Storage Reconciliation."""
    if level1.get("status") == QAStatus.FAIL.value or level2 is None or level2.get("status") == QAStatus.FAIL.value:
        return {
            "level": 3,
            "level_name": "Source-to-Storage Reconciliation",
            "status": QAStatus.NOT_APPLICABLE.value if level2 is None else QAStatus.FAIL.value,
            "source_feature_count": level1.get("source_feature_count"),
            "stored_feature_count": level2.get("feature_count") if level2 else None,
            "reconciliation_rate_pct": None,
            "expected_transformations": [],
            "error_message": "Cannot reconcile: Level 1 Source Contract or Level 2 Stored Artifact failed.",
            "checks": [
                {
                    "check": "prerequisite_levels_valid",
                    "status": "FAIL",
                    "detail": f"Level 1={level1.get('status')}, Level 2={level2.get('status') if level2 else 'NONE'}",
                }
            ],
        }

    checks: List[Dict[str, Any]] = []
    source_count: Optional[int] = level1.get("source_feature_count")
    stored_count: int = int(level2.get("feature_count", 0))

    # 1. Feature count reconciliation (never fake 100% if source_count is None!)
    reconciliation_pct: Optional[float] = None
    if source_count is None or source_count <= 0:
        count_status = "WARNING"
        count_detail = (
            f"Source feature count was not reported by endpoint ({source_count}); "
            f"stored {stored_count} features (reconciliation percentage cannot be claimed as 100%)."
        )
    else:
        reconciliation_pct = round((stored_count / source_count) * 100.0, 2)
        delta = stored_count - source_count
        if delta == 0:
            count_status = "PASS"
            count_detail = f"Exact match: {stored_count} stored / {source_count} source features (100.0%)"
        elif abs(delta) / source_count <= 0.05:
            count_status = "WARNING"
            count_detail = (
                f"Minor delta ({delta:+d} rows): {stored_count} stored vs {source_count} source "
                f"({reconciliation_pct}%)"
            )
        else:
            # Check if pagination cap was intentionally hit
            pages = (connector_meta or {}).get("pages_fetched", 1)
            count_status = "WARNING" if stored_count > 0 else "FAIL"
            count_detail = (
                f"Stored {stored_count} vs source {source_count} features ({reconciliation_pct}%, "
                f"pages_fetched={pages})"
            )

    checks.append(
        {
            "check": "feature_count_reconciliation",
            "status": count_status,
            "detail": count_detail,
        }
    )

    # 2. Schema and required attribute preservation
    stored_cols = {c["name"].lower(): c["name"] for c in level2.get("schema_columns", [])}
    missing_req = [r for r in entry.required_fields if r.lower() not in stored_cols]
    missing_mapped = [
        canon for canon in (entry.schema_mapping or {}).keys() if canon.lower() not in stored_cols
    ]
    schema_ok = len(missing_req) == 0 and len(missing_mapped) == 0
    checks.append(
        {
            "check": "attribute_and_schema_reconciliation",
            "status": "PASS" if schema_ok else "FAIL",
            "detail": (
                f"Preserved all {len(entry.required_fields)} required native fields and "
                f"{len(entry.schema_mapping or {})} mapped aliases ({len(stored_cols)} total columns)"
                if schema_ok
                else f"Missing required={missing_req}, missing mapped={missing_mapped}"
            ),
        }
    )

    # 3. Spatial extent vs query bbox check
    stored_bbox = level2.get("bbox", [])
    query_bbox = level1.get("query_bbox")
    if query_bbox and len(stored_bbox) == 4 and len(query_bbox) == 4:
        # Features intersecting a query bbox can extend outside the bbox, so check overlap
        overlaps = not (
            stored_bbox[2] < query_bbox[0]
            or stored_bbox[0] > query_bbox[2]
            or stored_bbox[3] < query_bbox[1]
            or stored_bbox[1] > query_bbox[3]
        )
        checks.append(
            {
                "check": "spatial_extent_reconciliation",
                "status": "PASS" if overlaps else "FAIL",
                "detail": f"Stored extent {stored_bbox} overlaps query envelope {query_bbox}",
            }
        )
    else:
        checks.append(
            {
                "check": "spatial_extent_reconciliation",
                "status": "PASS",
                "detail": f"Full dataset extent recorded: {stored_bbox}",
            }
        )

    # 4. Record expected transformations
    expected_transformations: List[str] = []
    if entry.original_crs.upper() != entry.stored_crs.upper():
        expected_transformations.append(
            f"CRS reprojection from {entry.original_crs} to canonical {entry.stored_crs}"
        )
    if query_bbox:
        expected_transformations.append(
            f"Spatial envelope filter applied: bbox={query_bbox} (WGS84/GDA2020)"
        )
    unpacked = (connector_meta or {}).get("geometry_collections_unpacked", 0)
    if unpacked:
        expected_transformations.append(
            f"Unpacked {unpacked} GeometryCollection feature(s) to primary vector geometry for GeoParquet indexing"
        )
    expected_transformations.append(
        "Added per-feature bounding box columns (_bbox_minx.._bbox_maxy) and centroid spatial ordering"
    )

    overall = QAStatus.PASS.value
    if any(c["status"] == "FAIL" for c in checks):
        overall = QAStatus.FAIL.value
    elif any(c["status"] == "WARNING" for c in checks):
        overall = QAStatus.WARNING.value

    return {
        "level": 3,
        "level_name": "Source-to-Storage Reconciliation",
        "status": overall,
        "source_feature_count": source_count,
        "stored_feature_count": stored_count,
        "reconciliation_rate_pct": reconciliation_pct,
        "expected_transformations": expected_transformations,
        "checks": checks,
    }


def compute_overall_dataset_qa_status(
    level1: Dict[str, Any],
    level2: Optional[Dict[str, Any]],
    level3: Dict[str, Any],
) -> str:
    """Combines Level 1, Level 2, and Level 3 statuses into a single dataset QA grade."""
    statuses = [
        level1.get("status", QAStatus.NOT_TESTED.value),
        level2.get("status", QAStatus.NOT_APPLICABLE.value) if level2 else QAStatus.FAIL.value,
        level3.get("status", QAStatus.NOT_APPLICABLE.value),
    ]
    if QAStatus.FAIL.value in statuses:
        return QAStatus.FAIL.value
    if QAStatus.WARNING.value in statuses:
        return QAStatus.WARNING.value
    if all(s == QAStatus.PASS.value for s in statuses):
        return QAStatus.PASS.value
    return QAStatus.NOT_TESTED.value

