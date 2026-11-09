"""
tests/unit/test_locality_gazetteer.py
Verifies the ABS ASGS Locality & Postal Gazetteer:
- Verifies authoritative gazetteer entries loaded from docs/data/locality_gazetteer.json.
- Verifies bounding box validity (minx < maxx, miny < maxy in Australian extent).
- Verifies smoothed extent polygon geometry (rounded corners, clockwise winding, closed ring).
- Verifies spatial query against ga_major_power_stations within Sydney extent finds stations.
"""
import json
import math
import os
import pytest


def test_gazetteer_contains_major_australian_localities():
    gaz_path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "data", "locality_gazetteer.json")
    assert os.path.exists(gaz_path), f"Gazetteer missing at {gaz_path}"
    with open(gaz_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) >= 1000, f"Expected at least 1,000 localities, got {len(data)}"

    # Check key Australian cities and regions
    for key in ["sydney", "newcastle", "parramatta", "melbourne", "brisbane", "nsw", "vic", "qld"]:
        assert key in data, f"Key '{key}' should exist in gazetteer"
        entry = data[key]
        assert "bbox" in entry, f"Entry {key} missing bbox"
        minx, miny, maxx, maxy = entry["bbox"]
        assert 110.0 <= minx < maxx <= 160.0, f"Invalid longitude bounds for {key}: [{minx}, {maxx}]"
        assert -45.0 <= miny < maxy <= -8.0, f"Invalid latitude bounds for {key}: [{miny}, {maxy}]"


def test_smoothed_extent_polygon_math():
    bbox = [150.60, -34.15, 151.35, -33.60]  # Greater Sydney
    min_x, min_y, max_x, max_y = bbox
    w = max_x - min_x
    h = max_y - min_y
    r = min(w, h) * 0.12
    ring = []
    num_arc_points = 6

    def add_arc(cx, cy, start_ang, end_ang):
        for i in range(num_arc_points + 1):
            ang = start_ang + (end_ang - start_ang) * (i / num_arc_points)
            x = round(cx + r * math.cos(ang), 5)
            y = round(cy + r * math.sin(ang), 5)
            ring.append([x, y])

    add_arc(min_x + r, max_y - r, math.pi, math.pi / 2)
    add_arc(max_x - r, max_y - r, math.pi / 2, 0)
    add_arc(max_x - r, min_y + r, 2 * math.pi, 1.5 * math.pi)
    add_arc(min_x + r, min_y + r, 1.5 * math.pi, math.pi)

    if ring[0] != ring[-1]:
        ring.append(ring[0])

    # Ring must be closed
    assert ring[0] == ring[-1]
    # Ring must have rounded corners (more than 4 vertices)
    assert len(ring) >= 28

    # Shoelace formula to verify clockwise winding
    shoelace_sum = sum(
        (ring[i + 1][0] - ring[i][0]) * (ring[i + 1][1] + ring[i][1])
        for i in range(len(ring) - 1)
    )
    assert shoelace_sum > 0, f"Expected clockwise winding (sum > 0), got {shoelace_sum}"


def test_spatial_extent_resolves_power_stations_in_sydney():
    """Verifies that filtering power stations by Sydney spatial bbox finds actual stations, whereas state ILIKE '%Sydney%' fails."""
    geojson_path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "qa", "data", "ga_major_power_stations.geojson")
    assert os.path.exists(geojson_path), f"GeoJSON missing at {geojson_path}"
    with open(geojson_path, "r", encoding="utf-8") as f:
        d = json.load(f)

    # 1. State ILIKE '%Sydney%' yields 0 features because state is 'NSW'
    state_match = [f for f in d["features"] if "sydney" in str(f.get("properties", {}).get("state", "")).lower()]
    assert len(state_match) == 0, "state is an Australian state (NSW), never 'Sydney'"

    # 2. Spatial bounding box filter for Sydney extent finds 5 stations
    sydney_bbox = [150.60, -34.15, 151.35, -33.60]
    spatial_match = []
    for f in d["features"]:
        x, y = f["geometry"]["coordinates"]
        if sydney_bbox[0] <= x <= sydney_bbox[2] and sydney_bbox[1] <= y <= sydney_bbox[3]:
            spatial_match.append(f)

    assert len(spatial_match) == 5, f"Expected 5 stations in Sydney extent, got {len(spatial_match)}"
    station_names = [f["properties"]["name"] for f in spatial_match]
    assert any("Smithfield" in n for n in station_names)
    assert any("Lucas Heights" in n for n in station_names)
