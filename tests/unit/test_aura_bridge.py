"""Unit Tests for AURA Siting Crafter Linkage Bridge."""

from src.catalogue.aura_bridge import get_aura_manifest_path, load_aura_datasets
from src.catalogue.dataset_registry import DatasetRegistry


def test_aura_bridge_discovers_and_loads_manifest():
    manifest_path = get_aura_manifest_path()
    assert manifest_path is not None
    assert manifest_path.exists()

    aura_datasets = load_aura_datasets(manifest_path)
    assert len(aura_datasets) >= 30
    assert "national_healthcare_nhsd_v2" in aura_datasets
    assert "national_schools_acara_v2" in aura_datasets
    assert "qld_transmission_grid_v2" in aura_datasets


def test_dataset_registry_includes_aura_linked_datasets():
    reg = DatasetRegistry(include_aura=True)
    keys = reg.list_keys()

    # Must contain both native emergency datasets and AURA linked datasets
    assert "ga_electricity_substations" in keys
    assert "next_lga_boundaries_asgs2025" in keys
    assert "national_healthcare_nhsd_v2" in keys
    assert "national_schools_acara_v2" in keys

    nhsd = reg.get("national_healthcare_nhsd_v2")
    assert nhsd.dataset_key == "national_healthcare_nhsd_v2"
    assert "Hospital" in nhsd.title
    assert nhsd.endpoint.startswith("https://")
    assert nhsd.jurisdiction == "NATIONAL"

