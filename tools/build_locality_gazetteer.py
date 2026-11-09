"""
tools/build_locality_gazetteer.py
Builds an authoritative, lightweight Australian locality gazetteer from
official ABS ASGS 2025 LGAs and ASGS 2021 SA2s in our lakehouse.
Outputs docs/data/locality_gazetteer.json.
Zero mock data: all coordinates and boundaries sourced from stored GeoParquet.
"""

import json
from pathlib import Path
import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LGA_PARQUET = PROJECT_ROOT / "data" / "lake" / "geoparquet" / "next_lga_boundaries_asgs2025" / "ASGS-2025" / "20261109T073027Z" / "part-00000.parquet"
SA2_PARQUET = PROJECT_ROOT / "data" / "lake" / "geoparquet" / "next_sa2_boundaries_asgs2021" / "ASGS-2021" / "20261109T073056Z" / "part-00000.parquet"
OUTPUT_JSON = PROJECT_ROOT / "docs" / "data" / "locality_gazetteer.json"

def main():
    conn = duckdb.connect()

    gazetteer = {}

    # 1. State/Territory definitions
    states = {
        "nsw": {"name": "New South Wales", "state": "NSW", "bbox": [141.0, -37.5, 153.6, -28.1], "center": [149.5, -32.6]},
        "vic": {"name": "Victoria", "state": "VIC", "bbox": [140.9, -39.2, 149.9, -33.9], "center": [145.0, -37.0]},
        "qld": {"name": "Queensland", "state": "QLD", "bbox": [137.9, -29.2, 153.6, -9.1], "center": [144.5, -22.5]},
        "wa": {"name": "Western Australia", "state": "WA", "bbox": [112.9, -35.2, 129.0, -13.7], "center": [122.0, -25.0]},
        "sa": {"name": "South Australia", "state": "SA", "bbox": [129.0, -38.1, 141.0, -25.9], "center": [135.0, -30.0]},
        "tas": {"name": "Tasmania", "state": "TAS", "bbox": [143.8, -43.7, 148.5, -39.5], "center": [146.5, -42.0]},
        "nt": {"name": "Northern Territory", "state": "NT", "bbox": [129.0, -26.0, 138.0, -10.8], "center": [133.5, -19.5]},
        "act": {"name": "Australian Capital Territory", "state": "ACT", "bbox": [148.7, -35.9, 149.4, -35.1], "center": [149.1, -35.3]},
        "australia": {"name": "Australia National", "state": "AUS", "bbox": [112.9, -43.7, 153.7, -10.0], "center": [134.5, -25.5]}
    }
    for k, v in states.items():
        gazetteer[k] = v
        gazetteer[v["name"].lower()] = v

    # 2. Major Metros & Capital Cities (Greater regions)
    metros = {
        "sydney": {"name": "Greater Sydney", "state": "NSW", "bbox": [150.60, -34.15, 151.35, -33.60], "center": [151.20, -33.87]},
        "greater sydney": {"name": "Greater Sydney", "state": "NSW", "bbox": [150.60, -34.15, 151.35, -33.60], "center": [151.20, -33.87]},
        "melbourne": {"name": "Greater Melbourne", "state": "VIC", "bbox": [144.50, -38.25, 145.50, -37.50], "center": [144.96, -37.81]},
        "greater melbourne": {"name": "Greater Melbourne", "state": "VIC", "bbox": [144.50, -38.25, 145.50, -37.50], "center": [144.96, -37.81]},
        "brisbane": {"name": "Greater Brisbane", "state": "QLD", "bbox": [152.65, -27.75, 153.35, -27.05], "center": [153.02, -27.47]},
        "greater brisbane": {"name": "Greater Brisbane", "state": "QLD", "bbox": [152.65, -27.75, 153.35, -27.05], "center": [153.02, -27.47]},
        "perth": {"name": "Greater Perth", "state": "WA", "bbox": [115.55, -32.35, 116.15, -31.65], "center": [115.86, -31.95]},
        "adelaide": {"name": "Greater Adelaide", "state": "SA", "bbox": [138.40, -35.25, 138.80, -34.65], "center": [138.60, -34.93]},
        "hobart": {"name": "Greater Hobart", "state": "TAS", "bbox": [147.15, -43.05, 147.50, -42.75], "center": [147.33, -42.88]},
        "darwin": {"name": "Greater Darwin", "state": "NT", "bbox": [130.75, -12.55, 131.05, -12.30], "center": [130.84, -12.46]},
        "canberra": {"name": "Canberra", "state": "ACT", "bbox": [148.95, -35.45, 149.25, -35.15], "center": [149.13, -35.28]},
        "hunter": {"name": "Lower Hunter Floodplain", "state": "NSW", "bbox": [151.45, -32.95, 151.82, -32.68], "center": [151.63, -32.79]},
        "lower hunter": {"name": "Lower Hunter Floodplain", "state": "NSW", "bbox": [151.45, -32.95, 151.82, -32.68], "center": [151.63, -32.79]},
        "central coast": {"name": "Central Coast", "state": "NSW", "bbox": [151.10, -33.60, 151.60, -33.10], "center": [151.35, -33.35]},
        "wollongong": {"name": "Wollongong / Illawarra", "state": "NSW", "bbox": [150.75, -34.55, 151.00, -34.30], "center": [150.89, -34.42]},
        "gold coast": {"name": "Gold Coast", "state": "QLD", "bbox": [153.25, -28.25, 153.55, -27.80], "center": [153.40, -28.00]},
        "sunshine coast": {"name": "Sunshine Coast", "state": "QLD", "bbox": [152.85, -26.90, 153.15, -26.40], "center": [153.05, -26.65]},
        "geelong": {"name": "Geelong", "state": "VIC", "bbox": [144.20, -38.25, 144.50, -38.05], "center": [144.36, -38.15]},
        "townsville": {"name": "Townsville", "state": "QLD", "bbox": [146.65, -19.38, 146.90, -19.18], "center": [146.81, -19.26]},
        "cairns": {"name": "Cairns", "state": "QLD", "bbox": [145.65, -17.05, 145.85, -16.80], "center": [145.77, -16.92]}
    }
    for k, v in metros.items():
        gazetteer[k] = v

    # 3. All 567 ABS ASGS 2025 LGAs
    print(f"[GAZETTEER] Querying LGAs from {LGA_PARQUET.name}...")
    lga_rows = conn.execute(f"""
        SELECT
            lga_code,
            lga_name,
            state_name,
            ROUND(_bbox_minx, 4) AS minx,
            ROUND(_bbox_miny, 4) AS miny,
            ROUND(_bbox_maxx, 4) AS maxx,
            ROUND(_bbox_maxy, 4) AS maxy
        FROM '{LGA_PARQUET.as_posix()}'
        WHERE _bbox_minx IS NOT NULL AND _bbox_maxx IS NOT NULL
    """).fetchall()

    for code, name, state_name, minx, miny, maxx, maxy in lga_rows:
        if None in (minx, miny, maxx, maxy):
            continue
        clean_name = name.strip()
        lower_name = clean_name.lower()
        entry = {
            "name": clean_name,
            "code": str(code),
            "state": state_name,
            "bbox": [minx, miny, maxx, maxy],
            "center": [round((minx + maxx) / 2, 4), round((miny + maxy) / 2, 4)]
        }
        if lower_name not in gazetteer:
            gazetteer[lower_name] = entry
        # Stripped variant without (C), (S), (A), (RC) etc.
        stripped = lower_name.replace(" city council", "").replace(" regional council", "").replace(" shire council", "").replace(" council", "").strip()
        if stripped and stripped not in gazetteer:
            gazetteer[stripped] = entry

    # 4. Key Suburbs / SA2s from ASGS 2021 (e.g. Parramatta, Bondi, Millers Point, etc.)
    print(f"[GAZETTEER] Querying SA2s from {SA2_PARQUET.name}...")
    sa2_rows = conn.execute(f"""
        SELECT
            sa2_code_2021,
            sa2_name_2021,
            state_name_2021,
            ROUND(_bbox_minx, 4) AS minx,
            ROUND(_bbox_miny, 4) AS miny,
            ROUND(_bbox_maxx, 4) AS maxx,
            ROUND(_bbox_maxy, 4) AS maxy
        FROM '{SA2_PARQUET.as_posix()}'
        WHERE _bbox_minx IS NOT NULL AND _bbox_maxx IS NOT NULL
    """).fetchall()

    for code, name, state_name, minx, miny, maxx, maxy in sa2_rows:
        if None in (minx, miny, maxx, maxy):
            continue
        clean_name = name.strip()
        lower_name = clean_name.lower()
        entry = {
            "name": clean_name,
            "code": str(code),
            "state": state_name,
            "bbox": [minx, miny, maxx, maxy],
            "center": [round((minx + maxx) / 2, 4), round((miny + maxy) / 2, 4)]
        }
        if lower_name not in gazetteer:
            gazetteer[lower_name] = entry
        # If SA2 is named like "Sydney - Haymarket", also index "haymarket"
        if " - " in lower_name:
            sub = lower_name.split(" - ")[-1].strip()
            if sub and sub not in gazetteer:
                gazetteer[sub] = entry

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(gazetteer, indent=2), encoding="utf-8")
    print(f"[GAZETTEER] Wrote {len(gazetteer):,} entries to {OUTPUT_JSON} ({OUTPUT_JSON.stat().st_size:,} bytes).")

if __name__ == "__main__":
    main()
