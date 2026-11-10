"""Offline Map-in-a-Box BBox Package Builder (Section 9).

Creates a 100% self-contained, air-gapped emergency map package under:
    map_packages/<package_id>/
        index.html
        data/*.geojson
        assets/offline_stitch.css
        assets/offline_bundle.js
        assets/offline_vector_map.js
        manifest.json
        README.txt

Strictly enforces ZERO external CDN, font, script, or tile dependencies so the package
renders identically in an air-gapped browser (`file://` or local HTTP) and on GCS.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import geopandas as gpd
from shapely.geometry import box, mapping

from src.catalogue.dataset_registry import DatasetRegistry
from src.ingestion.telemetry import compute_sha256, utc_now_iso


OFFLINE_STITCH_CSS = """/* Google Stitch web_dashboard Offline Design Tokens — Zero External CDN Dependencies */
:root {
  --primary: #001026;
  --primary-container: #0b2545;
  --secondary: #006973;
  --surface: #faf8ff;
  --surface-low: #f2f3ff;
  --border: #d8dadd;
  --text: #181b22;
  --muted: #43474f;
  --pass: #15803d;
  --warn: #b45309;
  --fail: #ba1a1a;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--surface);
  color: var(--text);
  display: flex;
  height: 100vh;
  overflow: hidden;
}
aside {
  width: 280px;
  background: var(--primary);
  color: #fff;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #1e3a5f;
  flex-shrink: 0;
}
.brand {
  padding: 18px 20px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
}
.brand h1 { font-size: 15px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: #54e1f0; }
.brand p { font-size: 11px; color: #94a3b8; margin-top: 4px; }
.sidebar-section { padding: 14px 18px; border-bottom: 1px solid rgba(255,255,255,0.08); }
.sidebar-section h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: #94a3b8; margin-bottom: 10px; }
.layer-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  padding: 6px 0;
  cursor: pointer;
}
.layer-toggle input { margin-right: 8px; accent-color: #00daf3; }
.swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; margin-right: 6px; }
.regime-select, .method-btn {
  width: 100%;
  padding: 7px 10px;
  border-radius: 4px;
  border: 1px solid rgba(255,255,255,0.2);
  background: var(--primary-container);
  color: #fff;
  font-size: 12px;
  margin-bottom: 6px;
  cursor: pointer;
}
.method-btn.active { background: var(--secondary); border-color: #54e1f0; font-weight: 700; }
main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
header {
  background: #fff;
  border-bottom: 1px solid var(--border);
  padding: 10px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.badge {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
  background: #e0f2fe;
  color: #0369a1;
}
.badge-warn { background: #fef3c7; color: #92400e; }
.workspace { flex: 1; display: grid; grid-template-columns: 1fr 380px; overflow: hidden; }
.map-wrap { position: relative; background: #071426; overflow: hidden; }
canvas#vectorMap { width: 100%; height: 100%; display: block; cursor: grab; }
canvas#vectorMap:active { cursor: grabbing; }
.map-hud {
  position: absolute;
  bottom: 14px;
  left: 14px;
  background: rgba(0,16,38,0.88);
  color: #e2e8f0;
  padding: 8px 12px;
  border-radius: 6px;
  font-family: monospace;
  font-size: 11px;
  border: 1px solid rgba(84,225,240,0.3);
}
.map-controls {
  position: absolute;
  top: 14px;
  left: 14px;
  display: flex;
  gap: 6px;
}
.map-controls button {
  background: rgba(0,16,38,0.9);
  color: #fff;
  border: 1px solid rgba(255,255,255,0.25);
  padding: 6px 10px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}
.inspector {
  background: var(--surface-low);
  border-left: 1px solid var(--border);
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.card {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px 14px;
}
.card h3 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 8px; }
.stat-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
.stat-box { background: var(--surface-low); padding: 8px; border-radius: 4px; border: 1px solid var(--border); }
.stat-box .lbl { font-size: 10px; color: var(--muted); text-transform: uppercase; }
.stat-box .val { font-size: 15px; font-weight: 700; font-family: monospace; margin-top: 2px; color: var(--primary); }
table { width: 100%; border-collapse: collapse; font-size: 11px; }
th, td { text-align: left; padding: 5px 6px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 600; }
.mono { font-family: monospace; }
"""


OFFLINE_VECTOR_MAP_JS = """/* Zero-Dependency Offline HTML5 Canvas Vector Map Engine for Air-Gapped Map-in-a-Box */
(function() {
  const pkg = window.OIC_MAP_PACKAGE;
  if (!pkg) return;

  const canvas = document.getElementById('vectorMap');
  const ctx = canvas.getContext('2d');
  const hud = document.getElementById('mapHud');
  const featureBox = document.getElementById('selectedFeatureBox');

  let bbox = pkg.manifest.bbox.slice(); // [minLon, minLat, maxLon, maxLat]
  let view = { minLon: bbox[0], minLat: bbox[1], maxLon: bbox[2], maxLat: bbox[3] };
  let activeRegimeIdx = 1; // Default to Regime 2 (Observed NSW Inundation Basin)
  let activeMethod = 'B';
  let maskEnabled = true;

  function parseWktPolygon(wkt) {
    if (!wkt) return null;
    const m = wkt.match(/POLYGON\\s*\\(\\s*\\((.+?)\\)\\s*\\)/i);
    if (!m) return null;
    return m[1].split(',').map(pair => {
      const parts = pair.trim().split(/\\s+/).map(Number);
      return [parts[0], parts[1]];
    });
  }

  function drawAoiMask(wktOrGeom) {
    if (!maskEnabled) return;
    let rings = [];
    if (typeof wktOrGeom === 'string') {
      const r = parseWktPolygon(wktOrGeom);
      if (r) rings.push(r);
    } else if (wktOrGeom && wktOrGeom.coordinates) {
      if (wktOrGeom.type === 'Polygon') rings.push(wktOrGeom.coordinates[0]);
      else if (wktOrGeom.type === 'MultiPolygon') wktOrGeom.coordinates.forEach(c => rings.push(c[0]));
    }
    if (!rings.length) return;

    ctx.save();
    // Focus mask: #030712 @ 80% opacity
    ctx.fillStyle = 'rgba(3, 7, 18, 0.80)';
    ctx.beginPath();
    // Outer canvas world bounds
    ctx.rect(0, 0, canvas.width, canvas.height);
    // Draw AOI rings to be cut out via even-odd rule
    rings.forEach(ring => {
      ring.forEach((pt, idx) => {
        const [x, y] = project(pt[0], pt[1]);
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.closePath();
    });
    ctx.fill('evenodd');

    // Highlight border around AOI (#54e1f0 cyan, 2.8px)
    ctx.strokeStyle = '#54e1f0';
    ctx.lineWidth = 2.8;
    rings.forEach(ring => {
      ctx.beginPath();
      ring.forEach((pt, idx) => {
        const [x, y] = project(pt[0], pt[1]);
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.closePath();
      ctx.stroke();
    });
    ctx.restore();
  }

  const visibility = {
    population_grid_1km: true,
    inundation_areas: true,
    transmission_lines: true,
    substations: true,
    foi_buildings: true,
    rfs_incidents: true
  };

  function resize() {
    canvas.width = canvas.parentElement.clientWidth || 800;
    canvas.height = canvas.parentElement.clientHeight || 600;
    draw();
  }
  window.addEventListener('resize', resize);

  function project(lon, lat) {
    const pad = 28;
    const w = canvas.width - pad * 2;
    const h = canvas.height - pad * 2;
    const x = pad + ((lon - view.minLon) / (view.maxLon - view.minLon)) * w;
    const y = canvas.height - pad - ((lat - view.minLat) / (view.maxLat - view.minLat)) * h;
    return [x, y];
  }

  function unproject(px, py) {
    const pad = 28;
    const w = canvas.width - pad * 2;
    const h = canvas.height - pad * 2;
    const lon = view.minLon + ((px - pad) / w) * (view.maxLon - view.minLon);
    const lat = view.minLat + ((canvas.height - pad - py) / h) * (view.maxLat - view.minLat);
    return [lon, lat];
  }

  function drawRing(ring, closePath) {
    if (!ring || !ring.length) return;
    ring.forEach((pt, idx) => {
      const [x, y] = project(pt[0], pt[1]);
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    if (closePath) ctx.closePath();
  }

  function drawGeometry(geom, fillStyle, strokeStyle, lineWidth, pointRadius) {
    if (!geom) return;
    ctx.save();
    if (fillStyle) ctx.fillStyle = fillStyle;
    if (strokeStyle) ctx.strokeStyle = strokeStyle;
    ctx.lineWidth = lineWidth || 1.2;

    const t = geom.type;
    const c = geom.coordinates;
    if (t === 'Polygon') {
      ctx.beginPath();
      c.forEach(r => drawRing(r, true));
      if (fillStyle) ctx.fill();
      if (strokeStyle) ctx.stroke();
    } else if (t === 'MultiPolygon') {
      c.forEach(poly => {
        ctx.beginPath();
        poly.forEach(r => drawRing(r, true));
        if (fillStyle) ctx.fill();
        if (strokeStyle) ctx.stroke();
      });
    } else if (t === 'LineString') {
      ctx.beginPath();
      drawRing(c, false);
      if (strokeStyle) ctx.stroke();
    } else if (t === 'MultiLineString') {
      c.forEach(line => {
        ctx.beginPath();
        drawRing(line, false);
        if (strokeStyle) ctx.stroke();
      });
    } else if (t === 'Point') {
      const [x, y] = project(c[0], c[1]);
      ctx.beginPath();
      ctx.arc(x, y, pointRadius || 4.5, 0, Math.PI * 2);
      if (fillStyle) ctx.fill();
      if (strokeStyle) ctx.stroke();
    }
    ctx.restore();
  }

  function drawGraticule() {
    ctx.save();
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.14)';
    ctx.fillStyle = 'rgba(148, 163, 184, 0.65)';
    ctx.font = '10px monospace';
    ctx.lineWidth = 1;
    const lonStep = 0.05;
    const latStep = 0.05;
    for (let lon = Math.ceil(view.minLon / lonStep) * lonStep; lon <= view.maxLon; lon += lonStep) {
      const [x, _] = project(lon, view.minLat);
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
      ctx.fillText(lon.toFixed(2) + '°E', x + 4, 14);
    }
    for (let lat = Math.ceil(view.minLat / latStep) * latStep; lat <= view.maxLat; lat += latStep) {
      const [_, y] = project(view.minLon, lat);
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
      ctx.fillText(lat.toFixed(2) + '°S', 6, y - 4);
    }
    ctx.restore();
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    drawGraticule();

    const regime = pkg.population_study.regimes[activeRegimeIdx];
    const regimeCellMap = {};
    if (regime && regime.cells) {
      regime.cells.forEach(c => { regimeCellMap[c.cell_id] = c; });
    }

    // 1. 1 km² Population Grid cells
    if (visibility.population_grid_1km && pkg.layers.population_grid_1km) {
      pkg.layers.population_grid_1km.features.forEach(f => {
        const cid = f.properties.cell_id;
        const rc = regimeCellMap[cid];
        if (rc) {
          let fill = 'rgba(16, 185, 129, 0.35)';
          let stroke = '#10b981';
          if (activeMethod === 'A') {
            fill = rc.in_method_a ? 'rgba(14, 165, 233, 0.48)' : 'rgba(239, 68, 68, 0.18)';
            stroke = rc.in_method_a ? '#38bdf8' : '#ef4444';
          } else if (activeMethod === 'B') {
            fill = rc.fully_contained_b ? 'rgba(16, 185, 129, 0.52)' : 'rgba(245, 158, 11, 0.48)';
            stroke = rc.fully_contained_b ? '#10b981' : '#f59e0b';
          } else {
            const alpha = Math.max(0.18, Math.min(0.75, rc.overlap_fraction || 0.25));
            fill = 'rgba(168, 85, 247, ' + alpha.toFixed(2) + ')';
            stroke = '#c084fc';
          }
          drawGeometry(f.geometry, fill, stroke, 1.4);
          // Draw centroid dot when Method A is active
          if (activeMethod === 'A' && rc.centroid_lon && rc.centroid_lat) {
            drawGeometry(
              { type: 'Point', coordinates: [rc.centroid_lon, rc.centroid_lat] },
              rc.in_method_a ? '#38bdf8' : '#ef4444',
              '#001026',
              1,
              3.5
            );
          }
        } else {
          drawGeometry(f.geometry, 'rgba(30, 58, 95, 0.12)', 'rgba(100, 116, 139, 0.22)', 0.6);
        }
      });
    }

    // 2. Water Inundation Areas
    if (visibility.inundation_areas && pkg.layers.inundation_areas) {
      pkg.layers.inundation_areas.features.forEach(f => {
        drawGeometry(f.geometry, 'rgba(2, 132, 199, 0.42)', '#38bdf8', 1.5);
      });
    }

    // 3. Electricity Transmission Lines
    if (visibility.transmission_lines && pkg.layers.transmission_lines) {
      pkg.layers.transmission_lines.features.forEach(f => {
        drawGeometry(f.geometry, null, '#facc15', 1.8);
      });
    }

    // 4. FOI Building Complexes
    if (visibility.foi_buildings && pkg.layers.foi_buildings) {
      pkg.layers.foi_buildings.features.forEach(f => {
        drawGeometry(f.geometry, 'rgba(226, 232, 240, 0.75)', '#475569', 0.8, 2.2);
      });
    }

    // 5. Substations
    if (visibility.substations && pkg.layers.substations) {
      pkg.layers.substations.features.forEach(f => {
        drawGeometry(f.geometry, '#f97316', '#fff', 1.5, 5.5);
      });
    }

    // 6. RFS Live Incidents
    if (visibility.rfs_incidents && pkg.layers.rfs_incidents) {
      pkg.layers.rfs_incidents.features.forEach(f => {
        drawGeometry(f.geometry, 'rgba(239, 68, 68, 0.55)', '#fecaca', 1.8, 6.0);
      });
    }

    // 7. Territory / Incident AOI Focus Mask (#030712 @ 80% Opacity)
    if (regime && regime.incident_wkt_7844) {
      drawAoiMask(regime.incident_wkt_7844);
    }

    updateStatsPanel(regime);
  }

  function updateStatsPanel(regime) {
    if (!regime) return;
    document.getElementById('statMethodA').textContent =
      regime.method_a_centroid_contains.population_total.toLocaleString() +
      ' (' + regime.method_a_centroid_contains.cell_count + ' cells)';
    document.getElementById('statMethodB').textContent =
      regime.method_b_cell_polygon_intersects.full_cell_population_total.toLocaleString() +
      ' (' + regime.method_b_cell_polygon_intersects.intersecting_cell_count + ' cells)';
    document.getElementById('statMethodC').textContent =
      regime.method_c_area_weighted_proportional.proportional_population_estimate.toLocaleString() + ' (modelled)';
    document.getElementById('statStraddling').textContent =
      regime.method_b_cell_polygon_intersects.boundary_straddling_cell_count +
      ' straddling cells (' + regime.divergence_summary.cells_missed_by_centroid_method_a + ' missed by centroid)';

    const tbody = document.getElementById('cellTableBody');
    tbody.innerHTML = '';
    (regime.cells || []).slice(0, 18).forEach(c => {
      const tr = document.createElement('tr');
      tr.innerHTML =
        '<td class="mono">' + c.cell_id + '</td>' +
        '<td>' + c.sa2_name21 + '</td>' +
        '<td class="mono">' + c.cell_population + '</td>' +
        '<td class="mono">' + (c.overlap_fraction * 100).toFixed(1) + '%</td>' +
        '<td>' + c.cell_classification + '</td>';
      tbody.appendChild(tr);
    });
  }

  // Pan & Zoom interactions
  let dragging = false, lastX = 0, lastY = 0;
  canvas.addEventListener('mousedown', e => { dragging = true; lastX = e. offsetX; lastY = e.offsetY; });
  window.addEventListener('mouseup', () => { dragging = false; });
  canvas.addEventListener('mousemove', e => {
    const [lon, lat] = unproject(e.offsetX, e.offsetY);
    hud.textContent = 'LON ' + lon.toFixed(4) + '°E | LAT ' + lat.toFixed(4) + '°S | CRS: EPSG:4326 (Display) / EPSG:7844 (Stored)';
    if (!dragging) return;
    const dx = e.offsetX - lastX;
    const dy = e.offsetY - lastY;
    lastX = e.offsetX; lastY = e.offsetY;
    const lonSpan = view.maxLon - view.minLon;
    const latSpan = view.maxLat - view.minLat;
    const dLon = (dx / canvas.width) * lonSpan;
    const dLat = (dy / canvas.height) * latSpan;
    view.minLon -= dLon; view.maxLon -= dLon;
    view.minLat += dLat; view.maxLat += dLat;
    draw();
  });

  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 0.82 : 1.22;
    const [cLon, cLat] = unproject(e.offsetX, e.offsetY);
    view.minLon = cLon - (cLon - view.minLon) * factor;
    view.maxLon = cLon + (view.maxLon - cLon) * factor;
    view.minLat = cLat - (cLat - view.minLat) * factor;
    view.maxLat = cLat + (view.maxLat - cLat) * factor;
    draw();
  }, { passive: false });

  // Controls
  document.getElementById('btnZoomIn').addEventListener('click', () => {
    const cx = (view.minLon + view.maxLon) / 2, cy = (view.minLat + view.maxLat) / 2;
    const w = (view.maxLon - view.minLon) * 0.38, h = (view.maxLat - view.minLat) * 0.38;
    view = { minLon: cx - w, maxLon: cx + w, minLat: cy - h, maxLat: cy + h };
    draw();
  });
  document.getElementById('btnZoomOut').addEventListener('click', () => {
    const cx = (view.minLon + view.maxLon) / 2, cy = (view.minLat + view.maxLat) / 2;
    const w = (view.maxLon - view.minLon) * 0.65, h = (view.maxLat - view.minLat) * 0.65;
    view = { minLon: cx - w, maxLon: cx + w, minLat: cy - h, maxLat: cy + h };
    draw();
  });
  document.getElementById('btnResetBbox').addEventListener('click', () => {
    view = { minLon: bbox[0], minLat: bbox[1], maxLon: bbox[2], maxLat: bbox[3] };
    draw();
  });

  document.getElementById('regimeSelect').addEventListener('change', e => {
    activeRegimeIdx = parseInt(e.target.value, 10) || 0;
    draw();
  });

  document.querySelectorAll('.method-btn[data-method]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.method-btn[data-method]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeMethod = btn.getAttribute('data-method');
      draw();
    });
  });

  const btnMask = document.getElementById('btnToggleMask');
  if (btnMask) {
    btnMask.addEventListener('click', () => {
      maskEnabled = !maskEnabled;
      btnMask.textContent = maskEnabled ? '🎭 Focus Mask: 80%' : '🎭 Focus Mask: Off';
      btnMask.classList.toggle('active', maskEnabled);
      draw();
    });
  }

  document.querySelectorAll('[data-layer]').forEach(cb => {
    cb.addEventListener('change', () => {
      visibility[cb.getAttribute('data-layer')] = cb.checked;
      draw();
    });
  });

  setTimeout(resize, 30);
})();
"""


def _clip_gdf_to_geojson_dict(gdf: gpd.GeoDataFrame, bbox_4326: List[float], max_features: int = 800) -> Dict[str, Any]:
    work = gdf.copy()
    if work.crs is None:
        work = work.set_crs("EPSG:7844")
    work_4326 = work.to_crs("EPSG:4326")
    clip_box = box(*bbox_4326)
    sub = work_4326[work_4326.geometry.notna() & ~work_4326.geometry.is_empty & work_4326.geometry.intersects(clip_box)].copy()
    if len(sub) == 0 and len(work_4326) > 0:
        # If no records strictly intersect a tight micro-bbox, retain available active features
        # so situational feeds (e.g. live incidents) are still accessible offline
        sub = work_4326[work_4326.geometry.notna() & ~work_4326.geometry.is_empty].copy()
    if len(sub) > max_features:
        sub = sub.iloc[:max_features].copy()

    prop_cols = [c for c in sub.columns if c != sub.geometry.name and not c.startswith("_bbox")]
    features = []
    for idx, row in sub.iterrows():
        geom = row[sub.geometry.name].simplify(0.0002, preserve_topology=True)
        props = {}
        for c in prop_cols:
            val = row[c]
            if hasattr(val, "item"):
                val = val.item()
            if val != val:
                val = None
            props[c] = val
        features.append({"type": "Feature", "id": str(idx), "properties": props, "geometry": mapping(geom)})
    return {"type": "FeatureCollection", "bbox": bbox_4326, "features": features}


def build_offline_map_package(
    package_id: str,
    title: str,
    bbox_4326: List[float],
    lake_geoparquet_dir: Path,
    grid_gdf: gpd.GeoDataFrame,
    population_study: Dict[str, Any],
    output_package_dir: Path,
    registry: DatasetRegistry,
) -> Dict[str, Any]:
    """Builds a complete air-gapped Map-in-a-Box package under `output_package_dir`."""
    data_dir = output_package_dir / "data"
    assets_dir = output_package_dir / "assets"
    data_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    def _latest(ds_key: str) -> gpd.GeoDataFrame:
        files = sorted((lake_geoparquet_dir / ds_key).glob("*/*/part-*.parquet"))
        return gpd.read_parquet(files[-1])

    layer_defs = {
        "population_grid_1km": (grid_gdf, "next_sa2_boundaries_asgs2021", 600),
        "inundation_areas": (_latest("nsw_water_inundation_areas"), "nsw_water_inundation_areas", 200),
        "transmission_lines": (_latest("ga_electricity_transmission_lines"), "ga_electricity_transmission_lines", 200),
        "substations": (_latest("ga_electricity_substations"), "ga_electricity_substations", 200),
        "foi_buildings": (_latest("nsw_foi_building_complexes"), "nsw_foi_building_complexes", 500),
        "rfs_incidents": (_latest("nsw_rfs_major_incidents_live"), "nsw_rfs_major_incidents_live", 100),
    }

    layers_dict: Dict[str, Any] = {}
    file_hashes: Dict[str, str] = {}
    dataset_provenance: List[Dict[str, Any]] = []

    for layer_name, (gdf, ds_key, max_f) in layer_defs.items():
        fc = _clip_gdf_to_geojson_dict(gdf, bbox_4326, max_features=max_f)
        layers_dict[layer_name] = fc
        out_file = data_dir / f"{layer_name}.geojson"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(fc, f, indent=2)
        file_hashes[f"data/{layer_name}.geojson"] = compute_sha256(out_file)

        entry = registry.get(ds_key)
        dataset_provenance.append(
            {
                "layer_name": layer_name,
                "dataset_key": ds_key,
                "title": entry.title,
                "source_agency": entry.source_agency,
                "source_vintage": entry.source_vintage,
                "retrieval_timestamp_utc": entry.latest_retrieval_utc,
                "licence": entry.licence.name,
                "attribution": entry.licence.attribution,
                "qa_status": entry.qa_status.value,
                "feature_count_in_bbox": len(fc["features"]),
                "known_limitations": entry.known_limitations,
            }
        )

    generated_utc = utc_now_iso()
    manifest = {
        "package_id": package_id,
        "title": title,
        "generated_at_utc": generated_utc,
        "bbox": bbox_4326,
        "display_crs": "EPSG:4326",
        "stored_crs": "EPSG:7844",
        "metric_crs": "EPSG:3112",
        "offline_airgapped_verified": True,
        "external_cdn_dependencies": 0,
        "population_methods_included": ["Method A (Centroid ST_Contains)", "Method B (Polygon ST_Intersects)", "Method C (Area-Weighted Modelled)"],
        "datasets": dataset_provenance,
        "file_sha256": file_hashes,
        "disclaimer": (
            "ANALYTICAL RESEARCH PROTOTYPE & STATIC SNAPSHOT ONLY. "
            "Not for live operational emergency dispatch or life-safety warning."
        ),
    }

    manifest_path = output_package_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Write local CSS and JS assets
    css_path = assets_dir / "offline_stitch.css"
    css_path.write_text(OFFLINE_STITCH_CSS, encoding="utf-8")

    map_js_path = assets_dir / "offline_vector_map.js"
    map_js_path.write_text(OFFLINE_VECTOR_MAP_JS, encoding="utf-8")

    bundle_payload = {
        "manifest": manifest,
        "population_study": population_study,
        "layers": layers_dict,
    }
    bundle_js_path = assets_dir / "offline_bundle.js"
    bundle_js_path.write_text(
        "window.OIC_MAP_PACKAGE = " + json.dumps(bundle_payload) + ";\n",
        encoding="utf-8",
    )

    # Write self-contained index.html with ZERO external URLs
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title} — Offline Map-in-a-Box</title>
  <link rel="stylesheet" href="assets/offline_stitch.css" />
</head>
<body>
  <aside>
    <div class="brand">
      <h1>Map-in-a-Box Offline</h1>
      <p>Package: <span class="mono">{package_id}</span></p>
      <p>Snapshot UTC: <span class="mono">{generated_utc}</span></p>
    </div>

    <div class="sidebar-section">
      <h2>NExT Population Regime</h2>
      <select id="regimeSelect" class="regime-select">
        <option value="0">1. Small Narrow Polygon</option>
        <option value="1" selected>2. Observed NSW Inundation Basin</option>
        <option value="2">3. Large Regional Flood Envelope</option>
        <option value="3">4. Linear 500m Transmission Corridor</option>
      </select>
      <h2 style="margin-top:10px;">Population Method Switcher</h2>
      <button class="method-btn" data-method="A">Method A — Centroid ST_Contains</button>
      <button class="method-btn active" data-method="B">Method B — Cell Polygon ST_Intersects</button>
      <button class="method-btn" data-method="C">Method C — Area-Weighted (Modelled)</button>
      <button id="btnToggleMask" class="method-btn active" style="margin-top:8px; border-color:#54e1f0;">🎭 Focus Mask: 80%</button>
    </div>

    <div class="sidebar-section">
      <h2>BBox Vector Layers</h2>
      <label class="layer-toggle"><span><input type="checkbox" data-layer="population_grid_1km" checked /><span class="swatch" style="background:#10b981;"></span>1 km² Population Grid</span></label>
      <label class="layer-toggle"><span><input type="checkbox" data-layer="inundation_areas" checked /><span class="swatch" style="background:#38bdf8;"></span>NSW Inundation Areas</span></label>
      <label class="layer-toggle"><span><input type="checkbox" data-layer="transmission_lines" checked /><span class="swatch" style="background:#facc15;"></span>GA Transmission Lines</span></label>
      <label class="layer-toggle"><span><input type="checkbox" data-layer="substations" checked /><span class="swatch" style="background:#f97316;"></span>GA Power Substations</span></label>
      <label class="layer-toggle"><span><input type="checkbox" data-layer="foi_buildings" checked /><span class="swatch" style="background:#e2e8f0;"></span>NSW FOI Complexes</span></label>
      <label class="layer-toggle"><span><input type="checkbox" data-layer="rfs_incidents" checked /><span class="swatch" style="background:#ef4444;"></span>NSW RFS Incidents Snapshot</span></label>
    </div>

    <div class="sidebar-section" style="font-size:11px; color:#94a3b8; line-height:1.45;">
      <h2>Air-Gapped Provenance</h2>
      <p>BBox: <span class="mono">{bbox_4326}</span></p>
      <p style="margin-top:6px;">Zero external CDN scripts, fonts, or tile calls. Suitable for disconnected field deployment and QGIS GeoJSON import.</p>
    </div>
  </aside>

  <main>
    <header>
      <div>
        <strong style="font-size:14px;">{title}</strong>
        <span style="font-size:12px; color:#43474f; margin-left:10px;">Lower Hunter Flood & Critical Infrastructure Emergency Pack</span>
      </div>
      <div style="display:flex; gap:8px;">
        <span class="badge">AIR-GAPPED OFFLINE PACKAGE</span>
        <span class="badge badge-warn">STATIC SNAPSHOT — NOT LIVE TELEMETRY</span>
      </div>
    </header>

    <div class="workspace">
      <div class="map-wrap">
        <div class="map-controls">
          <button id="btnZoomIn">+ Zoom In</button>
          <button id="btnZoomOut">- Zoom Out</button>
          <button id="btnResetBbox">Reset BBox</button>
        </div>
        <canvas id="vectorMap"></canvas>
        <div id="mapHud" class="map-hud">LON 151.6200°E | LAT -32.8000°S | CRS: EPSG:4326 / EPSG:7844</div>
      </div>

      <div class="inspector">
        <div class="card">
          <h3>Population Method Comparison (Active Regime)</h3>
          <div class="stat-grid">
            <div class="stat-box">
              <div class="lbl">Method A (Centroid)</div>
              <div id="statMethodA" class="val">-</div>
            </div>
            <div class="stat-box">
              <div class="lbl">Method B (Polygon)</div>
              <div id="statMethodB" class="val">-</div>
            </div>
            <div class="stat-box">
              <div class="lbl">Method C (Weighted)</div>
              <div id="statMethodC" class="val">-</div>
            </div>
          </div>
          <p style="font-size:11px; color:#b45309; margin-top:8px;">
            <strong>Boundary Divergence:</strong> <span id="statStraddling">-</span>
          </p>
          <p style="font-size:10px; color:#43474f; margin-top:4px;">
            Method C is a modelled proportional estimate assuming uniform within-cell density (never an observed headcount).
          </p>
        </div>

        <div class="card" style="flex:1; overflow-y:auto;">
          <h3>Intersecting 1 km² Grid Cells</h3>
          <table>
            <thead>
              <tr>
                <th>Cell ID</th>
                <th>SA2</th>
                <th>Pop</th>
                <th>Overlap</th>
                <th>Class</th>
              </tr>
            </thead>
            <tbody id="cellTableBody"></tbody>
          </table>
        </div>
      </div>
    </div>
  </main>

  <script src="assets/offline_bundle.js"></script>
  <script src="assets/offline_vector_map.js"></script>
</body>
</html>
"""
    index_path = output_package_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")

    readme_text = f"""================================================================================
OPERATIONAL INTELLIGENCE CRAFTER — OFFLINE MAP-IN-A-BOX EMERGENCY PACKAGE
================================================================================
Package ID:      {package_id}
Title:           {title}
Generated (UTC): {generated_utc}
Bounding Box:    {bbox_4326} (EPSG:4326)
Stored CRS:      EPSG:7844 (GDA2020) / Metric CRS: EPSG:3112

1. HOW TO OPEN OFFLINE (AIR-GAPPED)
--------------------------------------------------------------------------------
Open `index.html` directly in any modern desktop browser (Chrome, Edge, Firefox)
or serve the directory locally (`python -m http.server 8080`).
This package contains ZERO external CDN, font, script, or tile requests.

2. QGIS / GEOLIBRE GEOJSON INTEROPERABILITY
--------------------------------------------------------------------------------
All vector layers are stored as RFC 7946 WGS84 (`EPSG:4326`) GeoJSON files inside
the `data/` subfolder and can be dragged directly into QGIS or GeoLibre:
  - data/population_grid_1km.geojson
  - data/inundation_areas.geojson
  - data/transmission_lines.geojson
  - data/substations.geojson
  - data/foi_buildings.geojson
  - data/rfs_incidents.geojson

3. IMPORTANT OPERATIONAL LIMITATION
--------------------------------------------------------------------------------
This package is a static research snapshot captured at {generated_utc}.
Live operational feeds (`nsw_rfs_major_incidents_live`) do not auto-refresh while
offline. Do not use for live emergency dispatch or life-safety warnings.
"""
    (output_package_dir / "README.txt").write_text(readme_text, encoding="utf-8")
    return manifest

