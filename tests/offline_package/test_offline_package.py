"""Air-gapped Offline Map-in-a-Box Verification Tests (Section 9.3)."""

import json
import re

from tests._cloud_artifacts import resolve_map_package

PACKAGE_NAME = "hunter_flood_emergency_pack"


def test_offline_map_package_completeness_and_zero_external_urls() -> None:
    """Verifies that the Map-in-a-Box package contains all required assets, GeoJSON layers,
    manifest provenance, and zero external CDN/tile/font HTTP requests in index.html.

    The package is resolved from the local publish mirror when present, otherwise from
    its canonical GCS location (`gs://operational-intelligence-crafter-lake/map_packages/`).
    """
    PACK_DIR = resolve_map_package(PACKAGE_NAME)
    index_html = PACK_DIR / "index.html"
    manifest_json = PACK_DIR / "manifest.json"
    readme_txt = PACK_DIR / "README.txt"

    assert index_html.exists()
    assert manifest_json.exists()
    assert readme_txt.exists()
    assert (PACK_DIR / "assets" / "offline_stitch.css").exists()
    assert (PACK_DIR / "assets" / "offline_bundle.js").exists()
    assert (PACK_DIR / "assets" / "offline_vector_map.js").exists()

    html_text = index_html.read_text(encoding="utf-8")
    # Ensure zero external http:// or https:// script, link, img, or fetch URLs in index.html
    external_urls = re.findall(r"https?://[^\s\"'<>]+", html_text, flags=re.IGNORECASE)
    assert external_urls == [], f"Found forbidden external URLs in air-gapped index.html: {external_urls}"

    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    assert manifest["offline_airgapped_verified"] is True
    assert manifest["external_cdn_dependencies"] == 0
    assert len(manifest["datasets"]) == 6

    for ds in manifest["datasets"]:
        layer_file = PACK_DIR / "data" / f"{ds['layer_name']}.geojson"
        assert layer_file.exists(), f"Missing GeoJSON layer file: {layer_file}"
        fc = json.loads(layer_file.read_text(encoding="utf-8"))
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) > 0

