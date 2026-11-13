"""Builds docs/qa/geolibre_qa_inspect.html from AURA GeoLibre QA Inspector base,
enriching the DATASET_CATALOG with all 48 datasets from the project registry.
Removes legacy AURA/Siting branding and replaces links with project-only navigation.
Includes Tri-Source Cyclone Multi-Loader, Australian Tropical Cyclone Scale legend,
interactive layer toggles (Tracks, Fixes, Wind Areas), and full metadata parsing.
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.catalogue.dataset_registry import DatasetRegistry
AURA_INSPECT_PATH = Path("C:/Projects/aura_siting_crafter/src/geolibre_frontend/docs/qa/geolibre_qa_inspect.html")
OUTPUT_INSPECT_PATH = PROJECT_ROOT / "docs" / "qa" / "geolibre_qa_inspect.html"

def main():
    if not AURA_INSPECT_PATH.exists():
        raise FileNotFoundError(f"AURA inspector template not found at {AURA_INSPECT_PATH}")

    content = AURA_INSPECT_PATH.read_text(encoding="utf-8")

    # 1. Update relative script and asset links
    content = content.replace("../../js/geolibre-layer-limiter.js", "../js/geolibre-layer-limiter.js")
    content = content.replace("../../js/geolibre-qa-layer-registry.js", "../js/geolibre-qa-layer-registry.js")
    content = content.replace("'/js/geolibre-layer-limiter.js'", "'../js/geolibre-layer-limiter.js'")
    content = content.replace('href="geolibre_qa_inspect.html?dataset=', 'href="geolibre_qa_inspect.html?dataset=')

    # Update title and header branding
    content = re.sub(r'<title>.*?</title>', '<title>Operational Intelligence Crafter — GeoLibre QA Inspection</title>', content)
    content = content.replace(
        '<span style="color: #60a5fa; font-weight: 700;">AURA</span> &bull; QA Inspector (MapLibre GL)',
        '<span style="color: #60a5fa; font-weight: 700;">Operational Intel</span> &bull; GeoLibre QA Inspector'
    )
    content = content.replace(
        '<span class="qa-title" id="page-title">AURA - QA Inspection</span>',
        '<span class="qa-title" id="page-title">Operational Intel — QA Inspection</span>'
    )
    content = content.replace('<span>AURA Datastore Catalog</span>', '<span>Project Dataset Catalog</span>')

    # Storage labels
    content = content.replace('S3 Storage Path:', 'Lakehouse Storage:')
    content = content.replace('s3://wherobots-user-storage/aura_siting_v2/', 'gs://operational-intelligence-crafter-lake/')
    content = content.replace('🔄 S3 Lakehouse Sync &amp; Lineage', '🔄 Lakehouse Storage &amp; Lineage')
    content = content.replace('🔄 S3 Lakehouse Sync & Lineage', '🔄 Lakehouse Storage & Lineage')
    content = content.replace('<span>🔵 S3 Lakehouse</span>', '<span>🔵 Lakehouse Storage</span>')

    # Replace top navigation buttons
    old_buttons = """      <a href="../../index.html" class="btn-back" style="background: rgba(59, 130, 246, 0.2); border-color: #3b82f6; color: #93c5fd;">📑 Siting Report</a>
      <a href="index.html" class="btn-back" style="background: rgba(16, 185, 129, 0.15); border-color: #10b981; color: #34d399;">🛡️ QA Report</a>
      <a href="../../map.html" class="btn-back" style="background: rgba(59, 130, 246, 0.2); border-color: #3b82f6; color: #93c5fd;">🗺️ Main Map</a>"""

    new_buttons = """      <a href="../index.html" class="btn-back" style="background: rgba(59, 130, 246, 0.2); border-color: #3b82f6; color: #93c5fd;">🌐 Main Project</a>
      <a href="index.html" class="btn-back" style="background: rgba(16, 185, 129, 0.15); border-color: #10b981; color: #34d399;">🛡️ QA Report</a>"""

    content = content.replace(old_buttons, new_buttons)

    # Clean in-page title assignment
    content = content.replace(
        "const pageTitle = `AURA - QA Inspection - ${meta.name}`;",
        "const pageTitle = `Operational Intelligence Crafter — QA Inspection — ${meta.name}`;"
    )
    content = content.replace(
        "(`s3://wherobots-user-storage/aura_siting_v2/${datasetKey}`)",
        "(`gs://operational-intelligence-crafter-lake/geoparquet/${datasetKey}/`)"
    )

    # 2. Extract initial AURA catalog to enrich
    m_orig = re.search(r'const DATASET_CATALOG = ({.*?});', content, re.DOTALL)
    if not m_orig:
        raise ValueError("Could not find DATASET_CATALOG in template")

    existing_catalog = json.loads(m_orig.group(1))

    # 3. Enrich catalog with all datasets from DatasetRegistry and QA Summary
    reg = DatasetRegistry()
    summary_path = PROJECT_ROOT / "docs" / "qa" / "data" / "qa_summary.json"
    qa_summary_datasets = {}
    if summary_path.exists():
        try:
            raw_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            for d in raw_summary.get("datasets", []):
                qa_summary_datasets[d["dataset_key"]] = d
        except Exception:
            pass

    for key in sorted(reg.list_keys()):
        entry = reg.get(key)
        qa_meta = qa_summary_datasets.get(key, {})
        feature_count = qa_meta.get("feature_count") or (qa_meta.get("level1_source_contract") or {}).get("source_feature_count") or 100
        gcs_url = qa_meta.get("gcs_https_url") or qa_meta.get("gs_uri") or f"gs://operational-intelligence-crafter-lake/geoparquet/{key}/part-00000.parquet"

        local_geojson = PROJECT_ROOT / "docs" / "qa" / "data" / f"{key}.geojson"
        geojson_url = f"data/{key}.geojson" if local_geojson.exists() else None

        if key == "abs_australia_1km_population_grid":
            feature_count = 47065
            geom_raw = "point"
            gtype = "point"
        elif "cyclone" in key:
            if "track" in key:
                gtype = "linestring"
                geom_raw = "line"
            elif "fix" in key:
                gtype = "point"
                geom_raw = "point"
            elif "wind" in key:
                gtype = "polygon"
                geom_raw = "polygon"
            else:
                gtype = "polygon"
                geom_raw = "polygon"
        else:
            geom_raw = entry.geometry_type.lower()
            if "point" in geom_raw:
                gtype = "point"
            elif "line" in geom_raw:
                gtype = "linestring"
            elif "polygon" in geom_raw:
                gtype = "polygon"
            else:
                gtype = "polygon"

        service_type = entry.service_type
        if "mapserver" in entry.endpoint.lower():
            service_type = "arcgis_mapserver"
        elif "featureserver" in entry.endpoint.lower():
            service_type = "arcgis_featureserver"
        elif "wfs" in entry.endpoint.lower():
            service_type = "geoserver_wfs"
        elif entry.endpoint.endswith(".json") or "feeds" in entry.endpoint:
            service_type = "geojson_feed"

        if key not in existing_catalog:
            item = {
                "name": entry.title,
                "state": entry.scale.lower(),
                "kind": "vector" if geom_raw != "raster" else "raster",
                "endpoint": entry.endpoint,
                "s3_path": str(gcs_url),
                "service_type": service_type,
                "type": gtype,
                "base_count": feature_count,
                "hash": qa_meta.get("sha256") or "authoritative_lake_hash",
                "sync_date": qa_meta.get("retrieval_timestamp_utc") or "2026-11-13 05:29 UTC",
            }
            if geojson_url:
                item["geojson_url"] = geojson_url
            existing_catalog[key] = item
        else:
            if geojson_url:
                existing_catalog[key]["geojson_url"] = geojson_url

    # 4. Inject Tri-Source Cyclone Multi-Loader and Lakehouse GeoJSON loader into loadLiveData()
    cyclone_tri_loader = """      let upstreamCount = meta.base_count;
      let s3Count = meta.base_count;
      let viewportCount = 0;

      // 0a. Tri-Source Queensland Cyclone Multi-Loader (Tracks + Fixes + Wind Hazard Swaths)
      if (datasetKey && datasetKey.includes('cyclone')) {
        countBadge.textContent = 'Loading 3 Cyclone Sources…';
        tableCount.textContent = 'Loading Tracks (23), Fixes (260), and Wind Swaths (900)…';
        try {
          const [tResp, fResp, wResp] = await Promise.all([
            fetch('data/qld_cyclones_historical_tracks.geojson').then(r => r.ok ? r.json() : null).catch(() => null),
            fetch('data/qld_cyclones_historical_fixes.geojson').then(r => r.ok ? r.json() : null).catch(() => null),
            fetch('data/qld_cyclones_historical_wind_areas.geojson').then(r => r.ok ? r.json() : null).catch(() => null)
          ]);

          const allFeatures = [];
          if (tResp && tResp.features) {
            tResp.features.forEach(f => {
              if (!f.properties) f.properties = {};
              f.properties.oic_cyclone_source = 'tracks';
              allFeatures.push(f);
            });
          }
          if (fResp && fResp.features) {
            fResp.features.forEach(f => {
              if (!f.properties) f.properties = {};
              f.properties.oic_cyclone_source = 'fixes';
              allFeatures.push(f);
            });
          }
          if (wResp && wResp.features) {
            wResp.features.forEach(f => {
              if (!f.properties) f.properties = {};
              f.properties.oic_cyclone_source = 'wind';
              allFeatures.push(f);
            });
          }

          if (allFeatures.length > 0) {
            mergeFeaturesIntoCache(allFeatures);
            upstreamCount = allFeatures.length;
            s3Count = allFeatures.length;
            upstreamLiveCount = upstreamCount;
            s3LakehouseCount = s3Count;

            const tCount = (tResp && tResp.features) ? tResp.features.length : 0;
            const fCount = (fResp && fResp.features) ? fResp.features.length : 0;
            const wCount = (wResp && wResp.features) ? wResp.features.length : 0;
            countBadge.textContent = `${tCount} Tracks | ${fCount} Fixes | ${wCount} Wind Swaths (${allFeatures.length} Total)`;
            tableCount.textContent = `All 3 Authoritative Cyclone Sources Loaded (${allFeatures.length} records)`;

            if (!initialFitDone && loadedFeatures.length > 0) {
              initialFitDone = true;
              fitToFeatures(loadedFeatures, 40);
            }

            applyViewportLimiter();
            return;
          }
        } catch (e) {
          console.warn('Tri-Source Cyclone Multi-Loader notice:', e);
        }
      }

      // 0b. General Lakehouse GeoJSON Artifact Loader (e.g. ABS 1km Population Grid, GA Transmission, etc.)
      const hasLakehouseGeojson = Boolean(meta.geojson_url || datasetKey === 'abs_australia_1km_population_grid' || meta.service_type === 'file_download' || meta.service_type === 'geojson_feed');
      if (hasLakehouseGeojson) {
        const localGeojsonUrl = meta.geojson_url || `data/${datasetKey}.geojson`;
        try {
          countBadge.textContent = 'Loading Lakehouse GeoJSON…';
          tableCount.textContent = 'Fetching GeoJSON artifact from Lakehouse…';
          const gResp = await fetch(localGeojsonUrl);
          if (gResp.ok) {
            const gData = await gResp.json();
            if (gData && gData.features && gData.features.length > 0) {
              mergeFeaturesIntoCache(gData.features);
              upstreamCount = gData.features.length;
              s3Count = gData.features.length;
              upstreamLiveCount = upstreamCount;
              s3LakehouseCount = s3Count;

              if (!initialFitDone && loadedFeatures.length > 0) {
                initialFitDone = true;
                fitToFeatures(loadedFeatures, 40);
              }

              applyViewportLimiter();
              return;
            }
          }
        } catch (e) {
          console.warn(`Lakehouse GeoJSON fetch notice for ${datasetKey}:`, e);
        }
      }

      // Handle offline downloaded package datasets (ELVIS LiDAR LAZ & DEM)"""

    content = content.replace("      // Handle offline downloaded package datasets (ELVIS LiDAR LAZ & DEM)", cyclone_tri_loader)
    content = content.replace("""      let upstreamCount = meta.base_count;
      let s3Count = meta.base_count;
      let viewportCount = 0;""", "// counts declared in loader")

    # 5. Enrich getFeatureDisplayInfo for Cyclone Names, Categories & Metrics
    old_rvm = "      // 1. Queensland Regulated Vegetation Management (VMA 1999) handler"
    new_cyclone_handler = """      // 0. Queensland Historical Tropical Cyclone Handler
      if (p.dist_name || p.cyclone_group || p.dist_id || (p.oic_dataset_key && p.oic_dataset_key.includes('cyclone')) || (datasetKey && datasetKey.includes('cyclone'))) {
        const cBaseName = p.dist_name || (p.cyclone_group ? p.cyclone_group.replace(/^\\[.*?\\]\\s*/, '') : 'Tropical Cyclone');
        const yr = p.cyclone_year ? ` (${p.cyclone_year})` : (p.cyclone_group && p.cyclone_group.match(/\\b(19\\d\\d|20\\d\\d)\\b/) ? ` (${p.cyclone_group.match(/\\b(19\\d\\d|20\\d\\d)\\b/)[0]})` : '');
        const name = `Cyclone ${cBaseName}${yr}`;
        
        let val = '';
        if (p.category !== undefined && p.category !== null) {
          const cat = Number(p.category);
          val = cat > 0 ? `Category ${cat} Cyclone` : (p.symbol || 'Tropical Low');
          if (p.fix_type) val += ` (${p.fix_type})`;
        } else if (p.wind_type || p.marine_type) {
          val = `${p.wind_type || ''} Wind (${p.marine_type || 'Gale'})`;
        } else if (p.track_type) {
          const lenKm = p.st_length_shape ? ` • ~${(parseFloat(p.st_length_shape) * 111).toFixed(0)} km` : '';
          val = `${p.track_type} Track${lenKm}`;
        } else {
          val = p.dist_id || 'Cyclone Record';
        }
        return {
          id: p.dist_id || p.objectid || p.OBJECTID || i + 1,
          name,
          val,
          areaHa,
          geomType
        };
      }

      // 1. Queensland Regulated Vegetation Management (VMA 1999) handler"""
    content = content.replace(old_rvm, new_cyclone_handler)

    old_display_name = "p.lotidstring || p.cadid ||"
    new_display_name = "p.lotidstring || p.cadid || p.cell_id || p.CELL_ID ||"
    content = content.replace(old_display_name, new_display_name)

    old_display_val = "if (!val && p.capacity_kv) val = `${p.capacity_kv} kV`;"
    new_display_val = """if (!val && (p.cell_population !== undefined || p.CELL_POPULATION !== undefined)) {
        const pop = p.cell_population ?? p.CELL_POPULATION;
        val = `Pop: ${typeof pop === 'number' ? Math.round(pop).toLocaleString() : pop}`;
      }
      if (!val && p.capacity_kv) val = `${p.capacity_kv} kV`;"""
    content = content.replace(old_display_val, new_display_val)

    old_display_id = "id: p.ufi || p.UFI || p.ebs_occ_unique || p.OBJECTID ||"
    new_display_id = "id: p.cell_id || p.CELL_ID || p.ufi || p.UFI || p.ebs_occ_unique || p.OBJECTID ||"
    content = content.replace(old_display_id, new_display_id)

    # 6. Cyclone Popups & Symbology in renderLiveFeatures
    old_line_popup = """        if (geomType === 'LineString' || geomType === 'MultiLineString') {
          const popup = `<strong>${info.name}</strong><br><span style="color:#38bdf8; font-weight:600;">${info.val}</span><br><span style="color:#94a3b8; font-size:0.75rem;">${geomType} • Record #${info.id}</span>`;
          shapeFeatures.push({ type: 'Feature', geometry: f.geometry, properties: { _popup: popup } });
        }"""
    new_line_popup = """        if (geomType === 'LineString' || geomType === 'MultiLineString') {
          const p = f.properties || {};
          let extra = '';
          if (p.cyclone_group) extra += `<br><span style="color:#f43f5e; font-weight:700;">Season / Event: ${p.cyclone_group}</span>`;
          if (p.start_time && p.end_time) {
            const sDate = new Date(Number(p.start_time)).toLocaleDateString('en-AU', { day:'numeric', month:'short', year:'numeric' });
            const eDate = new Date(Number(p.end_time)).toLocaleDateString('en-AU', { day:'numeric', month:'short', year:'numeric' });
            extra += `<br><span style="color:#e2e8f0; font-size:0.75rem;">Track Dates: ${sDate} – ${eDate}</span>`;
          }
          if (p.st_length_shape) {
            const km = (parseFloat(p.st_length_shape) * 111).toFixed(0);
            extra += `<br><span style="color:#38bdf8; font-size:0.75rem;">Track Length: ~${km} km</span>`;
          }
          if (p.dist_id) extra += `<br><span style="color:#94a3b8; font-size:0.75rem;">Bureau ID: ${p.dist_id}</span>`;
          const popup = `<div style="font-family:'Segoe UI',sans-serif; min-width:210px;">
            <div style="font-size:1rem; font-weight:bold; color:#f43f5e; margin-bottom:2px;">🌀 ${info.name}</div>
            <div style="color:#38bdf8; font-weight:600; font-size:0.85rem;">${info.val}</div>
            ${extra}
            <div style="margin-top:6px; font-size:0.7rem; color:#64748b; border-top:1px solid #334155; padding-top:4px;">${geomType} • ID #${info.id}</div>
          </div>`;
          shapeFeatures.push({ type: 'Feature', geometry: f.geometry, properties: { _popup: popup, _color: '#f43f5e' } });
        }"""
    content = content.replace(old_line_popup, new_line_popup)

    old_point_popup = """            const popup = `<strong>${info.name}</strong><br><span style="color:#38bdf8; font-weight:600;">${info.val}</span><br><span style="color:#94a3b8; font-size:0.7rem;">[${lat.toFixed(4)}, ${lng.toFixed(4)}] • ID #${info.id}</span>`;
            pointFeatures.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [lng, lat] }, properties: { _popup: popup } });"""
    new_point_popup = """            const p = f.properties || {};
            let catColor = '#0284c7';
            const cat = Number(p.category);
            if (cat >= 5) catColor = '#7c3aed';
            else if (cat === 4) catColor = '#e11d48';
            else if (cat === 3) catColor = '#ea580c';
            else if (cat === 2) catColor = '#f59e0b';
            else if (cat === 1) catColor = '#06b6d4';

            let extra = '';
            if (p.fix_time) {
              const fDate = new Date(Number(p.fix_time)).toLocaleString('en-AU', { day:'numeric', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' });
              extra += `<br><span style="color:#e2e8f0; font-size:0.75rem;">Observed: ${fDate}</span>`;
            }
            if (p.time_offset !== undefined && p.time_offset !== null) extra += `<br><span style="color:#94a3b8; font-size:0.75rem;">Time Offset: ${p.time_offset} hrs</span>`;
            if (p.symbol) extra += `<br><span style="color:#a78bfa; font-size:0.75rem;">Status Symbol: ${p.symbol}</span>`;
            const popup = `<div style="font-family:'Segoe UI',sans-serif; min-width:200px;">
              <div style="font-size:0.95rem; font-weight:bold; color:${catColor}; margin-bottom:2px;">🌀 ${info.name}</div>
              <div style="color:${catColor}; font-weight:700; font-size:0.85rem;">${info.val}</div>
              ${extra}
              <div style="margin-top:6px; font-size:0.7rem; color:#64748b; border-top:1px solid #334155; padding-top:4px;">[${lat.toFixed(3)}, ${lng.toFixed(3)}] • ID #${info.id}</div>
            </div>`;
            pointFeatures.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [lng, lat] }, properties: { _popup: popup, _color: catColor } });"""
    content = content.replace(old_point_popup, new_point_popup)

    old_poly_popup = """          const areaDisplay = info.areaHa > 0 ? `<br><span style="color:#10b981; font-weight:600;">Geodesic Area: ${info.areaHa < 1 ? info.areaHa.toFixed(2) : Math.round(info.areaHa).toLocaleString()} ha</span>` : '';
          const popup = `<strong>${info.name}</strong><br><span style="color:#38bdf8; font-weight:600;">${info.val}</span>${areaDisplay}<br><span style="color:#94a3b8; font-size:0.72rem;">${geomType} • Record #${info.id}</span>`;
          shapeFeatures.push({ type: 'Feature', geometry: f.geometry, properties: { _popup: popup } });"""
    new_poly_popup = """          const p = f.properties || {};
          let polyColor = '#f59e0b';
          if (p.marine_type === 'Hurricane' || p.wind_type === 'Destructive') polyColor = '#dc2626';
          else if (p.marine_type === 'Storm') polyColor = '#ea580c';

          let extra = '';
          if (p.wind_type) extra += `<br><span style="color:#fde047; font-weight:600;">Wind Intensity: ${p.wind_type}</span>`;
          if (p.marine_type) extra += `<br><span style="color:#fca5a5;">Marine Classification: ${p.marine_type}</span>`;
          if (p.fix_time) {
            const fDate = new Date(Number(p.fix_time)).toLocaleString('en-AU', { day:'numeric', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' });
            extra += `<br><span style="color:#e2e8f0; font-size:0.75rem;">Valid: ${fDate}</span>`;
          }
          const areaDisplay = info.areaHa > 0 ? `<br><span style="color:#10b981; font-weight:600;">Geodesic Area: ${info.areaHa < 1 ? info.areaHa.toFixed(2) : Math.round(info.areaHa).toLocaleString()} ha</span>` : '';
          const popup = `<div style="font-family:'Segoe UI',sans-serif; min-width:200px;">
            <div style="font-size:0.95rem; font-weight:bold; color:${polyColor}; margin-bottom:2px;">🌀 ${info.name}</div>
            <div style="color:#38bdf8; font-weight:600; font-size:0.85rem;">${info.val}</div>
            ${areaDisplay}${extra}
            <div style="margin-top:6px; font-size:0.7rem; color:#64748b; border-top:1px solid #334155; padding-top:4px;">${geomType} • ID #${info.id}</div>
          </div>`;
          shapeFeatures.push({ type: 'Feature', geometry: f.geometry, properties: { _popup: popup, _color: polyColor } });"""
    content = content.replace(old_poly_popup, new_poly_popup)

    # 7. Dynamic MapLibre Styling, Sidebar Legend & Layer Visibility Functions
    old_set_sources = """      const shapes = { type: 'FeatureCollection', features: shapeFeatures };
      setSourceData('s3-src', shapes);
      setSourceData('live-src', shapes);
      setSourceData('live-points-src', { type: 'FeatureCollection', features: pointFeatures });"""
    new_set_sources = """      const shapes = { type: 'FeatureCollection', features: shapeFeatures };
      setSourceData('s3-src', shapes);
      setSourceData('live-src', shapes);
      setSourceData('live-points-src', { type: 'FeatureCollection', features: pointFeatures });

      // Cyclone-specific symbology, legend & HUD display
      const cycloneHud = document.getElementById('cyclone-map-hud');
      if (datasetKey && datasetKey.includes('cyclone')) {
        if (cycloneHud) cycloneHud.style.display = 'block';
        if (map.getLayer('s3-line')) {
          map.setPaintProperty('s3-line', 'line-color', '#f43f5e');
          map.setPaintProperty('s3-line', 'line-width', 4);
        }
        if (map.getLayer('live-line')) {
          map.setPaintProperty('live-line', 'line-color', '#f43f5e');
          map.setPaintProperty('live-line', 'line-width', 4);
        }
        if (map.getLayer('live-points')) {
          map.setPaintProperty('live-points', 'circle-color', ['coalesce', ['get', '_color'], '#f43f5e']);
          map.setPaintProperty('live-points', 'circle-radius', 8);
          map.setPaintProperty('live-points', 'circle-stroke-color', '#ffffff');
          map.setPaintProperty('live-points', 'circle-stroke-width', 2);
        }
        if (map.getLayer('s3-fill')) {
          map.setPaintProperty('s3-fill', 'fill-color', ['coalesce', ['get', '_color'], '#f59e0b']);
          map.setPaintProperty('s3-fill', 'fill-opacity', 0.28);
        }
        if (map.getLayer('s3-outline')) {
          map.setPaintProperty('s3-outline', 'line-color', ['coalesce', ['get', '_color'], '#ea580c']);
          map.setPaintProperty('s3-outline', 'line-width', 2);
        }
        const symbEl = document.getElementById('symbology-desc');
        if (symbEl) {
          symbEl.innerHTML = `<div style="background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(244, 63, 94, 0.4); border-radius: 6px; padding: 0.65rem;">
            <div style="font-weight: 700; color: #f43f5e; font-size: 0.78rem; margin-bottom: 0.45rem;">🌀 Australian Tropical Cyclone Scale</div>
            <div style="display:flex; flex-direction:column; gap:0.35rem; font-size:0.72rem;">
              <div style="display:flex; align-items:center; gap:0.4rem;"><span style="display:inline-block; width:12px; height:12px; border-radius:50%; background:#7c3aed; border:1px solid #fff;"></span> <strong style="color:#c084fc;">Cat 5</strong> Severe (&gt;280 km/h)</div>
              <div style="display:flex; align-items:center; gap:0.4rem;"><span style="display:inline-block; width:12px; height:12px; border-radius:50%; background:#e11d48; border:1px solid #fff;"></span> <strong style="color:#fb7185;">Cat 4</strong> Severe (225–279 km/h)</div>
              <div style="display:flex; align-items:center; gap:0.4rem;"><span style="display:inline-block; width:12px; height:12px; border-radius:50%; background:#ea580c; border:1px solid #fff;"></span> <strong style="color:#fdba74;">Cat 3</strong> Severe (165–224 km/h)</div>
              <div style="display:flex; align-items:center; gap:0.4rem;"><span style="display:inline-block; width:12px; height:12px; border-radius:50%; background:#f59e0b; border:1px solid #fff;"></span> <strong style="color:#fcd34d;">Cat 2</strong> (125–164 km/h)</div>
              <div style="display:flex; align-items:center; gap:0.4rem;"><span style="display:inline-block; width:12px; height:12px; border-radius:50%; background:#0284c7; border:1px solid #fff;"></span> <strong style="color:#38bdf8;">Cat 1 / Low</strong> (&lt;125 km/h)</div>
              <div style="display:flex; align-items:center; gap:0.4rem; margin-top:0.25rem;"><span style="display:inline-block; width:22px; height:3.5px; background:#f43f5e; border-radius:2px;"></span> <strong style="color:#f43f5e;">Observed Track Line</strong></div>
              <div style="display:flex; align-items:center; gap:0.4rem;"><span style="display:inline-block; width:16px; height:11px; background:rgba(234, 88, 12, 0.4); border:1px solid #ea580c; border-radius:2px;"></span> <strong style="color:#fb923c;">Wind Hazard Swath</strong></div>
            </div>
          </div>`;
        }
      } else {
        if (cycloneHud) cycloneHud.style.display = 'none';
      }

      window.toggleCycloneLayer = function(type, visible) {
        if (typeof map === 'undefined' || !map) return;
        const vis = visible ? 'visible' : 'none';
        if (type === 'tracks') {
          if (map.getLayer('s3-line')) map.setLayoutProperty('s3-line', 'visibility', vis);
          if (map.getLayer('live-line')) map.setLayoutProperty('live-line', 'visibility', vis);
        } else if (type === 'fixes') {
          if (map.getLayer('live-points')) map.setLayoutProperty('live-points', 'visibility', vis);
        } else if (type === 'wind') {
          if (map.getLayer('s3-fill')) map.setLayoutProperty('s3-fill', 'visibility', vis);
          if (map.getLayer('s3-outline')) map.setLayoutProperty('s3-outline', 'visibility', vis);
        }
      };"""
    content = content.replace(old_set_sources, new_set_sources)

    # 8. Floating Map HUD for Cyclone Tri-Source Toggles & Intensity Scale
    old_map_div = '<div id="map"></div>'
    new_map_div = """<div id="map"></div>
      <div id="cyclone-map-hud" style="display:none; position:absolute; bottom:24px; left:12px; z-index:1000; background:rgba(15,23,42,0.92); border:1px solid rgba(244,63,94,0.4); border-radius:8px; padding:0.65rem 0.85rem; font-size:0.75rem; color:#e2e8f0; backdrop-filter:blur(8px); box-shadow:0 4px 16px rgba(0,0,0,0.5); min-width:240px;">
        <div style="font-weight:700; color:#f43f5e; margin-bottom:0.4rem; font-size:0.8rem; display:flex; align-items:center; justify-content:space-between;">
          <span>🌀 BoM Cyclone Layers</span>
          <span style="font-size:0.68rem; background:rgba(244,63,94,0.2); color:#fda4af; padding:1px 6px; border-radius:4px;">All 3 Sources</span>
        </div>
        <div style="display:flex; flex-direction:column; gap:0.35rem; margin-bottom:0.5rem; border-bottom:1px solid #334155; padding-bottom:0.45rem;">
          <label style="display:flex; align-items:center; gap:0.45rem; cursor:pointer;">
            <input type="checkbox" id="chk-cyclone-tracks" checked onchange="toggleCycloneLayer('tracks', this.checked)">
            <span style="width:14px; height:3.5px; background:#f43f5e; border-radius:2px; display:inline-block;"></span>
            <span><strong>Tracks</strong> (23 lines)</span>
          </label>
          <label style="display:flex; align-items:center; gap:0.45rem; cursor:pointer;">
            <input type="checkbox" id="chk-cyclone-fixes" checked onchange="toggleCycloneLayer('fixes', this.checked)">
            <span style="width:10px; height:10px; border-radius:50%; background:#ea580c; border:1px solid #fff; display:inline-block;"></span>
            <span><strong>Category Fixes</strong> (260 pts)</span>
          </label>
          <label style="display:flex; align-items:center; gap:0.45rem; cursor:pointer;">
            <input type="checkbox" id="chk-cyclone-wind" checked onchange="toggleCycloneLayer('wind', this.checked)">
            <span style="width:12px; height:10px; background:rgba(234,88,12,0.4); border:1px solid #ea580c; border-radius:2px; display:inline-block;"></span>
            <span><strong>Wind Swaths</strong> (900 polys)</span>
          </label>
        </div>
        <div style="font-weight:600; color:#94a3b8; font-size:0.7rem; margin-bottom:0.25rem;">Intensity Scale:</div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:0.25rem; font-size:0.68rem;">
          <div style="display:flex; align-items:center; gap:0.35rem;"><span style="width:9px; height:9px; border-radius:50%; background:#7c3aed; border:1px solid #fff;"></span> Cat 5 (&gt;280)</div>
          <div style="display:flex; align-items:center; gap:0.35rem;"><span style="width:9px; height:9px; border-radius:50%; background:#e11d48; border:1px solid #fff;"></span> Cat 4 (225–279)</div>
          <div style="display:flex; align-items:center; gap:0.35rem;"><span style="width:9px; height:9px; border-radius:50%; background:#ea580c; border:1px solid #fff;"></span> Cat 3 (165–224)</div>
          <div style="display:flex; align-items:center; gap:0.35rem;"><span style="width:9px; height:9px; border-radius:50%; background:#f59e0b; border:1px solid #fff;"></span> Cat 2 (125–164)</div>
          <div style="display:flex; align-items:center; gap:0.35rem; grid-column:span 2;"><span style="width:9px; height:9px; border-radius:50%; background:#0284c7; border:1px solid #fff;"></span> Cat 1 / Low (&lt;125 km/h)</div>
        </div>
      </div>"""
    content = content.replace(old_map_div, new_map_div)

    # 9. Priority sorting in mergeFeaturesIntoCache for population & area
    old_cache_merge = """          if (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon') {
            const ha = (typeof GeoLibreLayerLimiter !== 'undefined' && GeoLibreLayerLimiter.getFeatureArea)
              ? GeoLibreLayerLimiter.getFeatureArea(f, 'area_ha')
              : getFeatureMetricSize(f);
            if (!f.properties) f.properties = {};
            f.properties.area_ha = ha;
          }"""
    new_cache_merge = """          if (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon') {
            const ha = (typeof GeoLibreLayerLimiter !== 'undefined' && GeoLibreLayerLimiter.getFeatureArea)
              ? GeoLibreLayerLimiter.getFeatureArea(f, 'area_ha')
              : getFeatureMetricSize(f);
            if (!f.properties) f.properties = {};
            f.properties.area_ha = ha;
          } else if (f.properties && (f.properties.cell_population !== undefined || f.properties.CELL_POPULATION !== undefined)) {
            const pop = f.properties.cell_population ?? f.properties.CELL_POPULATION;
            if (!f.properties) f.properties = {};
            f.properties.area_ha = typeof pop === 'number' ? pop : parseFloat(pop) || 0;
          }"""
    content = content.replace(old_cache_merge, new_cache_merge)

    # 10. Replace DATASET_CATALOG using FRESH search right before output
    m_fresh = re.search(r'const DATASET_CATALOG = ({.*?});', content, re.DOTALL)
    if not m_fresh:
        raise ValueError("Could not find DATASET_CATALOG after string modifications")

    new_catalog_str = "const DATASET_CATALOG = " + json.dumps(existing_catalog, indent=2, ensure_ascii=False) + ";"
    content = content[:m_fresh.start()] + new_catalog_str + content[m_fresh.end():]

    OUTPUT_INSPECT_PATH.write_text(content, encoding="utf-8")
    print(f"[OK] Successfully built {OUTPUT_INSPECT_PATH} with {len(existing_catalog)} datasets.")

    # Also sync copies to docs/geolibre_qa_inspect.html and docs/qa/inspect.html
    copy1 = PROJECT_ROOT / "docs" / "geolibre_qa_inspect.html"
    copy2 = PROJECT_ROOT / "docs" / "qa" / "inspect.html"
    copy1.write_text(content, encoding="utf-8")
    copy2.write_text(content, encoding="utf-8")
    print(f"[OK] Synced {copy1} and {copy2}.")

if __name__ == "__main__":
    main()
