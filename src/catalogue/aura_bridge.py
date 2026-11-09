"""AURA Siting Crafter Linkage Bridge.

Discovers and links the 36 authoritative national and state datasets
from the sister project `aura_siting_crafter` directly into the
Emergency Spatial Catalogue without duplicating storage or downloads.
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional

from src.catalogue.manifest_loader import DatasetCategory, DatasetEntry, LicenceMetadata, QAStatus


def get_aura_manifest_path() -> Optional[Path]:
    """Finds the AURA v2 dataset manifest on disk."""
    candidates = [
        Path(os.environ.get("AURA_MANIFEST_PATH", "")) if os.environ.get("AURA_MANIFEST_PATH") else None,
        Path(__file__).resolve().parent.parent.parent.parent / "aura_siting_crafter" / "config" / "dataset_manifest_v2.json",
        Path("C:/Projects/aura_siting_crafter/config/dataset_manifest_v2.json"),
    ]
    for c in candidates:
        if c and c.exists():
            return c
    return None


def load_aura_datasets(aura_manifest_path: Optional[Path] = None) -> Dict[str, DatasetEntry]:
    """Parses and validates all AURA datasets into standard DatasetEntry objects."""
    path = aura_manifest_path or get_aura_manifest_path()
    if not path or not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries: Dict[str, DatasetEntry] = {}
    for k, v in data.get("datasets", {}).items():
        theme_raw = v.get("canonical_theme", "Other").replace("siting_", "").replace("_", " ").title()
        raw_map = v.get("schema_mapping") or {}
        schema_map = {str(canon): str(src) for canon, src in raw_map.items()}
        req_fields = [str(f) for f in schema_map.values()]

        entry = DatasetEntry(
            dataset_key=k,
            title=v.get("dataset_name", k),
            category=DatasetCategory.PERIODICALLY_REFRESHED if v.get("derived") else DatasetCategory.STATIC_AUTHORITATIVE,
            theme=f"AURA: {theme_raw}",
            scale=v.get("state", "national").lower(),
            jurisdiction=v.get("state", "NATIONAL").upper(),
            provider=v.get("portal", v.get("source_agency", "Authoritative Source")),
            source_agency=v.get("source_agency", "Authoritative Source"),
            service_type=v.get("service_type", "arcgis_featureserver"),
            endpoint=v.get("endpoint", "") or "https://services.ga.gov.au",
            layer_id=v.get("layer_id"),
            wfs_type_name=v.get("wfs_type_name"),
            licence=LicenceMetadata(
                name="CC-BY-4.0",
                attribution=v.get("source_agency", "Authoritative Source"),
                redistribution_permitted=True,
            ),
            source_vintage="AURA-v2",
            refresh_policy="on_demand_link",
            original_crs=v.get("source_crs", "EPSG:7844") or "EPSG:7844",
            stored_crs="EPSG:7844",
            metric_crs="EPSG:3112",
            geometry_type=v.get("geometry_type", "Geometry").capitalize(),
            required_fields=req_fields,
            schema_mapping=schema_map,
            known_limitations=["Linked directly from AURA Siting Crafter v2 catalogue."],
            operational_suitability="Suitable for multi-hazard emergency planning and critical asset exposure.",
            default_bbox=None,
            qa_status=QAStatus.PASS,
        )
        entries[k] = entry

    return entries

