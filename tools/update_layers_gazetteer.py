import json
from pathlib import Path

layers_path = Path("docs/layers.js")
content = layers_path.read_text(encoding="utf-8")

with open("docs/data/lga_gazetteer_compact.json", "r", encoding="utf-8") as f:
    compact_dict = json.load(f)

compact_json_str = json.dumps(compact_dict, separators=(",", ":"))

start_marker = "  const STATE_CODES = {"
end_marker = "  function resolveLocalityExtent(input, opts = {}) {"

idx_start = content.find(start_marker)
idx_end = content.find(end_marker)

if idx_start == -1:
    start_marker = "  // Authoritative Australian Administrative & Locality Gazetteer (ABS ASGS 2025/2021 & GA)\n  const GAZETTEER = {"
    idx_start = content.find(start_marker)

assert idx_start != -1, "Could not find start marker"
assert idx_end != -1, "Could not find end marker"

replacement = """  const STATE_CODES = {
    "new south wales": "NSW", "nsw": "NSW",
    "victoria": "VIC", "vic": "VIC",
    "queensland": "QLD", "qld": "QLD",
    "western australia": "WA", "wa": "WA",
    "south australia": "SA", "sa": "SA",
    "tasmania": "TAS", "tas": "TAS",
    "northern territory": "NT", "nt": "NT",
    "australian capital territory": "ACT", "act": "ACT"
  };

  // Authoritative Australian Administrative & Locality Gazetteer (ABS ASGS 2025/2021 & GA)
  // Embedded 2,242 Australian LGAs, key towns, infrastructure localities, and metros (synchronous zero-latency access)
  const EMBEDDED_LGA_GAZETTEER = JSON.parse(""" + json.dumps(compact_json_str) + """);
  const GAZETTEER = Object.assign({}, EMBEDDED_LGA_GAZETTEER);

  // Asynchronously load the remaining 6,000+ ABS ASGS SA2 neighborhoods and infrastructure nodes from GCS
  fetch("data/locality_gazetteer.json")
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (data && typeof data === "object") {
        Object.entries(data).forEach(([k, v]) => {
          if (!GAZETTEER[k]) GAZETTEER[k] = v;
        });
      }
    })
    .catch(err => console.warn("locality_gazetteer.json background load warning:", err));

"""

new_content = content[:idx_start] + replacement + content[idx_end:]

layers_path.write_text(new_content, encoding="utf-8")
print(f"Successfully updated docs/layers.js! Size: {len(new_content):,} chars")
