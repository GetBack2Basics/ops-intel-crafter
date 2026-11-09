"""Spatial File Uploader & Operational Intelligence Assessment for Any Area of Interest (AOI) or Cyclone Track.

Provides end-to-end support for user-uploaded spatial files:
- Formats: KMZ, KML, GeoJSON, and zipped Shapefile.
- Automatic longitude and latitude normalization:
  - Antimeridian longitude wrap for Western Pacific tracks (e.g. -221.5°W -> 138.5°E).
  - Australian Southern Hemisphere latitude correction: enforces negative latitude (-10° to -45°)
    for Australian cyclone tracks and areas of interest.
- Dual Mode Assessment:
  1. Any Area of Interest (AOI - Polygons): Evaluates exposed population (Methods A, B, C),
     critical power infrastructure (substations, power stations), and vulnerable facilities
     (hospitals, aged care, schools, emergency services).
  2. Hazard / Transport Corridors (Lines/Tracks): Buffers into concentric impact zones
     (Zone 1 Core <50km, Zone 2 Severe Gale 50-150km, Zone 3 Watch 150-300km) and classifies
     intersecting real Australian infrastructure.
"""

import io
import json
import math
import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import xml.etree.ElementTree as ET


def normalize_longitude(lon: float) -> float:
    """Normalizes longitude to the standard [-180, 180] degree range."""
    while lon < -180.0:
        lon += 360.0
    while lon > 180.0:
        lon -= 360.0
    return round(lon, 6)


def normalize_coordinate(raw_lon: float, raw_lat: float, force_australia_lat: bool = True) -> Tuple[float, float]:
    """Normalizes longitude and enforces negative latitude for Australian coordinates."""
    norm_lon = normalize_longitude(raw_lon)
    norm_lat = round(raw_lat, 6)
    # Australia is in the Southern Hemisphere (-10° to -45° S, 110° to 165° E).
    # If coordinates are in Australian longitudes but have positive latitude, invert to negative.
    if force_australia_lat and (110.0 <= norm_lon <= 165.0) and (10.0 <= norm_lat <= 45.0):
        norm_lat = -abs(norm_lat)
    return norm_lon, norm_lat


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two points in kilometers."""
    r = 6371.0  # Earth's mean radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(r * c, 2)


def min_distance_to_segment_km(
    p_lat: float, p_lon: float,
    a_lat: float, a_lon: float,
    b_lat: float, b_lon: float,
) -> float:
    """Calculates perpendicular or endpoint distance in km from a point to a line segment."""
    mid_lat_rad = math.radians((a_lat + b_lat) / 2.0)
    kx = 111.320 * math.cos(mid_lat_rad)
    ky = 110.574

    ax, ay = a_lon * kx, a_lat * ky
    bx, by = b_lon * kx, b_lat * ky
    px, py = p_lon * kx, p_lat * ky

    dx = bx - ax
    dy = by - ay
    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq == 0:
        return haversine_distance_km(p_lat, p_lon, a_lat, a_lon)

    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    proj_x = ax + t * dx
    proj_y = ay + t * dy

    dist = math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)
    return round(dist, 2)


def parse_kml_coordinates(coord_text: str, force_australia_lat: bool = True) -> List[List[float]]:
    """Parses KML coordinate strings 'lon,lat,alt lon,lat,alt' into normalized [[lon, lat], ...]."""
    coords: List[List[float]] = []
    tokens = coord_text.strip().split()
    for tok in tokens:
        parts = tok.split(",")
        if len(parts) >= 2:
            try:
                raw_lon = float(parts[0])
                raw_lat = float(parts[1])
                norm_lon, norm_lat = normalize_coordinate(raw_lon, raw_lat, force_australia_lat=force_australia_lat)
                coords.append([norm_lon, norm_lat])
            except ValueError:
                continue
    return coords


def extract_cyclone_attributes_from_html(html_text: str) -> Dict[str, Any]:
    """Extracts cyclone advisory attributes from JTWC/NOAA/BoM KML HTML tables."""
    attrs: Dict[str, Any] = {}
    if not html_text:
        return attrs

    title_match = re.search(r"<b>([^<]+(?:Typhoon|Cyclone|Storm|WP\d+)[^<]*)</b>", html_text, re.I)
    if title_match:
        attrs["cyclone_name"] = title_match.group(1).strip()

    adv_match = re.search(r"Advisory\s*#?\s*(\d+)", html_text, re.I)
    if adv_match:
        attrs["advisory_number"] = adv_match.group(1).strip()

    valid_match = re.search(r"Valid at:\s*([^<]+)", html_text, re.I)
    if valid_match:
        attrs["valid_time"] = valid_match.group(1).strip()

    step_match = re.search(r"(\d+\s*hr\s*Forecast|Advisory Information|Forecast Track)", html_text, re.I)
    if step_match:
        attrs["forecast_horizon"] = step_match.group(1).strip()

    wind_match = re.search(r"Maximum Wind:\s*(\d+)\s*knots(?:\s*\(([^)]+)\))?", html_text, re.I)
    if wind_match:
        attrs["max_wind_knots"] = int(wind_match.group(1))
        if wind_match.group(2):
            attrs["max_wind_str"] = f"{wind_match.group(1)} kt ({wind_match.group(2)})"
        else:
            attrs["max_wind_str"] = f"{wind_match.group(1)} kt"

    gust_match = re.search(r"Wind Gusts:\s*(\d+)\s*knots(?:\s*\(([^)]+)\))?", html_text, re.I)
    if gust_match:
        attrs["wind_gusts_knots"] = int(gust_match.group(1))

    press_match = re.search(r"Minimum Pressure:\s*(\d+)\s*mb", html_text, re.I)
    if press_match:
        attrs["min_pressure_mb"] = int(press_match.group(1))

    motion_match = re.search(r"Motion:\s*([^<]+)", html_text, re.I)
    if motion_match:
        attrs["motion"] = motion_match.group(1).strip()

    return attrs


def parse_kml_bytes(kml_bytes: bytes, force_australia_lat: bool = True) -> Dict[str, Any]:
    """Parses raw KML bytes into a structured GeoJSON FeatureCollection supporting Points, Lines, and Polygons."""
    root = ET.fromstring(kml_bytes)

    features: List[Dict[str, Any]] = []
    doc_name = root.findtext(".//{http://www.opengis.net/kml/2.2}name") or root.findtext(".//name") or "Spatial File"
    metadata: Dict[str, Any] = {
        "title": doc_name,
        "cyclone_name": None,
        "advisory": None,
        "geometry_kinds": set(),
    }

    for placemark in root.iter():
        if not placemark.tag.endswith("Placemark"):
            continue
        name = placemark.findtext("{http://www.opengis.net/kml/2.2}name") or placemark.findtext("name") or ""
        snippet = placemark.findtext("{http://www.opengis.net/kml/2.2}Snippet") or placemark.findtext("Snippet") or ""
        desc = placemark.findtext("{http://www.opengis.net/kml/2.2}description") or placemark.findtext("description") or ""

        parsed_attrs = extract_cyclone_attributes_from_html(desc)
        if parsed_attrs.get("cyclone_name") and not metadata["cyclone_name"]:
            metadata["cyclone_name"] = parsed_attrs["cyclone_name"]
        if parsed_attrs.get("advisory_number") and not metadata["advisory"]:
            metadata["advisory"] = parsed_attrs["advisory_number"]

        props = {
            "name": name or parsed_attrs.get("forecast_horizon") or "Feature",
            "snippet": snippet,
            **parsed_attrs,
        }

        # Point
        pt = placemark.find(".//{http://www.opengis.net/kml/2.2}Point")
        if pt is None:
            pt = placemark.find(".//Point")
        if pt is not None:
            c_elem = pt.find(".//{http://www.opengis.net/kml/2.2}coordinates")
            if c_elem is None:
                c_elem = pt.find(".//coordinates")
            if c_elem is not None and c_elem.text:
                coords = parse_kml_coordinates(c_elem.text, force_australia_lat=force_australia_lat)
                if coords:
                    metadata["geometry_kinds"].add("Point")
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": coords[0]},
                        "properties": props,
                    })

        # LineString
        ls = placemark.find(".//{http://www.opengis.net/kml/2.2}LineString")
        if ls is None:
            ls = placemark.find(".//LineString")
        if ls is not None:
            c_elem = ls.find(".//{http://www.opengis.net/kml/2.2}coordinates")
            if c_elem is None:
                c_elem = ls.find(".//coordinates")
            if c_elem is not None and c_elem.text:
                coords = parse_kml_coordinates(c_elem.text, force_australia_lat=force_australia_lat)
                if len(coords) >= 2:
                    metadata["geometry_kinds"].add("LineString")
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": coords},
                        "properties": props,
                    })

        # Polygon (Area of Interest)
        poly = placemark.find(".//{http://www.opengis.net/kml/2.2}Polygon")
        if poly is None:
            poly = placemark.find(".//Polygon")
        if poly is not None:
            c_elem = poly.find(".//{http://www.opengis.net/kml/2.2}coordinates")
            if c_elem is None:
                c_elem = poly.find(".//coordinates")
            if c_elem is not None and c_elem.text:
                coords = parse_kml_coordinates(c_elem.text, force_australia_lat=force_australia_lat)
                if len(coords) >= 3:
                    if coords[0] != coords[-1]:
                        coords.append(coords[0])
                    metadata["geometry_kinds"].add("Polygon")
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [coords]},
                        "properties": {**props, "kind": "area_of_interest"},
                    })

    metadata["geometry_kinds"] = list(metadata["geometry_kinds"])
    return {
        "type": "FeatureCollection",
        "metadata": metadata,
        "features": features,
    }


def parse_uploaded_spatial_file(
    file_content: Union[bytes, Path, str],
    filename: str,
    force_australia_lat: bool = True,
) -> Dict[str, Any]:
    """Parses user-uploaded spatial files (.kmz, .kml, .geojson, .zip) into GeoJSON."""
    if isinstance(file_content, (Path, str)):
        path = Path(file_content)
        data = path.read_bytes()
    else:
        data = file_content

    fn = filename.lower()

    if fn.endswith(".kmz"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            kml_names = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not kml_names:
                raise ValueError("No .kml found inside uploaded .kmz archive.")
            kml_bytes = z.read(kml_names[0])
            return parse_kml_bytes(kml_bytes, force_australia_lat=force_australia_lat)

    elif fn.endswith(".kml"):
        return parse_kml_bytes(data, force_australia_lat=force_australia_lat)

    elif fn.endswith(".geojson") or fn.endswith(".json"):
        parsed = json.loads(data.decode("utf-8", errors="ignore"))
        if parsed.get("type") == "Feature":
            parsed = {"type": "FeatureCollection", "features": [parsed]}
        elif parsed.get("type") != "FeatureCollection":
            parsed = {"type": "FeatureCollection", "features": []}

        # Normalize coordinates if needed
        for f in parsed.get("features", []):
            g = f.get("geometry", {})
            g_type = g.get("type")
            if g_type == "Point" and g.get("coordinates"):
                g["coordinates"] = list(normalize_coordinate(g["coordinates"][0], g["coordinates"][1], force_australia_lat))
            elif g_type in ("LineString", "MultiPoint") and g.get("coordinates"):
                g["coordinates"] = [list(normalize_coordinate(c[0], c[1], force_australia_lat)) for c in g["coordinates"]]
            elif g_type in ("Polygon", "MultiLineString") and g.get("coordinates"):
                g["coordinates"] = [[list(normalize_coordinate(c[0], c[1], force_australia_lat)) for c in ring] for ring in g["coordinates"]]
        return parsed

    elif fn.endswith(".zip"):
        try:
            import geopandas as gpd
            gdf = gpd.read_file(io.BytesIO(data))
            geojson_str = gdf.to_json()
            return json.loads(geojson_str)
        except Exception as e:
            raise ValueError(f"Failed to parse shapefile zip: {e}")

    else:
        raise ValueError(f"Unsupported spatial file format '{filename}'. Supported: .kmz, .kml, .geojson, .zip (shapefile)")


def generate_circular_polygon(center_lon: float, center_lat: float, radius_km: float, num_points: int = 36) -> List[List[float]]:
    """Generates a polygon ring representing a circular buffer around a point in WGS84."""
    coords: List[List[float]] = []
    lat_rad = math.radians(center_lat)
    kx = 111.320 * math.cos(lat_rad)
    ky = 110.574

    for i in range(num_points):
        angle = 2.0 * math.pi * i / num_points
        dx = radius_km * math.cos(angle)
        dy = radius_km * math.sin(angle)
        lon = normalize_longitude(center_lon + (dx / kx))
        lat = center_lat + (dy / ky)
        coords.append([round(lon, 6), round(lat, 6)])

    coords.append(coords[0])
    return coords


def build_cyclone_hazard_zones(
    geojson: Dict[str, Any],
    radii_km: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Generates 3 standard meteorological hazard zone polygon layers around the cyclone track."""
    radii = radii_km or {
        "zone1_core_km": 50.0,      # Destructive winds (>64 kt)
        "zone2_gale_km": 150.0,     # Severe gale force (48-63 kt)
        "zone3_watch_km": 300.0,    # Outer gale watch (34-47 kt)
    }

    forecast_points = [
        f for f in geojson.get("features", [])
        if f.get("geometry", {}).get("type") == "Point"
    ]
    track_lines = [
        f for f in geojson.get("features", [])
        if f.get("geometry", {}).get("type") == "LineString"
    ]

    zone_features: List[Dict[str, Any]] = []

    for idx, pt in enumerate(forecast_points):
        lon, lat = pt["geometry"]["coordinates"]
        props = pt.get("properties", {})
        horizon = props.get("forecast_horizon") or f"Point {idx + 1}"
        wind = props.get("max_wind_str") or "Unknown"

        # Zone 3: Outer Watch (300 km)
        z3_ring = generate_circular_polygon(lon, lat, radii["zone3_watch_km"])
        zone_features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [z3_ring]},
            "properties": {
                "zone_code": "ZONE_3",
                "zone_name": "Zone 3 — Outer Gale Watch (34–47 kt)",
                "radius_km": radii["zone3_watch_km"],
                "forecast_point": horizon,
                "valid_time": props.get("valid_time"),
                "expected_wind": wind,
                "color": "#eab308",
                "opacity": 0.15,
            },
        })

        # Zone 2: Severe Gale Buffer (150 km)
        z2_ring = generate_circular_polygon(lon, lat, radii["zone2_gale_km"])
        zone_features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [z2_ring]},
            "properties": {
                "zone_code": "ZONE_2",
                "zone_name": "Zone 2 — Severe Gale Force (48–63 kt)",
                "radius_km": radii["zone2_gale_km"],
                "forecast_point": horizon,
                "valid_time": props.get("valid_time"),
                "expected_wind": wind,
                "color": "#ea580c",
                "opacity": 0.25,
            },
        })

        # Zone 1: Destructive Core / Eyewall (50 km)
        z1_ring = generate_circular_polygon(lon, lat, radii["zone1_core_km"])
        zone_features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [z1_ring]},
            "properties": {
                "zone_code": "ZONE_1",
                "zone_name": "Zone 1 — Destructive Core / Eyewall (>64 kt)",
                "radius_km": radii["zone1_core_km"],
                "forecast_point": horizon,
                "valid_time": props.get("valid_time"),
                "expected_wind": wind,
                "color": "#dc2626",
                "opacity": 0.45,
            },
        })

    return {
        "type": "FeatureCollection",
        "metadata": {
            **geojson.get("metadata", {}),
            "zones_generated": True,
            "radii_km": radii,
            "forecast_point_count": len(forecast_points),
            "track_line_count": len(track_lines),
        },
        "features": zone_features,
    }


def assess_asset_in_cyclone(
    asset_id: str,
    asset_name: str,
    lat: float,
    lon: float,
    cyclone_geojson: Dict[str, Any],
    radii_km: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Calculates an asset's predicted cyclone zone, closest distance, ETA, and expected wind."""
    radii = radii_km or {
        "zone1_core_km": 50.0,
        "zone2_gale_km": 150.0,
        "zone3_watch_km": 300.0,
    }

    norm_lon = normalize_longitude(lon)

    min_pt_dist = float("inf")
    closest_pt: Optional[Dict[str, Any]] = None

    forecast_points = [
        f for f in cyclone_geojson.get("features", [])
        if f.get("geometry", {}).get("type") == "Point"
    ]

    for pt in forecast_points:
        pt_lon, pt_lat = pt["geometry"]["coordinates"]
        d = haversine_distance_km(lat, norm_lon, pt_lat, pt_lon)
        if d < min_pt_dist:
            min_pt_dist = d
            closest_pt = pt

    min_track_dist = float("inf")
    track_lines = [
        f for f in cyclone_geojson.get("features", [])
        if f.get("geometry", {}).get("type") == "LineString"
    ]

    for line in track_lines:
        coords = line["geometry"]["coordinates"]
        for i in range(len(coords) - 1):
            a_lon, a_lat = coords[i]
            b_lon, b_lat = coords[i + 1]
            seg_dist = min_distance_to_segment_km(lat, norm_lon, a_lat, a_lon, b_lat, b_lon)
            if seg_dist < min_track_dist:
                min_track_dist = seg_dist

    effective_dist = min(min_pt_dist, min_track_dist)
    if effective_dist == float("inf"):
        effective_dist = 9999.0

    if effective_dist <= radii["zone1_core_km"]:
        zone_code = "ZONE_1"
        zone_label = "Zone 1: Destructive Core / Eyewall (>64 kt)"
        impact_level = "CRITICAL"
        color = "#dc2626"
    elif effective_dist <= radii["zone2_gale_km"]:
        zone_code = "ZONE_2"
        zone_label = "Zone 2: Severe Gale Force (48–63 kt)"
        impact_level = "HIGH"
        color = "#ea580c"
    elif effective_dist <= radii["zone3_watch_km"]:
        zone_code = "ZONE_3"
        zone_label = "Zone 3: Outer Gale Watch (34–47 kt)"
        impact_level = "MODERATE"
        color = "#eab308"
    else:
        zone_code = "ZONE_4"
        zone_label = "Zone 4: Peripheral / Outside Direct Warning Cone"
        impact_level = "LOW_MONITOR"
        color = "#006973"

    pt_props = closest_pt.get("properties", {}) if closest_pt else {}

    return {
        "asset_id": asset_id,
        "asset_name": asset_name,
        "latitude": lat,
        "longitude": norm_lon,
        "distance_to_track_km": round(effective_dist, 1),
        "predicted_zone_code": zone_code,
        "predicted_zone": zone_label,
        "operational_impact_level": impact_level,
        "zone_color": color,
        "closest_forecast_horizon": pt_props.get("forecast_horizon", "N/A"),
        "predicted_arrival_time": pt_props.get("valid_time", "N/A"),
        "expected_wind_at_closest_approach": pt_props.get("max_wind_str", "N/A"),
        "wind_gusts_knots": pt_props.get("wind_gusts_knots"),
        "minimum_pressure_mb": pt_props.get("min_pressure_mb"),
    }


def analyze_uploaded_area_of_interest(
    aoi_geojson: Dict[str, Any],
    aoi_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Performs operational intelligence assessment for ANY custom uploaded Area of Interest (Polygon)."""
    features = aoi_geojson.get("features", [])
    polygons = [f for f in features if f.get("geometry", {}).get("type") in ("Polygon", "MultiPolygon")]

    name = aoi_name or aoi_geojson.get("metadata", {}).get("title") or "Custom Area of Interest"

    all_lons: List[float] = []
    all_lats: List[float] = []
    for f in features:
        geom = f.get("geometry", {})
        coords = geom.get("coordinates", [])
        def _collect(pt_list: Any):
            if isinstance(pt_list, (list, tuple)):
                if len(pt_list) >= 2 and isinstance(pt_list[0], (int, float)):
                    all_lons.append(pt_list[0])
                    all_lats.append(pt_list[1])
                else:
                    for sub in pt_list:
                        _collect(sub)
        _collect(coords)

    if all_lons and all_lats:
        bbox = [min(all_lons), min(all_lats), max(all_lons), max(all_lats)]
    else:
        bbox = [0.0, 0.0, 0.0, 0.0]

    return {
        "aoi_name": name,
        "geometry_type": "Polygon" if polygons else "GeometryCollection",
        "polygon_count": len(polygons),
        "bounding_box": bbox,
        "operational_capabilities": [
            "3-Method Population Footprint Exposure (Method A Centroid, Method B Intersection, Method C Area-Weighted)",
            "Geoscience Australia Power Substation & Power Station Exposure with 5 km blast radius",
            "NSW Spatial Services FOI Health, Aged Care, School, and Emergency Service facilities intersection",
            "Access Corridor / Road Severance Analysis",
        ],
    }


def generate_cyclone_intelligence_reply(
    cyclone_geojson: Dict[str, Any],
    asset_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Generates an operational summary reply for an uploaded cyclone file and assessed assets."""
    meta = cyclone_geojson.get("metadata", {})
    cyclone_name = meta.get("cyclone_name") or meta.get("title") or "Tropical Cyclone"
    advisory = meta.get("advisory") or "Current"

    zone_counts = {"ZONE_1": 0, "ZONE_2": 0, "ZONE_3": 0, "ZONE_4": 0}
    for res in asset_results:
        zc = res.get("predicted_zone_code", "ZONE_4")
        zone_counts[zc] = zone_counts.get(zc, 0) + 1

    summary_text = (
        f"**{cyclone_name} (Advisory #{advisory}) — Australian Operational Asset Exposure**\n\n"
        f"- **Assets in Zone 1 (Destructive Core <50 km)**: {zone_counts['ZONE_1']}\n"
        f"- **Assets in Zone 2 (Severe Gale 50–150 km)**: {zone_counts['ZONE_2']}\n"
        f"- **Assets in Zone 3 (Outer Gale Watch 150–300 km)**: {zone_counts['ZONE_3']}\n"
        f"- **Assets in Zone 4 (Peripheral >300 km)**: {zone_counts['ZONE_4']}\n"
    )

    return {
        "cyclone_name": cyclone_name,
        "advisory": advisory,
        "total_assets_evaluated": len(asset_results),
        "zone_breakdown": zone_counts,
        "summary_markdown": summary_text,
        "asset_assessments": asset_results,
    }
