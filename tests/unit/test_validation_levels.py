"""Unit tests for Level 1, Level 2, and Level 3 validation logic."""

from pathlib import Path
from src.catalogue.dataset_registry import DatasetRegistry
from src.catalogue.manifest_loader import QAStatus
from src.validation.reconciliation import (
    compute_overall_dataset_qa_status,
    verify_level3_reconciliation,
)


def test_reconciliation_never_claims_100_percent_when_source_count_is_none():
    """Verifies anti-hallucination rule: never report 100% reconciliation if source_feature_count is None."""
    reg = DatasetRegistry()
    entry = reg.get("ga_major_power_stations")

    fake_l1 = {
        "status": QAStatus.WARNING.value,
        "source_feature_count": None,
        "query_bbox": None,
    }
    fake_l2 = {
        "status": QAStatus.PASS.value,
        "feature_count": 379,
        "bbox": [114.0, -43.0, 153.0, -12.0],
        "schema_columns": [
            {"name": "objectid"},
            {"name": "feature_name"},
            {"name": "primary_fuel_type"},
            {"name": "generation_capacity_mw"},
            {"name": "station_id"},
            {"name": "name"},
            {"name": "fuel_type"},
            {"name": "capacity_mw"},
            {"name": "state"},
        ],
    }

    l3 = verify_level3_reconciliation(entry, fake_l1, fake_l2)
    assert l3["reconciliation_rate_pct"] is None
    assert l3["status"] == QAStatus.WARNING.value


def test_failed_level1_propagates_to_overall_fail():
    """Verifies that a failed Level 1 Source Contract always produces an overall FAIL status."""
    l1 = {"status": QAStatus.FAIL.value}
    l2 = {"status": QAStatus.NOT_APPLICABLE.value}
    l3 = {"status": QAStatus.NOT_APPLICABLE.value}
    assert compute_overall_dataset_qa_status(l1, l2, l3) == QAStatus.FAIL.value
