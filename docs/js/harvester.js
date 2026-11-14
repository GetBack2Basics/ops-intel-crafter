const $ = (id) => document.getElementById(id);
const BACKEND_KEY = "oic_backend_url";
const APIKEY_KEY = "oic_api_key";

// Restore saved settings
$("backendUrl").value = localStorage.getItem(BACKEND_KEY) || "";
$("apiKey").value = localStorage.getItem(APIKEY_KEY) || "";

let pollTimer = null;

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

$("submitBtn").addEventListener("click", async () => {
  const url = $("portalUrl").value.trim();
  if (!url) { alert("Portal URL is required"); return; }
  $("submitBtn").disabled = true;
  $("status").textContent = "Submitting...";
  $("log").textContent = "";
  $("result").classList.add("hidden");
  $("jobId").textContent = "";
  try {
    const body = {
      url,
      key: $("keyOverride").value.trim() || null,
      theme: $("themeOverride").value.trim() || null,
      dry_run: $("dryRun").checked,
      skip_wherobots: $("skipWb").checked,
      refresh_geolibre: $("refreshGl").checked,
    };
    const r = await api("/harvest", { method: "POST", body: JSON.stringify(body) });
    $("jobId").textContent = `job: ${r.job_id}`;
    $("status").textContent = "Running...";
    poll(r.job_id);
  } catch (e) {
    $("status").textContent = "Error: " + e.message;
    $("submitBtn").disabled = false;
  }
});

function poll(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const d = await api(`/harvest/${jobId}`);
      $("log").textContent = d.log_tail || "";
      $("log").scrollTop = $("log").scrollHeight;
      if (d.status === "succeeded" || d.status === "failed") {
        clearInterval(pollTimer);
        pollTimer = null;
        $("submitBtn").disabled = false;
        $("status").textContent = d.status === "succeeded" ? "Succeeded" : "Failed";
        if (d.status === "succeeded") {
          $("result").classList.remove("hidden");
          $("resultBody").textContent = JSON.stringify(d, null, 2);
        }
      }
    } catch (e) {
      $("status").textContent = "Poll error: " + e.message;
    }
  }, 5000);
}