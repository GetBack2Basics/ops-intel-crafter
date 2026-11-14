const $ = (id) => document.getElementById(id);
const BACKEND_KEY = "oic_backend_url";
const APIKEY_KEY = "oic_api_key";

// Restore saved settings
const savedBackend = localStorage.getItem(BACKEND_KEY);
if (savedBackend) $("backendUrl").value = savedBackend;
const savedKey = localStorage.getItem(APIKEY_KEY);
if (savedKey) $("apiKey").value = savedKey;

let pollTimer = null;
let currentJobId = null;

function saveSettings() {
  localStorage.setItem(BACKEND_KEY, $("backendUrl").value.trim());
  localStorage.setItem(APIKEY_KEY, $("apiKey").value.trim());
}

async function api(path, opts = {}) {
  saveSettings();
  const base = $("backendUrl").value.trim().replace(/\/$/, "");
  if (!base) throw new Error("Backend URL is required");
  const res = await fetch(base + path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": $("apiKey").value.trim(),
      ...(opts.headers || {}),
    },
  });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = { raw: text }; }
  if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
  return data;
}

$("cancelBtn").addEventListener("click", async () => {
  if (!currentJobId) return;
  try {
    await api(`/harvest/${currentJobId}/cancel`, { method: "POST" });
    $("status").textContent = "Cancel requested";
  } catch (e) {
    $("status").textContent = "Cancel error: " + e.message;
  }
});
$("submitBtn").addEventListener("click", async () => {
  const url = $("portalUrl").value.trim();
  if (!url) { alert("Portal URL is required"); return; }
  $("submitBtn").disabled = true;
  $("status").textContent = "Submitting...";
  $("log").textContent = "";
  $("result").classList.add("hidden");
  $("jobId").textContent = "";
  const useJob = $("useJob").checked;
  try {
    const body = {
      url,
      key: $("keyOverride").value.trim() || null,
      theme: $("themeOverride").value.trim() || null,
      max_features: $("maxFeatures").value ? parseInt($("maxFeatures").value, 10) : null,
      licence_name: $("licenceName").value.trim() || null,
      licence_url: $("licenceUrl").value.trim() || null,
      licence_attribution: $("licenceAttr").value.trim() || null,
      dry_run: $("dryRun").checked,
      skip_wherobots: $("skipWb").checked,
      refresh_geolibre: $("refreshGl").checked,
    };
    const endpoint = useJob ? "/harvest-large" : "/harvest";
    const r = await api(endpoint, { method: "POST", body: JSON.stringify(body) });
    const id = useJob ? r.execution : r.job_id;
    $("jobId").textContent = `job: ${id}`;
    currentJobId = id;
    $("cancelBtn").disabled = !useJob; // cancel only for in-process
    $("status").textContent = "Running...";
    poll(id, useJob);
  } catch (e) {
    $("status").textContent = "Error: " + e.message;
    $("submitBtn").disabled = false;
  }
});

function poll(jobId, useJob = false) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const path = useJob ? `/harvest-large/${encodeURIComponent(jobId)}` : `/harvest/${jobId}`;
      const d = await api(path);
      if (useJob) {
        $("log").textContent = `status: ${d.status}\nexecution: ${d.execution}\n${d.log_url || ""}`;
        if (d.result) {
          $("log").textContent += `\n\nDataset: ${d.result.dataset_key}\nGCS: ${d.result.gs_uri}\nQA: ${d.result.qa_inspector_url}\nWherobots: ${d.result.wherobots_table || "skipped"}`;
        }
      } else {
        $("log").textContent = d.log_tail || "";
        $("log").scrollTop = $("log").scrollHeight;
      }
      if (["succeeded","failed","completed","cancelled"].includes(d.status)) {
        clearInterval(pollTimer);
        pollTimer = null;
        $("submitBtn").disabled = false;
        $("cancelBtn").disabled = true;
        $("status").textContent = d.status;
        $("result").classList.remove("hidden");
        $("resultBody").textContent = JSON.stringify(d, null, 2);
      }
    } catch (e) {
      $("status").textContent = "Poll error: " + e.message;
    }
  }, useJob ? 10000 : 5000);
}