"""Cloud Run service wrapping tools/harvest_portal_dataset.py.

Exposes:
  POST /harvest              -> {job_id} (202)  (in-process, small datasets)
  GET  /harvest/{job_id}     -> {status, log_tail, result}
  POST /harvest/{job_id}/cancel -> {status}
  POST /harvest-large        -> {execution} (202) (Cloud Run Job, large datasets)
  GET  /harvest-large/{execution} -> {status, ...}
  GET  /healthz

Auth: X-API-Key header must match the HARVESTER_API_KEY env/secret.

Job state is persisted to GCS (harvest_jobs/{job_id}.json) so polling
survives instance restarts.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import google.auth
from google.auth.transport.requests import AuthorizedSession

PROJECT_ROOT = Path(os.environ.get("OIC_PROJECT_ROOT", "/app"))
PROJECT = os.environ.get("OIC_GCP_PROJECT", "ops-intelligence-crafter")
REGION = os.environ.get("OIC_REGION", "australia-southeast1")
JOB_NAME = os.environ.get("OIC_RUN_JOB", "oic-harvester-job")
RUN_API = "https://run.googleapis.com/v2"

HARVESTER = PROJECT_ROOT / "tools" / "harvest_portal_dataset.py"
CONFIG = PROJECT_ROOT / "config" / "harvester_config.json"

API_KEY = os.environ.get("HARVESTER_API_KEY", "")

app = FastAPI(title="OIC Harvester Console", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("OIC_CORS_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def _store():
    from src.ingestion.gcs_storage import GCSLakeStorage
    return GCSLakeStorage()


def _check_key(x_api_key: Optional[str]) -> None:
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def _authed_session():
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return AuthorizedSession(creds)


JOB_PREFIX = "harvest_jobs/"
PROCS: Dict[str, subprocess.Popen] = {}
LOCK = threading.Lock()


class HarvestRequest(BaseModel):
    url: str
    key: Optional[str] = None
    theme: Optional[str] = None
    scale: Optional[str] = None
    jurisdiction: Optional[str] = None
    max_features: Optional[int] = None
    dry_run: bool = True
    skip_wherobots: bool = True
    refresh_geolibre: bool = False
    licence_name: Optional[str] = None
    licence_url: Optional[str] = None
    licence_attribution: Optional[str] = None


def _job_key(job_id: str) -> str:
    return f"{JOB_PREFIX}{job_id}.json"


def _read_job(job_id: str) -> Optional[Dict[str, Any]]:
    try:
        return _store().read_json_cloud(_job_key(job_id))
    except Exception:
        return None


def _write_job(job_id: str, data: Dict[str, Any]) -> None:
    try:
        _store().upload_bytes_cloud(
            _job_key(job_id),
            json.dumps(data, ensure_ascii=False).encode("utf-8"),
            content_type="application/json; charset=utf-8",
        )
    except Exception:
        pass


def _tail(path: Path, n: int = 200) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return ""
    return "\n".join(lines[-n:])


def _fetch_job_logs(execution: str) -> str:
    """Fetches recent log lines for a Cloud Run Job execution via Cloud Logging."""
    try:
        sess = _authed_session()
        exec_short = execution.split("/")[-1]
        body = {
            "resourceNames": [f"projects/{PROJECT}"],
            "filter": f'resource.type="cloud_run_job" AND labels."run.googleapis.com/execution_name"="{exec_short}"',
            "orderBy": "timestamp desc",
            "pageSize": 300,
        }
        resp = sess.post("https://logging.googleapis.com/v2/entries:list", json=body, timeout=30)
        if resp.status_code != 200:
            return ""
        entries = resp.json().get("entries", [])
        lines = []
        for e in reversed(entries):
            payload = e.get("textPayload") or ""
            if payload:
                lines.append(payload)
        return "\n".join(lines)
    except Exception:
        return ""


def _parse_result(log_text: str) -> Optional[Dict[str, Any]]:
    for line in reversed(log_text.splitlines()):
        if "OIC_RESULT_JSON:" in line:
            try:
                return json.loads(line.split("OIC_RESULT_JSON:", 1)[1].strip())
            except Exception:
                return None
    return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return ""
    return "\n".join(lines[-n:])


def _run_job(job_id: str, req: HarvestRequest) -> None:
    log_path = Path(f"/tmp/oic_harvest_{job_id}.log")
    state = {
        "job_id": job_id,
        "status": "queued",
        "log_path": str(log_path),
        "started_at": time.time(),
        "request": req.model_dump(),
        "returncode": None,
        "error": None,
        "cancel_requested": False,
        "finished_at": None,
        "result": None,
    }
    _write_job(job_id, state)
    state["status"] = "running"
    _write_job(job_id, state)

    args = ["python", str(HARVESTER), "--config", str(CONFIG), "--url", req.url]
    if req.key:
        args += ["--key", req.key]
    if req.theme:
        args += ["--theme", req.theme]
    if req.scale:
        args += ["--scale", req.scale]
    if req.jurisdiction:
        args += ["--jurisdiction", req.jurisdiction]
    if req.max_features:
        args += ["--max-features", str(req.max_features)]
    if req.licence_name:
        args += ["--licence-name", req.licence_name]
    if req.licence_url:
        args += ["--licence-url", req.licence_url]
    if req.dry_run:
        args += ["--dry-run"]
    if req.skip_wherobots:
        args += ["--skip-wherobots"]

    proc = None
    try:
        proc = subprocess.Popen(
            args,
            cwd=str(PROJECT_ROOT),
            stdout=open(log_path, "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "GDAL_DATA": "/usr/share/gdal", "PROJ_LIB": "/usr/share/proj", "PROJ_DATA": "/usr/share/proj"},
        )
        PROCS[job_id] = proc

        deadline = time.time() + int(os.environ.get("OIC_JOB_TIMEOUT_SEC", "540"))
        last_write = time.time()
        while True:
            cur = _read_job(job_id) or state
            cancel_requested = bool(cur.get("cancel_requested"))
            timed_out = time.time() > deadline
            if cancel_requested or timed_out:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=10)
                except Exception:
                    pass
                state["status"] = "cancelled" if cancel_requested else "failed"
                if timed_out:
                    state["error"] = "timeout"
                break
            rc = proc.poll()
            now = time.time()
            if now - last_write >= 5:
                state["log_tail"] = _tail(log_path)
                state["status"] = "running"
                _write_job(job_id, state)
                last_write = now
            if rc is not None:
                state["returncode"] = rc
                state["status"] = "succeeded" if rc == 0 else "failed"
                state["log_tail"] = _tail(log_path)
                state["result"] = _parse_result(state["log_tail"]) if state["status"] == "succeeded" else None
                break
            time.sleep(2)

        if state["status"] == "succeeded" and (not req.dry_run) and req.refresh_geolibre:
            refresh = PROJECT_ROOT / "tools" / "refresh_geolibre_library.py"
            if refresh.exists():
                with open(log_path, "a", encoding="utf-8") as lf:
                    lf.write("\n[GEOLIBRE] refreshing library...\n")
                    subprocess.run(
                        ["python", str(refresh)],
                        cwd=str(PROJECT_ROOT),
                        stdout=lf,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=300,
                    )

        state["log_tail"] = _tail(log_path)
        state["result"] = _parse_result(state["log_tail"]) if state.get("status") == "succeeded" else state.get("result")
        state["finished_at"] = time.time()
        _write_job(job_id, state)
    except Exception as exc:  # noqa: BLE001
        state["status"] = "failed"
        state["error"] = str(exc)
        state["log_tail"] = _tail(log_path)
        state["finished_at"] = time.time()
        _write_job(job_id, state)
    finally:
        PROCS.pop(job_id, None)


@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/harvest", status_code=202)
def harvest(req: HarvestRequest, x_api_key: Optional[str] = Header(default=None)) -> Dict[str, str]:
    _check_key(x_api_key)
    if not req.url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url must be http(s)")
    with LOCK:
        running = any(p.poll() is None for p in PROCS.values())
        if running:
            raise HTTPException(status_code=409, detail="Another harvest is running; try again later")
        job_id = uuid.uuid4().hex[:12]
        threading.Thread(target=_run_job, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id}


@app.get("/harvest/{job_id}")
def harvest_status(job_id: str, x_api_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check_key(x_api_key)
    job = _read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown job_id")
    if "log_tail" not in job and job.get("log_path"):
        job["log_tail"] = _tail(Path(job["log_path"]))
    return job


@app.post("/harvest/{job_id}/cancel")
def cancel(job_id: str, x_api_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check_key(x_api_key)
    job = _read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown job_id")
    job["cancel_requested"] = True
    _write_job(job_id, job)
    proc = PROCS.get(job_id)
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
    return {"job_id": job_id, "status": "cancel_requested"}


@app.post("/harvest-large", status_code=202)
def harvest_large(req: HarvestRequest, x_api_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check_key(x_api_key)
    if not req.url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url must be http(s)")
    args = ["tools/harvest_portal_dataset.py", "--config", "config/harvester_config.json", "--url", req.url]
    if req.key:
        args += ["--key", req.key]
    if req.theme:
        args += ["--theme", req.theme]
    if req.scale:
        args += ["--scale", req.scale]
    if req.jurisdiction:
        args += ["--jurisdiction", req.jurisdiction]
    if req.max_features:
        args += ["--max-features", str(req.max_features)]
    if req.licence_name:
        args += ["--licence-name", req.licence_name]
    if req.licence_url:
        args += ["--licence-url", req.licence_url]
    if req.dry_run:
        args += ["--dry-run"]
    if req.skip_wherobots:
        args += ["--skip-wherobots"]

    sess = _authed_session()
    url = f"{RUN_API}/projects/{PROJECT}/locations/{REGION}/jobs/{JOB_NAME}:run"
    body = {"overrides": {"containerOverrides": [{"args": args}]}}
    resp = sess.post(url, json=body, timeout=60)
    if resp.status_code not in (200, 202):
        raise HTTPException(status_code=502, detail=f"Cloud Run Jobs run failed: {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    exec_name = (data.get("metadata") or {}).get("name") or data.get("name")
    return {"execution": exec_name, "operation": data.get("name")}


@app.get("/harvest-large/{execution:path}")
def harvest_large_status(execution: str, x_api_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check_key(x_api_key)
    if not execution.startswith("projects/"):
        execution = f"projects/{PROJECT}/locations/{REGION}/jobs/{JOB_NAME}/executions/{execution}"
    sess = _authed_session()
    url = f"{RUN_API}/{execution}"
    resp = sess.get(url, timeout=30)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:300])
    data = resp.json()
    completed = data.get("completionTime")
    succeeded = (data.get("succeededCount") or 0) > 0
    failed = (data.get("failedCount") or 0) > 0
    if completed:
        status = "succeeded" if succeeded else ("failed" if failed else "completed")
    else:
        status = "running"
    logs = _fetch_job_logs(execution) if completed else ""
    result = _parse_result(logs) if (completed and status == "succeeded") else None
    return {
        "execution": execution,
        "status": status,
        "completionTime": completed,
        "succeededCount": data.get("succeededCount"),
        "failedCount": data.get("failedCount"),
        "log_tail": logs[-4000:],
        "result": result,
        "log_url": f"https://console.cloud.google.com/run/jobs/executions/details/{REGION}/{execution.split('/')[-1]}/logs?project={PROJECT}",
    }

