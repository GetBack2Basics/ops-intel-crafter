"""Unit tests for spatial file uploader & tropical cyclone hazard zone assessment."""

from pathlib import Path

try:
    import pytest
except ImportError:
    pass

from src.ai.spatial_agent import AISpatialAgent
from src.analysis.spatial_uploader import (
    assess_asset_in_cyclone,
    build_cyclone_hazard_zones,
    generate_cyclone_intelligence_reply,
    normalize_longitude,
    parse_uploaded_spatial_file,
)


KMZ_PATH = Path("docs/data/WP302026_TRACK_latest.kmz")


def test_normalize_longitude() -> None:
    assert normalize_longitude(-221.5) == 138.5
    assert normalize_longitude(-204.1) == 155.9
    assert normalize_longitude(151.5) == 151.5
    assert normalize_longitude(185.0) == -175.0


def test_uploaded_kmz_parsing() -> None:
    assert KMZ_PATH.exists(), f"Sample KMZ not found at {KMZ_PATH}"
    geo = parse_uploaded_spatial_file(KMZ_PATH, "WP302026_TRACK_latest.kmz")

    meta = geo["metadata"]
    assert "Typhoon In-Fa" in meta["cyclone_name"]
    assert meta["advisory"] == "48"

    features = geo["features"]
    assert len(features) == 7

    # Check that Western Pacific coordinates were normalized to Australian standard (negative lat, 138-156 E lon)
    for f in features:
        geom = f["geometry"]
        if geom["type"] == "Point":
            lon, lat = geom["coordinates"]
            assert 130.0 <= lon <= 160.0, f"Un-normalized longitude: {lon}"
            assert -45.0 <= lat <= -20.0, f"Latitude out of bounds (expected negative for Australia): {lat}"
        elif geom["type"] == "LineString":
            for lon, lat in geom["coordinates"]:
                assert 130.0 <= lon <= 160.0
                assert -45.0 <= lat <= -20.0


def test_cyclone_hazard_zones_buffering() -> None:
    geo = parse_uploaded_spatial_file(KMZ_PATH, "WP302026_TRACK_latest.kmz")
    zones = build_cyclone_hazard_zones(geo, radii_km={"zone1_core_km": 50.0, "zone2_gale_km": 150.0, "zone3_watch_km": 300.0})

    assert len(zones["features"]) == 15  # 5 points * 3 zones
    zone_codes = {f["properties"]["zone_code"] for f in zones["features"]}
    assert zone_codes == {"ZONE_1", "ZONE_2", "ZONE_3"}


def test_asset_zone_classification() -> None:
    geo = parse_uploaded_spatial_file(KMZ_PATH, "WP302026_TRACK_latest.kmz")

    # Point directly at -25.5 S, 138.5 E (Advisory Info point)
    res_direct = assess_asset_in_cyclone(
        asset_id="DIRECT_HIT",
        asset_name="Direct Inland Eye Station",
        lat=-25.5,
        lon=138.5,
        cyclone_geojson=geo,
    )
    assert res_direct["distance_to_track_km"] <= 5.0
    assert res_direct["predicted_zone_code"] == "ZONE_1"
    assert "80 kt" in res_direct["expected_wind_at_closest_approach"]
    assert res_direct["operational_impact_level"] == "CRITICAL"

    # Point ~100 km away
    res_gale = assess_asset_in_cyclone(
        asset_id="GALE_STATION",
        asset_name="Gale Station",
        lat=-26.0,
        lon=139.5,
        cyclone_geojson=geo,
    )
    assert 50.0 < res_gale["distance_to_track_km"] <= 150.0
    assert res_gale["predicted_zone_code"] == "ZONE_2"

    # Point ~500 km away (Peripheral)
    res_distant = assess_asset_in_cyclone(
        asset_id="SAFE_STATION",
        asset_name="Remote Substation",
        lat=-35.0,
        lon=130.0,
        cyclone_geojson=geo,
    )
    assert res_distant["distance_to_track_km"] > 300.0
    assert res_distant["predicted_zone_code"] == "ZONE_4"


def test_spatial_agent_assess_uploaded_file() -> None:
    agent = AISpatialAgent()
    out = agent.assess_uploaded_spatial_file(
        KMZ_PATH,
        "WP302026_TRACK_latest.kmz",
    )
    assert out["status"] == "SUCCESS"
    assert "Typhoon In-Fa" in out["reply"]["cyclone_name"]
    assert len(out["evaluated_assets"]) >= 1
    assert any(a["predicted_zone_code"] in ("ZONE_1", "ZONE_2", "ZONE_3") for a in out["evaluated_assets"])
