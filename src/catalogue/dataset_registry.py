"""Dataset Registry for querying and filtering catalogued spatial datasets."""

from pathlib import Path
from typing import Dict, List, Optional
from src.catalogue.manifest_loader import (
    DatasetCategory,
    DatasetEntry,
    DatasetManifest,
    QAStatus,
    load_manifest,
)


class DatasetRegistry:
    """Provides structured lookup and allow-list verification over the dataset manifest."""

    def __init__(
        self,
        manifest_path: Optional[Path] = None,
        include_aura: bool = True,
    ):
        self.manifest_path = manifest_path
        self._manifest: DatasetManifest = load_manifest(manifest_path)
        self.include_aura = include_aura
        if include_aura:
            try:
                from src.catalogue.aura_bridge import load_aura_datasets
                aura_entries = load_aura_datasets()
                for k, entry in aura_entries.items():
                    if k not in self._manifest.datasets:
                        self._manifest.datasets[k] = entry
            except Exception:
                pass

    def reload(self) -> None:
        self._manifest = load_manifest(self.manifest_path)
        if self.include_aura:
            try:
                from src.catalogue.aura_bridge import load_aura_datasets
                aura_entries = load_aura_datasets()
                for k, entry in aura_entries.items():
                    if k not in self._manifest.datasets:
                        self._manifest.datasets[k] = entry
            except Exception:
                pass

    @property
    def manifest(self) -> DatasetManifest:
        return self._manifest

    def list_keys(
        self,
        jurisdiction: Optional[str] = None,
        category: Optional[DatasetCategory] = None,
        theme: Optional[str] = None,
        scale: Optional[str] = None,
    ) -> List[str]:
        keys = []
        for k, entry in sorted(self._manifest.datasets.items()):
            if jurisdiction and entry.jurisdiction.upper() != jurisdiction.upper():
                continue
            if category and entry.category != category:
                continue
            if theme and entry.theme.lower() != theme.lower():
                continue
            if scale and entry.scale.lower() != scale.lower():
                continue
            keys.append(k)
        return keys

    def get(self, dataset_key: str) -> DatasetEntry:
        if dataset_key not in self._manifest.datasets:
            raise KeyError(
                f"Dataset '{dataset_key}' is not registered in the allow-listed catalogue. "
                f"Available keys: {sorted(self._manifest.datasets.keys())}"
            )
        return self._manifest.datasets[dataset_key]

    def is_allowlisted(self, dataset_key: str) -> bool:
        return dataset_key in self._manifest.datasets

    def get_schema_summary_for_ai(self) -> str:
        """Generates a strictly grounded schema summary for the AI query planner."""
        lines = ["### Allow-Listed Emergency Spatial Catalogue\n"]
        for k, ds in sorted(self._manifest.datasets.items()):
            req_fields = ", ".join(ds.required_fields) if ds.required_fields else "geometry"
            mapped = ", ".join(f"{canon}<-{src}" for canon, src in ds.schema_mapping.items())
            lines.append(
                f"- **`{k}`** ({ds.title})\n"
                f"  - Category: `{ds.category.value}` | Scale: `{ds.scale}` | Jurisdiction: `{ds.jurisdiction}`\n"
                f"  - Vintage: `{ds.source_vintage}` | CRS: `{ds.stored_crs}` | Geometry: `{ds.geometry_type}`\n"
                f"  - QA Status: `{ds.qa_status.value}` | Required Fields: `{req_fields}`\n"
                f"  - Mapped Attributes: `{mapped or 'native attributes preserved'}`\n"
                f"  - Limitations: {'; '.join(ds.known_limitations) if ds.known_limitations else 'None recorded'}"
            )
        return "\n".join(lines)

