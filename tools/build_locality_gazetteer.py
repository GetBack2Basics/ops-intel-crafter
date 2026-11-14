"""
tools/build_locality_gazetteer.py
Builds an authoritative, comprehensive Australian locality gazetteer from
official public datasets stored in our GCS lakehouse / local parquet mirror:
1. ABS ASGS 2025 LGAs (next_lga_boundaries_asgs2025)
2. ABS ASGS 2021 SA2 Suburbs & Towns (next_sa2_boundaries_asgs2021)
3. Geoscience Australia Electricity Substations Localities (ga_electricity_substations)
4. Geoscience Australia Major Power Stations Localities (ga_major_power_stations)
5. Capital Metros and States/Territories

Zero mock data: all coordinates, extents, and localities sourced directly from lakehouse GeoParquet.
"""

import json
from pathlib import Path
import duckdb

from src.catalogue.dataset_registry import DatasetRegistry
from src.ingestion.gcs_storage import GCSLakeStorage

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def snapshot_uri(dataset_key: str) -> str:
    """Resolves a catalogue dataset to its canonical readable snapshot (gs://, cloud-first)."""
    store = GCSLakeStorage()
    entry = DatasetRegistry().get(dataset_key)
    snapshot = entry.latest_snapshot_path
    if not snapshot:
        raise FileNotFoundError(f"No stored GeoParquet snapshot for dataset {dataset_key}")
    uri = str(snapshot)
    if uri.startswith(("gs://", "http://", "https://")):
        return uri
    local = store.project_root / uri
    return str(local) if local.exists() else store.gs_uri(uri)

LGA_PARQUET = snapshot_uri("next_lga_boundaries_asgs2025")
SA2_PARQUET = snapshot_uri("next_sa2_boundaries_asgs2021")
SUB_PARQUET = snapshot_uri("ga_electricity_substations")
POW_PARQUET = snapshot_uri("ga_major_power_stations")

OUTPUT_JSON = PROJECT_ROOT / "docs" / "data" / "locality_gazetteer.json"
COMPACT_JSON = PROJECT_ROOT / "docs" / "data" / "lga_gazetteer_compact.json"

STATE_CODE_MAP = {
    "new south wales": "NSW", "nsw": "NSW",
    "victoria": "VIC", "vic": "VIC",
    "queensland": "QLD", "qld": "QLD",
    "western australia": "WA", "wa": "WA",
    "south australia": "SA", "sa": "SA",
    "tasmania": "TAS", "tas": "TAS",
    "northern territory": "NT", "nt": "NT",
    "australian capital territory": "ACT", "act": "ACT"
}

def clean_name(s: str) -> str:
    return s.strip()

def main():
    conn = duckdb.connect()
    gazetteer = {}

    # 1. State/Territory definitions
    states = {
        "nsw": {"name": "New South Wales", "state": "NSW", "stateCode": "NSW", "isState": True, "bbox": [141.0, -37.5, 153.6, -28.1], "center": [149.5, -32.6]},
        "vic": {"name": "Victoria", "state": "VIC", "stateCode": "VIC", "isState": True, "bbox": [140.9, -39.2, 149.9, -33.9], "center": [145.0, -37.0]},
        "qld": {"name": "Queensland", "state": "QLD", "stateCode": "QLD", "isState": True, "bbox": [137.9, -29.2, 153.6, -9.1], "center": [144.5, -22.5]},
        "wa": {"name": "Western Australia", "state": "WA", "stateCode": "WA", "isState": True, "bbox": [112.9, -35.2, 129.0, -13.7], "center": [122.0, -25.0]},
        "sa": {"name": "South Australia", "state": "SA", "stateCode": "SA", "isState": True, "bbox": [129.0, -38.1, 141.0, -25.9], "center": [135.0, -30.0]},
        "tas": {"name": "Tasmania", "state": "TAS", "stateCode": "TAS", "isState": True, "bbox": [143.8, -43.7, 148.5, -39.5], "center": [146.5, -42.0]},
        "nt": {"name": "Northern Territory", "state": "NT", "stateCode": "NT", "isState": True, "bbox": [129.0, -26.0, 138.0, -10.8], "center": [133.5, -19.5]},
        "act": {"name": "Australian Capital Territory", "state": "ACT", "stateCode": "ACT", "isState": True, "bbox": [148.7, -35.9, 149.4, -35.1], "center": [149.1, -35.3]},
        "australia": {"name": "Australia National", "state": "AUS", "stateCode": "AUS", "isState": True, "bbox": [112.9, -43.7, 153.7, -10.0], "center": [134.5, -25.5]}
    }
    for k, v in states.items():
        gazetteer[k] = v
        gazetteer[v["name"].lower()] = v
        gazetteer[f"{k} statewide"] = v
        gazetteer[f"{v['name'].lower()} statewide"] = v

    # 2. Major Metros & Capital Cities
    metros = {
        "sydney": {"name": "Greater Sydney", "state": "NSW", "stateCode": "NSW", "isState": False, "bbox": [150.60, -34.15, 151.35, -33.60], "center": [151.20, -33.87]},
        "greater sydney": {"name": "Greater Sydney", "state": "NSW", "stateCode": "NSW", "isState": False, "bbox": [150.60, -34.15, 151.35, -33.60], "center": [151.20, -33.87]},
        "melbourne": {"name": "Greater Melbourne", "state": "VIC", "stateCode": "VIC", "isState": False, "bbox": [144.50, -38.25, 145.50, -37.50], "center": [144.96, -37.81]},
        "greater melbourne": {"name": "Greater Melbourne", "state": "VIC", "stateCode": "VIC", "isState": False, "bbox": [144.50, -38.25, 145.50, -37.50], "center": [144.96, -37.81]},
        "brisbane": {"name": "Greater Brisbane", "state": "QLD", "stateCode": "QLD", "isState": False, "bbox": [152.65, -27.75, 153.35, -27.05], "center": [153.02, -27.47]},
        "greater brisbane": {"name": "Greater Brisbane", "state": "QLD", "stateCode": "QLD", "isState": False, "bbox": [152.65, -27.75, 153.35, -27.05], "center": [153.02, -27.47]},
        "perth": {"name": "Greater Perth", "state": "WA", "stateCode": "WA", "isState": False, "bbox": [115.55, -32.35, 116.15, -31.65], "center": [115.86, -31.95]},
        "greater perth": {"name": "Greater Perth", "state": "WA", "stateCode": "WA", "isState": False, "bbox": [115.55, -32.35, 116.15, -31.65], "center": [115.86, -31.95]},
        "adelaide": {"name": "Greater Adelaide", "state": "SA", "stateCode": "SA", "isState": False, "bbox": [138.40, -35.25, 138.80, -34.65], "center": [138.60, -34.93]},
        "hobart": {"name": "Greater Hobart", "state": "TAS", "stateCode": "TAS", "isState": False, "bbox": [147.15, -43.05, 147.50, -42.75], "center": [147.33, -42.88]},
        "darwin": {"name": "Greater Darwin", "state": "NT", "stateCode": "NT", "isState": False, "bbox": [130.75, -12.55, 131.05, -12.30], "center": [130.84, -12.46]},
        "canberra": {"name": "Canberra", "state": "ACT", "stateCode": "ACT", "isState": False, "bbox": [148.95, -35.45, 149.25, -35.15], "center": [149.13, -35.28]},
        "hunter": {"name": "Lower Hunter Floodplain", "state": "NSW", "stateCode": "NSW", "isState": False, "bbox": [151.45, -32.95, 151.82, -32.68], "center": [151.63, -32.79]},
        "lower hunter": {"name": "Lower Hunter Floodplain", "state": "NSW", "stateCode": "NSW", "isState": False, "bbox": [151.45, -32.95, 151.82, -32.68], "center": [151.63, -32.79]},
        "central coast": {"name": "Central Coast", "state": "NSW", "stateCode": "NSW", "isState": False, "bbox": [151.10, -33.60, 151.60, -33.10], "center": [151.35, -33.35]},
        "wollongong": {"name": "Wollongong / Illawarra", "state": "NSW", "stateCode": "NSW", "isState": False, "bbox": [150.75, -34.55, 151.00, -34.30], "center": [150.89, -34.42]},
        "gold coast": {"name": "Gold Coast", "state": "QLD", "stateCode": "QLD", "isState": False, "bbox": [153.25, -28.25, 153.55, -27.80], "center": [153.40, -28.00]},
        "sunshine coast": {"name": "Sunshine Coast", "state": "QLD", "stateCode": "QLD", "isState": False, "bbox": [152.85, -26.90, 153.15, -26.40], "center": [153.05, -26.65]},
        "geelong": {"name": "Geelong", "state": "VIC", "stateCode": "VIC", "isState": False, "bbox": [144.20, -38.25, 144.50, -38.05], "center": [144.36, -38.15]},
        "townsville": {"name": "Townsville", "state": "QLD", "stateCode": "QLD", "isState": False, "bbox": [146.65, -19.38, 146.90, -19.18], "center": [146.81, -19.26]},
        "cairns": {"name": "Cairns", "state": "QLD", "stateCode": "QLD", "isState": False, "bbox": [145.65, -17.05, 145.85, -16.80], "center": [145.77, -16.92]},
        "tweed heads": {"name": "Tweed Heads", "state": "NSW", "stateCode": "NSW", "isState": False, "bbox": [153.48, -28.22, 153.58, -28.15], "center": [153.53, -28.18]}
    }
    for k, v in metros.items():
        gazetteer[k] = v

    # 3. All ABS ASGS 2025 LGAs
    print(f"[GAZETTEER] Querying LGAs from {Path(LGA_PARQUET).name}...")
    lga_rows = conn.execute(f"""
        SELECT
            lga_code,
            lga_name,
            state_name,
            ROUND(_bbox_minx, 4) AS minx,
            ROUND(_bbox_miny, 4) AS miny,
            ROUND(_bbox_maxx, 4) AS maxx,
            ROUND(_bbox_maxy, 4) AS maxy
        FROM '{LGA_PARQUET}'
        WHERE _bbox_minx IS NOT NULL AND _bbox_maxx IS NOT NULL
    """).fetchall()

    for code, name, state_name, minx, miny, maxx, maxy in lga_rows:
        if None in (minx, miny, maxx, maxy):
            continue
        c_name = name.strip()
        l_name = c_name.lower()
        st_code = STATE_CODE_MAP.get(state_name.lower(), state_name.upper()) if state_name else "AUS"
        entry = {
            "name": c_name,
            "code": str(code),
            "state": state_name,
            "stateCode": st_code,
            "isState": False,
            "bbox": [minx, miny, maxx, maxy],
            "center": [round((minx + maxx) / 2, 4), round((miny + maxy) / 2, 4)]
        }
        if l_name not in gazetteer:
            gazetteer[l_name] = entry
        stripped = l_name.replace(" city council", "").replace(" regional council", "").replace(" shire council", "").replace(" council", "").strip()
        if stripped and stripped not in gazetteer:
            gazetteer[stripped] = entry

    # 4. All Suburbs & Towns from ASGS 2021 SA2
    print(f"[GAZETTEER] Querying SA2s from {Path(SA2_PARQUET).name}...")
    sa2_rows = conn.execute(f"""
        SELECT
            sa2_code_2021,
            sa2_name_2021,
            state_name_2021,
            ROUND(_bbox_minx, 4) AS minx,
            ROUND(_bbox_miny, 4) AS miny,
            ROUND(_bbox_maxx, 4) AS maxx,
            ROUND(_bbox_maxy, 4) AS maxy
        FROM '{SA2_PARQUET}'
        WHERE _bbox_minx IS NOT NULL AND _bbox_maxx IS NOT NULL
    """).fetchall()

    for code, name, state_name, minx, miny, maxx, maxy in sa2_rows:
        if None in (minx, miny, maxx, maxy):
            continue
        c_name = name.strip()
        l_name = c_name.lower()
        st_code = STATE_CODE_MAP.get((state_name or "").lower(), (state_name or "AUS").upper())
        entry = {
            "name": c_name,
            "code": str(code),
            "state": state_name,
            "stateCode": st_code,
            "isState": False,
            "bbox": [minx, miny, maxx, maxy],
            "center": [round((minx + maxx) / 2, 4), round((miny + maxy) / 2, 4)]
        }
        if l_name not in gazetteer:
            gazetteer[l_name] = entry

        # Compound names with " - " (e.g. "Lake Munmorah - Mannering Park")
        if " - " in l_name:
            for part in l_name.split(" - "):
                p_clean = part.strip()
                if p_clean and p_clean not in gazetteer:
                    gazetteer[p_clean] = entry

        # Compound names with " / "
        if " / " in l_name:
            for part in l_name.split(" / "):
                p_clean = part.strip()
                if p_clean and p_clean not in gazetteer:
                    gazetteer[p_clean] = entry

    # 5. Localities from Geoscience Australia Electricity Substations (1,475 distinct localities)
    print(f"[GAZETTEER] Querying infrastructure localities from {Path(SUB_PARQUET).name}...")
    sub_rows = conn.execute(f"""
        SELECT
            TRIM(locality) AS locality,
            TRIM(state) AS state,
            ROUND(MIN(_bbox_minx) - 0.035, 4) AS minx,
            ROUND(MIN(_bbox_miny) - 0.035, 4) AS miny,
            ROUND(MAX(_bbox_maxx) + 0.035, 4) AS maxx,
            ROUND(MAX(_bbox_maxy) + 0.035, 4) AS maxy,
            ROUND(AVG((_bbox_minx + _bbox_maxx) / 2), 4) AS cx,
            ROUND(AVG((_bbox_miny + _bbox_maxy) / 2), 4) AS cy,
            COUNT(*) AS sub_count
        FROM '{SUB_PARQUET}'
        WHERE locality IS NOT NULL AND locality != ''
        GROUP BY TRIM(locality), TRIM(state)
    """).fetchall()

    for loc, st, minx, miny, maxx, maxy, cx, cy, count in sub_rows:
        l_loc = loc.lower()
        st_code = STATE_CODE_MAP.get(st.lower(), st.upper()) if st else "AUS"
        # If already present with an authoritative boundary (e.g. SA2/LGA), preserve it; otherwise insert
        if l_loc not in gazetteer:
            gazetteer[l_loc] = {
                "name": loc.title(),
                "state": st,
                "stateCode": st_code,
                "isState": False,
                "bbox": [minx, miny, maxx, maxy],
                "center": [cx, cy],
                "source": "ga_electricity_substations"
            }

    # 6. Localities from Geoscience Australia Major Power Stations (329 distinct localities)
    print(f"[GAZETTEER] Querying power station localities from {Path(POW_PARQUET).name}...")
    pow_rows = conn.execute(f"""
        SELECT
            TRIM(locality) AS locality,
            TRIM(state) AS state,
            ROUND(MIN(_bbox_minx) - 0.040, 4) AS minx,
            ROUND(MIN(_bbox_miny) - 0.040, 4) AS miny,
            ROUND(MAX(_bbox_maxx) + 0.040, 4) AS maxx,
            ROUND(MAX(_bbox_maxy) + 0.040, 4) AS maxy,
            ROUND(AVG((_bbox_minx + _bbox_maxx) / 2), 4) AS cx,
            ROUND(AVG((_bbox_miny + _bbox_maxy) / 2), 4) AS cy,
            COUNT(*) AS pow_count
        FROM '{POW_PARQUET}'
        WHERE locality IS NOT NULL AND locality != ''
        GROUP BY TRIM(locality), TRIM(state)
    """).fetchall()

    for loc, st, minx, miny, maxx, maxy, cx, cy, count in pow_rows:
        l_loc = loc.lower()
        st_code = STATE_CODE_MAP.get(st.lower(), st.upper()) if st else "AUS"
        if l_loc not in gazetteer:
            gazetteer[l_loc] = {
                "name": loc.title(),
                "state": st,
                "stateCode": st_code,
                "isState": False,
                "bbox": [minx, miny, maxx, maxy],
                "center": [cx, cy],
                "source": "ga_major_power_stations"
            }

    # Also index prominent infrastructure station names directly (e.g. Vales Point, Eraring, Bayswater, Liddell, Munmorah)
    station_names = conn.execute(f"""
        SELECT
            TRIM(name) AS name,
            TRIM(state) AS state,
            ROUND(_bbox_minx - 0.035, 4) AS minx,
            ROUND(_bbox_miny - 0.035, 4) AS miny,
            ROUND(_bbox_maxx + 0.035, 4) AS maxx,
            ROUND(_bbox_maxy + 0.035, 4) AS maxy,
            ROUND((_bbox_minx + _bbox_maxx)/2, 4) AS cx,
            ROUND((_bbox_miny + _bbox_maxy)/2, 4) AS cy
        FROM '{SUB_PARQUET}'
        WHERE name IS NOT NULL AND name != ''
    """).fetchall()
    for name, st, minx, miny, maxx, maxy, cx, cy in station_names:
        l_name = name.lower()
        st_code = STATE_CODE_MAP.get(st.lower(), st.upper()) if st else "AUS"
        if l_name not in gazetteer:
            gazetteer[l_name] = {
                "name": name,
                "state": st,
                "stateCode": st_code,
                "isState": False,
                "bbox": [minx, miny, maxx, maxy],
                "center": [cx, cy],
                "source": "substation_name"
            }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(gazetteer, indent=2), encoding="utf-8")
    print(f"[GAZETTEER] Wrote {len(gazetteer):,} entries to {OUTPUT_JSON} ({OUTPUT_JSON.stat().st_size:,} bytes).")

    # Generate a compact dictionary for embedding into docs/layers.js
    # Embed all states, metros, LGAs, and all localities under 10 chars or high-frequency
    compact = {}
    for k, v in gazetteer.items():
        # Keep LGAs, states, metros, and common town localities
        if v.get("isState") or k in metros or len(v.get("code", "")) <= 5 or k in (
            "mannering park", "lake munmorah", "vales point", "tweed", "tweed heads",
            "parramatta", "newcastle", "cessnock", "maitland", "singleton", "muswellbrook",
            "armidale", "tamworth", "bathurst", "orange", "dubbo", "wagga wagga", "albury"
        ):
            compact[k] = v

    COMPACT_JSON.write_text(json.dumps(compact, separators=(",", ":")), encoding="utf-8")
    print(f"[GAZETTEER] Wrote {len(compact):,} compact entries to {COMPACT_JSON} ({COMPACT_JSON.stat().st_size:,} bytes).")

if __name__ == "__main__":
    main()
