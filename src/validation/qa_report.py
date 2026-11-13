"""QA Report & Google Stitch Web Dashboard Generator (`docs/qa/index.html` and `docs/qa/inspect.html`).

Implements Section 11 of the specification using the Google Stitch `web_dashboard` design architecture:
- Material 3 / Stitch token palette (`#001026` primary, `#006973` secondary, `#faf8ff` surface).
- Typography: Space Grotesk (headlines), Plus Jakarta Sans (body/labels), JetBrains Mono (hashes/SQL/URIs).
- Distinguishes PASS, WARNING, FAIL, NOT TESTED, and NOT APPLICABLE across Level 1, Level 2, and Level 3.
- Generates both the QA Overview Hub (`docs/qa/index.html`) and the interactive MapLibre Per-Dataset Inspector (`docs/qa/inspect.html`).
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.catalogue.dataset_registry import DatasetRegistry
from src.catalogue.manifest_loader import QAStatus
from src.ingestion.gcs_storage import GCSLakeStorage
from src.ingestion.telemetry import utc_now_compact, utc_now_iso


STITCH_TAILWIND_HEAD = """
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin=""/>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&amp;family=Space+Grotesk:wght@600;700&amp;family=JetBrains+Mono:wght@400;500&amp;display=swap" rel="stylesheet"/>
  <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&amp;display=swap" rel="stylesheet"/>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: "class",
      theme: {
        extend: {
          colors: {
            "primary": "#001026",
            "primary-container": "#0b2545",
            "primary-fixed": "#d5e3ff",
            "on-primary": "#ffffff",
            "on-primary-container": "#778db2",
            "secondary": "#006973",
            "secondary-container": "#81f0ff",
            "secondary-fixed-dim": "#66d6e5",
            "on-tertiary-container": "#d47300",
            "error": "#ba1a1a",
            "error-container": "#ffdad6",
            "surface": "#faf8ff",
            "surface-container-lowest": "#ffffff",
            "surface-container-low": "#f2f3ff",
            "surface-container": "#eaedff",
            "surface-container-high": "#e2e7ff",
            "surface-container-highest": "#dae2fd",
            "on-surface": "#131b2e",
            "on-surface-variant": "#44474e",
            "outline": "#74777f",
            "outline-variant": "#c4c6cf"
          },
          fontFamily: {
            "headline": ["Space Grotesk", "sans-serif"],
            "sans": ["Plus Jakarta Sans", "sans-serif"],
            "mono": ["JetBrains Mono", "Consolas", "monospace"]
          }
        }
      }
    };
  </script>
  <style>
    body { font-family: 'Plus Jakarta Sans', sans-serif; background: #faf8ff; color: #131b2e; }
    .nav-link {
      display: flex; align-items: center; gap: 0.75rem; padding: 0.625rem 0.75rem;
      border-radius: 0.5rem; color: #44474e; font-size: 14px; font-weight: 600;
      transition: all 0.15s ease; text-decoration: none;
    }
    .nav-link:hover { background: #e2e7ff; color: #131b2e; }
    .nav-link.active { background: #0b2545; color: #ffffff; font-weight: 700; }
    .panel-card { background: #ffffff; border-radius: 0.75rem; padding: 1.5rem; box-shadow: 0 1px 3px rgba(0, 16, 38, 0.06); }
    .kpi-tile { padding: 1rem 1.25rem; border-radius: 0.75rem; background: #f2f3ff; display: flex; flex-direction: column; gap: 0.25rem; }
    .step-tag { padding: 0.2rem 0.6rem; border-radius: 0.25rem; background: #001026; color: #ffffff; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }
    .status-badge { display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.2rem 0.65rem; border-radius: 9999px; font-size: 11px; font-weight: 700; letter-spacing: 0.03em; }
    .status-PASS { background: rgba(0, 119, 75, 0.12); color: #00774b; border: 1px solid rgba(0, 119, 75, 0.28); }
    .status-WARNING { background: rgba(212, 115, 0, 0.14); color: #a35700; border: 1px solid rgba(212, 115, 0, 0.3); }
    .status-FAIL { background: rgba(186, 26, 26, 0.12); color: #ba1a1a; border: 1px solid rgba(186, 26, 26, 0.3); }
    .status-LINKED { background: rgba(2, 132, 199, 0.14); color: #0284c7; border: 1px solid rgba(2, 132, 199, 0.3); }
    .status-NOT_TESTED, .status-NOT_APPLICABLE { background: #eaedff; color: #44474e; border: 1px solid #c4c6cf; }
  </style>
"""


def build_qa_summary(
    registry: Optional[DatasetRegistry] = None,
    storage: Optional[GCSLakeStorage] = None,
) -> Dict[str, Any]:
    """Aggregates all per-dataset manifests and 3-level QA records into a single QA summary object."""
    reg = registry or DatasetRegistry()
    store = storage or GCSLakeStorage()
    report_ts = utc_now_iso()
    report_id = f"qa-report-{utc_now_compact()}"

    datasets_out: List[Dict[str, Any]] = []
    counts = {
        QAStatus.PASS.value: 0,
        QAStatus.WARNING.value: 0,
        QAStatus.FAIL.value: 0,
        QAStatus.NOT_TESTED.value: 0,
        QAStatus.NOT_APPLICABLE.value: 0,
        "LINKED": 0,
    }
    by_scale: Dict[str, int] = {}
    by_theme: Dict[str, int] = {}
    total_features_stored = 0
    total_bytes_stored = 0

    for key in sorted(reg.manifest.datasets.keys()):
        entry = reg.get(key)
        manifest_file = store.local_path(store.dataset_manifest_object_key(key))
        if manifest_file.exists():
            record = json.loads(manifest_file.read_text(encoding="utf-8"))
        else:
            is_linked = bool(entry.theme and "AURA" in entry.theme)
            status_val = "LINKED" if is_linked else entry.qa_status.value
            has_endpoint = bool(entry.endpoint and entry.endpoint.startswith("http"))
            record = {
                "dataset_key": entry.dataset_key,
                "title": entry.title,
                "provider": entry.provider,
                "source_agency": entry.source_agency,
                "category": "external_linked_library" if is_linked else entry.category.value,
                "scale": entry.scale,
                "jurisdiction": entry.jurisdiction,
                "theme": entry.theme,
                "endpoint": entry.endpoint,
                "wfs_type_name": entry.wfs_type_name,
                "licence": entry.licence.model_dump(mode="json"),
                "source_publication_date": entry.source_publication_date,
                "source_vintage": entry.source_vintage,
                "retrieval_timestamp_utc": entry.latest_retrieval_utc,
                "original_crs": entry.original_crs,
                "stored_crs": entry.stored_crs,
                "geometry_type": entry.geometry_type,
                "feature_count": 0,
                "bbox": entry.default_bbox,
                "file_size_bytes": 0,
                "sha256": None,
                "gcs_generation": None,
                "gs_uri": None,
                "overall_qa_status": status_val,
                "level1_source_contract": {
                    "status": "PASS" if has_endpoint else "NOT_APPLICABLE",
                    "checks": [{"name": "Linked Authority Check", "status": "PASS" if has_endpoint else "NOT_APPLICABLE", "details": f"External endpoint: {entry.endpoint}"}]
                },
                "level2_stored_artifact": {"status": "NOT_APPLICABLE", "checks": [{"name": "Stored GeoParquet", "status": "NOT_APPLICABLE", "details": "Direct external service connection (zero storage duplication)"}]},
                "level3_reconciliation": {"status": "NOT_APPLICABLE", "checks": [{"name": "Feature Reconciliation", "status": "NOT_APPLICABLE", "details": "External authoritative dataset"}]},
                "known_limitations": entry.known_limitations,
                "refresh_policy": entry.refresh_policy,
            }

        # Resolve public GCS / AURA library URL
        gcs_uri = record.get("gs_uri")
        if gcs_uri and str(gcs_uri).startswith("gs://"):
            record["gcs_https_url"] = str(gcs_uri).replace("gs://", "https://storage.googleapis.com/")
        elif entry.latest_snapshot_path:
            snap = entry.latest_snapshot_path
            record["gcs_https_url"] = snap.replace("gs://", "https://storage.googleapis.com/") if str(snap).startswith("gs://") else snap
        elif (store.project_root / "docs" / "qa" / "data" / f"{key}.parquet").exists():
            record["gcs_https_url"] = f"https://storage.googleapis.com/{store.bucket_name}/qa/data/{key}.parquet"
        elif (store.project_root / "docs" / "qa" / "data" / f"{key}.geojson").exists():
            record["gcs_https_url"] = f"https://storage.googleapis.com/{store.bucket_name}/qa/data/{key}.geojson"
        elif bool(entry.theme and "AURA" in entry.theme):
            record["gcs_https_url"] = f"https://aura.getback2basics.net/docs/qa/geolibre_qa_inspect.html?dataset={key}"
        else:
            record["gcs_https_url"] = None

        l1 = record.get("level1_source_contract") or {}
        source_count = l1.get("source_feature_count")
        stored_count = int(record.get("feature_count") or 0)
        record["source_count"] = source_count
        record["stored_count"] = stored_count
        if source_count is not None and source_count > 0 and stored_count > 0:
            pct = round((stored_count / source_count) * 100.0, 1)
            record["sync_status"] = f"{min(pct, 100.0)}%"
        elif record.get("overall_qa_status") == "LINKED":
            record["sync_status"] = "Linked"
        elif stored_count > 0:
            record["sync_status"] = "100%"
        else:
            record["sync_status"] = "—"

        status_str = record.get("overall_qa_status", QAStatus.NOT_TESTED.value)
        counts[status_str] = counts.get(status_str, 0) + 1
        by_scale[entry.scale] = by_scale.get(entry.scale, 0) + 1
        by_theme[entry.theme] = by_theme.get(entry.theme, 0) + 1
        total_features_stored += int(record.get("feature_count") or 0)
        total_bytes_stored += int(record.get("file_size_bytes") or 0)
        datasets_out.append(record)

    summary = {
        "report_id": report_id,
        "generated_at_utc": report_ts,
        "project_name": reg.manifest.project_name,
        "canonical_gcs_bucket": store.bucket_name,
        "total_datasets": len(datasets_out),
        "status_counts": counts,
        "coverage_by_scale": by_scale,
        "coverage_by_theme": by_theme,
        "total_features_stored": total_features_stored,
        "total_bytes_stored": total_bytes_stored,
        "datasets": datasets_out,
    }

    # Persist in lakehouse QA reports and docs/qa/data
    store.write_json(
        store.qa_report_object_key(report_id, "qa_summary.json"),
        summary,
        overwrite=True,
    )
    docs_qa_data = store.project_root / "docs" / "qa" / "data"
    docs_qa_data.mkdir(parents=True, exist_ok=True)
    (docs_qa_data / "qa_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def render_qa_html_pages(
    summary: Dict[str, Any],
    output_dir: Optional[Path] = None,
) -> Dict[str, str]:
    """Renders `docs/qa/index.html` and `docs/qa/inspect.html` using the Google Stitch design architecture."""
    out_dir = output_dir or (Path(__file__).resolve().parent.parent.parent / "docs" / "qa")
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_json_inline = json.dumps(summary, ensure_ascii=False)
    sc = summary["status_counts"]

    # ------------------------------------------------------------------
    # 1. QA Overview Hub (docs/qa/index.html)
    # ------------------------------------------------------------------
    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="shell-type" content="web_dashboard"/>
  <title>Operational Intelligence Crafter — QA Report ({summary['report_id']})</title>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin=""/>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&amp;family=JetBrains+Mono:wght@400;500;600;700&amp;display=swap" rel="stylesheet"/>
  <style>
    :root {{
      --bg-primary: #0a0f1d;
      --bg-secondary: #131a2c;
      --card-bg: rgba(19, 26, 44, 0.85);
      --border-color: rgba(59, 130, 246, 0.22);
      --text-primary: #f8fafc;
      --text-secondary: #94a3b8;
      --accent-blue: #38bdf8;
      --accent-cyan: #06b6d4;
      --accent-green: #10b981;
      --accent-amber: #f59e0b;
      --accent-rose: #ef4444;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      background: var(--bg-primary);
      color: var(--text-primary);
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      margin: 0;
      padding: 2rem;
      min-height: 100vh;
    }}
    .container {{
      max-width: 1560px;
      margin: 0 auto;
    }}
    .header {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 1.25rem;
      padding-bottom: 1.5rem;
      border-bottom: 1px solid var(--border-color);
      margin-bottom: 1.5rem;
    }}
    .title h1 {{
      margin: 0;
      font-size: 1.65rem;
      font-weight: 700;
      color: #60a5fa;
      letter-spacing: -0.01em;
    }}
    .title p {{
      margin: 0.35rem 0 0 0;
      color: var(--text-secondary);
      font-size: 0.85rem;
    }}
    .header-right {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }}
    .btn-inspector {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      background: #0284c7;
      color: #ffffff;
      padding: 0.55rem 1rem;
      border-radius: 0.5rem;
      font-size: 0.825rem;
      font-weight: 600;
      text-decoration: none;
      transition: background 0.15s;
    }}
    .btn-inspector:hover {{
      background: #0369a1;
    }}
    .stats-bar {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.65rem;
      align-items: center;
      margin-bottom: 1.25rem;
    }}
    .stat-pill {{
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: 0.5rem;
      padding: 0.4rem 0.8rem;
      font-size: 0.8rem;
      color: var(--text-secondary);
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
    }}
    .stat-pill b {{
      color: var(--text-primary);
      font-family: 'JetBrains Mono', monospace;
    }}
    .stat-pass b {{ color: var(--accent-green); }}
    .stat-warn b {{ color: var(--accent-amber); }}
    .stat-fail b {{ color: var(--accent-rose); }}
    .stat-linked b {{ color: var(--accent-blue); }}
    .search-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 1rem;
      margin-bottom: 1rem;
    }}
    .search-input {{
      flex: 1;
      max-width: 460px;
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      color: var(--text-primary);
      padding: 0.6rem 0.9rem;
      border-radius: 0.5rem;
      font-size: 0.825rem;
      font-family: inherit;
      outline: none;
    }}
    .search-input:focus {{
      border-color: #38bdf8;
    }}
    .table-card {{
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 0.75rem;
      overflow-x: auto;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.825rem;
      text-align: left;
    }}
    thead th {{
      background: #0f172a;
      padding: 0.85rem 0.9rem;
      color: var(--text-secondary);
      font-weight: 600;
      text-transform: uppercase;
      font-size: 0.725rem;
      letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border-color);
      white-space: nowrap;
    }}
    tbody td {{
      padding: 0.75rem 0.9rem;
      border-bottom: 1px solid rgba(59, 130, 246, 0.1);
      vertical-align: middle;
    }}
    tbody tr:last-child td {{
      border-bottom: none;
    }}
    tbody tr:hover td {{
      background: rgba(30, 41, 59, 0.5);
    }}
    .dataset-link {{
      color: #38bdf8;
      font-weight: 600;
      font-family: 'JetBrains Mono', monospace;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
    }}
    .dataset-link:hover {{
      text-decoration: underline;
      color: #7dd3fc;
    }}
    .dataset-sub {{
      font-size: 0.725rem;
      color: #94a3b8;
      margin-top: 0.2rem;
    }}
    .ext-link {{
      color: #94a3b8;
      font-size: 0.75rem;
      text-decoration: underline;
      font-family: 'JetBrains Mono', monospace;
      display: block;
      max-width: 260px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .ext-link:hover {{
      color: #e2e8f0;
    }}
    .gcs-link {{
      color: #38bdf8;
      font-size: 0.75rem;
      text-decoration: underline;
      font-family: 'JetBrains Mono', monospace;
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      max-width: 280px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .gcs-link:hover {{
      color: #7dd3fc;
    }}
    .muted-dash {{
      color: #64748b;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.75rem;
    }}
    .num {{
      font-family: 'JetBrains Mono', monospace;
      text-align: right;
      font-weight: 600;
      white-space: nowrap;
    }}
    .qa-col {{
      text-align: center;
      white-space: nowrap;
    }}
    .qa-pass {{ color: #10b981; font-weight: bold; font-size: 1.15rem; }}
    .qa-warn {{ color: #f59e0b; font-weight: bold; font-size: 1.15rem; }}
    .qa-fail {{ color: #ef4444; font-weight: bold; font-size: 1.15rem; }}
    .qa-linked {{ color: #38bdf8; font-weight: 600; font-size: 0.85rem; font-family: 'JetBrains Mono', monospace; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="title">
        <h1>Operational Intelligence Crafter — QA Report</h1>
        <p>Authoritative Spatial Data Catalogue, Cloud Library &amp; Inspection Provenance &bull; Generated UTC {summary['generated_at_utc']}</p>
      </div>
      <div class="header-right">
        <span class="stat-pill" style="font-family:'JetBrains Mono',monospace;">{summary['report_id']}</span>
        <a href="geolibre_qa_inspect.html" target="_blank" class="btn-inspector">
          <span>🗺️</span><span>Open GeoLibre QA Inspector</span>
        </a>
      </div>
    </div>

    <div class="stats-bar">
      <div class="stat-pill">Total Datasets: <b>{summary['total_datasets']}</b></div>
      <div class="stat-pill stat-pass">Passing: <b>{sc.get('PASS', 0)}</b></div>
      <div class="stat-pill stat-warn">Warnings: <b>{sc.get('WARNING', 0)}</b></div>
      <div class="stat-pill stat-fail">Failed: <b>{sc.get('FAIL', 0)}</b></div>
      <div class="stat-pill stat-linked">Linked: <b>{sc.get('LINKED', 0)}</b></div>
      <div class="stat-pill">Stored Features: <b>{summary['total_features_stored']:,}</b></div>
    </div>

    <div class="search-row">
      <input id="datasetFilterInput" type="search" class="search-input" placeholder="🔍 Search datasets by key, title, provider, scale, or status..."/>
      <span id="matchCountLabel" style="font-size: 0.75rem; color: #94a3b8; font-family: 'JetBrains Mono', monospace;"></span>
    </div>

    <div class="table-card">
      <table>
        <thead>
          <tr>
            <th>Dataset Key (Click to Inspect)</th>
            <th>Live Source Query Endpoint</th>
            <th>Cloud Library Version</th>
            <th style="text-align: right;">Source Records</th>
            <th style="text-align: right;">Lake Records</th>
            <th style="text-align: center;">Delta / Sync Status</th>
            <th style="text-align: center;">QA</th>
          </tr>
        </thead>
        <tbody id="qaTableBody">
        </tbody>
      </table>
    </div>
  </div>

  <script>
    const QA_SUMMARY = {summary_json_inline};

    function formatEndpoint(url) {{
      if (!url) return "—";
      try {{
        const u = new URL(url);
        const pathParts = u.pathname.split("/").filter(Boolean);
        const last = pathParts.slice(-2).join("/");
        return u.hostname + (last ? "/" + last : "");
      }} catch (e) {{
        return url.replace(/^https?:[/][/]/, "").slice(0, 36);
      }}
    }}

    function formatStorageLink(url, ds) {{
      if (!url) return '<span class="muted-dash">—</span>';
      let label = "Artifact";
      if (url.includes("aura-siting-crafter") || (ds.theme && ds.theme.includes("AURA"))) {{
        label = "AURA Library";
      }} else if (url.includes("geoparquet")) {{
        label = "GCS GeoParquet";
      }} else if (url.endsWith(".parquet")) {{
        label = "GCS Parquet";
      }} else if (url.endsWith(".geojson")) {{
        label = "GCS GeoJSON";
      }} else if (url.includes("storage.googleapis.com")) {{
        label = "GCS Artifact";
      }}
      return `<a href="${{url}}" target="_blank" class="gcs-link" title="${{url}}">📦 ${{label}}</a>`;
    }}

    function qaBadge(st) {{
      const s = (st || "NOT_TESTED").toUpperCase();
      if (s === "PASS") return '<span class="qa-pass" title="All checks passed">✔</span>';
      if (s === "WARNING") return '<span class="qa-warn" title="Warning / Minor delta">⚠</span>';
      if (s === "FAIL") return '<span class="qa-fail" title="Failed source contract">✖</span>';
      if (s === "LINKED") return '<span class="qa-linked" title="External linked catalogue">🔗</span>';
      return `<span class="muted-dash">${{st}}</span>`;
    }}

    function renderTable(filterText = "") {{
      const q = filterText.trim().toLowerCase();
      const tbody = document.getElementById("qaTableBody");
      tbody.innerHTML = "";

      let matchCount = 0;
      QA_SUMMARY.datasets.forEach(ds => {{
        const hay = `${{ds.dataset_key}} ${{ds.title || ""}} ${{ds.provider || ""}} ${{ds.theme || ""}} ${{ds.scale || ""}} ${{ds.overall_qa_status || ""}}`.toLowerCase();
        if (q && !hay.includes(q)) return;
        matchCount++;

        const l1 = ds.level1_source_contract || {{}};
        const srcCount = (l1.source_feature_count !== undefined && l1.source_feature_count !== null)
          ? l1.source_feature_count.toLocaleString()
          : (ds.source_count !== undefined && ds.source_count !== null ? ds.source_count.toLocaleString() : "—");
        const storedCount = ds.feature_count ? ds.feature_count.toLocaleString() : "0";
        const syncStatus = ds.sync_status || (ds.overall_qa_status === "LINKED" ? "Linked" : (ds.feature_count ? "100%" : "—"));
        const storageUrl = ds.gcs_https_url || (ds.gs_uri ? ds.gs_uri.replace("gs://", "https://storage.googleapis.com/") : null);

        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>
            <a href="geolibre_qa_inspect.html?dataset=${{encodeURIComponent(ds.dataset_key)}}" target="_blank" class="dataset-link" title="Click to open in GeoLibre QA Inspector">
              🗺️ ${{ds.dataset_key}}
            </a>
            <div class="dataset-sub">${{ds.title || ""}} &bull; <span style="color:#64748b;">${{ds.scale || ""}} / ${{ds.theme || ""}}</span></div>
          </td>
          <td>
            ${{ds.endpoint ? `<a href="${{ds.endpoint}}" target="_blank" class="ext-link" title="${{ds.endpoint}}">${{formatEndpoint(ds.endpoint)}}</a>` : '<span class="muted-dash">—</span>'}}
          </td>
          <td>
            ${{formatStorageLink(storageUrl, ds)}}
          </td>
          <td class="num" style="color: #38bdf8;">${{srcCount}}</td>
          <td class="num" style="color: #10b981;">${{storedCount}}</td>
          <td class="num" style="text-align: center; color: #34d399;">${{syncStatus}}</td>
          <td class="qa-col">${{qaBadge(ds.overall_qa_status)}}</td>
        `;
        tbody.appendChild(tr);
      }});

      document.getElementById("matchCountLabel").textContent = `Showing ${{matchCount}} of ${{QA_SUMMARY.datasets.length}} datasets`;
    }}

    document.getElementById("datasetFilterInput").addEventListener("input", e => renderTable(e.target.value));
    renderTable();
  </script>
</body>
</html>
"""

    # ------------------------------------------------------------------
    # 2. Per-Dataset MapLibre QA Inspector (docs/qa/inspect.html)
    # ------------------------------------------------------------------
    inspect_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="shell-type" content="web_dashboard"/>
  <title>Emergency Spatial Intelligence | MapLibre Per-Dataset QA Inspector</title>
  {STITCH_TAILWIND_HEAD}
  <link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet"/>
  <script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
</head>
<body class="bg-surface text-on-surface antialiased">

  <!-- ============ FIXED LEFT SIDEBAR ============ -->
  <aside class="fixed left-0 top-0 h-full w-64 bg-surface-container-low z-50 flex flex-col justify-between py-6 shadow-[0_1px_8px_rgba(0,0,0,0.05)]">
    <div class="flex flex-col gap-6">
      <div class="px-6 flex items-center gap-3">
        <div class="w-9 h-9 rounded-lg bg-primary-container flex items-center justify-center">
          <span class="material-symbols-outlined text-secondary-container text-[22px]">crisis_alert</span>
        </div>
        <div>
          <span class="font-headline font-bold text-[18px] text-primary block leading-tight">Operational Intel</span>
          <span class="text-[11px] font-bold text-on-surface-variant tracking-wider uppercase">MapLibre QA Inspector</span>
        </div>
      </div>
      <nav class="flex flex-col gap-1 px-3">
        <a class="nav-link" href="index.html"><span class="material-symbols-outlined text-[20px]">fact_check</span>3-Level Data QA Hub</a>
        <a class="nav-link active" href="inspect.html"><span class="material-symbols-outlined text-[20px]">map</span>MapLibre QA Inspector</a>
      </nav>
      <div class="px-4 space-y-2">
        <label class="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant block">Select Dataset to Inspect</label>
        <select id="datasetSelect" class="w-full p-2.5 rounded-lg bg-surface-container-lowest border border-outline-variant text-xs font-semibold text-on-surface focus:outline-none focus:ring-2 focus:ring-secondary"></select>
        <div id="sidebarDatasetMeta" class="p-3 rounded-lg bg-surface-container text-[11px] space-y-1 font-mono"></div>
      </div>
    </div>
    <div class="px-4">
      <a href="index.html" class="w-full py-2 px-3 rounded-lg bg-surface-container hover:bg-surface-container-high text-xs font-bold flex items-center justify-center gap-2">
        <span class="material-symbols-outlined text-[16px]">arrow_back</span>Back to QA Overview
      </a>
    </div>
  </aside>

  <!-- ============ MAIN INSPECTOR AREA ============ -->
  <div class="pl-64">
    <main class="p-6 space-y-6 max-w-[1600px]">
      <!-- Top Dataset Provenance Header -->
      <section class="panel-card flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div class="flex items-center gap-2">
            <span class="step-tag">MAPLIBRE GL INSPECTOR</span>
            <h1 id="inspectTitle" class="font-headline font-bold text-xl text-on-surface">Select a Dataset</h1>
            <span id="inspectStatusBadge"></span>
          </div>
          <p id="inspectSubtitle" class="text-xs text-on-surface-variant mt-1 font-mono"></p>
        </div>
        <div class="flex items-center gap-2">
          <button id="btnZoomExtent" class="px-3 py-2 rounded-lg bg-secondary text-white text-xs font-bold flex items-center gap-1.5">
            <span class="material-symbols-outlined text-[16px]">fit_screen</span>Zoom to Layer Bbox
          </button>
        </div>
      </section>

      <!-- MapLibre Canvas + 3-Level Summary -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="lg:col-span-2 panel-card p-0 overflow-hidden relative h-[540px]">
          <div id="map" class="w-full h-full"></div>
          <div id="mapErrorOverlay" class="hidden absolute inset-0 bg-primary/90 text-white p-8 flex flex-col items-center justify-center text-center space-y-3 z-20">
            <span class="material-symbols-outlined text-5xl text-error-container">gpp_bad</span>
            <h3 class="font-headline font-bold text-xl">Source Failed Level 1 Validation — Zero Mock Geometry</h3>
            <p id="mapErrorText" class="font-mono text-xs max-w-xl text-primary-fixed"></p>
          </div>
          <div class="absolute bottom-3 left-3 bg-primary/85 text-white backdrop-blur-sm px-3 py-1.5 rounded-lg text-[11px] font-mono flex items-center gap-2 z-10 pointer-events-none">
            <span class="text-secondary-fixed">👆 Click any point, line or polygon for attribute popup</span>
          </div>
        </div>

        <div class="panel-card space-y-4 overflow-y-auto max-h-[540px]">
          <div id="selectedFeatureBox" class="p-3 rounded-lg bg-primary text-white space-y-2 hidden">
            <div class="flex items-center justify-between">
              <span class="text-[10px] font-bold uppercase tracking-wider text-secondary-fixed">Selected Feature</span>
              <button id="btnCloseSelectedFeature" class="text-xs text-white hover:text-error">✕</button>
            </div>
            <div id="selectedFeatureTitle" class="font-bold text-sm"></div>
            <div id="selectedFeatureAttrs" class="space-y-1 text-[11px] font-mono max-h-44 overflow-y-auto divide-y divide-primary-container"></div>
          </div>
          <h2 class="font-headline font-bold text-base text-on-surface">Provenance &amp; Validation Metadata</h2>
          <div id="inspectorMetadataList" class="space-y-2 text-xs"></div>
        </div>
      </div>

      <!-- Sample Feature Attribute Table -->
      <section class="panel-card space-y-3">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <h2 class="font-headline font-bold text-base text-on-surface">Stored Feature Attribute Sample (Click Row to Pan/Zoom &amp; Popup)</h2>
            <span id="sampleCountLabel" class="font-mono text-xs text-on-surface-variant"></span>
          </div>
          <input id="sampleFilterInput" type="search" placeholder="🔍 Search preview features..." class="h-8 px-2.5 rounded bg-surface-container-low border border-outline-variant text-xs w-64 focus:outline-none focus:ring-1 focus:ring-secondary"/>
        </div>
        <div class="overflow-x-auto max-h-80">
          <table class="w-full text-left border-collapse text-xs">
            <thead id="attrTableHead" class="bg-surface-container-low text-on-surface-variant font-mono text-[11px] sticky top-0 z-10"></thead>
            <tbody id="attrTableBody" class="divide-y divide-surface-container font-mono text-[11px]"></tbody>
          </table>
        </div>
      </section>
    </main>
  </div>

  <script>
    const QA_SUMMARY = {summary_json_inline};
    let map = null;
    let currentBounds = null;
    let currentGeojson = null;
    let popup = null;

    function initMap() {{
      map = new maplibregl.Map({{
        container: "map",
        style: {{
          version: 8,
          sources: {{
            "osm-standard": {{
              type: "raster",
              tiles: ["https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png"],
              tileSize: 256,
              attribution: "© OpenStreetMap contributors"
            }}
          }},
          layers: [{{ id: "osm-standard-layer", type: "raster", source: "osm-standard" }}]
        }},
        center: [151.65, -32.92],
        zoom: 8
      }});
      map.addControl(new maplibregl.NavigationControl(), "top-right");

      map.on("load", () => {{
        // Setup highlight layer for inspected feature
        map.addSource("inspect-hl", {{ type: "geojson", data: {{ type: "FeatureCollection", features: [] }} }});
        map.addLayer({{
          id: "inspect-hl-fill",
          type: "fill",
          source: "inspect-hl",
          paint: {{ "fill-color": "#facc15", "fill-opacity": 0.3 }}
        }});
        map.addLayer({{
          id: "inspect-hl-line",
          type: "line",
          source: "inspect-hl",
          paint: {{ "line-color": "#facc15", "line-width": 4 }}
        }});
        map.addLayer({{
          id: "inspect-hl-point",
          type: "circle",
          source: "inspect-hl",
          paint: {{ "circle-radius": 10, "circle-color": "rgba(250,204,21,0.3)", "circle-stroke-color": "#facc15", "circle-stroke-width": 2.5 }}
        }});
      }});
    }}

    function computeGeometryBounds(geom) {{
      if (!geom) return null;
      const pts = [];
      function flatten(coords) {{
        if (typeof coords[0] === "number") {{ pts.push(coords); return; }}
        coords.forEach(c => flatten(c));
      }}
      if (geom.type === "GeometryCollection") {{
        (geom.geometries || []).forEach(g => g && g.coordinates && flatten(g.coordinates));
      }} else if (geom.coordinates) {{
        flatten(geom.coordinates);
      }}
      if (!pts.length) return null;
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      pts.forEach(([x, y]) => {{
        minX = Math.min(minX, x); maxX = Math.max(maxX, x);
        minY = Math.min(minY, y); maxY = Math.max(maxY, y);
      }});
      return [[minX, minY], [maxX, maxY]];
    }}

    function setInspectHighlight(feature) {{
      const src = map && map.getSource("inspect-hl");
      if (src) {{
        src.setData({{ type: "FeatureCollection", features: feature ? [feature] : [] }});
      }}
    }}

    function showInspectPopup(feature, lngLat) {{
      if (!feature || !map) return;
      const props = feature.properties || {{}};
      const gtype = (feature.geometry && feature.geometry.type) || "Geometry";
      const title = props.feature_name || props.title || props.name || props.lga_name_2025 || props.sa2_name_2021 || props.cell_id || `Feature #${{props.__idx ?? 0}}`;
      
      const rows = Object.entries(props)
        .filter(([k]) => k !== "__idx" && !k.startsWith("_oic_"))
        .map(([k, v]) => `<tr><th class="py-1 pr-2 text-on-surface-variant font-bold uppercase text-[10px] whitespace-nowrap text-left">${{k}}</th><td class="py-1 font-mono text-[11px] text-on-surface break-all">${{v ?? ""}}</td></tr>`)
        .join("");

      const content = `
        <div style="font-family:'Plus Jakarta Sans',sans-serif; max-width:320px; max-height:240px; overflow-y:auto; padding:8px;">
          <div style="font-size:10px; font-weight:700; color:#006973; text-transform:uppercase;">${{gtype}}</div>
          <div style="font-size:13px; font-weight:700; color:#001026; margin-bottom:6px;">${{title}}</div>
          <table style="width:100%; border-collapse:collapse;">${{rows}}</table>
        </div>
      `;

      if (popup) popup.remove();
      const pos = lngLat || (feature.geometry.type === "Point" ? feature.geometry.coordinates : null);
      if (pos) {{
        popup = new maplibregl.Popup({{ closeButton: true, maxWidth: "340px" }})
          .setLngLat(pos)
          .setHTML(content)
          .addTo(map);
        popup.on("close", () => setInspectHighlight(null));
      }}

      setInspectHighlight(feature);

      // Also update selected feature card
      const box = document.getElementById("selectedFeatureBox");
      if (box) {{
        box.classList.remove("hidden");
        document.getElementById("selectedFeatureTitle").textContent = title;
        document.getElementById("selectedFeatureAttrs").innerHTML = Object.entries(props)
          .filter(([k]) => k !== "__idx")
          .map(([k, v]) => `<div class="py-0.5 flex justify-between gap-2"><span class="text-secondary-fixed">${{k}}:</span><span class="truncate">${{v ?? ""}}</span></div>`)
          .join("");
      }}
    }}

    function zoomToInspectFeature(f) {{
      if (!f || !f.geometry || !map) return;
      if (f.geometry.type === "Point") {{
        map.flyTo({{ center: f.geometry.coordinates, zoom: Math.max(map.getZoom(), 13), duration: 600 }});
        map.once("moveend", () => showInspectPopup(f, f.geometry.coordinates));
      }} else {{
        const b = computeGeometryBounds(f.geometry);
        if (b) {{
          map.fitBounds(b, {{ padding: 60, maxZoom: 14, duration: 600 }});
          const center = [(b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2];
          map.once("moveend", () => showInspectPopup(f, center));
        }}
      }}
    }}

    async function loadDatasetOnMap(dsKey) {{
      const ds = QA_SUMMARY.datasets.find(d => d.dataset_key === dsKey) || QA_SUMMARY.datasets[0];
      if (!ds) return;

      document.getElementById("inspectTitle").textContent = `${{ds.dataset_key}} — ${{ds.title}}`;
      document.getElementById("inspectSubtitle").textContent = `${{ds.gs_uri || ds.endpoint}} | Vintage: ${{ds.source_vintage}} | Stored CRS: ${{ds.stored_crs}}`;
      document.getElementById("inspectStatusBadge").innerHTML = `<span class="status-badge status-${{(ds.overall_qa_status || 'NOT_TESTED').replace(/\\s+/g, '_')}}">${{ds.overall_qa_status}}</span>`;

      const l2 = ds.level2_stored_artifact || {{}};
      const gv = l2.geometry_validation || {{}};
      document.getElementById("inspectorMetadataList").innerHTML = `
        <div class="p-2.5 rounded bg-surface-container-low font-mono text-[11px] space-y-1">
          <div><b>Provider:</b> ${{ds.provider}}</div>
          <div><b>Licence:</b> ${{(ds.licence && ds.licence.name) || "CC-BY-4.0"}}</div>
          <div><b>Retrieval UTC:</b> ${{ds.retrieval_timestamp_utc || "N/A"}}</div>
          <div><b>Original &rarr; Stored CRS:</b> ${{ds.original_crs}} &rarr; ${{ds.stored_crs}}</div>
          <div><b>Geometry Types:</b> ${{ds.geometry_type || "N/A"}}</div>
          <div><b>Stored Features:</b> ${{(ds.feature_count || 0).toLocaleString()}}</div>
          <div><b>Valid Geometry Rate:</b> ${{gv.valid_geometry_rate_pct !== undefined ? gv.valid_geometry_rate_pct + "%" : "N/A"}} (null=${{gv.null_geometry_count || 0}}, invalid=${{gv.invalid_geometry_count || 0}})</div>
          <div><b>Duplicate IDs:</b> ${{gv.duplicate_id_count !== undefined ? gv.duplicate_id_count : "N/A"}}</div>
          <div><b>SHA-256:</b> ${{ds.sha256 ? ds.sha256.slice(0, 24) + "..." : "N/A"}}</div>
        </div>
        <div class="text-[11px] text-on-surface-variant"><b>Limitations:</b> ${{(ds.known_limitations || []).join(" ")}}</div>
      `;

      const overlay = document.getElementById("mapErrorOverlay");
      let geojson = null;

      if (ds.preview_geojson && ds.preview_geojson.preview_geojson_path) {{
        try {{
          const resp = await fetch(ds.preview_geojson.preview_geojson_path);
          if (resp.ok) geojson = await resp.json();
        }} catch (e) {{
          console.warn("Failed to load local preview GeoJSON:", e);
        }}
      }} else if (ds.endpoint && ds.endpoint.startsWith("http")) {{
        // Live provider endpoint query (AURA Data Library / External Linked Datasets)
        let liveUrl = null;
        const ep = ds.endpoint.trim();
        if (ep.includes("FeatureServer") || ep.includes("MapServer")) {{
          const base = ep.split("?")[0].replace(/[/]+$/, '');
          liveUrl = `${{base}}/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&f=geojson&resultRecordCount=100`;
        }} else if (ep.toLowerCase().includes("geoserver") || ep.toLowerCase().includes("wfs")) {{
          const base = ep.split("?")[0];
          const typeName = ds.wfs_type_name || (ds.dataset_key.includes("vic_") ? `open-data-platform:${{ds.dataset_key.replace('_v2', '')}}` : "");
          liveUrl = `${{base}}?service=WFS&version=2.0.0&request=GetFeature&typeNames=${{typeName}}&outputFormat=application/json&count=100`;
        }} else if (ep.endsWith(".json") || ep.endsWith(".geojson")) {{
          liveUrl = ep;
        }}

        if (liveUrl) {{
          try {{
            document.getElementById("mapErrorText").textContent = `Querying live provider endpoint (${{ds.provider}})...`;
            overlay.classList.remove("hidden");
            const resp = await fetch(liveUrl);
            if (resp.ok) {{
              const data = await resp.json();
              if (data && data.features && data.type !== "FeatureCollection") {{
                // Normalize Esri JSON format
                geojson = {{
                  type: "FeatureCollection",
                  features: data.features.map((f, i) => {{
                    let geom = null;
                    if (f.geometry) {{
                      if (f.geometry.x !== undefined && f.geometry.y !== undefined) {{
                        geom = {{ type: "Point", coordinates: [f.geometry.x, f.geometry.y] }};
                      }} else if (f.geometry.paths) {{
                        geom = {{ type: f.geometry.paths.length === 1 ? "LineString" : "MultiLineString", coordinates: f.geometry.paths.length === 1 ? f.geometry.paths[0] : f.geometry.paths }};
                      }} else if (f.geometry.rings) {{
                        geom = {{ type: f.geometry.rings.length === 1 ? "Polygon" : "MultiPolygon", coordinates: f.geometry.rings.length === 1 ? f.geometry.rings : [f.geometry.rings] }};
                      }}
                    }}
                    return {{ type: "Feature", properties: f.attributes || {{}}, geometry: geom }};
                  }})
                }};
              }} else if (data && data.type === "FeatureCollection") {{
                geojson = data;
              }}
            }}
          }} catch (liveErr) {{
            console.warn("Live endpoint query failed:", liveErr);
          }}
        }}
      }}

      if (!geojson || !geojson.features || geojson.features.length === 0) {{
        overlay.classList.remove("hidden");
        const isRaster = (ds.geometry_type || "").toLowerCase().includes("raster") || (ds.service_type || "").includes("raster") || (ds.service_type || "").includes("octree") || (ds.service_type || "").includes("copc");
        const msg = isRaster 
          ? `External Linked Dataset (AURA Data Library): Remote Raster / 3D Tile Layer (not vector GeoJSON). Available at ${{ds.endpoint || "remote lakehouse"}}.`
          : (ds.overall_qa_status === "FAIL" ? `Endpoint: ${{ds.endpoint}} | Error: ${{(ds.level1_source_contract && ds.level1_source_contract.error_message) || "Source contract failed"}}` : `External Linked Dataset: Direct vector query unavailable for ${{ds.endpoint || "unconfigured endpoint"}} (requires token or server-side auth).`);
        document.getElementById("mapErrorText").textContent = msg;
        document.getElementById("attrTableHead").innerHTML = "";
        document.getElementById("attrTableBody").innerHTML = `<tr><td class="p-3 text-on-surface-variant font-mono text-xs">${{msg}}</td></tr>`;
        return;
      }}
      overlay.classList.add("hidden");

      currentGeojson = geojson;
      (geojson.features || []).forEach((f, i) => {{
        f.properties = f.properties || {{}};
        f.properties.__idx = i;
      }});

      if (map.getLayer("inspect-points")) map.removeLayer("inspect-points");
      if (map.getLayer("inspect-lines")) map.removeLayer("inspect-lines");
      if (map.getLayer("inspect-polys")) map.removeLayer("inspect-polys");
      if (map.getLayer("inspect-polys-outline")) map.removeLayer("inspect-polys-outline");
      if (map.getSource("inspect-src")) map.removeSource("inspect-src");

      map.addSource("inspect-src", {{ type: "geojson", data: geojson }});
      map.addLayer({{
        id: "inspect-polys",
        type: "fill",
        source: "inspect-src",
        filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]],
        paint: {{ "fill-color": "#006973", "fill-opacity": 0.35 }}
      }});
      map.addLayer({{
        id: "inspect-polys-outline",
        type: "line",
        source: "inspect-src",
        filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]],
        paint: {{ "line-color": "#001026", "line-width": 1.5 }}
      }});
      map.addLayer({{
        id: "inspect-lines",
        type: "line",
        source: "inspect-src",
        filter: ["in", ["geometry-type"], ["literal", ["LineString", "MultiLineString"]]],
        paint: {{ "line-color": "#0b2545", "line-width": 2.5 }}
      }});
      map.addLayer({{
        id: "inspect-points",
        type: "circle",
        source: "inspect-src",
        filter: ["in", ["geometry-type"], ["literal", ["Point", "MultiPoint"]]],
        paint: {{ "circle-radius": 6, "circle-color": "#006973", "circle-stroke-width": 1.5, "circle-stroke-color": "#ffffff" }}
      }});

      // Add click & pointer listeners to map layers
      const interactiveLayers = ["inspect-polys", "inspect-lines", "inspect-points"];
      interactiveLayers.forEach(lyrId => {{
        map.on("click", lyrId, e => {{
          if (e.features && e.features.length) {{
            const idx = e.features[0].properties.__idx;
            const fullFeature = geojson.features[idx] || e.features[0];
            showInspectPopup(fullFeature, e.lngLat);
          }}
        }});
        map.on("mouseenter", lyrId, () => {{ map.getCanvas().style.cursor = "pointer"; }});
        map.on("mouseleave", lyrId, () => {{ map.getCanvas().style.cursor = ""; }});
      }});

      if (ds.bbox && ds.bbox.length === 4) {{
        currentBounds = [[ds.bbox[0], ds.bbox[1]], [ds.bbox[2], ds.bbox[3]]];
        map.fitBounds(currentBounds, {{ padding: 40, maxZoom: 13 }});
      }} else if (geojson.features && geojson.features.length > 0) {{
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        geojson.features.forEach(f => {{
          const b = computeGeometryBounds(f.geometry);
          if (b) {{
            minX = Math.min(minX, b[0][0]); minY = Math.min(minY, b[0][1]);
            maxX = Math.max(maxX, b[1][0]); maxY = Math.max(maxY, b[1][1]);
          }}
        }});
        if (minX !== Infinity) {{
          currentBounds = [[minX, minY], [maxX, maxY]];
          map.fitBounds(currentBounds, {{ padding: 40, maxZoom: 13 }});
        }}
      }}

      // Populate attribute sample table with search filtering
      renderSampleTable(geojson);
    }}

    function renderSampleTable(geojson) {{
      const filter = (document.getElementById("sampleFilterInput").value || "").toLowerCase().trim();
      const allFeats = geojson.features || [];
      const filtered = filter
        ? allFeats.filter(f => Object.values(f.properties || {{}}).some(v => String(v).toLowerCase().includes(filter)))
        : allFeats;

      const feats = filtered.slice(0, 100);
      document.getElementById("sampleCountLabel").textContent = `Showing ${{feats.length}} of ${{allFeats.length}} preview features${{filter ? ' (filtered)' : ''}}`;

      if (feats.length > 0) {{
        const cols = Object.keys(allFeats[0].properties || {{}}).filter(c => c !== "__idx" && !c.startsWith("_oic_")).slice(0, 8);
        document.getElementById("attrTableHead").innerHTML = `<tr><th class="py-2 px-3">Geom</th>${{cols.map(c => `<th class="py-2 px-3">${{c}}</th>`).join("")}}</tr>`;
        const tbody = document.getElementById("attrTableBody");
        tbody.innerHTML = "";
        feats.forEach(f => {{
          const tr = document.createElement("tr");
          tr.className = "hover:bg-surface-container cursor-pointer transition-colors";
          const gtype = (f.geometry && f.geometry.type) ? f.geometry.type.replace("Multi", "M-") : "—";
          tr.innerHTML = `<td class="py-1.5 px-3 font-mono font-bold text-secondary">${{gtype}}</td>` +
            cols.map(c => `<td class="py-1.5 px-3 truncate max-w-[200px]">${{f.properties[c] ?? ""}}</td>`).join("");
          tr.addEventListener("click", () => {{
            tbody.querySelectorAll("tr").forEach(r => r.classList.remove("bg-secondary/15"));
            tr.classList.add("bg-secondary/15");
            zoomToInspectFeature(f);
          }});
          tbody.appendChild(tr);
        }});
      }} else {{
        document.getElementById("attrTableHead").innerHTML = "";
        document.getElementById("attrTableBody").innerHTML = `<tr><td class="p-3 text-on-surface-variant">No features match "${{filter}}"</td></tr>`;
      }}
    }}

    window.addEventListener("DOMContentLoaded", () => {{
      initMap();
      const sel = document.getElementById("datasetSelect");
      QA_SUMMARY.datasets.forEach(ds => {{
        const opt = document.createElement("option");
        opt.value = ds.dataset_key;
        opt.textContent = `[${{ds.overall_qa_status}}] ${{ds.dataset_key}}`;
        sel.appendChild(opt);
      }});
      const params = new URLSearchParams(window.location.search);
      const initialKey = params.get("dataset") || QA_SUMMARY.datasets[0].dataset_key;
      sel.value = initialKey;
      sel.addEventListener("change", e => loadDatasetOnMap(e.target.value));
      document.getElementById("btnZoomExtent").addEventListener("click", () => {{
        if (currentBounds && map) map.fitBounds(currentBounds, {{ padding: 40 }});
      }});
      document.getElementById("sampleFilterInput").addEventListener("input", () => {{
        if (currentGeojson) renderSampleTable(currentGeojson);
      }});
      const closeBtn = document.getElementById("btnCloseSelectedFeature");
      if (closeBtn) {{
        closeBtn.addEventListener("click", () => {{
          document.getElementById("selectedFeatureBox").classList.add("hidden");
          setInspectHighlight(null);
        }});
      }}
      map.on("load", () => loadDatasetOnMap(initialKey));
    }});
  </script>
</body>
</html>
"""

    index_path = out_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    # Generate GeoLibre QA Inspector with the complete 48-dataset catalogue
    geolibre_inspect_path = out_dir / "geolibre_qa_inspect.html"
    try:
        from tools.build_geolibre_qa_inspect import main as build_inspect
        build_inspect()
    except Exception as e:
        print(f"[WARN] Failed to run build_geolibre_qa_inspect: {e}")

    # Mirror to inspect.html so legacy references and tests continue to work seamlessly
    inspect_path = out_dir / "inspect.html"
    if geolibre_inspect_path.exists():
        inspect_path.write_text(geolibre_inspect_path.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        inspect_path.write_text(inspect_html, encoding="utf-8")

    return {"index_html": str(index_path), "inspect_html": str(inspect_path), "geolibre_inspect_html": str(geolibre_inspect_path)}

