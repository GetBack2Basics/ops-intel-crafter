"""Build GeoLibre 0.2.0 Project Specification for Operational Intelligence Crafter."""

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
QA_SUMMARY_PATH = DOCS_DIR / "qa" / "data" / "qa_summary.json"


def load_qa_summary() -> dict:
    """Loads the canonical QA summary from GCS (cloud-first), local docs mirror as fallback."""
    try:
        from google.cloud import storage
        bucket = os.environ.get("OIC_GCS_BUCKET", "operational-intelligence-crafter-lake")
        project = os.environ.get("OIC_GCP_PROJECT", "operational-intelligence-crafter")
        client = storage.Client(project=project)
        blob = client.bucket(bucket).blob("qa/data/qa_summary.json")
        if blob.exists(client):
            return json.loads(blob.download_as_text())
    except Exception as exc:
        print(f"[WARN] GCS QA summary unavailable ({exc.__class__.__name__}); using local mirror.")
    if QA_SUMMARY_PATH.exists():
        return json.loads(QA_SUMMARY_PATH.read_text(encoding="utf-8"))
    return {}


def build_spec():
    qa_data = load_qa_summary()

    qa_by_key = {d["dataset_key"]: d for d in qa_data.get("datasets", [])}

    layer_groups = [
        {"id": "grp_emergency", "name": "🚨 Emergency Operations & Active Incidents", "visible": True, "collapsed": False, "opacity": 1.0},
        {"id": "grp_population", "name": "👥 ABS Population Grid (Methods A/B/C)", "visible": True, "collapsed": False, "opacity": 1.0},
        {"id": "grp_infrastructure", "name": "⚡ Energy & Critical Infrastructure", "visible": True, "collapsed": False, "opacity": 1.0},
        {"id": "grp_hazards", "name": "🌊 Flood, Cyclone & Seismic Hazards", "visible": True, "collapsed": False, "opacity": 0.85},
        {"id": "grp_receptors", "name": "🏥 Health, Schools & Sensitive Receptors", "visible": True, "collapsed": False, "opacity": 1.0},
        {"id": "grp_boundaries", "name": "🗺️ Statistical & Administrative Boundaries", "visible": False, "collapsed": False, "opacity": 0.5},
    ]

    catalog_layers = [
        {
            "id": "derived_hunter_1km_population_grid",
            "name": "1 km² Population Grid (Methods A/B/C)",
            "groupId": "grp_population",
            "type": "geojson",
            "visible": True,
            "opacity": 0.65,
            "style": {
                "fillColor": "#006973",
                "strokeColor": "#004f57",
                "strokeWidth": 1.0,
                "fillOpacity": 0.65
            },
            "source": {
                "type": "geojson",
                "path": "exports/hunter_population_grid_comparison/result.geojson",
                "gcs_lakehouse": "gs://operational-intelligence-crafter-lake/exports/hunter_population_grid_comparison/"
            },
            "metadata": {
                "methodology": "3-Method Multi-Grid Comparison: Method A (Centroid Contains), Method B (Footprint Intersects), Method C (Area-Weighted Proportional)",
                "crs": "EPSG:7844 (GDA2020) / Metric EPSG:3112",
                "source": "ABS 1 km² Population Grid & ASGS 2021/2025"
            }
        },
        {
            "id": "hunter_substation_flood_dependency",
            "name": "Substation Flood Dependency (Derived)",
            "groupId": "grp_infrastructure",
            "type": "geojson",
            "visible": True,
            "opacity": 0.9,
            "style": {
                "circleRadius": 7,
                "fillColor": "#ea580c",
                "strokeColor": "#ffffff",
                "strokeWidth": 1.5
            },
            "source": {
                "type": "geojson",
                "path": "exports/hunter_substation_flood_dependency/result.geojson",
                "gcs_lakehouse": "gs://operational-intelligence-crafter-lake/exports/hunter_substation_flood_dependency/"
            },
            "metadata": {
                "methodology": "Spatial join of GA power substations with NSW water inundation flood extent and FOI sensitive complexes",
                "crs": "EPSG:7844 (GDA2020)"
            }
        },
        {
            "id": "nsw_rfs_major_incidents_live",
            "name": "NSW RFS Major Incidents (Live)",
            "groupId": "grp_emergency",
            "type": "geojson",
            "visible": True,
            "opacity": 1.0,
            "style": {
                "circleRadius": 8,
                "fillColor": "#dc2626",
                "strokeColor": "#fef2f2",
                "strokeWidth": 2.0
            },
            "source": {
                "type": "geojson",
                "path": "qa/data/nsw_rfs_major_incidents_live.geojson",
                "gcs_lakehouse": "gs://operational-intelligence-crafter-lake/geoparquet/nsw_rfs_major_incidents_live/"
            },
            "metadata": {
                "provider": "NSW Rural Fire Service (RFS)",
                "crs": "EPSG:7844 (GDA2020)"
            }
        },
        {
            "id": "nsw_water_inundation_areas",
            "name": "NSW Water Inundation Areas",
            "groupId": "grp_hazards",
            "type": "geojson",
            "visible": True,
            "opacity": 0.45,
            "style": {
                "fillColor": "#38bdf8",
                "strokeColor": "#0284c7",
                "strokeWidth": 1.0,
                "fillOpacity": 0.45
            },
            "source": {
                "type": "geojson",
                "path": "qa/data/nsw_water_inundation_areas.geojson",
                "gcs_lakehouse": "gs://operational-intelligence-crafter-lake/geoparquet/nsw_water_inundation_areas/"
            },
            "metadata": {
                "provider": "NSW Department of Customer Service / Spatial Services",
                "crs": "EPSG:7844 (GDA2020)"
            }
        },
        {
            "id": "ga_electricity_transmission_lines",
            "name": "GA Transmission Lines",
            "groupId": "grp_infrastructure",
            "type": "geojson",
            "visible": True,
            "opacity": 0.85,
            "style": {
                "strokeColor": "#eab308",
                "strokeWidth": 2.0
            },
            "source": {
                "type": "geojson",
                "path": "qa/data/ga_electricity_transmission_lines.geojson",
                "gcs_lakehouse": "gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_transmission_lines/"
            },
            "metadata": {
                "provider": "Geoscience Australia",
                "crs": "EPSG:7844 (GDA2020)"
            }
        },
        {
            "id": "ga_electricity_substations",
            "name": "GA Power Substations",
            "groupId": "grp_infrastructure",
            "type": "geojson",
            "visible": True,
            "opacity": 0.9,
            "style": {
                "circleRadius": 6,
                "fillColor": "#c2410c",
                "strokeColor": "#ffffff",
                "strokeWidth": 1.2
            },
            "source": {
                "type": "geojson",
                "path": "qa/data/ga_electricity_substations.geojson",
                "gcs_lakehouse": "gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_substations/"
            },
            "metadata": {
                "provider": "Geoscience Australia",
                "crs": "EPSG:7844 (GDA2020)"
            }
        },
        {
            "id": "ga_major_power_stations",
            "name": "GA Major Power Stations",
            "groupId": "grp_infrastructure",
            "type": "geojson",
            "visible": True,
            "opacity": 0.9,
            "style": {
                "circleRadius": 7,
                "fillColor": "#7c3aed",
                "strokeColor": "#ffffff",
                "strokeWidth": 1.5
            },
            "source": {
                "type": "geojson",
                "path": "qa/data/ga_major_power_stations.geojson",
                "gcs_lakehouse": "gs://operational-intelligence-crafter-lake/geoparquet/ga_major_power_stations/"
            },
            "metadata": {
                "provider": "Geoscience Australia",
                "crs": "EPSG:7844 (GDA2020)"
            }
        },
        {
            "id": "nsw_foi_building_complexes",
            "name": "NSW FOI Building Complexes (Emergency & Health)",
            "groupId": "grp_receptors",
            "type": "geojson",
            "visible": True,
            "opacity": 0.85,
            "style": {
                "circleRadius": 5,
                "fillColor": "#16a34a",
                "strokeColor": "#ffffff",
                "strokeWidth": 1.0
            },
            "source": {
                "type": "geojson",
                "path": "qa/data/nsw_foi_building_complexes.geojson",
                "gcs_lakehouse": "gs://operational-intelligence-crafter-lake/geoparquet/nsw_foi_building_complexes/"
            },
            "metadata": {
                "provider": "NSW Spatial Services Features of Interest",
                "crs": "EPSG:7844 (GDA2020)"
            }
        },
        {
            "id": "next_lga_boundaries_asgs2025",
            "name": "ABS LGA Boundaries (ASGS 2025)",
            "groupId": "grp_boundaries",
            "type": "geojson",
            "visible": False,
            "opacity": 0.6,
            "style": {
                "fillColor": "transparent",
                "strokeColor": "#006973",
                "strokeWidth": 1.5
            },
            "source": {
                "type": "geojson",
                "path": "qa/data/next_lga_boundaries_asgs2025.geojson",
                "gcs_lakehouse": "gs://operational-intelligence-crafter-lake/geoparquet/next_lga_boundaries_asgs2025/"
            },
            "metadata": {
                "provider": "Australian Bureau of Statistics (ABS)",
                "crs": "EPSG:7844 (GDA2020)"
            }
        },
        {
            "id": "ga_seismic_hazard_pga_10pct",
            "name": "NSHA 2018 Seismic PGA Contours",
            "groupId": "grp_hazards",
            "type": "geojson",
            "visible": False,
            "opacity": 0.7,
            "style": {
                "strokeColor": "#be185d",
                "strokeWidth": 1.5,
                "lineDasharray": [4, 2]
            },
            "source": {
                "type": "geojson",
                "path": "qa/data/ga_seismic_hazard_pga_10pct.geojson",
                "gcs_lakehouse": "gs://operational-intelligence-crafter-lake/geoparquet/ga_seismic_hazard_pga_10pct/"
            },
            "metadata": {
                "provider": "Geoscience Australia (NSHA 2018)",
                "crs": "EPSG:7844 (GDA2020)"
            }
        },
        {
            "id": "national_healthcare_nhsd_v2",
            "name": "AURA: National Hospitals (NHSD)",
            "groupId": "grp_receptors",
            "type": "geojson",
            "visible": True,
            "opacity": 0.9,
            "style": {
                "circleRadius": 6,
                "fillColor": "#059669",
                "strokeColor": "#ffffff",
                "strokeWidth": 1.5
            },
            "source": {
                "type": "geojson",
                "endpoint": "https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Features_of_Interest_Category/FeatureServer/3",
                "s3_path": "s3://wherobots-user-storage/aura_siting/receptors/national_healthcare_nhsd.parquet"
            },
            "metadata": {
                "provider": "National Health Services Directory (NHSD) / AURA",
                "crs": "EPSG:7844 (GDA2020)"
            }
        },
        {
            "id": "national_schools_acara_v2",
            "name": "AURA: National Schools (ACARA)",
            "groupId": "grp_receptors",
            "type": "geojson",
            "visible": True,
            "opacity": 0.85,
            "style": {
                "circleRadius": 5,
                "fillColor": "#2563eb",
                "strokeColor": "#ffffff",
                "strokeWidth": 1.0
            },
            "source": {
                "type": "geojson",
                "endpoint": "https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Features_of_Interest_Category/FeatureServer/3",
                "s3_path": "s3://wherobots-user-storage/aura_siting/receptors/national_schools_acara.parquet"
            },
            "metadata": {
                "provider": "Australian Curriculum, Assessment and Reporting Authority (ACARA)",
                "crs": "EPSG:7844 (GDA2020)"
            }
        },
        {
            "id": "national_cyclone_hazard_tcha_v2",
            "name": "AURA: Tropical Cyclone Hazard (TCHA)",
            "groupId": "grp_hazards",
            "type": "geojson",
            "visible": False,
            "opacity": 0.75,
            "style": {
                "strokeColor": "#06b6d4",
                "strokeWidth": 1.8,
                "lineDasharray": [3, 2]
            },
            "source": {
                "type": "geojson",
                "endpoint": "https://services.ga.gov.au/gis/rest/services/National_Seismic_Hazard_Assessment_2018/MapServer/15",
                "s3_path": "s3://wherobots-user-storage/aura_siting/hazards/national_cyclone_hazard_tcha.parquet"
            },
            "metadata": {
                "provider": "Geoscience Australia (TCHA)",
                "crs": "EPSG:7844 (GDA2020)"
            }
        }
    ]

    for layer in catalog_layers:
        key = layer["id"]
        if key in qa_by_key:
            layer["metadata"].update({
                "source_agency": qa_by_key[key].get("source_agency", ""),
                "features_stored": qa_by_key[key].get("feature_count") or qa_by_key[key].get("stored_count") or 0,
                "qa_status": qa_by_key[key].get("overall_qa_status", "PASS")
            })

    spec = {
        "version": "0.2.0",
        "name": "Operational Intelligence Crafter — Emergency Spatial Workbench",
        "description": "Declarative spatial intelligence definition for Australian Emergency Operations, Critical Infrastructure Dependencies, Multi-Hazard Analysis, and ABS 1 km² Population Grid (Methods A/B/C).",
        "mapView": {
            "center": [151.75, -32.85],
            "zoom": 9.5,
            "bearing": 0,
            "pitch": 0,
            "bbox": [112.9, -43.7, 153.7, -10.0]
        },
        "basemapStyleUrl": "https://tiles.openfreemap.org/styles/liberty",
        "basemapVisible": True,
        "basemapOpacity": 0.75,
        "blankBackgroundColor": None,
        "layerGroups": layer_groups,
        "layers": catalog_layers,
        "styles": {},
        "metadata": {
            "project": "Operational Intelligence Crafter",
            "copyright": "©® 2026 GetBack2Basics. Based on open-source projects from GetBack2Basics.",
            "disclaimer": "Engineering proof of concept and research prototype only. Should not be relied on for operational emergency warning, dispatch, or life-safety decisions.",
            "workbench_role": "Australian Emergency Spatial Intelligence Lakehouse",
            "canonical_lakehouse": "gs://operational-intelligence-crafter-lake",
            "s3_aura_lakehouse": "s3://wherobots-user-storage/aura_siting/",
            "crs": "EPSG:7844 (GDA2020 Geographic) / EPSG:3112 (GDA2020 Lambert Metric)",
            "zero_mock": True,
            "population_methods": [
                "Method A: Centroid Point-in-Polygon (ST_Contains)",
                "Method B: 1km² Cell Polygon Footprint Intersection (ST_Intersects)",
                "Method C: Area-weighted Proportional Estimate"
            ]
        }
    }

    out_file = DOCS_DIR / "operational-intelligence-crafter.geolibre.json"
    out_file.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print(f"[OK] Wrote {len(catalog_layers)} layers to {out_file}")


if __name__ == "__main__":
    build_spec()
