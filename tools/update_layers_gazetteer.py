import json
from pathlib import Path

layers_path = Path("docs/layers.js")
content = layers_path.read_text(encoding="utf-8")

with open("docs/data/lga_gazetteer_compact.json", "r", encoding="utf-8") as f:
    compact_dict = json.load(f)

compact_json_str = json.dumps(compact_dict, separators=(",", ":"))

start_marker = "  // Authoritative Australian Administrative & Locality Gazetteer (ABS ASGS 2025/2021 & GA)\n  const GAZETTEER = {"
end_marker = "  function resolveLocalityExtent(input, opts = {}) {"

idx_start = content.find(start_marker)
idx_end = content.find(end_marker)

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
  // Embedded 575 Australian LGAs, major cities, and regions (synchronous zero-latency access)
  const EMBEDDED_LGA_GAZETTEER = JSON.parse(""" + json.dumps(compact_json_str) + """);
  const GAZETTEER = Object.assign({}, EMBEDDED_LGA_GAZETTEER);

  // Asynchronously load the remaining 3,000+ ABS ASGS SA2 neighborhoods from GCS
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

old_build_return = "stateCode: entry.stateCode || (entry.state ? entry.state.toUpperCase() : null),"
new_build_return = "stateCode: entry.stateCode || STATE_CODES[(entry.state || \"\").toLowerCase()] || (entry.state ? entry.state.toUpperCase() : null),"
new_content = new_content.replace(old_build_return, new_build_return)

layers_path.write_text(new_content, encoding="utf-8")
print(f"Successfully updated docs/layers.js! Size: {len(new_content):,} chars")
