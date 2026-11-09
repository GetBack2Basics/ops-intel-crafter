"""Manifest Loader and Pydantic Schemas for the Emergency Spatial Catalogue.

Strictly distinguishes between:
- static_authoritative
- periodically_refreshed_authoritative
- live_operational_feed
- open_community
- derived
- scenario_input
"""

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class DatasetCategory(str, Enum):
    STATIC_AUTHORITATIVE = "static_authoritative"
    PERIODICALLY_REFRESHED = "periodically_refreshed_authoritative"
    LIVE_OPERATIONAL_FEED = "live_operational_feed"
    OPEN_COMMUNITY = "open_community"
    DERIVED = "derived"
    SCENARIO_INPUT = "scenario_input"


class QAStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    NOT_TESTED = "NOT TESTED"
    NOT_APPLICABLE = "NOT APPLICABLE"


class LicenceMetadata(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    attribution: Optional[str] = None
    redistribution_permitted: Optional[bool] = None
    verified_on: Optional[str] = None


class DatasetEntry(BaseModel):
    dataset_key: str
    title: str
    category: DatasetCategory
    theme: str
    scale: str = Field(..., description="national, state, regional, or local")
    jurisdiction: str = Field(..., description="NATIONAL, NSW, QLD, VIC, WA, SA, TAS, ACT, NT")
    provider: str
    source_agency: str
    service_type: str = Field(
        ...,
        description="arcgis_mapserver, arcgis_featureserver, ogc_wfs, geojson_feed, file_download, osm_extract, derived_parquet",
    )
    endpoint: str
    layer_id: Optional[int] = None
    wfs_type_name: Optional[str] = None
    licence: LicenceMetadata
    source_publication_date: Optional[str] = None
    source_vintage: str
    refresh_policy: str
    original_crs: str
    stored_crs: str = "EPSG:7844"
    metric_crs: str = "EPSG:3112"
    geometry_type: str
    primary_key: Optional[str] = None
    required_fields: List[str] = Field(default_factory=list)
    schema_mapping: Dict[str, str] = Field(default_factory=dict)
    known_limitations: List[str] = Field(default_factory=list)
    operational_suitability: str
    default_bbox: Optional[List[float]] = None
    qa_status: QAStatus = QAStatus.NOT_TESTED
    latest_snapshot_path: Optional[str] = None
    latest_retrieval_utc: Optional[str] = None

    @field_validator("dataset_key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not v or " " in v:
            raise ValueError(f"Invalid dataset_key: {v!r}")
        return v


class DatasetManifest(BaseModel):
    manifest_version: str = "1.0.0"
    project_name: str = "operational_intelligence_crafter"
    canonical_gcs_bucket: str = "operational-intelligence-crafter-lake"
    updated_at_utc: str
    default_stored_crs: str = "EPSG:7844"
    default_metric_crs: str = "EPSG:3112"
    default_export_crs: str = "EPSG:4326"
    datasets: Dict[str, DatasetEntry]


def get_default_manifest_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "config" / "dataset_manifest.json"


def load_manifest(manifest_path: Optional[Path] = None) -> DatasetManifest:
    path = manifest_path or get_default_manifest_path()
    if not path.exists():
        raise FileNotFoundError(f"Dataset manifest not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return DatasetManifest(**raw)


def save_manifest(manifest: DatasetManifest, manifest_path: Optional[Path] = None) -> Path:
    path = manifest_path or get_default_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest.model_dump(mode="json"), f, indent=2)
    return path
