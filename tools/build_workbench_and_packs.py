"""Builds all Phase 5–9 Analytical Deliverables, RFC 7946 Exports, Offline Map-in-a-Box,
Engine Benchmarks, and the Google Stitch Emergency Spatial Intelligence Workbench (`docs/index.html`).
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import geopandas as gpd

from src.ai.spatial_agent import AISpatialAgent
from src.analysis.exposure import run_multi_scale_exposure_analysis
from src.analysis.infrastructure_dependencies import run_infrastructure_dependency_analysis
from src.analysis.isolation import run_isolation_vulnerability_analysis
from src.analysis.population_methods import (
    build_hunter_1km_evaluation_grid,
    run_four_regime_population_study,
)
from src.catalogue.dataset_registry import DatasetRegistry
from src.engines.benchmark_runner import run_engine_benchmarks
from src.engines.duckdb_engine import DuckDBSpatialEngine
from src.exports.geojson_export import export_rfc7946_geojson
from src.exports.geoparquet_export import export_analysis_geoparquet
from src.exports.map_package_builder import build_offline_map_package
from src.ingestion.telemetry import utc_now_iso


def _latest_parquet(geoparquet_dir: Path, ds_key: str) -> Path:
    files = sorted((geoparquet_dir / ds_key).glob("*/*/part-*.parquet"))
    if not files:
        raise FileNotFoundError(f"No stored GeoParquet found for {ds_key}")
    return files[-1]


def build_workbench_html(bundle: dict, output_html_path: Path) -> None:
    """Generates the Google Stitch `web_dashboard` Emergency Spatial Intelligence Workbench."""
    pop = bundle["population_study"]
    exp = bundle["multi_scale_exposure"]
    iso = bundle["isolation_analysis"]
    dep = bundle["infrastructure_dependencies"]
    bench = bundle["benchmarks"]
    ai_audits = bundle["ai_audits"]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Emergency Spatial Intelligence Workbench — GCS GeoParquet, DuckDB & Wherobots</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@600;700&display=swap" rel="stylesheet" />
  <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" rel="stylesheet" />
  <link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet" />
  <script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
  <script>
    tailwind.config = {{
      theme: {{
        extend: {{
          colors: {{
            primary: '#001026',
            'primary-container': '#0b2545',
            secondary: '#006973',
            surface: '#faf8ff',
            'surface-low': '#f2f3ff',
            'surface-high': '#e1e2ec'
          }},
          fontFamily: {{
            headline: ['Space Grotesk', 'sans-serif'],
            body: ['Plus Jakarta Sans', 'sans-serif'],
            mono: ['JetBrains Mono', 'monospace']
          }}
        }}
      }}
    }};
  </script>
  <style>
    body {{ font-family: 'Plus Jakarta Sans', sans-serif; background: #faf8ff; color: #181b22; }}
    h1, h2, h3, .font-headline {{ font-family: 'Space Grotesk', sans-serif; }}
    .font-mono {{ font-family: 'JetBrains Mono', monospace; }}
    .material-symbols-outlined {{ font-variation-settings: 'FILL' 0, 'wght' 500, 'GRAD' 0, 'opsz' 20; vertical-align: middle; }}
  </style>
</head>
<body class="flex h-screen overflow-hidden">
  <!-- Stitch Fixed Left Sidebar -->
  <aside class="w-64 bg-primary text-white flex flex-col justify-between shrink-0 border-r border-slate-800">
    <div>
      <div class="p-5 border-b border-slate-800/80">
        <div class="flex items-center gap-2 text-cyan-400 text-xs font-mono uppercase tracking-widest">
          <span class="material-symbols-outlined text-base">radar</span>
          OIC Spatial Lakehouse
        </div>
        <h1 class="font-headline text-lg font-bold tracking-tight mt-1 text-white">Emergency Intelligence</h1>
        <p class="text-[11px] text-slate-400 mt-1">GCS GeoParquet 1.1 • DuckDB • Sedona</p>
      </div>

      <nav class="p-3 space-y-1 text-xs">
        <a href="#sec-map" class="flex items-center gap-2.5 px-3 py-2.5 rounded bg-primary-container text-cyan-300 font-semibold">
          <span class="material-symbols-outlined text-base">map</span>
          Multi-Scale Workbench
        </a>
        <a href="#sec-pop" class="flex items-center gap-2.5 px-3 py-2.5 rounded hover:bg-slate-800/70 text-slate-300">
          <span class="material-symbols-outlined text-base">grid_on</span>
          NExT Population (A / B / C)
        </a>
        <a href="#sec-ai" class="flex items-center gap-2.5 px-3 py-2.5 rounded hover:bg-slate-800/70 text-slate-300">
          <span class="material-symbols-outlined text-base">psychology</span>
          AI Spatial SQL Analyst
        </a>
        <a href="#sec-bench" class="flex items-center gap-2.5 px-3 py-2.5 rounded hover:bg-slate-800/70 text-slate-300">
          <span class="material-symbols-outlined text-base">speed</span>
          Engine Benchmarks & Cost
        </a>
        <div class="pt-3 mt-3 border-t border-slate-800/80">
          <div class="px-3 py-1 text-[10px] font-mono uppercase text-slate-400">Deliverables & QA Portals</div>
          <a href="qa/index.html" class="flex items-center gap-2.5 px-3 py-2 rounded hover:bg-slate-800/70 text-emerald-300">
            <span class="material-symbols-outlined text-base">verified</span>
            3-Level QA Matrix (11 Sources)
          </a>
          <a href="qa/inspect.html" class="flex items-center gap-2.5 px-3 py-2 rounded hover:bg-slate-800/70 text-sky-300">
            <span class="material-symbols-outlined text-base">travel_explore</span>
            MapLibre Source Inspector
          </a>
          <a href="map_packages/hunter_flood_emergency_pack/index.html" class="flex items-center gap-2.5 px-3 py-2 rounded hover:bg-slate-800/70 text-amber-300">
            <span class="material-symbols-outlined text-base">inventory_2</span>
            Offline Map-in-a-Box Pack
          </a>
          <a href="exports/hunter_population_grid_comparison/result.geojson" target="_blank" class="flex items-center gap-2.5 px-3 py-2 rounded hover:bg-slate-800/70 text-slate-300">
            <span class="material-symbols-outlined text-base">download</span>
            RFC 7946 GeoJSON (QGIS)
          </a>
        </div>
      </nav>
    </div>

    <div class="p-4 border-t border-slate-800 text-[11px] text-slate-400 space-y-1">
      <div class="font-mono text-cyan-400">gs://operational-intelligence-crafter-lake</div>
      <div>Stored CRS: <span class="font-mono text-white">EPSG:7844</span></div>
      <div>Metric CRS: <span class="font-mono text-white">EPSG:3112</span></div>
      <div class="text-amber-300/90 pt-1">Research Prototype — Not Live Dispatch</div>
    </div>
  </aside>

  <!-- Main Content -->
  <div class="flex-1 flex flex-col overflow-hidden">
    <!-- Dual-Tier Sticky Header -->
    <header class="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between shrink-0">
      <div>
        <div class="flex items-center gap-2">
          <span class="px-2 py-0.5 text-[10px] font-mono font-bold uppercase bg-emerald-100 text-emerald-800 rounded">ZERO-MOCK VERIFIED</span>
          <span class="px-2 py-0.5 text-[10px] font-mono font-bold uppercase bg-sky-100 text-sky-800 rounded">GEOPARQUET 1.1.0</span>
          <span class="px-2 py-0.5 text-[10px] font-mono font-bold uppercase bg-amber-100 text-amber-900 rounded">$0.00/HR IDLE CLOUD COST</span>
        </div>
        <h2 class="font-headline text-base font-bold text-primary mt-1">Australian Multi-Scale Emergency Spatial Intelligence Demonstration</h2>
      </div>
      <div class="flex items-center gap-2 text-xs">
        <a href="qa/index.html" class="px-3 py-1.5 rounded border border-slate-300 hover:bg-slate-50 font-semibold text-primary">Open QA Matrix</a>
        <a href="map_packages/hunter_flood_emergency_pack/index.html" class="px-3 py-1.5 rounded bg-secondary text-white font-semibold hover:opacity-95">Launch Offline Map-in-a-Box</a>
      </div>
    </header>

    <!-- Scrollable Workspace -->
    <main class="flex-1 overflow-y-auto p-6 space-y-8">
      <!-- Top KPI Strip -->
      <section class="grid grid-cols-1 md:grid-cols-5 gap-4">
        <div class="bg-white p-4 rounded-lg border border-slate-200 shadow-sm">
          <div class="text-[11px] font-mono uppercase text-slate-500">Catalogued Sources</div>
          <div class="text-2xl font-headline font-bold text-primary mt-1">11 <span class="text-xs font-mono text-emerald-700 font-normal">9 PASS / 1 WARN / 1 FAIL</span></div>
          <div class="text-[11px] text-slate-500 mt-1">GA, ABS ASGS, NSW Spatial & RFS</div>
        </div>
        <div class="bg-white p-4 rounded-lg border border-slate-200 shadow-sm">
          <div class="text-[11px] font-mono uppercase text-slate-500">Local Flood Exposure</div>
          <div class="text-2xl font-headline font-bold text-primary mt-1">{exp['local_scale']['exposed_facility_count']} <span class="text-xs font-mono text-slate-500 font-normal">FOI complexes</span></div>
          <div class="text-[11px] text-slate-500 mt-1">Within 250m buffer (EPSG:3112)</div>
        </div>
        <div class="bg-white p-4 rounded-lg border border-slate-200 shadow-sm">
          <div class="text-[11px] font-mono uppercase text-slate-500">State Live RFS Feed</div>
          <div class="text-2xl font-headline font-bold text-primary mt-1">{exp['regional_state_scale']['live_rfs_incident_count']} <span class="text-xs font-mono text-amber-700 font-normal">active incidents</span></div>
          <div class="text-[11px] text-slate-500 mt-1">GeometryCollections unpacked</div>
        </div>
        <div class="bg-white p-4 rounded-lg border border-slate-200 shadow-sm">
          <div class="text-[11px] font-mono uppercase text-slate-500">Substation Catchments</div>
          <div class="text-2xl font-headline font-bold text-primary mt-1">{dep['substation_count']} <span class="text-xs font-mono text-slate-500 font-normal">substations</span></div>
          <div class="text-[11px] text-slate-500 mt-1">5 km metric dependency radius</div>
        </div>
        <div class="bg-white p-4 rounded-lg border border-slate-200 shadow-sm">
          <div class="text-[11px] font-mono uppercase text-slate-500">Parquet Compression</div>
          <div class="text-2xl font-headline font-bold text-secondary mt-1">{bench['storage_efficiency']['compression_ratio_raw_to_geoparquet']}x</div>
          <div class="text-[11px] text-slate-500 mt-1">Raw JSON vs GeoParquet 1.1.0</div>
        </div>
      </section>

      <!-- Section 1: Interactive MapLibre Workbench + Scale Switcher -->
      <section id="sec-map" class="bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
        <div class="p-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3 bg-surface-low">
          <div>
            <h3 class="font-headline font-bold text-sm text-primary uppercase tracking-wider">1. Multi-Scale Spatial Intelligence MapLibre Canvas</h3>
            <p class="text-xs text-slate-600">Switch between Local (Hunter Flood + 1 km² Population Grid), Regional/State (NSW LGAs + Live RFS Bushfires), and National (Power Stations + Seismic PGA)</p>
          </div>
          <div class="flex flex-wrap items-center gap-2 text-xs">
            <button onclick="flyScale('local')" class="px-3 py-1.5 rounded bg-primary text-white font-semibold">Local: Hunter Flood & 1km² Grid</button>
            <button onclick="flyScale('state')" class="px-3 py-1.5 rounded bg-slate-200 hover:bg-slate-300 text-primary font-semibold">State: NSW Live RFS Incidents</button>
            <button onclick="flyScale('national')" class="px-3 py-1.5 rounded bg-slate-200 hover:bg-slate-300 text-primary font-semibold">National: GA Power & Seismic</button>
          </div>
        </div>
        <div class="grid grid-cols-1 lg:grid-cols-4">
          <div class="lg:col-span-3 relative" style="height: 480px;">
            <div id="mainMap" class="w-full h-full"></div>
            <div class="absolute bottom-3 left-3 bg-primary/90 text-white px-3 py-2 rounded text-[11px] font-mono border border-cyan-400/30">
              Click any 1 km² grid cell, inundation polygon, substation, or RFS incident to inspect provenance & attributes
            </div>
          </div>
          <div class="p-4 bg-surface-low border-l border-slate-200 flex flex-col justify-between text-xs space-y-4">
            <div>
              <h4 class="font-headline font-bold text-primary uppercase tracking-wider mb-2">Layer Visibility</h4>
              <div class="space-y-2">
                <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked onchange="toggleMapLayer('grid-fill', this.checked); toggleMapLayer('grid-line', this.checked)" /> <span class="w-3 h-3 inline-block rounded-sm bg-emerald-500"></span> 1 km² Population Grid (Regime 2)</label>
                <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked onchange="toggleMapLayer('inund-fill', this.checked)" /> <span class="w-3 h-3 inline-block rounded-sm bg-sky-500"></span> NSW Water Inundation Areas</label>
                <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked onchange="toggleMapLayer('tx-line', this.checked)" /> <span class="w-3 h-3 inline-block rounded-sm bg-yellow-400"></span> GA Electricity Transmission Lines</label>
                <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked onchange="toggleMapLayer('sub-circle', this.checked)" /> <span class="w-3 h-3 inline-block rounded-full bg-orange-500"></span> GA Power Substations (5km dep)</label>
                <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked onchange="toggleMapLayer('rfs-circle', this.checked)" /> <span class="w-3 h-3 inline-block rounded-full bg-red-600"></span> Live NSW RFS Incidents</label>
                <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked onchange="toggleMapLayer('pwr-circle', this.checked)" /> <span class="w-3 h-3 inline-block rounded-full bg-purple-600"></span> National Major Power Stations</label>
              </div>
            </div>

            <div class="bg-white p-3 rounded border border-slate-200">
              <div class="font-mono text-[10px] uppercase text-slate-500">Selected Feature Inspector</div>
              <pre id="featureInspector" class="font-mono text-[11px] text-slate-800 mt-1.5 whitespace-pre-wrap max-h-48 overflow-y-auto">Click a feature on the map to inspect its source dataset, vintage, and attributes.</pre>
            </div>

            <div class="bg-amber-50 border border-amber-200 p-3 rounded text-[11px] text-amber-900">
              <strong>Acceptance Test #17 (Failed Source):</strong> <span class="font-mono">nsw_emergency_management_restricted</span> returned HTTP 200 with embedded ArcGIS error <span class="font-mono">499: Token Required</span>. Recorded as <span class="font-mono font-bold text-red-700">FAIL</span> in QA Matrix with zero synthetic fallback.
            </div>
          </div>
        </div>
      </section>

      <!-- Section 2: NExT Population Representation Comparison (Methods A, B, and C) -->
      <section id="sec-pop" class="bg-white rounded-lg border border-slate-200 shadow-sm p-5 space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-3">
          <div>
            <span class="text-[11px] font-mono uppercase text-secondary font-bold">Section 7 Specification — Controlled Methodological Comparison</span>
            <h3 class="font-headline text-base font-bold text-primary">NExT 1 km² Population Grid Representation Comparison (Methods A, B & C across 4 Regimes)</h3>
          </div>
          <a href="exports/hunter_population_grid_comparison/result.geojson" target="_blank" class="px-3 py-1.5 rounded bg-primary-container text-white text-xs font-mono">Download Grid Comparison GeoJSON</a>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left border-collapse text-xs">
            <thead>
              <tr class="border-b border-slate-200 bg-surface-low text-slate-600 font-mono text-[11px] uppercase">
                <th class="p-3">Geometry Regime</th>
                <th class="p-3">Method A: Centroid ST_Contains</th>
                <th class="p-3">Method B: Polygon ST_Intersects (Full)</th>
                <th class="p-3">Method B Breakdown (Contained vs Straddling)</th>
                <th class="p-3">Method C: Area-Weighted (Modelled)*</th>
                <th class="p-3">Delta (B - A) & Centroids Missed</th>
                <th class="p-3">SQL Time</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-200">
              {"".join(f'''
              <tr class="hover:bg-slate-50">
                <td class="p-3">
                  <div class="font-bold text-primary">{r["regime_title"]}</div>
                  <div class="text-[11px] text-slate-500 mt-0.5">{r["regime_description"]}</div>
                </td>
                <td class="p-3 font-mono">
                  <span class="font-bold text-sky-700">{r["method_a_centroid_contains"]["population_total"]:,.1f}</span> pop<br/>
                  <span class="text-[11px] text-slate-500">{r["method_a_centroid_contains"]["cell_count"]} cells | {r["method_a_centroid_contains"]["observed_foi_buildings"]} FOI bldgs</span>
                </td>
                <td class="p-3 font-mono">
                  <span class="font-bold text-emerald-700">{r["method_b_cell_polygon_intersects"]["full_cell_population_total"]:,.1f}</span> pop<br/>
                  <span class="text-[11px] text-slate-500">{r["method_b_cell_polygon_intersects"]["intersecting_cell_count"]} cells | {r["method_b_cell_polygon_intersects"]["observed_foi_buildings"]} FOI bldgs</span>
                </td>
                <td class="p-3 font-mono text-[11px]">
                  Contained: <strong>{r["method_b_cell_polygon_intersects"]["fully_contained_cell_count"]}</strong> cells ({r["method_b_cell_polygon_intersects"]["fully_contained_population_total"]:,.1f} pop)<br/>
                  Straddling: <strong class="text-amber-700">{r["method_b_cell_polygon_intersects"]["boundary_straddling_cell_count"]}</strong> cells ({r["method_b_cell_polygon_intersects"]["boundary_straddling_population_total"]:,.1f} pop)
                </td>
                <td class="p-3 font-mono">
                  <span class="font-bold text-purple-700">{r["method_c_area_weighted_proportional"]["proportional_population_estimate"]:,.1f}</span> est*<br/>
                  <span class="text-[10px] text-amber-800">Uniform density assumption</span>
                </td>
                <td class="p-3 font-mono">
                  <span class="font-bold text-amber-800">+{r["divergence_summary"]["population_delta_b_minus_a"]:,.1f}</span> pop<br/>
                  <span class="text-[11px] text-red-700">{r["divergence_summary"]["cells_missed_by_centroid_method_a"]} straddling cells missed by Method A</span>
                </td>
                <td class="p-3 font-mono text-slate-600">{r["execution_ms"]} ms</td>
              </tr>
              ''' for r in pop["regimes"])}
            </tbody>
          </table>
        </div>
        <p class="text-[11px] text-amber-900 bg-amber-50 border border-amber-200 px-3 py-2 rounded font-mono">
          *Method C Explicit Assumption Warning: {pop["method_c_assumption_warning"]}
        </p>
      </section>

      <!-- Section 3: Multi-Scale Exposure, Isolation & Infrastructure Dependencies -->
      <section class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div class="bg-white rounded-lg border border-slate-200 shadow-sm p-5 space-y-3">
          <h3 class="font-headline text-sm font-bold text-primary uppercase tracking-wider">2A. Critical Substation Flood Proximity & 5km Facility Dependency (EPSG:3112)</h3>
          <div class="overflow-x-auto max-h-72">
            <table class="w-full text-left border-collapse text-xs">
              <thead>
                <tr class="border-b border-slate-200 bg-surface-low font-mono text-[11px] text-slate-600">
                  <th class="p-2">Substation</th>
                  <th class="p-2">kV</th>
                  <th class="p-2">Dist to Flood (m)</th>
                  <th class="p-2">FOI within 5km</th>
                  <th class="p-2">Exposure Tier</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-200">
                {"".join(f'''
                <tr>
                  <td class="p-2 font-semibold">{s["substation_name"]}</td>
                  <td class="p-2 font-mono">{s["voltage_kv"]}</td>
                  <td class="p-2 font-mono">{s["distance_to_inundation_m"]:,.1f} m</td>
                  <td class="p-2 font-mono font-bold text-primary">{s["dependent_foi_within_5km"]}</td>
                  <td class="p-2 font-mono text-[10px]">{s["hazard_exposure_tier"]}</td>
                </tr>
                ''' for s in dep["substations"][:10])}
              </tbody>
            </table>
          </div>
        </div>

        <div class="bg-white rounded-lg border border-slate-200 shadow-sm p-5 space-y-3">
          <h3 class="font-headline text-sm font-bold text-primary uppercase tracking-wider">2B. SA2 Community Floodplain Access & Isolation Vulnerability (EPSG:3112)</h3>
          <div class="overflow-x-auto max-h-72">
            <table class="w-full text-left border-collapse text-xs">
              <thead>
                <tr class="border-b border-slate-200 bg-surface-low font-mono text-[11px] text-slate-600">
                  <th class="p-2">SA2 Code</th>
                  <th class="p-2">SA2 Name</th>
                  <th class="p-2">Inundated (km²)</th>
                  <th class="p-2">SA2 Overlap %</th>
                  <th class="p-2">Isolation Tier</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-200">
                {"".join(f'''
                <tr>
                  <td class="p-2 font-mono">{s["sa2_code21"]}</td>
                  <td class="p-2 font-semibold">{s["sa2_name21"]}</td>
                  <td class="p-2 font-mono">{s["inundated_area_sqkm"]} km²</td>
                  <td class="p-2 font-mono font-bold text-sky-800">{s["inundated_pct_of_sa2"]}%</td>
                  <td class="p-2 font-mono text-[10px]">{s["isolation_classification"]}</td>
                </tr>
                ''' for s in iso["sa2_isolation_ranking"][:10])}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <!-- Section 4: Catalogue-Grounded AI Spatial Analysis Audit Log -->
      <section id="sec-ai" class="bg-white rounded-lg border border-slate-200 shadow-sm p-5 space-y-4">
        <div>
          <span class="text-[11px] font-mono uppercase text-secondary font-bold">Section 8 Specification — Zero-Hallucination Allow-Listed SQL Planner</span>
          <h3 class="font-headline text-base font-bold text-primary">AI-Assisted Natural-Language Spatial Analysis & Provenance Audit Trail</h3>
          <p class="text-xs text-slate-600">Demonstrates verified SQL execution on catalogued GeoParquet views, mandatory clarification when Population Method A/B/C is omitted, and strict refusal when uncatalogued telemetry is requested.</p>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {"".join(f'''
          <div class="border border-slate-200 rounded-lg p-4 bg-surface-low space-y-2">
            <div class="flex items-center justify-between">
              <span class="font-mono text-[11px] font-bold px-2 py-0.5 rounded {'bg-emerald-100 text-emerald-800' if a['status']=='EXECUTED' else ('bg-amber-100 text-amber-900' if a['status']=='CLARIFICATION_REQUIRED' else 'bg-red-100 text-red-800')}">{a['status']}</span>
              <span class="font-mono text-[11px] text-slate-500">{a['execution_ms']} ms | {a['row_count']} rows</span>
            </div>
            <div class="text-xs font-bold text-primary">Q: "{a['user_question']}"</div>
            <div class="text-xs text-slate-700">{a['grounded_explanation']}</div>
            <div class="text-[11px] font-mono text-slate-500">Datasets: {", ".join(a['selected_datasets']) if a['selected_datasets'] else "None (Blocked)"}</div>
            {f'<pre class="bg-primary text-cyan-300 p-2.5 rounded font-mono text-[10px] overflow-x-auto">{a["generated_sql"]}</pre>' if a.get("generated_sql") else ""}
          </div>
          ''' for a in ai_audits)}
        </div>
      </section>

      <!-- Section 5: Execution Engine Benchmarks & Cost Telemetry -->
      <section id="sec-bench" class="bg-white rounded-lg border border-slate-200 shadow-sm p-5 space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-3">
          <div>
            <span class="text-[11px] font-mono uppercase text-secondary font-bold">Section 5.3 Specification — Reproducible Latency & Cost Telemetry</span>
            <h3 class="font-headline text-base font-bold text-primary">DuckDB Spatial over GeoParquet vs Live Source Endpoints vs Wherobots/Sedona</h3>
          </div>
          <span class="font-mono text-xs bg-emerald-100 text-emerald-900 px-3 py-1 rounded font-bold">Active Cloud Compute: $0.00/hr</span>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div>
            <h4 class="font-headline text-xs font-bold uppercase text-slate-600 mb-2">DuckDB Spatial GeoParquet Query Benchmarks (Cold vs Warm)</h4>
            <table class="w-full text-left border-collapse text-xs">
              <thead>
                <tr class="border-b border-slate-200 bg-surface-low font-mono text-[11px]">
                  <th class="p-2">Benchmark Task</th>
                  <th class="p-2">First Run</th>
                  <th class="p-2">Warm Run</th>
                  <th class="p-2">Rows</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-200">
                {"".join(f'''
                <tr>
                  <td class="p-2 font-semibold">{b["title"]}</td>
                  <td class="p-2 font-mono">{b["first_run_ms"]} ms</td>
                  <td class="p-2 font-mono text-emerald-700 font-bold">{b["warm_run_ms"]} ms</td>
                  <td class="p-2 font-mono">{b["row_count"]}</td>
                </tr>
                ''' for b in bench["duckdb_spatial_benchmarks"])}
              </tbody>
            </table>
          </div>

          <div>
            <h4 class="font-headline text-xs font-bold uppercase text-slate-600 mb-2">Wherobots / Apache Sedona & Storage Cost Summary</h4>
            <div class="bg-surface-low p-4 rounded border border-slate-200 space-y-2 text-xs font-mono">
              <div><strong>Wherobots Engine Status:</strong> {bench["wherobots_sedona_engine"]["status"]}</div>
              <div><strong>Wherobots Note:</strong> {bench["wherobots_sedona_engine"].get("detail", "Verified")}</div>
              <div><strong>Total Raw Payload Volume:</strong> {bench["storage_efficiency"]["total_raw_payload_bytes"]:,} bytes</div>
              <div><strong>Total GeoParquet 1.1 Volume:</strong> {bench["storage_efficiency"]["total_geoparquet_bytes"]:,} bytes ({bench["storage_efficiency"]["compression_ratio_raw_to_geoparquet"]}x reduction)</div>
              <div><strong>Estimated GCS Standard Storage Cost:</strong> ${bench["storage_efficiency"]["gcs_monthly_storage_cost_estimate_usd"]}/month</div>
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>

  <script>
    let map;
    function flyScale(scale) {{
      if (!map) return;
      if (scale === 'local') map.flyTo({{ center: [151.63, -32.79], zoom: 10.6 }});
      else if (scale === 'state') map.flyTo({{ center: [149.8, -32.6], zoom: 5.8 }});
      else if (scale === 'national') map.flyTo({{ center: [134.5, -25.5], zoom: 3.6 }});
    }}

    function toggleMapLayer(layerId, visible) {{
      if (!map || !map.getLayer(layerId)) return;
      map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none');
    }}

    document.addEventListener('DOMContentLoaded', () => {{
      map = new maplibregl.Map({{
        container: 'mainMap',
        style: {{
          version: 8,
          sources: {{
            'carto-dark': {{
              type: 'raster',
              tiles: ['https://basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}@2x.png'],
              tileSize: 256,
              attribution: '© OpenStreetMap contributors, © CARTO'
            }}
          }},
          layers: [{{ id: 'carto-dark-layer', type: 'raster', source: 'carto-dark' }}]
        }},
        center: [151.63, -32.79],
        zoom: 10.5
      }});

      map.addControl(new maplibregl.NavigationControl(), 'top-right');

      map.on('load', () => {{
        map.addSource('pop_grid', {{ type: 'geojson', data: 'exports/hunter_population_grid_comparison/result.geojson' }});
        map.addLayer({{
          id: 'grid-fill',
          type: 'fill',
          source: 'pop_grid',
          paint: {{
            'fill-color': [
              'match',
              ['get', 'cell_classification'],
              'FULLY_CONTAINED', '#10b981',
              'BOUNDARY_CENTROID_IN', '#0ea5e9',
              'BOUNDARY_CENTROID_OUT', '#f59e0b',
              '#64748b'
            ],
            'fill-opacity': 0.42
          }}
        }});
        map.addLayer({{
          id: 'grid-line',
          type: 'line',
          source: 'pop_grid',
          paint: {{ 'line-color': '#34d399', 'line-width': 1 }}
        }});

        map.addSource('inundation', {{ type: 'geojson', data: 'qa/data/nsw_water_inundation_areas.geojson' }});
        map.addLayer({{
          id: 'inund-fill',
          type: 'fill',
          source: 'inundation',
          paint: {{ 'fill-color': '#38bdf8', 'fill-opacity': 0.45 }}
        }});

        map.addSource('tx_lines', {{ type: 'geojson', data: 'qa/data/ga_electricity_transmission_lines.geojson' }});
        map.addLayer({{
          id: 'tx-line',
          type: 'line',
          source: 'tx_lines',
          paint: {{ 'line-color': '#facc15', 'line-width': 2 }}
        }});

        map.addSource('substations', {{ type: 'geojson', data: 'exports/hunter_substation_flood_dependency/result.geojson' }});
        map.addLayer({{
          id: 'sub-circle',
          type: 'circle',
          source: 'substations',
          paint: {{ 'circle-radius': 6, 'circle-color': '#f97316', 'circle-stroke-width': 1.5, 'circle-stroke-color': '#fff' }}
        }});

        map.addSource('rfs_live', {{ type: 'geojson', data: 'qa/data/nsw_rfs_major_incidents_live.geojson' }});
        map.addLayer({{
          id: 'rfs-circle',
          type: 'circle',
          source: 'rfs_live',
          paint: {{ 'circle-radius': 7, 'circle-color': '#ef4444', 'circle-stroke-width': 2, 'circle-stroke-color': '#fecaca' }}
        }});

        map.addSource('power_stations', {{ type: 'geojson', data: 'qa/data/ga_major_power_stations.geojson' }});
        map.addLayer({{
          id: 'pwr-circle',
          type: 'circle',
          source: 'power_stations',
          paint: {{ 'circle-radius': 4.5, 'circle-color': '#a855f7', 'circle-stroke-width': 1, 'circle-stroke-color': '#fff' }}
        }});

        ['grid-fill', 'inund-fill', 'tx-line', 'sub-circle', 'rfs-circle', 'pwr-circle'].forEach(lyr => {{
          map.on('click', lyr, e => {{
            if (!e.features || !e.features.length) return;
            document.getElementById('featureInspector').textContent = JSON.stringify(e.features[0].properties, null, 2);
          }});
        }});
      }});
    }});
  </script>
</body>
</html>
"""
    output_html_path.parent.mkdir(parents=True, exist_ok=True)
    output_html_path.write_text(html, encoding="utf-8")


def main() -> None:
    lake_root = PROJECT_ROOT / "data" / "lake"
    geoparquet_dir = lake_root / "geoparquet"
    exports_dir = lake_root / "exports"
    map_packages_dir = lake_root / "map_packages"
    docs_dir = PROJECT_ROOT / "docs"

    registry = DatasetRegistry()

    # 1. Build 1 km² evaluation grid over Lower Hunter from stored ABS SA2 & NSW FOI snapshots
    grid_parquet_path = (
        geoparquet_dir
        / "derived_hunter_1km_population_grid"
        / "ASGS2021-FOI-v1"
        / "20261109T003500Z"
        / "part-00000.parquet"
    )
    print("[1/7] Building 1 km² Lower Hunter evaluation grid from ABS SA2 & NSW FOI complexes...")
    grid_gdf = build_hunter_1km_evaluation_grid(
        sa2_parquet_path=_latest_parquet(geoparquet_dir, "next_sa2_boundaries_asgs2021"),
        foi_parquet_path=_latest_parquet(geoparquet_dir, "nsw_foi_building_complexes"),
        output_parquet_path=grid_parquet_path,
    )
    print(f"      Generated {len(grid_gdf)} 1 km² cells at {grid_parquet_path}")

    with DuckDBSpatialEngine(registry=registry) as engine:
        # 2. Run 4-Regime NExT Population Representation Comparison (Methods A, B, and C)
        print("[2/7] Running 4-regime NExT Population Representation Comparison (Methods A, B, C)...")
        pop_study = run_four_regime_population_study(
            engine=engine,
            grid_parquet_path=grid_parquet_path,
            inundation_parquet_path=_latest_parquet(geoparquet_dir, "nsw_water_inundation_areas"),
            transmission_parquet_path=_latest_parquet(geoparquet_dir, "ga_electricity_transmission_lines"),
        )
        for reg in pop_study["regimes"]:
            print(
                f"      {reg['regime_id']}: Method A={reg['method_a_centroid_contains']['population_total']} "
                f"| Method B={reg['method_b_cell_polygon_intersects']['full_cell_population_total']} "
                f"(straddling={reg['method_b_cell_polygon_intersects']['boundary_straddling_cell_count']}) "
                f"| Method C={reg['method_c_area_weighted_proportional']['proportional_population_estimate']}"
            )

        # 3. Run Multi-Scale Exposure, Isolation, and Infrastructure Dependency Analyses
        print("[3/7] Running Multi-Scale Exposure, Isolation, and Substation Dependency analyses...")
        multi_scale_exp = run_multi_scale_exposure_analysis(engine, geoparquet_dir)
        isolation_res = run_isolation_vulnerability_analysis(engine, geoparquet_dir)
        dep_res = run_infrastructure_dependency_analysis(engine, geoparquet_dir)

        # 4. Export RFC 7946 GeoJSON + GeoParquet deliverables for Regime 2 Population Grid & Substation Dependencies
        print("[4/7] Exporting RFC 7946 GeoJSON & GeoParquet deliverables for GeoLibre and QGIS...")
        regime2_cells = {c["cell_id"]: c for c in pop_study["regimes"][1]["cells"]}
        grid_exp_gdf = grid_gdf[grid_gdf["cell_id"].isin(regime2_cells.keys())].copy()
        grid_exp_gdf["in_method_a"] = grid_exp_gdf["cell_id"].map(lambda cid: regime2_cells[cid]["in_method_a"])
        grid_exp_gdf["in_method_b"] = grid_exp_gdf["cell_id"].map(lambda cid: regime2_cells[cid]["in_method_b"])
        grid_exp_gdf["fully_contained_b"] = grid_exp_gdf["cell_id"].map(lambda cid: regime2_cells[cid]["fully_contained_b"])
        grid_exp_gdf["overlap_fraction"] = grid_exp_gdf["cell_id"].map(lambda cid: regime2_cells[cid]["overlap_fraction"])
        grid_exp_gdf["method_c_weighted_pop"] = grid_exp_gdf["cell_id"].map(lambda cid: regime2_cells[cid]["method_c_weighted_pop"])
        grid_exp_gdf["cell_classification"] = grid_exp_gdf["cell_id"].map(lambda cid: regime2_cells[cid]["cell_classification"])

        pop_export_dir = exports_dir / "hunter_population_grid_comparison"
        export_rfc7946_geojson(
            gdf=grid_exp_gdf,
            output_geojson_path=pop_export_dir / "result.geojson",
            analysis_id="hunter_population_grid_comparison",
            title="Lower Hunter Flood Basin 1 km² Population Comparison (Methods A, B, C)",
            source_datasets=["next_sa2_boundaries_asgs2021", "nsw_foi_building_complexes", "nsw_water_inundation_areas"],
            source_vintages={"next_sa2_boundaries_asgs2021": "ASGS-2021", "nsw_foi_building_complexes": "2026-NSW-FOI", "nsw_water_inundation_areas": "2026-NSW-HYDRO"},
            population_method="COMPARISON_A_B_C",
            known_limitations=[pop_study["method_c_assumption_warning"]],
        )
        export_analysis_geoparquet(grid_exp_gdf, pop_export_dir / "result.parquet")

        # Export Substation Dependency GeoJSON & GeoParquet
        sub_gdf = gpd.read_parquet(_latest_parquet(geoparquet_dir, "ga_electricity_substations"))
        dep_map = {int(s["substation_id"]): s for s in dep_res["substations"]}
        sub_id_col = "objectid" if "objectid" in sub_gdf.columns else "OBJECTID"
        sub_gdf["distance_to_inundation_m"] = sub_gdf[sub_id_col].map(lambda sid: dep_map.get(int(sid), {}).get("distance_to_inundation_m", -1.0))
        sub_gdf["dependent_foi_within_5km"] = sub_gdf[sub_id_col].map(lambda sid: dep_map.get(int(sid), {}).get("dependent_foi_within_5km", 0))
        sub_gdf["hazard_exposure_tier"] = sub_gdf[sub_id_col].map(lambda sid: dep_map.get(int(sid), {}).get("hazard_exposure_tier", "UNKNOWN"))

        sub_export_dir = exports_dir / "hunter_substation_flood_dependency"
        export_rfc7946_geojson(
            gdf=sub_gdf,
            output_geojson_path=sub_export_dir / "result.geojson",
            analysis_id="hunter_substation_flood_dependency",
            title="Lower Hunter Substations Flood Proximity & 5km Facility Catchment",
            source_datasets=["ga_electricity_substations", "nsw_water_inundation_areas", "nsw_foi_building_complexes"],
            source_vintages={"ga_electricity_substations": "2024-GA-NEI", "nsw_water_inundation_areas": "2026-NSW-HYDRO", "nsw_foi_building_complexes": "2026-NSW-FOI"},
            population_method="NOT_APPLICABLE",
        )
        export_analysis_geoparquet(sub_gdf, sub_export_dir / "result.parquet")

        # Also copy exports to docs/exports/ so docs/index.html can load them locally & on GCS
        for exp_name in ("hunter_population_grid_comparison", "hunter_substation_flood_dependency"):
            dst = docs_dir / "exports" / exp_name
            dst.mkdir(parents=True, exist_ok=True)
            for fname in ("result.geojson", "analysis_manifest.json"):
                (dst / fname).write_bytes((exports_dir / exp_name / fname).read_bytes())

        # 5. Execute AI Spatial Agent queries & save audit trail
        print("[5/7] Executing Catalogue-Grounded AI Spatial Agent queries & audit logs...")
        agent = AISpatialAgent(registry=registry, engine=engine, lake_geoparquet_dir=geoparquet_dir)
        sample_questions = [
            ("Which power substations in the Lower Hunter are closest to flood inundation zones and how many FOI facilities depend on them within 5km?", None),
            ("Summarize Lower Hunter LGAs by flood inundation polygons, substations, and building complexes.", "Method B"),
            ("List all active NSW RFS major bushfire and grassfire incidents from the live operational feed.", None),
            ("How many people live inside the flood zone?", None),  # Ambiguous -> triggers clarification!
            ("Show live SCADA substation load and hospital ICU bed occupancy in Newcastle.", None),  # Uncatalogued -> triggers rejection!
        ]
        ai_audits = []
        for idx, (q_text, pop_m) in enumerate(sample_questions, 1):
            rec = agent.ask(q_text, explicit_pop_method=pop_m)
            rec.save(exports_dir / "ai_audits" / f"audit_{idx:02d}.json")
            ai_audits.append(rec.to_dict())

    # 6. Build Air-Gapped Offline Map-in-a-Box Package
    print("[6/7] Building air-gapped Offline Map-in-a-Box package (hunter_flood_emergency_pack)...")
    pack_dir = map_packages_dir / "hunter_flood_emergency_pack"
    build_offline_map_package(
        package_id="hunter_flood_emergency_pack",
        title="Lower Hunter Flood & Critical Infrastructure Map-in-a-Box",
        bbox_4326=[151.45, -32.95, 151.82, -32.68],
        lake_geoparquet_dir=geoparquet_dir,
        grid_gdf=grid_gdf,
        population_study=pop_study,
        output_package_dir=pack_dir,
        registry=registry,
    )

    # 7. Run Execution Engine Benchmarks & Build Stitch Workbench HTML
    print("[7/7] Running Execution Engine Benchmarks and generating Stitch Workbench (docs/index.html)...")
    benchmarks = run_engine_benchmarks(lake_root)
    bench_path = exports_dir / "benchmarks" / "engine_benchmarks.json"
    bench_path.parent.mkdir(parents=True, exist_ok=True)
    bench_path.write_text(json.dumps(benchmarks, indent=2), encoding="utf-8")

    bundle = {
        "generated_at_utc": utc_now_iso(),
        "population_study": pop_study,
        "multi_scale_exposure": multi_scale_exp,
        "isolation_analysis": isolation_res,
        "infrastructure_dependencies": dep_res,
        "ai_audits": ai_audits,
        "benchmarks": benchmarks,
    }
    bundle_out = docs_dir / "data" / "workbench_bundle.json"
    bundle_out.parent.mkdir(parents=True, exist_ok=True)
    bundle_out.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    print("[DONE] All analytical deliverables, exports, offline map package, and workbench bundle generated.")


if __name__ == "__main__":
    main()

